"""Evaluation logic for RAG system.

This module provides the main evaluation function that evaluates a single question
using the RAG pipeline and various metrics.
"""

import re
from typing import List, Dict, Any, Optional
from langchain_core.documents import Document
from src.rag_answerer import RAGAnswerer, AnswerSchema
from src.metrics import (
    calculate_retrieval_metrics,
    llm_evaluate_answer,
    detect_pii,
    detect_prohibited_policy,
)


def extract_doc_ids_from_evidence(evidence: List[str]) -> List[str]:
    """Extract document IDs from evidence.
    
    Since RAGAnswerer.answer() now returns actual document IDs in evidence field,
    this function simply returns the evidence list as-is (after removing duplicates).
    
    Args:
        evidence: List of document IDs (from RAGAnswerer.answer().evidence)
        
    Returns:
        List of document IDs (deduplicated)
    """
    # Remove duplicates while preserving order
    seen = set()
    unique_ids = []
    for doc_id in evidence:
        if doc_id and doc_id not in seen:
            seen.add(doc_id)
            unique_ids.append(doc_id)
    
    return unique_ids


def format_evidence_for_llm(evidence: List[str]) -> str:
    """Format evidence list into a single string for LLM evaluation.
    
    Args:
        evidence: List of evidence strings
        
    Returns:
        Formatted evidence string
    """
    return "\n\n".join([f"[根拠{i+1}]\n{ev}" for i, ev in enumerate(evidence)])


def evaluate_question(
    question: str,
    rag_answerer: RAGAnswerer,
    expected_doc_ids: Optional[List[str]] = None,
    expected_answer: Optional[str] = None,
    llm_model: str = "gpt-4o-mini",
    tenant_contract_id: Optional[str] = None
) -> Dict[str, Any]:
    """Evaluate a single question using the RAG pipeline.
    
    This function:
    1. Runs the RAG pipeline to get an answer
    2. Extracts retrieved document IDs from evidence
    3. Calculates retrieval metrics (Recall@K, MRR) if expected_doc_ids provided
    4. Evaluates answer quality using LLM (Relevance + Hallucination in single call)
    5. Checks for PII leakage and prohibited policy mentions (rule-based)
    
    Args:
        question: User question
        expected_doc_ids: List of expected document IDs for retrieval evaluation (optional)
        expected_answer: Expected answer text (optional, for reference)
        rag_answerer: RAG answerer instance
        llm_model: LLM model name for evaluation
        tenant_contract_id: Tenant contract ID (optional)
        
    Returns:
        Dictionary with evaluation metrics and results
    """
    try:
        # 1. Run RAG pipeline
        answer: AnswerSchema = rag_answerer.answer(question, tenant_contract_id)
        
        # 2. Extract retrieved document IDs from evidence
        retrieved_ids = extract_doc_ids_from_evidence(answer.evidence)
        
        # 3. Calculate retrieval metrics (only if expected_doc_ids provided)
        if expected_doc_ids:
            retrieval_metrics = calculate_retrieval_metrics(
                retrieved_ids,
                expected_doc_ids,
                k_values=[5, 10]
            )
        else:
            # No expected IDs - set retrieval metrics to None
            retrieval_metrics = {
                "recall_at_5": None,
                "recall_at_10": None,
                "mrr": None,
            }
        
        # 4. Format answer text for evaluation
        answer_text = f"{answer.conclusion} {answer.next_action} {answer.caveats}".strip()
        
        # 5. Format evidence for LLM evaluation
        context_text = format_evidence_for_llm(answer.evidence)
        
        # 6. LLM evaluation (Relevance + Hallucination in single call)
        llm_metrics = llm_evaluate_answer(
            question=question,
            context=context_text,
            answer=answer_text,
            llm_model=llm_model
        )
        
        # 7. Rule-based evaluation
        pii_detected = detect_pii(answer_text)
        prohibited_mentioned = detect_prohibited_policy(answer_text, question)
        
        # 8. Compile results
        result = {
            "question": question,
            "success": True,
            "recall_at_5": retrieval_metrics["recall_at_5"],
            "recall_at_10": retrieval_metrics["recall_at_10"],
            "mrr": retrieval_metrics["mrr"],
            "relevance": llm_metrics["relevance"],
            "hallucination": llm_metrics["hallucination"],
            "contains_pii": pii_detected,
            "mentions_prohibited": prohibited_mentioned,
            "answer": {
                "conclusion": answer.conclusion,
                "next_action": answer.next_action,
                "caveats": answer.caveats,
                "evidence": answer.evidence,
            },
            "answer_text": answer_text,
            "retrieved_ids": retrieved_ids,
            "expected_doc_ids": expected_doc_ids or [],
            "expected_answer": expected_answer,
        }
        return result
        
    except Exception as e:
        return {
            "question": question,
            "success": False,
            "error": str(e),
            "recall_at_5": 0.0,
            "recall_at_10": 0.0,
            "mrr": 0.0,
            "relevance": 0.0,
            "hallucination": 0.0,
            "contains_pii": False,
            "mentions_prohibited": False,
        }
