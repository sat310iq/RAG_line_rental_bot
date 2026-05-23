"""Sprint 3 #2: important_matters non-contract queries enable master TXT search."""

from unittest.mock import MagicMock

import pytest
from langchain_core.documents import Document

from src.kb_fast_path import KBFastPathResult
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
    enable_individual_contract_handoff = False
    rag_template_clause_scope_enabled = True
    rag_contract_source_drop_kb_faq_entirely = True
    contract_source_master_top_k = 10
    contract_source_retry_top_k = 12
    master_section_inject_enabled = False

    def get_source_score_thresholds(self):
        return {"csv": 0.0, "pdf": 0.0}

    def get_kb_csv_path(self):
        return ""


class _FakeChain:
    def invoke(self, _payload):
        return AnswerSchema(
            items=[AnswerItem(text="ok", citation="c1")],
            summary="ok",
            evidence=[],
            next_action="",
            caveats="",
        )


class _FakePrompt:
    def __or__(self, _rhs):
        return _FakeChain()


def _im_doc() -> Document:
    return Document(
        page_content="洪水浸水想定区域に該当",
        metadata={
            "type": "master_txt",
            "filename": "重要事項説明書.txt",
            "doc_kind": "important_matters",
            "section_id": "12",
            "stable_id": "im-hazard",
        },
    )


def _build_rag(hierarchical_calls: list) -> RAGAnswerer:
    rag = RAGAnswerer.__new__(RAGAnswerer)
    rag.config = _DummyConfig()
    rag.query_cache = _DummyCache()
    rag.tenant_auth = None
    rag.answer_prompt = _FakePrompt()
    rag.contract_answer_prompt = _FakePrompt()
    rag.contract_source_qa_prompt = _FakePrompt()
    rag.llm_structured = object()
    vsm_stub = MagicMock()
    vsm_stub.fetch_master_by_metadata.return_value = []
    vsm_stub.fetch_master_by_cite_kind.return_value = []
    rag.vector_store_manager = vsm_stub
    rag._decide_answer_path = lambda question, forced_system="auto": {
        "system": "RAG",
        "decision_path": "rag",
    }

    def _capture_hier(question, tenant_contract_id=None, **kwargs):
        hierarchical_calls.append(kwargs)
        return {"deal": [], "master": [_im_doc()]}

    rag._hierarchical_search = _capture_hier
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
    rag._contract_source_master_retry = lambda question, include_trace=False: ([], {})
    return rag


@pytest.mark.parametrize(
    "question",
    [
        "この物件は洪水のリスクはありますか？",
        "ハザードマップで何か注意点は？",
    ],
)
def test_important_matters_non_contract_enables_master_search(
    monkeypatch: pytest.MonkeyPatch, question: str
) -> None:
    monkeypatch.setattr(
        "src.question_typing.QuestionTyper.classify",
        lambda self, q: "fact_lookup",
    )
    monkeypatch.setattr(
        "src.rag_answerer.try_kb_fast_path",
        lambda *args, **kwargs: KBFastPathResult(kind="miss"),
    )
    calls: list = []
    rag = _build_rag(calls)
    rag.answer(question)
    assert len(calls) == 1
    assert calls[0]["force_master"] is True
    assert calls[0]["master_top_k"] >= 3


def test_deal_only_query_keeps_master_top_k_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "src.question_typing.QuestionTyper.classify",
        lambda self, q: "fact_lookup",
    )
    monkeypatch.setattr(
        "src.rag_answerer.try_kb_fast_path",
        lambda *args, **kwargs: KBFastPathResult(kind="miss"),
    )
    calls: list = []
    rag = _build_rag(calls)
    rag.answer("駐車場は使えますか")
    assert len(calls) == 1
    assert calls[0]["force_master"] is False
    assert calls[0]["master_top_k"] == 0
