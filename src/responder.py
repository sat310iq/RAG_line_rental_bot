"""Response generator using schema columns as control parameters."""

import re
from datetime import datetime
from typing import List, Dict, Any, Optional, Literal, Tuple
from pydantic import BaseModel, Field
from langchain_core.documents import Document
from langchain.chat_models import init_chat_model
from langchain_core.prompts import ChatPromptTemplate
from src.config import Config
from src.kb_fast_path import normalize_for_match
from src.utils.question_terms import (
    count_distinct_pipe_tokens_in_question,
    count_pipe_field_hits,
    has_content_keyword_hit,
)


class CitationSchema(BaseModel):
    """Citation schema for OpenAI compatibility."""
    intent: Optional[str] = Field(default=None, description="Intent ID")
    row_index: Optional[int] = Field(default=None, description="Row index")
    score: Optional[float] = Field(default=None, description="Relevance score")


class ResponseSchema(BaseModel):
    """Structured response schema."""
    selected_intent: str = Field(description="Selected intent ID")
    selected_category: str = Field(description="Category")
    response_type: Literal["fact", "instruction", "warning", "policy"] = Field(description="Response type")
    confidence_level: Literal["high", "medium", "low"] = Field(description="Confidence level")
    answer_text: str = Field(description="Answer text")
    urgency: Literal["low", "medium", "high"] = Field(description="Urgency level")
    required_inputs: List[str] = Field(description="Required input fields")
    escalation: Literal["bot_only", "management_required", "owner_required", "conditional_owner"] = Field(description="Escalation type")
    handoff_message: Optional[str] = Field(default=None, description="Handoff message for escalation")
    citations: List[CitationSchema] = Field(default_factory=list, description="Citation information")


class Responder:
    """Response generator using schema columns for control."""
    
    # Exception phrases to remove from high-confidence policy answers
    EXCEPTION_PHRASES = [
        "例外がある場合があります",
        "原則として",
        "可能性があります",
        "場合によっては",
        "許可されることがあります",
        "詳細は管理会社に",
        "状況に応じて",
        "相談の上で可能",
        "詳細は管理会社にご確認ください",
        "念のため管理会社に",
    ]
    
    def __init__(self, config: Config):
        """Initialize responder.
        
        Args:
            config: Application configuration
        """
        self.config = config
        self.llm = init_chat_model(
            config.openai_model,
            model_provider="openai"
        )
        
        # Structured output LLM (use function_calling method for better compatibility)
        self.llm_structured = self.llm.with_structured_output(ResponseSchema, method="function_calling")
        
        # Response generation prompt
        self.response_prompt = ChatPromptTemplate.from_template("""
以下の情報を基に、質問に回答してください。

質問: {question}

検索結果（上位{top_k}件）:
{retrieved_docs}

**重要な回答ルール（厳守）**:
1. **外部知識の追加禁止**: 検索結果に記載されていない情報は一切含めない。推測や一般常識に基づく情報も含めない。
2. **answerフィールドを基本とする**: 検索結果の「answer」フィールドを基本として、必要に応じて整形・要約のみ行う。
3. **メタデータフィールドの正確な抽出**: 検索結果の各ドキュメントから以下のフィールドを正確に抽出すること:
   - intent: intentフィールドの値をそのまま使用
   - category: categoryフィールドの値をそのまま使用
   - response_type: response_typeフィールドの値（fact/instruction/warning/policyのいずれか）
   - confidence_level: confidence_levelフィールドの値（high/medium/lowのいずれか）
   - urgency: urgencyフィールドの値（low/medium/highのいずれか）
   - escalation: escalationフィールドの値（bot_only/management_required/owner_required/conditional_ownerのいずれか）**重要: escalation_reasonではなくescalationフィールドを使用**
   - handoff_message: handoff_messageフィールドの値（存在する場合）
   - required_inputs: required_inputsフィールドをカンマ区切りで分割したリスト

4. **スキーマ列による制御**: 以下のルールに従って回答を構成すること:
   - urgency=high または response_type=warning → 冒頭に【緊急／注意】＋一次対応を必ず含める
   - required_inputs が非空 → **検索結果のanswer本文を必ずそのまま含める（省略禁止）**。連絡先・手順がanswerにあれば必ず反映する。そのうえで、確認してほしい項目としてrequired_inputsを箇条書きで追記してよい（answerの置き換えにしない）
   - confidence_level=medium/low → 「原則」「例外」「確認誘導」を必ず含める
   - escalation != bot_only → 末尾に人対応案内＋handoff_messageを含める

5. **response_typeに応じた構成**:
   - fact: 事実説明（淡々と）
   - instruction: 行動手順（箇条書き）
   - warning: 危険/注意（強め、最優先）
   - policy: ルール/規約
     * confidence_level=high の場合: 「全面的に禁止」「一切認められない」などの断定的な表現のみを使用。例外の言及は一切含めない。
     * confidence_level=medium/low の場合: 「原則＋例外の順」で構成

6. **confidence_levelに応じた表現**:
   - high: 断定して良い。検索結果の`answer`フィールドの内容をそのまま使用し、追加の説明や例外の言及は一切含めない。
   - medium: 「原則」「例外あり」を含める
   - low: 「念のため管理会社へ」誘導を入れる

**最重要**: 
- escalationフィールドは必ず検索結果の「escalation」列の値をそのまま使用してください。値は必ず以下の4つのいずれかです: "bot_only", "management_required", "owner_required", "conditional_owner"
- escalation_reasonやhandoff_messageの値はescalationフィールドには使用しないでください。これらは別のフィールドです。
- 検索結果の各ドキュメントには「escalation: [値]」という行があります。その値をそのまま使用してください。

**citationsフィールドの生成（必須）**:
- citationsフィールドには、検索結果の各ドキュメントから抽出したCitationSchemaのリストを必ず含めること
- 各CitationSchemaには以下の情報を含めること:
  - intent: 検索結果の「intent」フィールドの値（例: "契約_証明書"）
  - row_index: 検索結果の「row_index」フィールドの値（存在する場合、デフォルトは0）
  - score: 関連度スコア（1.0を推奨、または検索結果の順序に基づいて0.9, 0.8など）
- 検索結果が複数ある場合、すべてのドキュメントのcitationsを含めること（最大3件まで）
- citationsフィールドは空のリストにしてはいけません。最低1件は含めること

例:
- 検索結果に「escalation: management_required」とあれば、escalationフィールドには"management_required"を設定
- 検索結果に「escalation_reason: 日程調整・立会いが必要」とあっても、escalationフィールドには使用しない（これはescalation_reasonフィールド用）
- 検索結果に「intent: 契約_証明書」「row_index: 12」とあれば、citationsには[{"intent": "契約_証明書", "row_index": 12, "score": 1.0}]を含める

回答を生成してください。検索結果にない情報は含めないでください。
""")
    
    def _kb_question_evidence_aligned(self, question: str, metadata: Dict[str, Any]) -> bool:
        """Require minimal overlap between question tokens and KB row signals (keywords + answer)."""
        exclude = metadata.get("exclude_keywords") or ""
        if exclude and count_pipe_field_hits(question, str(exclude)) > 0:
            return False
        neg = (metadata.get("negative_keywords") or "").strip()
        if neg:
            tokens = [t for t in re.split(r"[\s|]+", neg) if t]
            if any(t in question for t in tokens):
                return False
        qn = normalize_for_match(question)
        short = len(qn) <= int(getattr(self.config, "kb_fast_path_short_max_len", 10) or 10)
        hits = count_distinct_pipe_tokens_in_question(
            question,
            str(metadata.get("keywords") or ""),
            str(metadata.get("keywords_primary") or ""),
        )
        min_h = 2 if short else int(getattr(self.config, "responder_kb_min_keyword_hits", 1) or 1)
        if hits >= min_h:
            return True
        hay = "\n".join(
            x
            for x in (
                metadata.get("answer") or "",
                metadata.get("canonical_question") or "",
            )
            if x
        )
        return has_content_keyword_hit(
            question,
            hay,
            stopwords=self.config.question_term_stopwords or None,
            synonyms=self.config.question_term_synonyms or None,
        )

    def _format_retrieved_docs(self, documents: List[Document]) -> str:
        """Format retrieved documents for prompt.
        
        Args:
            documents: List of retrieved Document objects
            
        Returns:
            Formatted string
        """
        formatted = []
        for idx, doc in enumerate(documents, 1):
            metadata = doc.metadata
            intent = metadata.get('intent', 'unknown')
            category = metadata.get('category', '')
            answer = metadata.get('answer', doc.page_content)
            response_type = metadata.get('response_type', '')
            confidence_level = metadata.get('confidence_level', '')
            urgency = metadata.get('urgency', '')
            required_inputs_str = metadata.get('required_inputs', '')
            # Parse comma-separated string back to list
            required_inputs = [item.strip() for item in required_inputs_str.split(',')] if required_inputs_str else []
            escalation = metadata.get('escalation', '')
            handoff_message = metadata.get('handoff_message', '')
            
            escalation_reason = metadata.get('escalation_reason', '')
            
            doc_str = f"[結果{idx}]\n"
            doc_str += f"intent: {intent}\n"
            doc_str += f"category: {category}\n"
            doc_str += f"answer: {answer}\n"
            doc_str += f"response_type: {response_type}\n"
            doc_str += f"confidence_level: {confidence_level}\n"
            doc_str += f"urgency: {urgency}\n"
            if required_inputs:
                doc_str += f"required_inputs: {', '.join(required_inputs)}\n"
            # Clearly mark escalation field with valid values
            doc_str += f"escalation: {escalation} (有効値: bot_only/management_required/owner_required/conditional_owner)\n"
            if escalation_reason:
                doc_str += f"escalation_reason: {escalation_reason} (注意: これはescalationフィールドではありません)\n"
            if handoff_message:
                doc_str += f"handoff_message: {handoff_message}\n"
            
            formatted.append(doc_str)
        
        return "\n\n".join(formatted)
    
    def _sanitize_policy_answer(self, text: str) -> str:
        """Remove exception language from high-confidence policy answers.
        
        Args:
            text: Answer text to sanitize
            
        Returns:
            Sanitized text with exception phrases removed
        """
        sanitized = text
        for phrase in self.EXCEPTION_PHRASES:
            sanitized = sanitized.replace(phrase, "")
        return sanitized.strip()
    
    def generate(
        self,
        question: str,
        retrieved_docs: List[Document],
        user_inputs: Optional[Dict[str, str]] = None,
        tenant_info: Optional[Dict[str, str]] = None
    ) -> Tuple[ResponseSchema, str]:
        """Generate response using schema columns for control.
        
        Args:
            question: User question
            retrieved_docs: List of retrieved Document objects (top_k)
            user_inputs: Optional dictionary of user-provided inputs
            
        Returns:
            Tuple of (ResponseSchema, human-readable text)
        """
        if not retrieved_docs:
            # No documents found
            return ResponseSchema(
                selected_intent="unknown",
                selected_category="unknown",
                response_type="fact",
                confidence_level="low",
                answer_text="申し訳ございませんが、該当する情報が見つかりませんでした。管理会社にお問い合わせください。",
                urgency="low",
                required_inputs=[],
                escalation="management_required",
                handoff_message=None,
                citations=[]
            ), "申し訳ございませんが、該当する情報が見つかりませんでした。管理会社にお問い合わせください。"
        
        # Use top document as primary source (trust retriever ranking)
        top_doc = retrieved_docs[0]
        metadata = top_doc.metadata

        if (
            getattr(self.config, "responder_kb_alignment_enabled", True)
            and metadata.get("type") == "kb_faq"
            and not self._kb_question_evidence_aligned(question, metadata)
        ):
            fb = (self.config.responder_misalignment_fallback_message or "").strip()
            return ResponseSchema(
                selected_intent="unknown",
                selected_category="unknown",
                response_type="fact",
                confidence_level="low",
                answer_text=fb,
                urgency="low",
                required_inputs=[],
                escalation="management_required",
                handoff_message=None,
                citations=[],
            ), fb

        # Extract schema columns
        intent = metadata.get('intent', 'unknown')
        category = metadata.get('category', '')
        answer = metadata.get('answer', top_doc.page_content)
        response_type = metadata.get('response_type', 'fact')
        confidence_level = metadata.get('confidence_level', 'high')
        urgency = metadata.get('urgency', 'low')
        required_inputs_str = metadata.get('required_inputs', '')
        # Parse comma-separated string back to list
        required_inputs = [item.strip() for item in required_inputs_str.split(',')] if required_inputs_str else []
        escalation = metadata.get('escalation', 'bot_only')
        handoff_message = metadata.get('handoff_message', '')
        
        # Format retrieved docs for prompt
        formatted_docs = self._format_retrieved_docs(retrieved_docs[:3])  # Top 3 for context
        
        # Validate escalation value
        valid_escalation_values = ["bot_only", "management_required", "owner_required", "conditional_owner"]
        if escalation not in valid_escalation_values:
            print(f"[WARNING] Invalid escalation value '{escalation}', defaulting to 'bot_only'")
            escalation = "bot_only"
        
        # Generate structured response
        # For KB CSV responses, use metadata directly to avoid LLM schema errors.
        use_llm_structured = False
        if use_llm_structured:
            try:
                response = self.llm_structured.invoke(
                    self.response_prompt.format_messages(
                        question=question,
                        retrieved_docs=formatted_docs,
                        top_k=len(retrieved_docs)
                    )
                )
                # Always use metadata escalation value to ensure correctness (LLM may confuse escalation_reason)
                response.escalation = escalation
                # Ensure citations are properly formatted
                if not response.citations:
                    response.citations = [CitationSchema(
                        intent=intent,
                        row_index=metadata.get('row_index', 0),
                        score=1.0
                    )]
                else:
                    # Fill missing intent/row_index if LLM omitted
                    for citation in response.citations:
                        if not citation.intent:
                            citation.intent = intent
                        if citation.row_index is None:
                            citation.row_index = metadata.get('row_index', 0)
                        if citation.score is None:
                            citation.score = 1.0
                # Also ensure other critical fields match metadata if LLM made mistakes
                if response.selected_intent != intent:
                    response.selected_intent = intent
                if response.selected_category != category:
                    response.selected_category = category
                if response.response_type != response_type:
                    response.response_type = response_type
                if response.confidence_level != confidence_level:
                    response.confidence_level = confidence_level
                if response.urgency != urgency:
                    response.urgency = urgency
            except Exception as e:
                print(f"Error generating structured response: {e}")
                use_llm_structured = False
        
        if not use_llm_structured:
            # Use metadata values directly
            response = ResponseSchema(
                selected_intent=intent,
                selected_category=category,
                response_type=response_type,
                confidence_level=confidence_level,
                answer_text=answer,
                urgency=urgency,
                required_inputs=required_inputs,
                escalation=escalation,  # Use validated escalation from metadata
                handoff_message=handoff_message if escalation != 'bot_only' else None,
                citations=[CitationSchema(
                    intent=intent,
                    row_index=metadata.get('row_index', 0),
                    score=1.0
                )]
            )
        
        # Build human-readable text (order: header → KB body → disclaimers/handoff → optional follow-up questions)
        text_parts = []
        
        # Rule 1: urgency=high or response_type=warning → emergency header
        if urgency == "high" or response_type == "warning":
            text_parts.append("【緊急・注意】")
            text_parts.append("")
        
        # Post-process: Remove exception language for high confidence policy responses
        if confidence_level == "high" and response_type == "policy":
            response.answer_text = self._sanitize_policy_answer(response.answer_text)
        
        # KB body first: required_inputs must not replace or omit the base answer
        text_parts.append(response.answer_text)
        
        # Rule 3: confidence_level=medium/low → add disclaimer
        if confidence_level in ["medium", "low"]:
            text_parts.append("")
            if confidence_level == "medium":
                text_parts.append("※ 原則として上記の通りですが、例外がある場合があります。詳細は管理会社にご確認ください。")
            else:
                text_parts.append("※ 念のため、管理会社にご確認いただくことをお勧めします。")
        
        # Rule 4: escalation != bot_only → add handoff message
        if escalation != "bot_only":
            text_parts.append("")
            text_parts.append("この件は管理会社での対応が必要です。")
            if handoff_message:
                text_parts.append(f"（{handoff_message}）")
        
        # Rule 5: optional follow-up fields (after KB answer; not a substitute for answer)
        if required_inputs and not user_inputs:
            text_parts.append("")
            text_parts.append("より正確な対応のため、以下をお知らせください：")
            for req_input in required_inputs:
                text_parts.append(f"  - {req_input}")
        
        # Generate escalation data (structured JSON) if escalation needed and tenant info available
        # Note: escalation_data is not stored in ResponseSchema to avoid OpenAI compatibility issues
        # It will be generated in rag_answerer.py if needed
        escalation_data = None
        if escalation != "bot_only" and tenant_info:
            escalation_data = {
                "intent": response.selected_intent,
                "category": response.selected_category,
                "question": question,
                "tenant": {
                    "room_number": tenant_info.get('room_number', ''),
                    "name": tenant_info.get('name', ''),
                },
                "urgency": urgency,
                "escalation_type": escalation,
                "handoff_message": handoff_message,
                "timestamp": datetime.now().isoformat()
            }
            # Store escalation_data as a separate attribute (not in schema)
            # Use setattr to avoid Pydantic validation errors
            object.__setattr__(response, 'escalation_data', escalation_data)
        
        human_text = "\n".join(text_parts)
        
        return response, human_text
