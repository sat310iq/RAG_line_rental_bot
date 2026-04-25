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


def test_answer_uses_contract_prompt_when_pdf_docs_present(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "src.question_typing.QuestionTyper.classify",
        lambda self, question: "fact_lookup",
    )
    rag = _build_rag_with_stubbed_pipeline(
        [
            Document(
                page_content="契約条項の抜粋。解約予告期間に関する条件が記載されています。" * 3,
                metadata={"type": "pdf", "filename": "master.pdf", "page": 5},
            )
        ]
    )

    answer = rag.answer("解約予告期間を教えてください")

    assert answer.summary.startswith("contract_prompt")
    assert answer.next_action


def test_answer_uses_default_prompt_when_non_pdf_docs(monkeypatch: pytest.MonkeyPatch):
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
