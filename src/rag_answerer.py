"""RAG answerer with Router Chain, Planner, Semantic Reranking, and structured output."""

import re
from typing import List, Dict, Optional, Literal
from pydantic import BaseModel, Field
from langchain.chat_models import init_chat_model
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.documents import Document
from src.config import Config
from src.vector_store_manager import VectorStoreManager
from src.query_cache import QueryCache
from src.tenant_auth import TenantAuth


class AnswerSchema(BaseModel):
    """Structured answer schema."""
    conclusion: str = Field(description="結論・回答の要約")
    evidence: List[str] = Field(description="根拠（文書ID/ページ/ログID等のリスト）")
    next_action: str = Field(description="次アクション（入居者が取るべき行動）")
    caveats: str = Field(description="注意点・例外事項")


class RAGAnswerer:
    """RAG answerer with full pipeline."""
    
    def __init__(
        self,
        config: Config,
        vector_store_manager: VectorStoreManager,
        query_cache: QueryCache,
        tenant_auth: Optional[TenantAuth] = None
    ):
        """Initialize RAG answerer.
        
        Args:
            config: Application configuration
            vector_store_manager: Vector store manager
            query_cache: Query cache
            tenant_auth: Tenant authentication (optional)
        """
        self.config = config
        self.vector_store_manager = vector_store_manager
        self.query_cache = query_cache
        self.tenant_auth = tenant_auth
        
        # Initialize LLM
        self.llm = init_chat_model(
            config.openai_model,
            model_provider="openai"
        )
        
        # Structured output LLM
        self.llm_structured = self.llm.with_structured_output(AnswerSchema)
        
        # Prompts
        self.router_prompt = ChatPromptTemplate.from_template("""
質問を分析して、どのデータソースから回答すべきか分類してください。

分類:
- "faq_only": FAQだけで回答できる質問（例: 基本的なルール、よくある質問）
- "pdf_only": PDF文書（契約/ガイドライン）から回答すべき質問（例: 契約条項、詳細な規定）
- "ops_only": 運用ログから回答すべき質問（例: 過去の対応事例）
- "multi": 複数のソースから統合して回答すべき質問

質問: {question}

分類（faq_only/pdf_only/ops_only/multiのいずれか）:
""")
        
        self.planner_prompt = ChatPromptTemplate.from_template("""
ユーザーの質問を分析し、検索に適したサブクエリを生成してください。

質問: {question}

以下の形式で、最大5つのサブクエリを生成してください:
1. [サブクエリ1]
2. [サブクエリ2]
...

サブクエリ:
""")
        
        self.rerank_prompt = ChatPromptTemplate.from_template("""
質問と候補文書の関連度を評価してください。

質問: {question}

候補文書:
{candidates}

各候補文書について、質問との関連度を1-5で評価し、上位{top_n}件を選んでください。
出力形式:
- 文書ID: スコア (理由)

評価結果:
""")
        
        self.answer_prompt = ChatPromptTemplate.from_template("""
以下の情報を基に、質問に回答してください。

質問: {question}

根拠情報:
{evidence}

回答ルール:
- 推測しない（根拠にない情報は含めない）
- FAQがあればFAQを優先し、FAQの内容を正確に反映すること
- 特に「禁止」「許可」「申請が必要」などの明確なルールがある場合は、それを正確に伝えること
- 出典（文書ID/ページ/ログID）を必ず明記
- 不明な点や判断が必要な場合は、管理会社への問い合わせを案内

{tenant_context}

回答を生成してください。
""")
    
    def _route_query(self, question: str) -> Literal["faq_only", "pdf_only", "ops_only", "multi"]:
        """Route query to appropriate source(s).
        
        Args:
            question: User question
            
        Returns:
            Source type to search
        """
        chain = self.router_prompt | self.llm | StrOutputParser()
        result = chain.invoke({"question": question}).strip().lower()
        
        # Parse result
        if "faq_only" in result or "faq" in result:
            return "faq_only"
        elif "pdf_only" in result or "pdf" in result:
            return "pdf_only"
        elif "ops_only" in result or "ops" in result:
            return "ops_only"
        else:
            return "multi"
    
    def _plan_subqueries(self, question: str) -> List[str]:
        """Generate subqueries from question.
        
        Args:
            question: User question
            
        Returns:
            List of subqueries
        """
        chain = self.planner_prompt | self.llm | StrOutputParser()
        result = chain.invoke({"question": question})
        
        # Parse subqueries from numbered list
        subqueries = []
        lines = result.split('\n')
        for line in lines:
            line = line.strip()
            # Match numbered list items
            match = re.match(r'^\d+[\.\)]\s*(.+)', line)
            if match:
                subqueries.append(match.group(1).strip())
        
        # If no subqueries found, use original question
        if not subqueries:
            subqueries = [question]
        
        # Limit to 5 subqueries
        return subqueries[:5]
    
    def _format_evidence(self, documents: List[Document], max_snippet_length: int = 200) -> str:
        """Format evidence documents for LLM input.
        
        Args:
            documents: List of Document objects
            max_snippet_length: Maximum length of snippet per document
            
        Returns:
            Formatted evidence string
        """
        evidence_parts = []
        
        for idx, doc in enumerate(documents, 1):
            snippet = doc.page_content[:max_snippet_length]
            if len(doc.page_content) > max_snippet_length:
                snippet += "..."
            
            source_info = []
            if 'filename' in doc.metadata:
                source_info.append(f"ファイル: {doc.metadata['filename']}")
            if 'page' in doc.metadata:
                source_info.append(f"ページ: {doc.metadata['page']}")
            if 'stable_id' in doc.metadata:
                source_info.append(f"ログID: {doc.metadata['stable_id']}")
            if 'intent' in doc.metadata:
                source_info.append(f"意図: {doc.metadata['intent']}")
            
            source_str = " | ".join(source_info) if source_info else "不明"
            
            evidence_parts.append(
                f"[文書{idx}] {source_str}\n{snippet}"
            )
        
        return "\n\n".join(evidence_parts)
    
    def _semantic_rerank(
        self,
        question: str,
        candidates: List[Document],
        top_n: int
    ) -> List[Document]:
        """Rerank candidates using LLM.
        
        Args:
            question: User question
            candidates: Candidate documents
            top_n: Number of top documents to return
            
        Returns:
            Reranked top N documents
        """
        if len(candidates) <= top_n:
            return candidates
        
        # Format candidates for reranking
        candidates_text = []
        for idx, doc in enumerate(candidates):
            snippet = doc.page_content[:200]
            candidates_text.append(f"文書{idx}: {snippet}")
        
        candidates_str = "\n\n".join(candidates_text)
        
        # Use LLM to rerank (simplified - in production, use cross-encoder)
        # For PoC, just return top N by taking first N (can be improved)
        # In a real implementation, you would score each candidate
        
        # For now, return top N candidates as-is
        # TODO: Implement proper LLM-based reranking with scoring
        return candidates[:top_n]
    
    def _filter_tenant_info(
        self,
        documents: List[Document],
        tenant_contract_id: Optional[str]
    ) -> List[Document]:
        """Filter documents to show only tenant's own information.
        
        Args:
            documents: List of Document objects
            tenant_contract_id: Authenticated tenant's contract ID
            
        Returns:
            Filtered list of Document objects
        """
        if not tenant_contract_id or not self.tenant_auth:
            return documents
        
        tenant_info = self.tenant_auth.get_tenant_info(tenant_contract_id)
        if not tenant_info:
            return documents
        
        tenant_room = tenant_info['room_number']
        filtered = []
        
        for doc in documents:
            # For ops_log, check if room matches tenant's room
            if doc.metadata.get('type') == 'ops_log':
                doc_room = doc.metadata.get('tenant_room', '')
                if doc_room and tenant_room not in doc_room:
                    # Skip documents from other tenants
                    continue
            
            filtered.append(doc)
        
        return filtered
    
    def _check_pii_leakage(self, text: str) -> bool:
        """Check for PII leakage in output.
        
        Args:
            text: Text to check
            
        Returns:
            True if PII detected, False otherwise
        """
        # Patterns to detect
        patterns = [
            r'\d{1,4}号室',  # Room numbers (except tenant's own)
            r'0\d{1,4}-\d{1,4}-\d{4}',  # Phone numbers
            r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}',  # Email
            r'\d{4}[-/]\d{1,2}[-/]\d{1,2}',  # Dates
        ]
        
        for pattern in patterns:
            if re.search(pattern, text):
                return True
        
        return False
    
    def answer(
        self,
        question: str,
        tenant_contract_id: Optional[str] = None
    ) -> AnswerSchema:
        """Generate answer for question.
        
        Args:
            question: User question
            tenant_contract_id: Authenticated tenant's contract ID (optional)
            
        Returns:
            Structured answer
        """
        # Check cache first
        cached_result = self.query_cache.get(question)
        if cached_result:
            return cached_result
        
        # Route query
        source_type = self._route_query(question)
        
        # Map source type to sources list
        source_map = {
            "faq_only": ["faq"],
            "pdf_only": ["pdf"],
            "ops_only": ["ops"],
            "multi": ["faq", "pdf", "ops"],
        }
        sources = source_map.get(source_type, ["faq", "pdf", "ops"])
        
        # Plan subqueries
        subqueries = self._plan_subqueries(question)
        
        # Search across sources
        all_documents = []
        for subquery in subqueries:
            results = self.vector_store_manager.search(subquery, sources=sources)
            for source_docs in results.values():
                all_documents.extend(source_docs)
        
        # Filter tenant-specific information
        all_documents = self._filter_tenant_info(all_documents, tenant_contract_id)
        
        # Deduplicate
        seen_ids = set()
        unique_docs = []
        for doc in all_documents:
            doc_id = doc.metadata.get('stable_id') or hash(doc.page_content)
            if doc_id not in seen_ids:
                seen_ids.add(doc_id)
                unique_docs.append(doc)
        
        # Rerank
        reranked = self._semantic_rerank(
            question,
            unique_docs,
            self.config.rag_rerank_top_n
        )
        
        # Format evidence
        evidence_text = self._format_evidence(reranked)
        
        # Extract document IDs from reranked documents for evaluation
        evidence_ids = []
        for doc in reranked:
            # Priority: intent (FAQ) > stable_id (OPS) > filename+page (PDF) > filename only
            if 'intent' in doc.metadata and doc.metadata['intent']:
                evidence_ids.append(doc.metadata['intent'])
            elif 'stable_id' in doc.metadata and doc.metadata['stable_id']:
                evidence_ids.append(doc.metadata['stable_id'])
            elif 'filename' in doc.metadata and 'page' in doc.metadata:
                filename = doc.metadata['filename']
                page = doc.metadata['page']
                if filename and page is not None:
                    evidence_ids.append(f"{filename} p{page}")
            elif 'filename' in doc.metadata and doc.metadata['filename']:
                evidence_ids.append(doc.metadata['filename'])
        
        # Build tenant context
        tenant_context = ""
        if tenant_contract_id and self.tenant_auth:
            tenant_info = self.tenant_auth.get_tenant_info(tenant_contract_id)
            if tenant_info:
                tenant_context = f"\n入居者情報: {tenant_info['name']}様 ({tenant_info['room_number']}号室)"
        
        # Generate answer using prompt chain
        answer_chain = self.answer_prompt | self.llm_structured
        answer = answer_chain.invoke({
            "question": question,
            "evidence": evidence_text,
            "tenant_context": tenant_context,
        })
        
        # Replace LLM-generated evidence with actual document IDs for evaluation
        answer.evidence = evidence_ids
        
        # Check for PII leakage
        answer_text = f"{answer.conclusion} {answer.next_action} {answer.caveats}"
        if self._check_pii_leakage(answer_text):
            # Replace with safe message (preserve evidence_ids)
            answer = AnswerSchema(
                conclusion="回答を生成しましたが、個人情報が含まれる可能性があるため、詳細は管理会社にお問い合わせください。",
                evidence=evidence_ids,  # Preserve actual document IDs
                next_action="管理会社に直接お問い合わせください。",
                caveats="個人情報保護のため、詳細な情報は直接お問い合わせください。"
            )
        
        # Cache result
        self.query_cache.set(question, answer)
        
        return answer
