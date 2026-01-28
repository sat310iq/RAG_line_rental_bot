"""RAG answerer with Router Chain, Planner, Semantic Reranking, and structured output."""

import re
from typing import List, Dict, Optional, Literal, Any
from pydantic import BaseModel, Field
from langchain.chat_models import init_chat_model
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.documents import Document
from src.config import Config
from src.vector_store_manager import VectorStoreManager, filter_effective_documents
from src.query_cache import QueryCache
from src.tenant_auth import TenantAuth
from src.responder import Responder, ResponseSchema


class AnswerSchema(BaseModel):
    """Structured answer schema (legacy, for backward compatibility)."""
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
        
        # Initialize Responder (new schema-based response generator)
        self.responder = Responder(config)
        
        # Initialize LLM (for router/planner/reranking)
        self.llm = init_chat_model(
            config.openai_model,
            model_provider="openai"
        )
        
        # Structured output LLM (legacy, for backward compatibility)
        self.llm_structured = self.llm.with_structured_output(AnswerSchema)
        
        # Prompts
        self.router_prompt = ChatPromptTemplate.from_template("""
質問を分析して、どのデータソースから回答すべきか分類してください。

**重要**: KB CSV（15列スキーマ）に該当する質問は優先的に「faq_only」を選択してください。
特に以下のような質問はKB CSVを優先:
- 契約解除、解約、退去
- ゴミ出し、設備トラブル、ペット飼育
- よくある質問（FAQ）

分類:
- "faq_only": FAQ/KB CSVだけで回答できる質問（優先推奨）
- "pdf_only": PDF文書（契約/ガイドライン）から回答すべき質問（詳細な契約条項のみ）
- "ops_only": 運用ログから回答すべき質問（過去の対応事例）
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

**重要な回答ルール（厳守）**:
1. **推測・創作の禁止**: 根拠情報に記載されていない情報は一切含めない。推測や一般常識に基づく情報も含めない。
2. **情報不足時の対応**: 根拠情報が不十分で質問に完全に答えられない場合は、「根拠情報が不足しているため、詳細は管理会社にお問い合わせください」と明記する。
3. **FAQ優先**: FAQがあればFAQを優先し、FAQの内容を正確に反映すること。
4. **ルールの正確性**: 特に「禁止」「許可」「申請が必要」などの明確なルールがある場合は、それを正確に伝えること。根拠情報にないルールは記載しない。
5. **出典の明記**: 出典（文書ID/ページ/ログID）を必ず明記すること。
6. **不明点の案内**: 不明な点や判断が必要な場合は、管理会社への問い合わせを案内すること。

{tenant_context}

回答を生成してください。根拠情報にない情報は含めないでください。
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
        tenant_contract_id: Optional[str] = None,
        tenant_info: Optional[Dict[str, str]] = None
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
        search_debug_info = {
            "subqueries": subqueries,
            "sources": sources,
            "results_by_source": {},
            "total_documents": 0,
        }
        
        for subquery in subqueries:
            results = self.vector_store_manager.search(subquery, sources=sources)
            for source, source_docs in results.items():
                if source not in search_debug_info["results_by_source"]:
                    search_debug_info["results_by_source"][source] = []
                search_debug_info["results_by_source"][source].append({
                    "subquery": subquery,
                    "count": len(source_docs),
                    "doc_ids": [
                        doc.metadata.get('intent') or 
                        doc.metadata.get('stable_id') or 
                        (f"{doc.metadata.get('filename', '')} p{doc.metadata.get('page', '')}" if doc.metadata.get('filename') and doc.metadata.get('page') is not None else doc.metadata.get('filename', ''))
                        for doc in source_docs[:5]  # First 5 for debugging
                    ]
                })
                all_documents.extend(source_docs)
        
        search_debug_info["total_documents"] = len(all_documents)
        
        # Filter tenant-specific information
        all_documents = self._filter_tenant_info(all_documents, tenant_contract_id)
        search_debug_info["after_tenant_filter"] = len(all_documents)
        
        # Filter by effective_from/to dates (for KB CSV)
        all_documents = filter_effective_documents(all_documents)
        
        # Deduplicate
        seen_ids = set()
        unique_docs = []
        for doc in all_documents:
            doc_id = doc.metadata.get('stable_id') or hash(doc.page_content)
            if doc_id not in seen_ids:
                seen_ids.add(doc_id)
                unique_docs.append(doc)
        
        search_debug_info["after_deduplication"] = len(unique_docs)
        
        # Log debug info if no documents found
        if len(unique_docs) == 0:
            import json
            print(f"[DEBUG] No documents found for question: {question}")
            print(f"[DEBUG] Search debug info: {json.dumps(search_debug_info, indent=2, ensure_ascii=False)}")
        
        # Rerank
        reranked = self._semantic_rerank(
            question,
            unique_docs,
            self.config.rag_rerank_top_n
        )
        
        # Prioritize KB CSV documents
        kb_docs_in_results = [doc for doc in reranked if doc.metadata.get('type') == 'kb_faq']
        other_docs = [doc for doc in reranked if doc.metadata.get('type') != 'kb_faq']
        
        # Reorder: KB CSV first, then others
        reranked = kb_docs_in_results + other_docs
        reranked = reranked[:self.config.rag_rerank_top_n]
        
        search_debug_info["after_rerank"] = len(reranked)
        search_debug_info["reranked_intents"] = [
            doc.metadata.get('intent', doc.metadata.get('type', 'unknown'))
            for doc in reranked
        ]
        search_debug_info["reranked_types"] = [
            doc.metadata.get('type', 'unknown')
            for doc in reranked
        ]
        
        # Check if KB documents are found (new schema-based responses)
        kb_docs = [doc for doc in reranked if doc.metadata.get('type') == 'kb_faq']
        
        # Debug logging: Check if KB CSV is found
        if kb_docs:
            print(f"[DEBUG] KB CSV documents found: {[doc.metadata.get('intent') for doc in kb_docs]}")
        else:
            print(f"[DEBUG] No KB CSV documents in reranked results")
            print(f"[DEBUG] Reranked types: {[doc.metadata.get('type', 'unknown') for doc in reranked]}")
            print(f"[DEBUG] Reranked intents: {[doc.metadata.get('intent', 'N/A') for doc in reranked]}")
            print(f"[DEBUG] Source type: {source_type}")
            
            # Task 4: Fallback improvement - If KB CSV not found but router says faq_only, try searching FAQ collection specifically
            if source_type == "faq_only":
                print(f"[DEBUG] Router selected faq_only but no KB CSV found. Retrying FAQ-only search...")
                # Retry search with FAQ only
                faq_results = self.vector_store_manager.search(question, sources=["faq"])
                faq_docs = faq_results.get("faq", [])
                faq_kb_docs = [doc for doc in faq_docs if doc.metadata.get('type') == 'kb_faq']
                if faq_kb_docs:
                    print(f"[DEBUG] Found KB CSV in FAQ-only retry: {[doc.metadata.get('intent') for doc in faq_kb_docs]}")
                    # Filter by effective dates
                    faq_kb_docs = filter_effective_documents(faq_kb_docs)
                    if faq_kb_docs:
                        # Use KB CSV from FAQ-only search, rerank them
                        faq_kb_docs = self._semantic_rerank(
                            question,
                            faq_kb_docs,
                            self.config.rag_rerank_top_n
                        )
                        kb_docs = faq_kb_docs[:self.config.rag_rerank_top_n]
                        # Update reranked to include these KB docs at the top
                        reranked = kb_docs + [doc for doc in reranked if doc.metadata.get('type') != 'kb_faq']
                        reranked = reranked[:self.config.rag_rerank_top_n]
        
        if kb_docs:
            # Use new Responder for KB-based responses
            try:
                response_schema, human_text = self.responder.generate(
                    question, kb_docs, user_inputs=None, tenant_info=tenant_info
                )
                
                # Extract evidence IDs from citations
                evidence_ids = []
                for citation in response_schema.citations:
                    # Citation is now a CitationSchema object, not a dict
                    intent = citation.intent if hasattr(citation, 'intent') else (citation.get('intent', '') if isinstance(citation, dict) else '')
                    if intent:
                        evidence_ids.append(intent)
                
                # Build caveats with escalation info
                caveats_parts = [
                    f"カテゴリ: {response_schema.selected_category}",
                    f"緊急度: {response_schema.urgency}",
                    f"エスカレーション: {response_schema.escalation}"
                ]
                caveats = ", ".join(caveats_parts)
                
                # Store escalation_data as attribute (not in schema to avoid OpenAI compatibility issues)
                answer = AnswerSchema(
                    conclusion=human_text,
                    evidence=evidence_ids if evidence_ids else [kb_docs[0].metadata.get('intent', '')],
                    next_action=response_schema.handoff_message or "",
                    caveats=caveats
                )
                # Attach escalation_data as attribute (not part of schema)
                # escalation_data is generated in responder.generate() and stored in response_schema
                # But since we removed it from ResponseSchema for OpenAI compatibility, we need to generate it here
                if hasattr(response_schema, 'escalation_data'):
                    answer.escalation_data = response_schema.escalation_data
                elif response_schema.escalation != "bot_only" and tenant_info:
                    # Generate escalation_data if not present but escalation is needed
                    from datetime import datetime
                    answer.escalation_data = {
                        "intent": response_schema.selected_intent,
                        "category": response_schema.selected_category,
                        "question": question,
                        "tenant": {
                            "room_number": tenant_info.get('room_number', ''),
                            "name": tenant_info.get('name', ''),
                        },
                        "urgency": response_schema.urgency,
                        "escalation_type": response_schema.escalation,
                        "handoff_message": response_schema.handoff_message,
                        "timestamp": datetime.now().isoformat()
                    }
                
                # Cache result
                self.query_cache.set(question, answer)
                return answer
            except Exception as e:
                print(f"Warning: Responder failed, falling back to legacy method: {e}")
                import traceback
                traceback.print_exc()
                # Fall through to legacy method
        
        # Format evidence
        evidence_text = self._format_evidence(reranked)
        
        # Check if evidence is insufficient
        insufficient_evidence = len(reranked) == 0 or len(evidence_text.strip()) < 50
        
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
        
        # Add warning if evidence is insufficient
        if insufficient_evidence:
            evidence_text += "\n\n[注意] 根拠情報が不十分です。推測せず、管理会社への問い合わせを案内してください。"
        
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
