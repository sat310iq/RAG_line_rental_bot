import re
from pathlib import Path

from langchain_core.documents import Document
import pytest

from src.rag_answerer import AnswerItem, AnswerSchema, RAGAnswerer


class _DummyCache:
    def get(self, _key, allow_semantic=True):
        return None

    def set(self, _key, _value, include_embedding=True):
        return None


class _DummyConfig:
    kb_fast_path_short_max_len = 32
    kb_empty_try_master_pdf = False
    rag_rerank_top_n = 3
    fallback_message = "fallback"
    question_term_stopwords = None
    question_term_synonyms = None
    enable_individual_contract_handoff = True
    rag_template_clause_scope_enabled = True
    rag_contract_source_drop_kb_faq_entirely = True
    contract_source_master_top_k = 10
    contract_source_retry_top_k = 12

    def get_source_score_thresholds(self):
        return {"csv": 0.0, "pdf": 0.0}

    def get_kb_csv_path(self):
        return ""


class _FakeChain:
    def __init__(self, label: str):
        self.label = label

    def invoke(self, _payload):
        return AnswerSchema(
            items=[AnswerItem(text=f"{self.label} item", citation="c1")],
            summary=f"{self.label} summary",
            evidence=[],
            next_action="管理会社へお問い合わせください",
            caveats="",
        )


class _FakePrompt:
    def __init__(self, label: str):
        self.label = label

    def __or__(self, _rhs):
        return _FakeChain(self.label)


def _build_rag_with_stubbed_pipeline(docs):
    rag = RAGAnswerer.__new__(RAGAnswerer)
    rag.config = _DummyConfig()
    rag.query_cache = _DummyCache()
    rag.tenant_auth = None
    rag.answer_prompt = _FakePrompt("default_prompt")
    rag.contract_answer_prompt = _FakePrompt("contract_prompt")
    rag.contract_source_qa_prompt = _FakePrompt("contract_source_qa_prompt")
    rag.llm_structured = object()

    rag._decide_answer_path = lambda question, forced_system="auto": {
        "system": "RAG",
        "decision_path": "rag",
    }
    rag._hierarchical_search = lambda question, tenant_contract_id=None, **kwargs: {
        "deal": [],
        "master": docs,
    }
    rag._resolve_documents = lambda csv_docs, pdf_docs: csv_docs + pdf_docs
    rag._filter_tenant_info = lambda documents, tenant_contract_id: documents
    rag._enforce_answer_structure = lambda answer, question_type, retrieved_docs: answer
    rag._check_pii_leakage = lambda text: False
    rag._persist_to_cache = lambda question, answer, persist_cache: None
    rag._attach_decision_meta = (
        lambda answer, system, decision_path, latency_ms, retrieval_used: None
    )
    rag._relevance_guard_detail = lambda question, docs_for_answer: {
        "low_relevance_signal": False
    }
    return rag


def _pdf_doc(article_seq: int, *, stable_id: str) -> Document:
    return Document(
        page_content=f"第{article_seq}条の本文です。居住のみを目的として使用する旨を定めます。",
        metadata={
            "type": "master_txt",
            "filename": "グランマーレ大分空港契約書.txt",
            "page": article_seq,
            "article_seq": article_seq,
            "article_number": f"第{article_seq}条",
            "stable_id": stable_id,
        },
    )


def test_answer_uses_contract_prompt_when_master_txt_docs_present(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "src.question_typing.QuestionTyper.classify",
        lambda self, question: "fact_lookup",
    )
    rag = _build_rag_with_stubbed_pipeline(
        [
            Document(
                page_content="契約条項の抜粋。解約予告期間に関する条件が記載されています。" * 3,
                metadata={"type": "master_txt", "filename": "グランマーレ大分空港契約書.txt", "page": 5},
            )
        ]
    )

    answer = rag.answer("解約予告期間を教えてください")

    assert answer.summary.startswith("contract_prompt")
    assert answer.next_action


def test_answer_uses_default_prompt_when_non_master_docs(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "src.question_typing.QuestionTyper.classify",
        lambda self, question: "fact_lookup",
    )
    rag = _build_rag_with_stubbed_pipeline(
        [
            Document(
                page_content="運用ルールのメモです。問い合わせ窓口は管理会社です。" * 3,
                metadata={"type": "ops_log", "stable_id": "ops-001"},
            )
        ]
    )

    answer = rag.answer("問い合わせ窓口を教えてください")

    assert answer.summary.startswith("default_prompt")


def test_answer_uses_contract_source_qa_prompt_for_article_question(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        "src.question_typing.QuestionTyper.classify",
        lambda self, question: "fact_lookup",
    )
    rag = _build_rag_with_stubbed_pipeline(
        [
            Document(
                page_content="第4条（賃料）の本文抜粋。頭書(3)の記載に従い日割り計算する旨が記載されています。" * 3,
                metadata={"type": "master_txt", "filename": "グランマーレ大分空港契約書.txt", "page": 4},
            )
        ]
    )

    answer = rag.answer("本文第4条では、賃料の支払いと日割りについてどう書かれていますか。")

    assert answer.summary.startswith("contract_source_qa_prompt")


def test_contract_source_article_retry_merges_even_when_master_exists(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        "src.question_typing.QuestionTyper.classify",
        lambda self, question: "fact_lookup",
    )
    rag = _build_rag_with_stubbed_pipeline([_pdf_doc(10, stable_id="art10")])
    rag.vector_store_manager = object()

    def _retry(_question: str, *, include_trace: bool = False):
        extra = [_pdf_doc(3, stable_id="art3")]
        trace = {"queries": ["第3条"], "per_query": [], "merged_count": 1}
        return (extra, trace) if include_trace else extra

    rag._contract_source_master_retry = _retry

    answer = rag.answer("第3条の使用目的は？")

    debug = getattr(answer, "search_debug_info", {})
    used_candidates = [
        row for row in debug.get("retrieval_candidates", []) if row.get("used_for_answer")
    ]
    article_seqs = {row.get("article_seq") for row in used_candidates}
    assert 3 in article_seqs
    assert debug.get("contract_article_index") == 3
    retry_debug = debug.get("contract_source_retry", {})
    assert retry_debug.get("attempted") is True
    assert retry_debug.get("added_docs", 0) >= 1


def test_contract_source_non_article_usage_question_uses_retry(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        "src.question_typing.QuestionTyper.classify",
        lambda self, question: "fact_lookup",
    )
    rag = _build_rag_with_stubbed_pipeline([])
    rag.vector_store_manager = object()
    rag._hierarchical_search = lambda question, tenant_contract_id=None, **kwargs: {
        "deal": [],
        "master": [],
    }

    def _retry(_question: str, *, include_trace: bool = False):
        extra = [_pdf_doc(3, stable_id="art3")]
        trace = {"queries": ["この契約の使用目的は何ですか？", "居住のみを目的として"], "per_query": [], "merged_count": 1}
        return (extra, trace) if include_trace else extra

    rag._contract_source_master_retry = _retry

    answer = rag.answer("この契約の使用目的は何ですか？")

    debug = getattr(answer, "search_debug_info", {})
    retry_debug = debug.get("contract_source_retry", {})
    assert debug.get("contract_source_q") is True
    assert retry_debug.get("attempted") is True
    assert retry_debug.get("added_docs", 0) >= 1
    used_candidates = [
        row for row in debug.get("retrieval_candidates", []) if row.get("used_for_answer")
    ]
    assert any(row.get("article_seq") == 3 for row in used_candidates)


def _contract_source_qa_prompt_block() -> str:
    path = Path(__file__).resolve().parent.parent / "src" / "rag_answerer.py"
    text = path.read_text(encoding="utf-8")
    m = re.search(
        r"self\.contract_source_qa_prompt = ChatPromptTemplate\.from_template\(\n"
        r'            """(.+?)"""\n        \)',
        text,
        re.DOTALL,
    )
    assert m, "contract_source_qa_prompt template not found in rag_answerer.py"
    return m.group(1)


def test_contract_source_qa_prompt_has_appendix_burden_format_rules() -> None:
    """プロンプト変更の回帰防止（キーワードの有無のみ）。"""
    prompt = _contract_source_qa_prompt_block()
    assert "別表" in prompt
    assert "負担区分" in prompt
    assert "賃借人負担" in prompt
    assert "賃貸人負担" in prompt
    assert "根拠チャンク" in prompt
    assert "無理に" in prompt
    assert "【別表・負担区分の出力形式】" in prompt
    assert "【根拠制約】" in prompt
    assert "平易" in prompt
    assert "抵当権" in prompt
