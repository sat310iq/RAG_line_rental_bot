"""Evaluation metrics for RAG system.

This module provides evaluation metrics including:
- Retrieval metrics (Recall@K, MRR)
- LLM-based evaluation (Relevance, Hallucination - combined in single call)
- Rule-based evaluation (PII detection, Prohibited policy detection)
"""

import re
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
from langchain.chat_models import init_chat_model
from langchain_core.prompts import ChatPromptTemplate


class LLMEvaluationResult(BaseModel):
    """Result of LLM-based evaluation."""
    relevance: float = Field(description="Relevance score (0-1)", ge=0.0, le=1.0)
    hallucination: float = Field(description="Factuality score (0-1, higher is better - 1.0=fully grounded, 0.0=many hallucinations)", ge=0.0, le=1.0)


def calculate_retrieval_metrics(
    retrieved_ids: List[str],
    expected_ids: List[str],
    k_values: List[int] = [5, 10]
) -> Dict[str, float]:
    """Calculate retrieval metrics (Recall@K, MRR).
    
    Args:
        retrieved_ids: List of retrieved document IDs
        expected_ids: List of expected document IDs
        k_values: List of K values for Recall@K calculation
        
    Returns:
        Dictionary with metrics: recall_at_5, recall_at_10, mrr
    """
    if not expected_ids:
        return {f"recall_at_{k}": 0.0 for k in k_values} | {"mrr": 0.0}
    
    metrics = {}
    
    # Calculate Recall@K for each k
    for k in k_values:
        retrieved_top_k = retrieved_ids[:k]
        relevant_retrieved = len(set(retrieved_top_k) & set(expected_ids))
        recall = relevant_retrieved / len(expected_ids) if expected_ids else 0.0
        metrics[f"recall_at_{k}"] = recall
    
    # Calculate MRR (Mean Reciprocal Rank)
    mrr = 0.0
    for rank, doc_id in enumerate(retrieved_ids, 1):
        if doc_id in expected_ids:
            mrr = 1.0 / rank
            break
    
    metrics["mrr"] = mrr
    
    return metrics


def llm_evaluate_answer(
    question: str,
    context: str,
    answer: str,
    llm_model: str = "gpt-4o-mini"
) -> Dict[str, float]:
    """Evaluate answer using LLM (Relevance + Hallucination in single call).
    
    This function uses a single LLM call to evaluate both relevance and hallucination,
    reducing cost and latency compared to separate calls.
    
    Args:
        question: User question
        context: Context/evidence used to generate the answer
        answer: Generated answer to evaluate
        llm_model: LLM model name to use for evaluation
        
    Returns:
        Dictionary with relevance and hallucination scores (0-1)
    """
    # Initialize LLM
    llm = init_chat_model(llm_model, model_provider="openai")
    
    # Use structured output with Pydantic model
    llm_structured = llm.with_structured_output(LLMEvaluationResult)
    
    # Create evaluation prompt (combining Relevance + Factuality)
    evaluation_prompt = ChatPromptTemplate.from_template("""
質問: {question}

根拠情報（コンテキスト）:
{context}

評価対象の回答:
{answer}

以下の2つの観点で評価してください：

1. **Relevance（関連性）**: 回答が質問に関連しているか、質問に適切に答えているか
   - 1.0: 完全に関連している、質問に正確に対応している
   - 0.5: 部分的に関連しているが、質問の一部にしか答えていない
   - 0.0: 関連性が低い、質問に答えていない

2. **Factuality Score（事実性スコア）**: 回答が根拠情報に基づいている度合い（1.0=完全に根拠に基づく=良い、0.0=根拠にない情報が多い=悪い）
   - 1.0: 完全に根拠情報に基づいている、根拠にない情報は含まれていない（良い）
   - 0.5: 主に根拠情報に基づいているが、一部推測や根拠のない情報が含まれる
   - 0.0: 根拠情報に基づいていない、多くの根拠のない情報が含まれる（悪い）
   
   注意: このスコアは「根拠情報に基づいている度合い」を評価します。高いスコア（1.0に近い）= 良い回答、低いスコア（0.0に近い）= 幻覚が多い悪い回答です。

JSON形式で出力してください。hallucinationフィールドには事実性スコア（1.0=良い、0.0=悪い）を設定してください。
""")
    
    # Create chain and invoke
    chain = evaluation_prompt | llm_structured
    
    try:
        result = chain.invoke({
            "question": question,
            "context": context,
            "answer": answer,
        })
        
        # Ensure result is a dict with float values
        if isinstance(result, LLMEvaluationResult):
            return {
                "relevance": result.relevance,
                "hallucination": result.hallucination,
            }
        elif isinstance(result, dict):
            return {
                "relevance": float(result.get("relevance", 0.0)),
                "hallucination": float(result.get("hallucination", 0.0)),
            }
        else:
            # Fallback: return default scores
            return {"relevance": 0.0, "hallucination": 0.0}
            
    except Exception as e:
        # On error, return default scores
        import sys
        print(f"Warning: LLM evaluation failed: {e}", file=sys.stderr)
        return {"relevance": 0.0, "hallucination": 0.0}


def detect_pii(text: str) -> bool:
    """Detect PII (Personally Identifiable Information) in text using regex patterns.
    
    Args:
        text: Text to check for PII
        
    Returns:
        True if PII detected, False otherwise
    """
    patterns = [
        r'\d{1,4}号室',  # Room numbers (e.g., "101号室")
        r'0\d{1,4}-\d{1,4}-\d{4}',  # Phone numbers (e.g., "03-1234-5678")
        r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}',  # Email addresses
        r'\d{4}[-/]\d{1,2}[-/]\d{1,2}',  # Dates (e.g., "2024-01-01")
    ]
    
    for pattern in patterns:
        if re.search(pattern, text):
            return True
    
    return False


def detect_prohibited_policy(text: str, question: str) -> bool:
    """Detect if answer mentions prohibited policy for prohibited-related questions.
    
    This function checks if the answer mentions "prohibited" keywords when the question
    is about prohibited policies (e.g., pet ownership).
    
    Args:
        text: Answer text to check
        question: Original question
        
    Returns:
        True if prohibited policy is mentioned, False otherwise
    """
    # Keywords that indicate questions about prohibited policies
    prohibited_question_keywords = [
        "ペット", "pet", "飼育", "動物",
        "禁止", "不可", "できない", "認められない",
    ]
    
    # Keywords that indicate prohibited policy in answer
    prohibited_answer_keywords = [
        "禁止", "不可", "できません", "認められません",
        "禁止されています", "禁止です", "禁止となっています",
    ]
    
    # Check if question is about prohibited policies
    is_prohibited_question = any(
        keyword in question.lower() for keyword in prohibited_question_keywords
    )
    
    if not is_prohibited_question:
        return False
    
    # Check if answer mentions prohibited keywords
    return any(
        keyword in text for keyword in prohibited_answer_keywords
    )
