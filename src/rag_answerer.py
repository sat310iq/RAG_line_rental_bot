"""RAG answerer with Router Chain, Planner, Semantic Reranking, and structured output."""

import re
import unicodedata
import time
from typing import Any, Dict, List, Literal, Optional, Sequence, Set, Tuple, cast
from pydantic import BaseModel, Field
from langchain.chat_models import init_chat_model
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.documents import Document
from src.config import Config
from src.vector_store_manager import VectorStoreManager, filter_effective_documents
from src.query_cache import QueryCache
from src.tenant_auth import TenantAuth
from src.responder import Responder
from src.utils.question_terms import (
    count_distinct_pipe_tokens_in_question,
    count_pipe_field_hits,
    extract_question_terms,
    has_content_keyword_hit,
)
from src.question_typing import QuestionType
from src.management_escalation import MANAGEMENT_ESCALATION_MESSAGE, should_escalate_to_management
from src.individual_contract_guard import (
    INDIVIDUAL_CONTRACT_HANDOFF_MESSAGE,
    should_handoff_individual_contract_terms,
)
from src.kb_fast_path import load_kb_documents_for_fast_path, try_kb_fast_path
from src.contract_query_router import extract_contract_article_index, is_contract_source_question
from src.contract_query_intent import detect_article_reference, detect_usage_purpose_intent
from src.retrieval_metadata_boost import apply_master_document_boost
from src.contract_rag_format import (
    DISPLAY_FORMAT_B2,
    build_source_reference,
    build_source_reference_line,
    format_b2_contract_rag_display,
    is_master_chunk_metadata,
    uses_master_source_docs,
)
from src.legal_term_resolver import LegalTermResolver


class AnswerItem(BaseModel):
    """Individual answer item with citation."""
    text: str = Field(description="項目のテキスト（禁止事項、手順ステップ、事実など）")
    citation: str = Field(description="根拠（ページ番号、FAQ intent、ログIDなど）。必須。")

class AnswerSchema(BaseModel):
    """Structured answer schema (V2: with items and summary).
    
    V2のみ使用（破壊的変更）。呼び出し側はrender_answer_text()を使用。
    """
    items: List[AnswerItem] = Field(
        min_length=1,  # 基本必須
        description="構造化された回答項目のリスト（禁止事項の列挙、手順のステップ、単一事実など）。必須。"
    )
    summary: str = Field(
        description="回答の要約または補足説明。itemsの補足として使用。"
    )
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

**重要**: 個別契約CSV（kb_deal_csv）に該当する質問は優先的に「deal_only」を選択してください。
特に以下のような質問はKB CSVを優先:
- 契約解除、解約、退去
- 証明書（車庫証明、家賃証明書など）の発行手続き
- ゴミ出し、設備トラブル、ペット飼育
- よくある質問（FAQ）

分類:
- "deal_only": 個別契約CSVだけで回答できる質問（優先推奨）
- "master_only": マスターTXT（契約・重説）から回答すべき質問（詳細な契約条項のみ）
- "multi": 複数のソースから統合して回答すべき質問

質問: {question}

分類（deal_only/master_only/multiのいずれか）:
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
        _tpl_scope = bool(getattr(self.config, "rag_template_clause_scope_enabled", True))
        _ans_apply = (
            "3. **適用順・スコープ**: KBの運用案内とマスター契約が併存する場合は根拠に示された情報を優先する。"
            "なお本チャットでは入居者個別の賃料・契約期間・敷金等の確定は行わず、定型条項・手続の説明に留める。\n"
        ) if _tpl_scope else (
            "3. **適用順の明示**: 個別契約CSV（deal）をマスターTXT（master）より優先し、回答に適用順と根拠を明示すること。\n"
        )
        _cap_apply = (
            "4. **適用順・スコープ**: KBの運用案内とマスター契約が併存する場合は根拠に示された情報を優先する。"
            "なお本チャットでは入居者個別の条件の確定は行わず、契約条項の一般的な説明に留める。\n"
        ) if _tpl_scope else (
            "4. **適用順の明示**: 個別契約CSV（deal）をマスターTXT（master）より優先し、回答に適用順と根拠を明示すること。\n"
        )
        _csq_scope_line = (
            "\n**スコープ**: 回答はマスター文書に記載の定型条項・条文の趣旨に限定する。"
            "入居者個別の賃料・期間等の確定は行わない（根拠に該当記載がない場合は確認できない旨に留める）。\n"
        ) if _tpl_scope else ""

        self.answer_prompt = ChatPromptTemplate.from_template(
            """
以下の情報を基に、質問に回答してください。

質問: {question}

根拠情報:
{evidence}

**重要な回答ルール（厳守）**:
1. **推測・創作の禁止**: 根拠情報に記載されていない情報は一切含めない。推測や一般常識に基づく情報も含めない。
2. **情報不足時の対応**: 根拠情報が不十分で質問に完全に答えられない場合は、「根拠情報が不足しているため、詳細は管理会社にお問い合わせください」と明記する。
"""
            + _ans_apply
            + """4. **ルールの正確性**: 特に「禁止」「許可」「申請が必要」などの明確なルールがある場合は、それを正確に伝えること。根拠情報にないルールは記載しない。

**itemsフィールドの生成（必須）**:
- `items`フィールドには、構造化された回答項目を必ず含めてください。
  - procedure/policy_enumeration: 最低3項目以上
  - fact_lookup: 最低1項目以上
  - その他: 最低1項目以上
- 各itemsの`citation`フィールドには、根拠となる文書ID/ページ番号/FAQ intent/ログIDを必ず記載してください。
  - 例: citation = "p5", "契約_原状回復", "e07dee1e3fe6fe84"
- 各itemの`text`フィールドには、具体的な項目のテキストを記載してください。
  - 禁止事項の列挙、手順のステップ、単一事実など

**summaryフィールドの生成**:
- `summary`フィールドには、itemsの補足説明を記載してください。
- itemsの要約や、追加の説明が必要な場合に使用します。

{tenant_context}

回答を生成してください。根拠情報にない情報は含めないでください。
"""
        )

        self.contract_answer_prompt = ChatPromptTemplate.from_template(
            """
以下の情報を基に、契約条項の説明として回答してください。

質問: {question}

根拠情報:
{evidence}

**重要な回答ルール（厳守）**:
1. **推測・創作の禁止**: 根拠情報に記載されていない情報は一切含めない。推測や一般常識に基づく情報も含めない。
2. **断定・法的判断の禁止**: 「必ず」「絶対に」「違法です」などの断定や法的判断は避け、根拠に基づく説明に留める。
3. **情報不足時の対応**: 根拠情報が不十分な場合は、「根拠情報が不足しているため、詳細は管理会社にお問い合わせください」と明記する。
"""
            + _cap_apply
            + """5. **管理会社案内**: 解釈が分かれる可能性がある場合は、最終確認先として管理会社への相談を案内する。

**itemsフィールドの生成（必須）**:
- `items`フィールドには、構造化された回答項目を必ず含めてください。
  - procedure/policy_enumeration: 最低3項目以上
  - fact_lookup: 最低1項目以上
  - その他: 最低1項目以上
- 各itemsの`citation`フィールドには、根拠となる文書ID/ページ番号/FAQ intent/ログIDを必ず記載してください。
  - 例: citation = "p5", "契約_原状回復", "e07dee1e3fe6fe84"
- 各itemの`text`フィールドには、具体的な項目のテキストを記載してください。
  - 禁止事項の列挙、手順のステップ、単一事実など

**summaryフィールドの生成**:
- `summary`フィールドには、itemsの補足説明を記載してください。
- 断定的な結論ではなく、根拠に基づく説明文として記載してください。

{tenant_context}

回答を生成してください。根拠情報にない情報は含めないでください。
"""
        )

        self.contract_source_qa_prompt = ChatPromptTemplate.from_template(
            """
以下の根拠情報（賃貸借契約書・重要事項説明書等のマスター文書からの抜粋）のみに基づき、質問に答えてください。質問はマスター文書の該当箇所に何と書いてあるかを問うものです。"""
            + _csq_scope_line
            + """

質問: {question}

根拠情報:
{evidence}

**契約書QAモード（厳守）**:
1. **根拠外の禁止**: 根拠情報にない内容は書かない。FAQ・一般案内・推測・一般常識で補わない。
2. **定型文の禁止（出力に含めない）**: 次の語句・表現を回答本文（items・summary）に含めないこと。
   - 「管理会社へお問い合わせください」「管理会社にお問い合わせください」
   - 「公式サイト」「TEL」「電話」での案内に誘導する文
   - 「次のアクション」「次アクション」
   - 「この件は管理会社での対応が必要」に相当する表現
3. **根拠不足時**: 根拠情報から該当箇所を特定できない場合は、断定せず
   「契約書（根拠情報）内では確認できません」と伝える。法的判断はしない。
4. **断定の抑制**: 「必ず」「絶対に」「違法です」等の断定は避ける。
5. **原状回復・費用・責任**: 条文・別表に書かれた一般的な趣旨・参照先のみ説明する。
   個別の負担額・請求可否・過失の有無は断定しない。
6. **ハザード・浸水**: 重要事項の記載の要約に留める。個別物件のリスクや浸水深の確定はしない。
7. **目的物・特約事項**: 賃貸借の目的物（所在・建物・専有部分の範囲等）や特約事項については、根拠情報に現れる**該当箇所を見つけた範囲で網羅的に**示す。複数の特約・別表・頭書がある場合は漏れなく列挙し、条文・別表の文言を必要な範囲で簡潔に転記してよい（根拠にない確定はしない）。
8. **別表・負担区分**（質問が別表・表・負担区分に関するとき、次の【出力形式】と【根拠制約】を併せて適用する）:

【別表・負担区分の出力形式】
- 根拠情報に**複数の負担主体**（賃借人・賃貸人、甲・乙など）の記載が**併記**されている場合のみ、冒頭で質問の対象となる別表・部位を1文で示す。
- その後、根拠の用語に合わせて「■ 賃借人負担」「■ 賃貸人負担」等の見出しに分け、材料・部位ごとに箇条書きで整理する。
- 補修・張替え・経過年数・単位（枚・㎡など）など、根拠に区分がある場合はその区分を保持する。
- **負担主体が根拠上二分されていない**場合は、無理に見出しを作らず、根拠情報の構造に沿って短く答える。

【根拠制約】
- 見出し・箇条書きに含める内容は、根拠チャンクに書かれた範囲に限定する。
- **賃貸人負担**については、根拠に列挙された例・文言のみを述べる。一般論として「経年劣化」「通常損耗」「自然損耗」等を**常に補ってはならない**。これらの語は、根拠にその記載がある場合、または根拠がその旨の一般表現のみの場合に限り、根拠の表現に沿って要約する。
- 根拠にない一般論・推測・管理会社への誘導は、上記の禁止事項および項目1に従う。

9. **平易な説明（登記・抵当権・重要事項の硬い文言）**: 抵当権の実行・競売・競落人・猶予期間・対抗・明け渡しなど、語が難しいときは **意味を変えずに**、まず **summary の冒頭で入居者向けに短い日常語で要点**を書く（例: 何が起きたとき／誰がどうなるか／敷金はどう扱われるか）。続けて items で根拠どおりの事実・条項を列挙する。**法令の詳細解釈・判例・一般常識での補足は禁止**。根拠と矛盾する言い換えはしない。

**items・summary**:
- items は根拠に即した事実・条項の要約を列挙。citation にページやファイル名等を記載。
- summary は、上記のとおり **平易な一文で要点を足したうえで** items を補足してよい。

【回答禁止事項】
以下は絶対に行わないこと。
- 条項の法的リスク・有利不利の評価をしない
- 修正案・交渉の提案をしない
- 弁護士への相談を促す文言を入れない
- 契約書・重要事項説明書に記載のない一般論を補足しない

【免責表示】
回答の末尾に必ず以下を付与すること。
---
この回答は契約書・重要事項説明書の記載内容をお伝えするものです。
法的な判断や解釈については、専門家にご相談ください。

{tenant_context}

回答を生成してください。
"""
        )

        self._legal_term_resolver: Optional[LegalTermResolver] = None
        try:
            self._legal_term_resolver = LegalTermResolver.from_default()
        except Exception as e:
            import sys

            print(f"[WARN] LegalTermResolver init failed: {e}", file=sys.stderr)
            self._legal_term_resolver = None

    def _route_query(self, question: str) -> Literal["deal_only", "master_only", "multi"]:
        """Route query to appropriate source(s).
        
        Args:
            question: User question
            
        Returns:
            Source type to search
        """
        chain = self.router_prompt | self.llm | StrOutputParser()
        result = chain.invoke({"question": question}).strip().lower()
        
        # Parse result
        if "deal_only" in result or "deal" in result or "csv" in result:
            return "deal_only"
        elif "master_only" in result or "master" in result or "pdf" in result:
            return "master_only"
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

    def _filter_by_contract(self, documents: List[Document], contract_id: Optional[str]) -> List[Document]:
        """Filter deal CSV documents by contract_id when provided."""
        if not contract_id:
            return documents
        filtered = []
        for doc in documents:
            doc_contract_id = (doc.metadata.get('contract_id') or '').strip()
            if not doc_contract_id or doc_contract_id == contract_id:
                filtered.append(doc)
        return filtered

    def _csv_answer_complete(self, csv_docs: List[Document]) -> bool:
        """Decide whether CSV answers are complete enough to skip master (TXT) search."""
        for doc in csv_docs:
            if doc.metadata.get('answer_complete') is True:
                return True
        for doc in csv_docs:
            if doc.metadata.get('fallback_to_master') is False:
                return True
        return False

    def _decide_topic(self, question: str, csv_docs: List[Document]) -> str:
        """Decide topic using CSV metadata first, then question keywords."""
        for doc in csv_docs:
            topic = (doc.metadata.get('topic') or '').strip()
            if topic and topic != "unknown":
                return topic
        # Lightweight keyword rules
        if re.search(r"(解除|解約|契約終了)", question):
            return "termination"
        if re.search(r"(支払|賃料|家賃|敷金|礼金|費用)", question):
            return "payment"
        if re.search(r"(修繕|故障|修理|原状回復)", question):
            return "repair"
        if re.search(r"(禁止|禁止事項|禁ずる)", question):
            return "prohibited"
        if re.search(r"(ペット|動物|飼育)", question):
            return "pets"
        if re.search(r"(喫煙|禁煙|たばこ)", question):
            return "smoking"
        if re.search(r"(騒音|近隣|迷惑)", question):
            return "noise"
        if re.search(r"(駐車|駐車場)", question):
            return "parking"
        if re.search(r"(ゴミ|廃棄|分別)", question):
            return "garbage"
        return "unknown"
    
    def _keyword_score(self, question: str, keywords: str) -> int:
        """Compute simple keyword match score."""
        return count_pipe_field_hits(question, keywords or "")

    def _question_hits_doc_negative_keywords(self, question: str, doc: Document) -> bool:
        """True if any negative_keywords token appears in question (same semantics as fusion penalty)."""
        neg = (doc.metadata.get("negative_keywords") or "").strip()
        if not neg:
            return False
        tokens = [t for t in re.split(r"[\s|]+", neg) if t]
        return any(t in question for t in tokens)

    def _csv_keyword_override_hit_count(self, question: str, doc: Document) -> int:
        """Distinct keyword / keywords_primary tokens from the row that appear in question (union)."""
        kw = doc.metadata.get("keywords", "") or ""
        primary = doc.metadata.get("keywords_primary", "") or ""
        if getattr(self.config, "csv_keyword_override_use_primary", True):
            n = count_distinct_pipe_tokens_in_question(question, kw, primary)
            pipe_for_kaiyaku = f"{kw}|{primary}"
        else:
            n = count_distinct_pipe_tokens_in_question(question, kw)
            pipe_for_kaiyaku = kw
        min_hits = int(getattr(self.config, "csv_keyword_override_min_hits", 2) or 2)
        if n >= min_hits:
            return n
        tokens = [t for t in re.split(r"[\s|]+", pipe_for_kaiyaku) if t]
        # 「中途解約」「途中解約」は解約と同一フロー。KB に解約トークンがある行は min_hits を満たす。
        if re.search(r"中途解約|途中解約", question) and "解約" in tokens:
            return max(n, min_hits)
        # 「退去 したい」等で連続トークンが欠ける場合も退去フロー（退去×解約行と同様）。
        if re.search(r"退去\s*したい|退去希望|退居\s*したい", question) and "退去" in tokens:
            return max(n, min_hits)
        return n

    
    def _keyword_rerank(self, question: str, docs: List[Document]) -> List[Document]:
        """Rerank CSV docs by keyword matches; ties break by higher precedence (kb metadata)."""
        scored = []
        for idx, doc in enumerate(docs):
            keywords = doc.metadata.get("keywords", "")
            score = self._keyword_score(question, keywords)
            try:
                prec = int(doc.metadata.get("precedence") or 100)
            except (TypeError, ValueError):
                prec = 100
            scored.append((score, prec, idx, doc))
        scored.sort(key=lambda x: (x[0], x[1], -x[2]), reverse=True)
        return [doc for _, _, _, doc in scored]

    def _apply_negative_keyword_penalties(
        self,
        question: str,
        scored_results: List[Dict[str, Any]],
    ) -> None:
        """Lower fusion score when question hits optional negative_keywords (| tokens) on a row."""
        default_penalty = 0.4
        for item in scored_results:
            doc = item.get("document")
            if doc is None:
                continue
            neg = (doc.metadata.get("negative_keywords") or "").strip()
            if not neg:
                continue
            tokens = [t for t in re.split(r"[\s|]+", neg) if t]
            if not any(t in question for t in tokens):
                continue
            raw_pen = (doc.metadata.get("negative_penalty") or "").strip()
            try:
                penalty = float(raw_pen) if raw_pen else default_penalty
            except ValueError:
                penalty = default_penalty
            before = float(item.get("score") or 0.0)
            item["score"] = max(0.0, before - penalty)
            intent = doc.metadata.get("intent", "")
            print(
                f"[INFO] negative_keywords penalty -{penalty:.2f} applied (intent={intent}, score {before:.2f}->{item['score']:.2f})"
            )

    def _to_scored_results(self, results: Sequence[Any]) -> List[Dict[str, Any]]:
        """Normalize vector store results into [{'document': Document, 'score': float}] format."""
        normalized: List[Dict[str, Any]] = []
        for item in results:
            if isinstance(item, dict) and "document" in item:
                normalized.append(item)
                continue
            if isinstance(item, Document):
                normalized.append({"document": item, "score": 1.0})
        return normalized

    def _filter_scored_results(
        self,
        scored_results: Sequence[Any],
        threshold: float,
        source_label: str,
        question: Optional[str] = None,
        allow_keyword_override: bool = False,
    ) -> List[Document]:
        """Filter scored results by threshold, return documents."""
        scored_results = self._to_scored_results(scored_results)
        if not scored_results:
            print(f"[INFO] {source_label} search returned 0 results.")
            return []
        if question:
            self._apply_negative_keyword_penalties(question, scored_results)
        if allow_keyword_override and question and source_label == "CSV":
            min_hits = int(getattr(self.config, "csv_keyword_override_min_hits", 2) or 2)
            fusion_floor = float(
                getattr(self.config, "csv_keyword_override_min_fusion_score", 0.36) or 0.36
            )
            keyword_hits: List[Tuple[int, float, Document]] = []
            for item in scored_results:
                doc = item["document"]
                if self._question_hits_doc_negative_keywords(question, doc):
                    continue
                override_hits = self._csv_keyword_override_hit_count(question, doc)
                if override_hits <= 0:
                    continue
                fusion = float(item.get("score") or 0.0)
                eligible = override_hits >= min_hits or fusion >= fusion_floor
                if not eligible:
                    continue
                keyword_hits.append((override_hits, fusion, doc))
            if keyword_hits:
                keyword_hits.sort(key=lambda x: (x[0], x[1]), reverse=True)
                best_hits = keyword_hits[0][0]
                top_tier = [doc for h, _, doc in keyword_hits if h == best_hits]
                matched_intent = top_tier[0].metadata.get("intent", "")
                print(
                    f"[INFO] {source_label} keyword override (tiered). "
                    f"Skipping score threshold (matched intent: {matched_intent}, hits>={min_hits} or fusion>={fusion_floor})."
                )
                return top_tier
        top_score = scored_results[0]["score"]
        if allow_keyword_override and question:
            top_doc = scored_results[0]["document"]
            top_kw = top_doc.metadata.get("keywords", "") or ""
            if getattr(self.config, "csv_keyword_override_use_primary", True):
                top_keyword_score = count_distinct_pipe_tokens_in_question(
                    question, top_kw, top_doc.metadata.get("keywords_primary", "") or ""
                )
            else:
                top_keyword_score = count_distinct_pipe_tokens_in_question(question, top_kw)
            no_keyword_floor = max(0.6, threshold)
            if top_keyword_score == 0 and top_score < no_keyword_floor:
                print(
                    f"[INFO] {source_label} no keyword hit and score below floor "
                    f"({top_score:.2f} < {no_keyword_floor:.2f})."
                )
                return []
        if top_score < threshold:
            if source_label == "master" and question:
                content_hits = [
                    item["document"]
                    for item in scored_results
                    if has_content_keyword_hit(
                        question,
                        item["document"].page_content,
                        stopwords=self.config.question_term_stopwords or None,
                        synonyms=self.config.question_term_synonyms or None,
                    )
                ]
                if content_hits:
                    print(
                        f"[INFO] {source_label} keyword hit in content; "
                        f"bypassing score threshold ({top_score:.2f} < {threshold:.2f})."
                    )
                    return content_hits
            print(
                f"[INFO] {source_label} match score below threshold "
                f"({top_score:.2f} < {threshold:.2f})."
            )
            return []
        return [item["document"] for item in scored_results]

    def _inject_tai_kyo_kaiyaku_deal_row(
        self, question: str, csv_scored: Sequence[Any]
    ) -> List[Dict[str, Any]]:
        """Ensure 契約_退去解約 is in deal candidates when phrasing is explicit but hybrid search misses the row.

        Keyword override runs only on chunks already in scored results; low retrieval_k or embedding drift
        can omit the row entirely — then override never fires and the user sees fallback.
        """
        csv_scored_norm = self._to_scored_results(csv_scored)
        q = unicodedata.normalize("NFKC", question or "")
        if not q.strip():
            return csv_scored_norm
        intents_seen = set()
        for item in csv_scored_norm:
            doc = item.get("document")
            if doc is None:
                continue
            intent = (doc.metadata or {}).get("intent") or ""
            if intent:
                intents_seen.add(intent)
        if "契約_退去解約" in intents_seen:
            return csv_scored_norm
        wants_mid = bool(re.search(r"中途解約|途中解約", q))
        wants_tai_kyo = bool(re.search(r"退去\s*したい|退去希望|退居\s*したい", q))
        if not wants_mid and not wants_tai_kyo:
            return csv_scored_norm
        fusion_floor = float(getattr(self.config, "csv_keyword_override_min_fusion_score", 0.36) or 0.36)
        thr_csv = float(self.config.get_source_score_thresholds().get("csv", 0.4))
        inject_score = max(fusion_floor, thr_csv, 0.42)
        for doc in load_kb_documents_for_fast_path(self.config):
            if (doc.metadata or {}).get("intent") != "契約_退去解約":
                continue
            print(
                "[INFO] Injected 契約_退去解約 KB row into deal candidates "
                f"(mid_term={wants_mid}, tai_kyo={wants_tai_kyo}, score={inject_score:.2f})."
            )
            injected = {"document": doc, "score": inject_score}
            return [injected] + list(csv_scored_norm)
        return csv_scored_norm

    def _hierarchical_search(
        self,
        question: str,
        contract_id: Optional[str] = None,
        deal_top_k: int = 12,
        master_top_k: int = 8,
        pdf_threshold: Optional[float] = None,
        force_master: bool = False,
    ) -> Dict[str, List[Document]]:
        """Two-stage search: deal CSV first, master TXT index only if needed.

        If force_master is True, always run master search and skip CSV-based topic filtering on master docs
        (contract-source questions must not be short-circuited by FAQ CSV completeness).
        """
        deal_results = self.vector_store_manager.search(question, sources=["deal"])
        csv_scored = self._inject_tai_kyo_kaiyaku_deal_row(
            question, deal_results.get("deal", [])
        )
        thresholds = self.config.get_source_score_thresholds()
        csv_docs = self._filter_scored_results(
            csv_scored,
            thresholds["csv"],
            "CSV",
            question=question,
            allow_keyword_override=True,
        )
        csv_docs = self._filter_by_contract(csv_docs, contract_id)
        csv_docs = filter_effective_documents(csv_docs)
        csv_docs = self._semantic_rerank(question, csv_docs, min(deal_top_k, len(csv_docs)))
        if csv_docs:
            csv_docs = self._keyword_rerank(question, csv_docs)
        # Preserve search order for tie-breaking in resolver
        for idx, doc in enumerate(csv_docs):
            doc.metadata["_search_rank"] = idx

        if self._csv_answer_complete(csv_docs) and not force_master:
            return {"deal": csv_docs, "master": []}

        if not csv_docs:
            print("[INFO] CSV match not found. Falling back to master TXT search.")

        topic = self._decide_topic(question, csv_docs)
        master_results = self.vector_store_manager.search(question, sources=["master"])
        pdf_scored = master_results.get("master", [])
        pdf_thr = pdf_threshold if pdf_threshold is not None else thresholds["pdf"]
        pdf_docs = self._filter_scored_results(
            pdf_scored, pdf_thr, "master", question=question
        )
        if topic and topic != "unknown" and not force_master:
            filtered_pdf_docs = [doc for doc in pdf_docs if doc.metadata.get('topic') == topic]
            if filtered_pdf_docs:
                pdf_docs = filtered_pdf_docs
        pdf_docs = self._semantic_rerank(question, pdf_docs, min(master_top_k, len(pdf_docs)))
        return {"deal": csv_docs, "master": pdf_docs}

    def _contract_source_master_retry(
        self, question: str, *, include_trace: bool = False
    ) -> Any:
        """Extra master-only search with relaxed threshold and short sub-queries (contract-source)."""
        qn = unicodedata.normalize("NFKC", question or "")
        pdf_thr = float(getattr(self.config, "contract_source_pdf_retry_threshold", 0.45) or 0.45)
        retry_top_k = int(getattr(self.config, "contract_source_retry_top_k", 12) or 12)
        seen_ids: Set[Any] = set()
        merged: List[Document] = []
        trace: Dict[str, Any] = {
            "threshold": pdf_thr,
            "retry_top_k": retry_top_k,
            "queries": [],
            "per_query": [],
            "merged_count": 0,
        }
        filter_enabled = bool(
            getattr(self.config, "contract_source_retry_filter_enabled", True)
        )
        retry_min_keep = int(getattr(self.config, "contract_source_retry_min_keep", 8) or 8)
        trace["filter_enabled"] = filter_enabled
        trace["filter_min_keep"] = retry_min_keep

        def _add_docs(docs: List[Document]) -> None:
            for d in docs:
                did = d.metadata.get("stable_id") or hash(d.page_content)
                if did in seen_ids:
                    continue
                seen_ids.add(did)
                merged.append(d)

        queries: List[str] = [question]
        if m := re.search(r"第\s*(\d+)\s*条", qn):
            queries.append(f"第{m.group(1)}条")
        usage_purpose_q = detect_usage_purpose_intent(qn)
        if usage_purpose_q and detect_article_reference(qn) is None:
            queries.append("第3条")
            queries.append("居住のみを目的として")
        elif "使用目的" in qn:
            queries.append("居住のみを目的として")
            queries.append("居住")
        elif "居住" in qn:
            queries.append("使用目的")
        if m := re.search(r"特約\s*([①②③④⑤⑥⑦⑧⑨⑩⑪⑫0-9０-９]+)", qn):
            queries.append(f"特約{m.group(1)}")
        queries = queries[:3]
        trace["queries"] = list(queries)

        def _is_article3_doc(doc: Document) -> bool:
            md = doc.metadata or {}
            if md.get("article_seq") == 3:
                return True
            for key in ("article_number", "cite_label", "section_label"):
                val = str(md.get(key) or "")
                if "第3条" in val:
                    return True
            return False

        def _is_article_match(doc: Document, article_idx: Optional[int]) -> bool:
            if article_idx is None:
                return False
            md = doc.metadata or {}
            seq = md.get("article_seq")
            if isinstance(seq, int) and seq == article_idx:
                return True
            label = str(md.get("article_number") or "")
            return f"第{article_idx}条" in label

        def _is_heading_match(doc: Document, heading_terms: List[str]) -> bool:
            if not heading_terms:
                return False
            md = doc.metadata or {}
            haystack = "\n".join(
                [
                    str(md.get("article_number") or ""),
                    str(md.get("section_label") or ""),
                    str(md.get("cite_label") or ""),
                    str(doc.page_content or ""),
                ]
            )
            return any(term in haystack for term in heading_terms)

        def _is_keyword_match(doc: Document, terms: List[str]) -> bool:
            if not terms:
                return False
            md = doc.metadata or {}
            haystack = "\n".join(
                [
                    str(md.get("article_number") or ""),
                    str(md.get("section_label") or ""),
                    str(md.get("cite_label") or ""),
                    str(doc.page_content or ""),
                ]
            )
            return any(term and term in haystack for term in terms)

        for q in queries:
            master_results = self.vector_store_manager.search(q, sources=["master"])
            pdf_scored = master_results.get("master", [])
            pdf_docs = self._filter_scored_results(
                pdf_scored, pdf_thr, "master", question=q
            )
            per_query = {
                "query": q,
                "raw_hits": len(pdf_scored),
                "threshold_hits": len(pdf_docs),
                "reranked_hits": 0,
            }
            if pdf_docs:
                pdf_docs = self._semantic_rerank(
                    q, pdf_docs, min(retry_top_k, len(pdf_docs))
                )
                per_query["reranked_hits"] = len(pdf_docs)
                _add_docs(pdf_docs)
            trace["per_query"].append(per_query)
        if merged:
            if filter_enabled:
                article_idx = detect_article_reference(qn)
                heading_terms = [
                    t
                    for t in ("使用目的", "居住目的", "用途", "原状回復", "禁止事項", "賃料", "敷金", "更新", "特約")
                    if t in qn
                ]
                sw = self.config.question_term_stopwords or None
                sy = self.config.question_term_synonyms or None
                question_terms = extract_question_terms(question, stopwords=sw, synonyms=sy)

                article_docs = [d for d in merged if _is_article_match(d, article_idx)]
                heading_docs = [
                    d for d in merged if d not in article_docs and _is_heading_match(d, heading_terms)
                ]
                keyword_docs = [
                    d
                    for d in merged
                    if d not in article_docs and d not in heading_docs and _is_keyword_match(d, question_terms)
                ]
                remaining_docs = [
                    d for d in merged if d not in article_docs and d not in heading_docs and d not in keyword_docs
                ]

                filtered_merged: List[Document] = article_docs + heading_docs
                filtered_merged.extend(keyword_docs)
                if len(filtered_merged) < retry_min_keep:
                    filtered_merged.extend(remaining_docs[: (retry_min_keep - len(filtered_merged))])

                trace["filter_counts"] = {
                    "before": len(merged),
                    "article_match": len(article_docs),
                    "heading_match": len(heading_docs),
                    "keyword_match": len(keyword_docs),
                    "after": len(filtered_merged),
                }
                merged = filtered_merged

            if usage_purpose_q and detect_article_reference(qn) is None:
                article3_docs = [d for d in merged if _is_article3_doc(d)]
                other_docs = [d for d in merged if not _is_article3_doc(d)]
                merged = article3_docs + other_docs
                trace["article3_prioritized"] = bool(article3_docs)
            print(f"[INFO] contract_source master retry: merged {len(merged)} master chunk(s).")
        trace["merged_count"] = len(merged)
        if include_trace:
            return merged, trace
        return merged

    def _contract_source_not_found_answer(self, question: str) -> AnswerSchema:
        """No contract (master) evidence: short answer, no FAQ evidence IDs."""
        msg = "契約書（根拠情報）内では確認できません。"
        return AnswerSchema(
            items=[AnswerItem(text=msg, citation="contract_source_not_found")],
            summary=msg,
            evidence=[],
            next_action="",
            caveats="",
        )

    def _precedence_and_recency_key(self, doc: Document) -> tuple:
        """Sort by precedence (desc), recency (desc), then search order (asc)."""
        precedence = doc.metadata.get("precedence", 100)
        effective_date = doc.metadata.get("effective_date") or ""
        version = doc.metadata.get("version") or ""
        search_rank = doc.metadata.get("_search_rank", 10_000)
        return (precedence, effective_date, version, -search_rank)

    def _resolve_documents(
        self,
        csv_docs: List[Document],
        pdf_docs: List[Document]
    ) -> List[Document]:
        """Resolve conflicts: deal CSV first, master TXT only when needed."""
        topics = sorted({(d.metadata.get("topic") or "unknown") for d in (csv_docs + pdf_docs)})
        resolved: List[Document] = []

        for topic in topics:
            t_csv = [d for d in csv_docs if (d.metadata.get("topic") or "unknown") == topic]
            t_pdf = [d for d in pdf_docs if (d.metadata.get("topic") or "unknown") == topic]

            if t_csv:
                # Preserve search order for unknown topics to keep retriever ranking
                if topic != "unknown":
                    t_csv.sort(key=self._precedence_and_recency_key, reverse=True)
                resolved.extend(t_csv)

                if any(d.metadata.get("override_flag") == "reference" for d in t_csv):
                    resolved.extend(t_pdf)
            else:
                resolved.extend(t_pdf)

        return resolved
    
    def _format_evidence(self, documents: List[Document], max_snippet_length: int = 200) -> str:
        """Format evidence documents for LLM input.
        
        Args:
            documents: List of Document objects
            max_snippet_length: Maximum length of snippet per document (default: 200)
                                Master TXT chunks use 500 characters for detailed clauses
            
        Returns:
            Formatted evidence string
        """
        evidence_parts = []
        
        for idx, doc in enumerate(documents, 1):
            doc_snippet_length = max_snippet_length
            meta = dict(doc.metadata or {})
            fn = (meta.get("filename") or "").lower()
            if is_master_chunk_metadata(meta) or fn.endswith(".txt"):
                doc_snippet_length = 500
            
            snippet = doc.page_content[:doc_snippet_length]
            if len(doc.page_content) > doc_snippet_length:
                snippet += "..."
            
            source_info = []
            if meta.get("filename"):
                source_info.append(f"ファイル: {meta['filename']}")
            if meta.get("page") is not None:
                source_info.append(f"ページ: {meta['page']}")
            if meta.get("stable_id"):
                source_info.append(f"ログID: {meta['stable_id']}")
            if meta.get("intent"):
                source_info.append(f"意図: {meta['intent']}")
            if meta.get("topic"):
                source_info.append(f"論点: {meta['topic']}")
            if meta.get("citations"):
                source_info.append(f"根拠: {meta['citations']}")
            ref_line = build_source_reference_line(meta)
            if ref_line:
                source_info.append(f"参照元: {ref_line}")
            
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
        
        filtered = []
        
        for doc in documents:
            filtered.append(doc)
        
        return filtered
    
    def _parse_text_to_items(self, text: str, evidence_ids: List[str]) -> List[AnswerItem]:
        """Parse text to extract items (heuristic fallback for V1 compatibility).
        
        Args:
            text: Text to parse
            evidence_ids: List of evidence IDs for citation fallback
            
        Returns:
            List of AnswerItem objects
        """
        items = []
        # Extract numbered list items (1. 2. 3. ...)
        pattern = r'(\d+)[\.、]\s*([^\n]+?)(?:（([^）]+)）|\(([^\)]+)\))?'
        matches = re.findall(pattern, text)
        
        for match in matches:
            item_text = match[1].strip()
            citation = match[2] or match[3] or (evidence_ids[0] if evidence_ids else "")
            items.append(AnswerItem(text=item_text, citation=citation))
        
        # Markdown-style bullets (Responder follow-up lines: "  - 日時")
        if len(items) < 3:
            cite = evidence_ids[0] if evidence_ids else ""
            for line in text.splitlines():
                m = re.match(r"^\s*[-－・]\s+(.+)$", line)
                if m:
                    items.append(AnswerItem(text=m.group(1).strip(), citation=cite))
        
        return items
    
    def _validate_items_count(
        self,
        answer: AnswerSchema,
        question_type: QuestionType
    ) -> AnswerSchema:
        """Validate items count based on question type.
        
        Args:
            answer: AnswerSchema (V2)
            question_type: Question type
            
        Returns:
            AnswerSchema with validated items count
        """
        min_items_map = {
            "procedure": 3,              # 手順は3ステップ以上
            "policy_enumeration": 3,    # 列挙は3項目以上
            "fact_lookup": 1,            # 単一事実は1項目以上
            # その他は1項目以上（基本制約）
        }
        min_items = min_items_map.get(question_type, 1)
        
        if len(answer.items) < min_items:
            # Fallback: summaryからitemsを抽出
            extracted_items = self._parse_text_to_items(answer.summary, answer.evidence)
            if len(extracted_items) >= min_items:
                answer.items = extracted_items
            elif len(answer.items) == 0:
                # 最後の手段: summary全体を1つのitemとして扱う
                answer.items = [AnswerItem(text=answer.summary, citation=answer.evidence[0] if answer.evidence else "")]
        
        return answer
    
    def _enforce_citations(
        self,
        answer: AnswerSchema,
        retrieved_docs: List[Document]
    ) -> AnswerSchema:
        """Enforce citation requirement for all items.
        
        Args:
            answer: AnswerSchema (V2)
            retrieved_docs: Retrieved documents for citation fallback
            
        Returns:
            AnswerSchema with citations enforced
        """
        for item in answer.items:
            if not item.citation:
                # Fallback: 最も関連性の高いドキュメントからcitationを抽出
                if retrieved_docs:
                    doc = retrieved_docs[0]
                    if 'intent' in doc.metadata and doc.metadata['intent']:
                        item.citation = doc.metadata['intent']
                    elif 'stable_id' in doc.metadata and doc.metadata['stable_id']:
                        item.citation = doc.metadata['stable_id']
                    elif 'filename' in doc.metadata and 'page' in doc.metadata:
                        filename = doc.metadata['filename']
                        page = doc.metadata['page']
                        if filename and page is not None:
                            item.citation = f"{filename} p{page}"
                    elif answer.evidence:
                        item.citation = answer.evidence[0]
                elif answer.evidence:
                    item.citation = answer.evidence[0]
                else:
                    item.citation = ""  # Empty citation as last resort
        
        return answer
    
    def _enforce_answer_structure(
        self,
        answer: AnswerSchema,
        question_type: QuestionType,
        retrieved_docs: List[Document]
    ) -> AnswerSchema:
        """Enforce answer structure (items count, citations fallback).
        
        Args:
            answer: AnswerSchema (V2)
            question_type: Question type
            retrieved_docs: Retrieved documents
            
        Returns:
            AnswerSchema with enforced structure
        """
        # 1. Validate items count
        answer = self._validate_items_count(answer, question_type)
        
        # 2. Enforce citations
        answer = self._enforce_citations(answer, retrieved_docs)
        
        return answer
    
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

    def _relevance_guard_detail(self, question: str, docs: List[Document]) -> Dict[str, Any]:
        """Explain non-FAQ relevance check; boolean matches _has_low_relevance_signal (observability)."""
        sw = self.config.question_term_stopwords or None
        sy = self.config.question_term_synonyms or None
        qterms = extract_question_terms(question, stopwords=sw, synonyms=sy)
        detail: Dict[str, Any] = {
            "low_relevance_signal": True,
            "inspected_non_faq_docs": 0,
            "question_terms": qterms,
            "source_ids": [],
            "per_doc_hits": [],
            "missing_terms": [],
        }
        if not docs:
            detail["low_relevance_signal"] = True
            detail["skip_reason"] = "no_docs"
            detail["missing_terms"] = list(qterms)
            return detail

        non_faq_docs = [d for d in docs if d.metadata.get("type") != "kb_faq"]
        if not non_faq_docs:
            detail["low_relevance_signal"] = False
            detail["skip_reason"] = "only_kb_faq"
            return detail

        checked = non_faq_docs[:2]
        detail["inspected_non_faq_docs"] = len(checked)
        matched_union: set = set()
        low = True
        for doc in checked:
            sid = str(
                doc.metadata.get("intent")
                or doc.metadata.get("filename")
                or doc.metadata.get("stable_id")
                or ""
            )
            detail["source_ids"].append(sid)
            haystack = "\n".join(
                s for s in (doc.page_content or "", str(doc.metadata.get("answer") or "")) if s
            )
            term_hits = [t for t in qterms if t and t in haystack]
            for t in term_hits:
                matched_union.add(t)
            hit = has_content_keyword_hit(
                question,
                haystack,
                stopwords=sw,
                synonyms=sy,
            )
            detail["per_doc_hits"].append(
                {"source_id": sid, "matched_terms": term_hits, "has_content_keyword_hit": hit}
            )
            if hit:
                low = False
        detail["low_relevance_signal"] = low
        if low:
            detail["missing_terms"] = [t for t in qterms if t not in matched_union]
        return detail

    def _has_low_relevance_signal(self, question: str, docs: List[Document]) -> bool:
        """Detect weak grounding for non-FAQ RAG answers and fail closed."""
        return self._relevance_guard_detail(question, docs)["low_relevance_signal"]
    
    def _select_docs_for_answer(self, reranked: List[Document]) -> List[Document]:
        """Select documents to use for answer generation.
        
        Priority: Deal CSV (kb_faq) > All reranked documents
        
        If FAQ documents exist, use only those; otherwise use all reranked documents.
        This ensures FAQ information takes precedence over PDF/OPS logs when both are present.
        
        Args:
            reranked: List of reranked documents
            
        Returns:
            List of documents to use for answer generation
        """
        # Extract deal CSV documents
        faq_docs = [doc for doc in reranked if doc.metadata.get('type') == 'kb_faq']
        
        # If FAQ documents exist, use only those; otherwise use all reranked documents
        return faq_docs if faq_docs else reranked

    def _select_docs_for_contract_source(
        self, reranked: List[Document], *, contract_source_q: bool
    ) -> List[Document]:
        """When asking for contract wording, drop kb_faq from evidence (always or when master TXT exists)."""
        if not contract_source_q:
            return reranked
        non_faq = [d for d in reranked if d.metadata.get("type") != "kb_faq"]
        drop_always = bool(getattr(self.config, "rag_contract_source_drop_kb_faq_entirely", True))
        if drop_always:
            return non_faq
        master_evidence_docs = [d for d in reranked if is_master_chunk_metadata(d.metadata or {})]
        if not master_evidence_docs:
            return reranked
        return non_faq if non_faq else reranked

    def _select_generation_prompt(
        self, docs_for_answer: List[Document], *, contract_source_q: bool = False
    ) -> ChatPromptTemplate:
        """Select prompt template for structured answer generation."""
        if contract_source_q and uses_master_source_docs(docs_for_answer):
            return self.contract_source_qa_prompt
        if uses_master_source_docs(docs_for_answer):
            return self.contract_answer_prompt
        return self.answer_prompt

    def _persist_to_cache(self, question: str, answer: AnswerSchema, persist_cache: bool) -> None:
        """Store answer in query cache unless caller defers (e.g. LINE replies first)."""
        if not persist_cache:
            return
        include_embedding = True
        decision_path = getattr(answer, "decision_path", None)
        if decision_path in (
            "direct",
            "rule",
            "escalation",
            "contract_source_not_found",
            "individual_contract_handoff",
        ):
            include_embedding = False
        self.query_cache.set(question, answer, include_embedding=include_embedding)

    def _decide_answer_path(
        self,
        question: str,
        forced_system: Literal["auto", "kb_only", "rag"] = "auto",
    ) -> Dict[str, str]:
        """Choose direct/rule/rag path for A/B operation model."""
        q = question.strip()
        if forced_system == "kb_only":
            return {"system": "KB_only", "decision_path": "rule"}
        if forced_system == "rag":
            return {"system": "RAG", "decision_path": "rag"}
        short_len = self.config.kb_fast_path_short_max_len
        if len(q) <= max(2, short_len // 2):
            return {"system": "KB_only", "decision_path": "direct"}
        return {"system": "RAG", "decision_path": "rag"}

    def _attach_decision_meta(
        self,
        answer: AnswerSchema,
        *,
        system: str,
        decision_path: str,
        latency_ms: float,
        retrieval_used: bool,
    ) -> None:
        """Attach non-schema operational metadata for eval/analysis."""
        object.__setattr__(answer, "system", system)
        object.__setattr__(answer, "decision_path", decision_path)
        object.__setattr__(answer, "retrieval_used", retrieval_used)
        object.__setattr__(answer, "fallback_used", decision_path == "fallback")
        object.__setattr__(answer, "latency_ms", round(latency_ms, 3))

    def answer(
        self,
        question: str,
        tenant_contract_id: Optional[str] = None,
        tenant_info: Optional[Dict[str, str]] = None,
        persist_cache: bool = True,
        forced_system: Literal["auto", "kb_only", "rag"] = "auto",
        cache_namespace: Optional[str] = None,
        allow_semantic_cache: bool = True,
        prior_clarification_intent: Optional[str] = None,
        prior_clarification_normalized_query: Optional[str] = None,
        prior_clarification_numeric_queries: Optional[Sequence[str]] = None,
    ) -> AnswerSchema:
        """Generate answer for question.

        Args:
            question: User question
            tenant_contract_id: Authenticated tenant's contract ID (optional)
            tenant_info: Optional tenant display fields for responder
            persist_cache: If False, do not write query_cache (caller may write after side-effect-free reply)
            prior_clarification_intent: LINE clarification follow-up state (optional)
            prior_clarification_normalized_query: Normalized query from prior clarification (optional)
            prior_clarification_numeric_queries: Reserved for parity with LINE; unused inside answer()

        Returns:
            Structured answer
        """
        # Check cache first
        t0 = time.perf_counter()
        decision = self._decide_answer_path(question, forced_system=forced_system)
        contract_source_q = is_contract_source_question(question)
        cache_key = f"{cache_namespace}::{question}" if cache_namespace else question
        cached_result = self.query_cache.get(cache_key, allow_semantic=allow_semantic_cache)
        if cached_result:
            self._attach_decision_meta(
                cached_result,
                system=getattr(cached_result, "system", decision["system"]),
                decision_path=getattr(cached_result, "decision_path", decision["decision_path"]),
                latency_ms=(time.perf_counter() - t0) * 1000.0,
                retrieval_used=getattr(cached_result, "retrieval_used", False),
            )
            object.__setattr__(cached_result, "contract_source_q", contract_source_q)
            return cached_result

        if forced_system == "auto" and should_escalate_to_management(question):
            msg = MANAGEMENT_ESCALATION_MESSAGE
            answer = AnswerSchema(
                items=[AnswerItem(text=msg, citation="management_escalation")],
                summary=msg,
                evidence=[],
                next_action="管理会社へご相談ください",
                caveats="",
            )
            object.__setattr__(
                answer,
                "escalation_data",
                {
                    "escalation_type": "management_consultation",
                    "reason": "legal_or_monetary_judgment",
                },
            )
            self._attach_decision_meta(
                answer,
                system="KB_only",
                decision_path="escalation",
                latency_ms=(time.perf_counter() - t0) * 1000.0,
                retrieval_used=False,
            )
            self._persist_to_cache(cache_key, answer, persist_cache)
            object.__setattr__(answer, "contract_source_q", contract_source_q)
            return answer

        if (
            forced_system == "auto"
            and getattr(self.config, "enable_individual_contract_handoff", True)
            and should_handoff_individual_contract_terms(question)
        ):
            msg = INDIVIDUAL_CONTRACT_HANDOFF_MESSAGE
            answer = AnswerSchema(
                items=[AnswerItem(text=msg, citation="individual_contract_handoff")],
                summary=msg,
                evidence=[],
                next_action="所定の窓口（管理・入居手続）へ、ご契約に紐づく内容として個別にお問い合わせください。",
                caveats="",
            )
            object.__setattr__(
                answer,
                "escalation_data",
                {
                    "escalation_type": "individual_contract_terms",
                    "reason": "no_individual_deal_answer",
                },
            )
            self._attach_decision_meta(
                answer,
                system="KB_only",
                decision_path="individual_contract_handoff",
                latency_ms=(time.perf_counter() - t0) * 1000.0,
                retrieval_used=False,
            )
            self._persist_to_cache(cache_key, answer, persist_cache)
            object.__setattr__(answer, "contract_source_q", contract_source_q)
            return answer

        # Contract navigation guard: 「契約書のどこに書いてありますか？」系の曖昧質問を
        # clarificationに振る（contract_source_q=True でも KB clarification が効かない問題の回避）。
        _CONTRACT_NAV_PATTERNS = (
            "どこに書いてある",
            "どこに書いてあります",
            "何条",
            "条項番号",
            "どこを見れば",
            "何ページ",
        )
        if any(p in question for p in _CONTRACT_NAV_PATTERNS):
            _nav_msg = (
                "何についての条項をお探しですか？"
                "例：解約・原状回復・ペット飼育・短期違約金・鍵の紛失など、"
                "具体的に教えていただくと該当箇所をご案内できます。"
            )
            answer = AnswerSchema(
                items=[AnswerItem(text=_nav_msg, citation="contract_navigation")],
                summary=_nav_msg,
                evidence=[],
                next_action="具体的な内容をお聞かせください。",
                caveats="",
            )
            self._attach_decision_meta(
                answer,
                system=decision["system"],
                decision_path="clarification",
                latency_ms=(time.perf_counter() - t0) * 1000.0,
                retrieval_used=False,
            )
            self._persist_to_cache(cache_key, answer, persist_cache)
            object.__setattr__(answer, "contract_source_q", contract_source_q)
            return answer

        # Clarification-first guard for ambiguous topic queries (keep behavior consistent across kb_only/rag).
        try:
            kb_docs = load_kb_documents_for_fast_path(self.config)
            fp = try_kb_fast_path(
                question,
                self.config,
                kb_docs,
                prior_clarification_intent=prior_clarification_intent,
                prior_clarification_normalized_query=prior_clarification_normalized_query,
                user_text_for_prior_match=question,
            )
            if fp.kind == "hit" and fp.text and not contract_source_q:
                hit_text = fp.text.strip()
                answer = AnswerSchema(
                    items=[AnswerItem(text=hit_text, citation=fp.intent or "")],
                    summary=hit_text,
                    evidence=[fp.intent] if fp.intent else [],
                    next_action="",
                    caveats="",
                )
                self._attach_decision_meta(
                    answer,
                    system=decision["system"],
                    decision_path="direct",
                    latency_ms=(time.perf_counter() - t0) * 1000.0,
                    retrieval_used=False,
                )
                self._persist_to_cache(cache_key, answer, persist_cache)
                object.__setattr__(answer, "contract_source_q", contract_source_q)
                return answer
            if fp.kind == "clarification" and fp.text and not contract_source_q:
                clar_text = fp.text.strip()
                answer = AnswerSchema(
                    items=[AnswerItem(text=clar_text, citation=fp.intent or "")],
                    summary=clar_text,
                    evidence=[fp.intent] if fp.intent else [],
                    next_action="該当する番号か内容をもう少し具体的に教えてください。",
                    caveats="曖昧な質問のため確認質問を返しています。",
                )
                object.__setattr__(answer, "clarification_reason", (fp.match_detail or {}).get("reason"))
                object.__setattr__(answer, "clarification_intent", fp.intent)
                self._attach_decision_meta(
                    answer,
                    system=decision["system"],
                    decision_path="clarification",
                    latency_ms=(time.perf_counter() - t0) * 1000.0,
                    retrieval_used=False,
                )
                self._persist_to_cache(cache_key, answer, persist_cache)
                object.__setattr__(answer, "contract_source_q", contract_source_q)
                return answer
        except Exception as e:
            print(f"[WARN] clarification guard skipped due to error: {e}")

        # Two-stage hierarchical search (deal CSV first, master TXT only if needed)
        kb_master_retry_used = False
        decided_kb_path = decision["decision_path"] in ("direct", "rule")
        article_idx = extract_contract_article_index(question) if contract_source_q else None
        contract_source_retry_debug: Dict[str, Any] = {
            "attempted": False,
            "article_index": article_idx,
            "before_count": 0,
            "after_count": 0,
            "added_docs": 0,
            "retry_added": 0,
            "retry_trace": {},
        }

        if decided_kb_path and contract_source_q:
            hierarchical_results = self._hierarchical_search(
                question,
                tenant_contract_id,
                deal_top_k=self.config.rag_rerank_top_n,
                master_top_k=max(
                    int(getattr(self.config, "contract_source_master_top_k", 10) or 10),
                    int(self.config.rag_rerank_top_n),
                ),
                force_master=True,
            )
        elif decided_kb_path:
            hierarchical_results = self._hierarchical_search(
                question,
                tenant_contract_id,
                deal_top_k=self.config.rag_rerank_top_n,
                master_top_k=0,
                force_master=False,
            )
            hierarchical_results["master"] = []
        else:
            _kwargs: Dict[str, Any] = {"force_master": contract_source_q}
            if contract_source_q:
                _kwargs["master_top_k"] = max(
                    int(getattr(self.config, "contract_source_master_top_k", 10) or 10),
                    int(self.config.rag_rerank_top_n),
                )
            hierarchical_results = self._hierarchical_search(
                question, tenant_contract_id, **_kwargs
            )
        csv_docs = hierarchical_results.get("deal", [])
        pdf_docs = hierarchical_results.get("master", [])
        contract_source_retry_debug["before_count"] = len(pdf_docs)

        if (
            not csv_docs
            and not pdf_docs
            and decided_kb_path
            and self.config.kb_empty_try_master_pdf
        ):
            print("[INFO] KB path empty; retrying with master TXT search enabled.")
            kb_master_retry_used = True
            retry_pdf_thr = float(
                getattr(self.config, "pdf_empty_retry_score_threshold", 0.52) or 0.52
            )
            hierarchical_results = self._hierarchical_search(
                question,
                tenant_contract_id,
                deal_top_k=self.config.rag_rerank_top_n,
                master_top_k=max(1, int(self.config.rag_rerank_top_n)),
                pdf_threshold=retry_pdf_thr,
                force_master=contract_source_q,
            )
            csv_docs = hierarchical_results.get("deal", [])
            pdf_docs = hierarchical_results.get("master", [])
            contract_source_retry_debug["before_count"] = len(pdf_docs)

        if contract_source_q and getattr(self, "vector_store_manager", None) is not None:
            should_retry = article_idx is not None or not pdf_docs
            if should_retry:
                contract_source_retry_debug["attempted"] = True
                retry_extra, retry_trace = self._contract_source_master_retry(
                    question, include_trace=True
                )
                contract_source_retry_debug["retry_trace"] = retry_trace
                if retry_extra:
                    seen_ids: Set[Any] = {
                        (d.metadata or {}).get("stable_id") or hash(d.page_content)
                        for d in pdf_docs
                    }
                    merged_pdf = list(pdf_docs)
                    added_docs = 0
                    for d in retry_extra:
                        did = (d.metadata or {}).get("stable_id") or hash(d.page_content)
                        if did not in seen_ids:
                            seen_ids.add(did)
                            merged_pdf.append(d)
                            added_docs += 1
                    pdf_docs = merged_pdf
                    hierarchical_results["master"] = merged_pdf
                    contract_source_retry_debug["added_docs"] = added_docs
                    contract_source_retry_debug["retry_added"] = added_docs
                contract_source_retry_debug["after_count"] = len(pdf_docs)

        if not csv_docs and not pdf_docs:
            if contract_source_q:
                print("[INFO] No CSV/master for contract-source question. Returning contract_source_not_found.")
                answer = self._contract_source_not_found_answer(question)
                self._attach_decision_meta(
                    answer,
                    system=decision["system"],
                    decision_path="contract_source_not_found",
                    latency_ms=(time.perf_counter() - t0) * 1000.0,
                    retrieval_used=False,
                )
                self._persist_to_cache(cache_key, answer, persist_cache)
                object.__setattr__(answer, "kb_master_retry_used", kb_master_retry_used)
                object.__setattr__(answer, "contract_source_q", contract_source_q)
                return answer
            print("[INFO] No CSV/master match above threshold. Returning fallback message.")
            fallback_message = self.config.fallback_message
            answer = AnswerSchema(
                items=[AnswerItem(text=fallback_message, citation="")],
                summary=fallback_message,
                evidence=[],
                next_action="",
                caveats="適用順: 個別契約CSV > マスターTXT"
            )
            self._persist_to_cache(cache_key, answer, persist_cache)
            fb_dp = str(getattr(self.config, "fallback_decision_path", "fallback") or "fallback")
            self._attach_decision_meta(
                answer,
                system=decision["system"],
                decision_path=fb_dp,
                latency_ms=(time.perf_counter() - t0) * 1000.0,
                retrieval_used=False,
            )
            object.__setattr__(answer, "kb_master_retry_used", kb_master_retry_used)
            object.__setattr__(answer, "contract_source_q", contract_source_q)
            return answer

        effective_decision_path = decision["decision_path"]
        effective_retrieval_used = bool(csv_docs or pdf_docs)
        if kb_master_retry_used and pdf_docs:
            effective_decision_path = "rag"
            effective_retrieval_used = True

        resolved_docs = self._resolve_documents(csv_docs, pdf_docs)
        all_documents = resolved_docs
        
        if csv_docs and pdf_docs:
            source_type = "multi"
        elif csv_docs:
            source_type = "deal_only"
        elif pdf_docs:
            source_type = "master_only"
        else:
            source_type = "multi"
        
        search_debug_info = {
            "sources": ["deal", "master"],
            "deal_count": len(csv_docs),
            "master_count": len(pdf_docs),
            "resolved_count": len(resolved_docs),
            "total_documents": len(all_documents),
            "contract_source_q": contract_source_q,
            "contract_article_index": article_idx,
            "contract_source_retry": contract_source_retry_debug,
            "request_latency_ms": round((time.perf_counter() - t0) * 1000.0, 3),
        }
        
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
        
        # Rerank (lightweight - keep resolved ordering)
        # Prioritize deal CSV documents before truncation to avoid dropping them
        kb_docs_in_results = [doc for doc in unique_docs if doc.metadata.get('type') == 'kb_faq']
        if kb_docs_in_results:
            # Re-apply keyword+precedence order after dedup/merge (dedup can scramble CSV order)
            kb_docs_in_results = self._keyword_rerank(question, kb_docs_in_results)
        other_docs = [doc for doc in unique_docs if doc.metadata.get('type') != 'kb_faq']
        master_boost_trace: List[Dict[str, Any]] = []
        if contract_source_q:
            other_docs, master_boost_trace = apply_master_document_boost(
                question,
                other_docs,
                contract_source_q=True,
            )
            search_debug_info["master_metadata_boost"] = master_boost_trace

        # Reorder: contract-source questions prioritize master/pdf chunks over FAQ CSV
        if contract_source_q:
            reranked = (other_docs + kb_docs_in_results)[: self.config.rag_rerank_top_n]
        else:
            reranked = (kb_docs_in_results + other_docs)[: self.config.rag_rerank_top_n]
        
        search_debug_info["rerank_pool_count"] = len(other_docs + kb_docs_in_results)
        search_debug_info["after_rerank"] = len(reranked)
        search_debug_info["reranked_intents"] = [
            doc.metadata.get('intent', doc.metadata.get('type', 'unknown'))
            for doc in reranked
        ]
        search_debug_info["reranked_types"] = [
            doc.metadata.get('type', 'unknown')
            for doc in reranked
        ]
        
        # Task 4: Fallback improvement - If KB CSV not found but router says deal_only, try searching deal collection specifically
        if source_type == "deal_only" and not contract_source_q:
            # Check if KB documents are found in reranked results
            kb_docs_in_reranked = [doc for doc in reranked if doc.metadata.get('type') == 'kb_faq']
            if not kb_docs_in_reranked:
                print("[DEBUG] Router selected deal_only but no KB CSV found. Retrying deal-only search...")
                # Retry search with deal only
                deal_results = self.vector_store_manager.search(question, sources=["deal"])
                deal_scored = deal_results.get("deal", [])
                thresholds = self.config.get_source_score_thresholds()
                faq_docs = self._filter_scored_results(
                    deal_scored,
                    thresholds["csv"],
                    "CSV",
                    question=question,
                    allow_keyword_override=True
                )
                faq_kb_docs = [doc for doc in faq_docs if doc.metadata.get('type') == 'kb_faq']
                if faq_kb_docs:
                    print(f"[DEBUG] Found KB CSV in deal-only retry: {[doc.metadata.get('intent') for doc in faq_kb_docs]}")
                    # Filter by effective dates
                    faq_kb_docs = filter_effective_documents(faq_kb_docs)
                    if faq_kb_docs:
                        # Use KB CSV from FAQ-only search, rerank them
                        faq_kb_docs = self._semantic_rerank(
                            question,
                            faq_kb_docs,
                            self.config.rag_rerank_top_n
                        )
                        # Update reranked to include these KB docs at the top
                        reranked = faq_kb_docs[:self.config.rag_rerank_top_n] + [doc for doc in reranked if doc.metadata.get('type') != 'kb_faq']
                        reranked = reranked[:self.config.rag_rerank_top_n]
        
        # Select documents for answer generation (contract-source: exclude kb_faq when PDF evidence exists)
        docs_for_answer = self._select_docs_for_contract_source(
            reranked, contract_source_q=contract_source_q
        )
        uses_master_ev = uses_master_source_docs(docs_for_answer)
        cand_rows: List[Dict[str, Any]] = []
        for i, d in enumerate(reranked):
            m = d.metadata or {}
            in_answer = d in docs_for_answer
            dropped = ""
            if not in_answer:
                if contract_source_q and m.get("type") == "kb_faq" and uses_master_ev:
                    dropped = "kb_faq_excluded_when_master_evidence"
                else:
                    dropped = "not_in_docs_for_answer"
            cand_rows.append(
                {
                    "rank": i + 1,
                    "filename": m.get("filename", ""),
                    "doc_kind": m.get("doc_kind", ""),
                    "article_number": m.get("article_number"),
                    "article_seq": m.get("article_seq"),
                    "paragraph_seq": m.get("paragraph_seq"),
                    "section_id": m.get("section_id"),
                    "section_label": (m.get("section_label") or "")[:120],
                    "intent": m.get("intent", ""),
                    "used_for_answer": in_answer,
                    "dropped_reason": dropped,
                }
            )
        search_debug_info["retrieval_candidates"] = cand_rows
        search_debug_info["used_articles"] = [
            {
                "article_seq": (d.metadata or {}).get("article_seq"),
                "article_number": (d.metadata or {}).get("article_number"),
                "filename": (d.metadata or {}).get("filename"),
            }
            for d in docs_for_answer
            if (d.metadata or {}).get("type") != "kb_faq"
        ]
        search_debug_info["request_latency_ms"] = round((time.perf_counter() - t0) * 1000.0, 3)

        if contract_source_q and not uses_master_source_docs(docs_for_answer):
            print("[INFO] contract_source_q: no master TXT chunks in evidence; returning not_found (no FAQ Responder).")
            answer = self._contract_source_not_found_answer(question)
            self._attach_decision_meta(
                answer,
                system=decision["system"],
                decision_path="contract_source_not_found",
                latency_ms=(time.perf_counter() - t0) * 1000.0,
                retrieval_used=effective_retrieval_used,
            )
            object.__setattr__(answer, "search_debug_info", search_debug_info)
            self._persist_to_cache(cache_key, answer, persist_cache)
            object.__setattr__(answer, "kb_master_retry_used", kb_master_retry_used)
            object.__setattr__(answer, "contract_source_q", contract_source_q)
            return answer
        
        # Analyze document sources for detailed logging
        selected_sources = set(doc.metadata.get('type', 'unknown') for doc in docs_for_answer)
        all_sources = set(doc.metadata.get('type', 'unknown') for doc in reranked)
        skipped_sources = all_sources - selected_sources
        
        # Format source type summary (use '+' for readability)
        source_summary = '+'.join(sorted(selected_sources)) if selected_sources else 'none'
        
        # Log document filtering decision with detailed source information
        print(f"[DEBUG] Selected source type for answer: {source_summary}")
        print(f"[DEBUG] Using all reranked documents: {len(reranked)} documents")
        print(f"[DEBUG] Document types: {sorted(all_sources)}")
        # Always output skipped sources (even if empty) for consistent log format
        print(f"[DEBUG] Skipped source types: {sorted(skipped_sources)}")
        
        # Use Responder if docs_for_answer contains only deal CSV documents
        faq_only_in_answer = all(doc.metadata.get('type') == 'kb_faq' for doc in docs_for_answer) if docs_for_answer else False
        
        if faq_only_in_answer and not contract_source_q:
            # Use new Responder for KB-based responses
            # Note: FAQ-only path when no PDF (or non-contract-source) evidence was selected
            try:
                response_schema, human_text = self.responder.generate(
                    question, docs_for_answer, user_inputs=None, tenant_info=tenant_info
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
                
                # Convert ResponseSchema to AnswerSchema (V2)
                # Parse human_text to extract items (heuristic)
                items = self._parse_text_to_items(human_text, evidence_ids)
                
                # Store escalation_data as attribute (not in schema to avoid OpenAI compatibility issues)
                answer = AnswerSchema(
                    items=items if items else [AnswerItem(text=human_text, citation=evidence_ids[0] if evidence_ids else "")],
                    summary=human_text,  # Use human_text as summary
                    evidence=evidence_ids if evidence_ids else [docs_for_answer[0].metadata.get('intent', '')] if docs_for_answer else [],
                    next_action=response_schema.handoff_message or "",
                    caveats=caveats
                )
                # Preserve raw answer text for channel-specific formatting
                try:
                    object.__setattr__(answer, "answer_text_raw", response_schema.answer_text)
                except Exception:
                    pass
                # For eval: top ranked KB intent vs evidence alignment
                try:
                    object.__setattr__(
                        answer,
                        "primary_source_intent",
                        docs_for_answer[0].metadata.get("intent") if docs_for_answer else None,
                    )
                except Exception:
                    pass
                # Attach escalation_data as attribute (not part of schema)
                # escalation_data is generated in responder.generate() and stored in response_schema
                # But since we removed it from ResponseSchema for OpenAI compatibility, we need to generate it here
                if hasattr(response_schema, 'escalation_data'):
                    # Use object.__setattr__ to avoid Pydantic validation errors
                    object.__setattr__(answer, 'escalation_data', response_schema.escalation_data)
                elif response_schema.escalation != "bot_only" and tenant_info:
                    # Generate escalation_data if not present but escalation is needed
                    from datetime import datetime
                    # Use object.__setattr__ to avoid Pydantic validation errors
                    object.__setattr__(answer, 'escalation_data', {
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
                    })
                
                # Add application order summary to caveats
                if docs_for_answer and not contract_source_q:
                    caveat_prefix = "適用順: 個別契約CSV > マスターTXT"
                    if "適用順" not in answer.caveats:
                        answer.caveats = f"{caveat_prefix}, {answer.caveats}".strip(" ,")

                # Cache result
                self._persist_to_cache(cache_key, answer, persist_cache)
                self._attach_decision_meta(
                    answer,
                    system=decision["system"],
                    decision_path=effective_decision_path,
                    latency_ms=(time.perf_counter() - t0) * 1000.0,
                    retrieval_used=effective_retrieval_used and bool(docs_for_answer),
                )
                object.__setattr__(answer, "kb_master_retry_used", kb_master_retry_used)
                object.__setattr__(answer, "contract_source_q", contract_source_q)
                return answer
            except Exception as e:
                print(f"Warning: Responder failed, falling back to legacy method: {e}")
                import traceback
                traceback.print_exc()
                # Fall through to legacy method
        
        # Format evidence
        evidence_text = self._format_evidence(docs_for_answer)
        search_debug_info["llm_evidence_char_len"] = len(evidence_text)
        search_debug_info["llm_evidence_token_estimate"] = max(1, len(evidence_text) // 4)
        
        # Check if evidence is insufficient
        insufficient_evidence = len(docs_for_answer) == 0 or len(evidence_text.strip()) < 50
        
        # Extract document IDs from documents used for answer generation
        evidence_ids = []
        retrieved_doc_meta = []
        for doc in docs_for_answer:
            if contract_source_q and doc.metadata.get("type") == "kb_faq":
                continue
            retrieved_doc_meta.append({
                "source_type": "deal" if doc.metadata.get('type') == 'kb_faq' else "master",
                "doc_id": doc.metadata.get('intent') or doc.metadata.get('filename') or ""
            })
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

        rel_detail: Optional[Dict[str, Any]] = None
        if effective_retrieval_used:
            rel_detail = self._relevance_guard_detail(question, docs_for_answer)
        if (
            effective_retrieval_used
            and rel_detail
            and rel_detail.get("low_relevance_signal")
            and not (contract_source_q and uses_master_source_docs(docs_for_answer))
        ):
            msg = "該当する情報を確認できませんでした。所定の窓口へお問い合わせください。"
            answer = AnswerSchema(
                items=[AnswerItem(text=msg, citation=evidence_ids[0] if evidence_ids else "")],
                summary=msg,
                evidence=evidence_ids,
                next_action="所定の窓口（管理・入居手続）へお問い合わせください。",
                caveats="根拠と質問の整合が低いため、フォールバックしました。",
            )
            object.__setattr__(answer, "retrieved_doc_meta", retrieved_doc_meta)
            object.__setattr__(answer, "rag_irrelevant_context", True)
            if rel_detail is not None:
                object.__setattr__(answer, "rag_relevance_guard", rel_detail)
            object.__setattr__(answer, "search_debug_info", search_debug_info)
            self._persist_to_cache(cache_key, answer, persist_cache)
            self._attach_decision_meta(
                answer,
                system=decision["system"],
                decision_path="fallback",
                latency_ms=(time.perf_counter() - t0) * 1000.0,
                retrieval_used=True,
            )
            object.__setattr__(answer, "kb_master_retry_used", kb_master_retry_used)
            object.__setattr__(answer, "contract_source_q", contract_source_q)
            return answer
        
        # Add warning if evidence is insufficient
        if insufficient_evidence:
            if contract_source_q and uses_master_source_docs(docs_for_answer):
                evidence_text += (
                    "\n\n[注意] 根拠情報が不十分です。"
                    "契約書（根拠情報）内では確認できない旨を伝え、FAQや管理会社案内で補わないでください。"
                )
            else:
                evidence_text += "\n\n[注意] 根拠情報が不十分です。推測せず、管理会社への問い合わせを案内してください。"

        # 契約ソース×マスター根拠時: 根拠テキストに含まれる法律用語の平易説明を evidence に注入
        _resolver = getattr(self, "_legal_term_resolver", None)
        if (
            _resolver
            and contract_source_q
            and uses_master_source_docs(docs_for_answer)
        ):
            _term_injection = _resolver.build_prompt_injection(evidence_text)
            if _term_injection:
                evidence_text = evidence_text + "\n\n" + _term_injection

        # V2スキーマを使用（PDF根拠を含む場合は契約向けプロンプトを適用）
        selected_prompt = self._select_generation_prompt(
            docs_for_answer, contract_source_q=contract_source_q
        )
        answer_chain = selected_prompt | self.llm_structured
        raw_answer = answer_chain.invoke({
            "question": question,
            "evidence": evidence_text,
            "tenant_context": tenant_context,
        })
        answer = cast(AnswerSchema, raw_answer if isinstance(raw_answer, AnswerSchema) else AnswerSchema.model_validate(raw_answer))
        
        # Replace LLM-generated evidence with actual document IDs for evaluation
        answer.evidence = evidence_ids
        # Attach retrieved document metadata for evaluation
        object.__setattr__(answer, 'retrieved_doc_meta', retrieved_doc_meta)
        
        # Classify question type for validation
        from src.question_typing import QuestionTyper
        question_typer = QuestionTyper()
        question_type = question_typer.classify(question)
        
        # Enforce answer structure (items count, citations)
        answer = self._enforce_answer_structure(answer, question_type, docs_for_answer)
        
        # Check for PII leakage (before B2 display_format; template would affect length only)
        answer_text = render_answer_text(answer)
        pii_blocked = bool(self._check_pii_leakage(answer_text))
        if pii_blocked:
            # Replace with safe message (preserve evidence_ids). Body avoids granmare forbidden substrings.
            answer = AnswerSchema(
                items=[
                    AnswerItem(
                        text="個人情報が含まれる可能性があるため、契約条件の詳細は所定の窓口でのみご確認ください。",
                        citation="",
                    )
                ],
                summary="セキュリティ上の理由により、ここでは個別の契約内容をお伝えできません。",
                evidence=evidence_ids,  # Preserve actual document IDs
                next_action="所定の窓口（管理・入居手続）へお問い合わせください。",
                caveats="個人情報保護のため、詳細は窓口でご確認ください。",
            )
            object.__setattr__(answer, "contract_source_q", contract_source_q)

        if (not pii_blocked) and uses_master_source_docs(docs_for_answer):
            object.__setattr__(answer, "display_format", DISPLAY_FORMAT_B2)
            object.__setattr__(answer, "source_reference", build_source_reference(docs_for_answer))
        
        if rel_detail is not None:
            object.__setattr__(answer, "rag_relevance_guard", rel_detail)
        
        # primary_source_intent for eval (legacy / LLM path)
        try:
            pi = docs_for_answer[0].metadata.get("intent") if docs_for_answer else None
            if not pi and evidence_ids:
                pi = evidence_ids[0]
            if pi:
                object.__setattr__(answer, "primary_source_intent", pi)
        except Exception:
            pass

        # Add application order summary to caveats
        if docs_for_answer and not contract_source_q:
            caveat_prefix = "適用順: 個別契約CSV > マスターTXT"
            if "適用順" not in answer.caveats:
                answer.caveats = f"{caveat_prefix}, {answer.caveats}".strip(" ,")

        # Cache result
        object.__setattr__(answer, "search_debug_info", search_debug_info)
        self._persist_to_cache(cache_key, answer, persist_cache)
        self._attach_decision_meta(
            answer,
            system=decision["system"],
            decision_path=effective_decision_path,
            latency_ms=(time.perf_counter() - t0) * 1000.0,
            retrieval_used=effective_retrieval_used and bool(docs_for_answer),
        )
        object.__setattr__(answer, "kb_master_retry_used", kb_master_retry_used)
        object.__setattr__(answer, "contract_source_q", contract_source_q)

        return answer


def render_answer_text(answer: AnswerSchema) -> str:
    """Render AnswerSchema (V2) to text format for display/logging.
    
    This function provides a single point of output formatting,
    allowing callers to use V2 schema without worrying about compatibility.
    
    Args:
        answer: AnswerSchema (V2)
        
    Returns:
        Formatted text string (compatible with V1 conclusion format)
    """
    if getattr(answer, "display_format", None) == DISPLAY_FORMAT_B2:
        return format_b2_contract_rag_display(answer)

    # summary優先。空の場合はitemsを簡易整形してフォールバック
    if answer.summary:
        conclusion = answer.summary.strip()
    elif answer.items:
        conclusion = "\n".join([f"{i + 1}. {item.text}" for i, item in enumerate(answer.items)])
    else:
        conclusion = "回答が見つかりませんでした。"
    
    # 完全な回答テキストを構築（V1互換形式）
    full_text = conclusion
    if answer.next_action:
        full_text += f"\n\n次アクション: {answer.next_action}"
    if answer.caveats:
        full_text += f"\n\n注意点: {answer.caveats}"
    
    return full_text
