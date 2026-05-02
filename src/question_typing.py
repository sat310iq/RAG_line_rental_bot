"""Question typing module for metrics v2.

This module provides question type classification for conditional metrics evaluation.
Supports LLM-based classification with CSV override capability.
"""

from typing import Literal, Optional, Dict
from pydantic import BaseModel, Field
from langchain.chat_models import init_chat_model
from langchain_core.prompts import ChatPromptTemplate


QuestionType = Literal[
    "fact_lookup",          # 単一事実
    "procedure",            # 手続き・フロー
    "policy_confirmation",  # 可否確認（〜できますか）
    "policy_enumeration",   # 禁止/義務の列挙
    "explanation",          # 理由・背景説明
    "open_ended"            # 曖昧・相談系
]


class QuestionTypeResult(BaseModel):
    """Result of question type classification."""
    question_type: QuestionType = Field(description="Classified question type")
    confidence: float = Field(description="Confidence score (0-1)", ge=0.0, le=1.0)
    reasoning: str = Field(description="Brief reasoning for classification")


class QuestionTyper:
    """Question type classifier with LLM-based classification and CSV override."""
    
    def __init__(self, llm_model: str = "gpt-4o-mini"):
        """Initialize question typer.
        
        Args:
            llm_model: LLM model name for classification
        """
        self.llm_model = llm_model
        self.llm = None
        self._cache: Dict[str, QuestionType] = {}
        
    def _get_llm(self):
        """Lazy initialization of LLM."""
        if self.llm is None:
            self.llm = init_chat_model(self.llm_model, model_provider="openai")
        return self.llm
    
    def classify(self, question: str, override: Optional[QuestionType] = None) -> QuestionType:
        """Classify question type.
        
        Args:
            question: User question
            override: Manual override from CSV (takes precedence)
            
        Returns:
            Question type
        """
        # Check cache first
        if question in self._cache:
            return self._cache[question]
        
        # Use override if provided
        if override:
            self._cache[question] = override
            return override
        
        # LLM-based classification
        question_type = self._classify_with_llm(question)
        self._cache[question] = question_type
        return question_type
    
    def _classify_with_llm(self, question: str) -> QuestionType:
        """Classify question type using LLM.
        
        Args:
            question: User question
            
        Returns:
            Question type
        """
        llm = self._get_llm()
        llm_structured = llm.with_structured_output(QuestionTypeResult)
        
        prompt = ChatPromptTemplate.from_template("""
質問を分析して、以下の6つのタイプのいずれかに分類してください。

**質問タイプの定義**:

1. **fact_lookup** (単一事実): 特定の事実情報を尋ねる質問
   - 例: 「管理費の支払い方法は？」「鍵の紛失時の対応は？」
   - 特徴: 1つの明確な答えが期待される

2. **procedure** (手続き・フロー): 手順やプロセスを尋ねる質問
   - 例: 「契約期間の延長手続きは？」「退去時の立会い検査の流れは？」
   - 特徴: 複数のステップが含まれる

3. **policy_confirmation** (可否確認): 「〜できますか？」「〜可能ですか？」という確認質問
   - 例: 「ペット飼育の可否と条件は？」「室内のリフォームは可能か？」
   - 特徴: 可否を確認する質問

4. **policy_enumeration** (禁止/義務の列挙): 禁止事項や義務を列挙する質問
   - 例: 「契約で禁止されている行為は？」「近隣への配慮事項は？」
   - 特徴: 複数の項目を列挙する必要がある

5. **explanation** (理由・背景説明): 理由や背景を説明する質問
   - 例: 「原状回復の費用負担と契約条項の関係は？」
   - 特徴: 「なぜ」「どうして」という説明が求められる

6. **open_ended** (曖昧・相談系): 曖昧な質問や相談
   - 例: 「不明な質問（存在しない情報について）」
   - 特徴: 明確な答えが期待できない

質問: {question}

上記の6つのタイプのいずれかに分類してください。
""")
        
        chain = prompt | llm_structured
        
        try:
            result = chain.invoke({"question": question})
            return result.question_type
        except Exception as e:
            # Fallback to open_ended on error
            import sys
            print(f"Warning: Question type classification failed: {e}", file=sys.stderr)
            return "open_ended"
    
    def clear_cache(self):
        """Clear classification cache."""
        self._cache.clear()


def classify_question_type(
    question: str,
    override: Optional[QuestionType] = None,
    llm_model: str = "gpt-4o-mini"
) -> QuestionType:
    """Convenience function to classify question type.
    
    Args:
        question: User question
        override: Manual override from CSV
        llm_model: LLM model name
        
    Returns:
        Question type
    """
    typer = QuestionTyper(llm_model=llm_model)
    return typer.classify(question, override)
