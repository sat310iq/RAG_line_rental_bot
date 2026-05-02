"""RAG answer() short-circuits to individual-contract handoff before retrieval."""

import pytest

from src.rag_answerer import RAGAnswerer, AnswerItem, AnswerSchema


class _NoCache:
    def get(self, _key, allow_semantic=True):
        return None

    def set(self, _key, _value, include_embedding=True):
        return None


class _Cfg:
    kb_fast_path_short_max_len = 32
    enable_individual_contract_handoff = True
    rag_template_clause_scope_enabled = True
    rag_contract_source_drop_kb_faq_entirely = True


def test_answer_individual_handoff_before_rag(monkeypatch: pytest.MonkeyPatch) -> None:
    called = {"h": 0}

    def _no_hier(*_a, **_k):
        called["h"] += 1
        return {"deal": [], "master": []}

    rag = RAGAnswerer.__new__(RAGAnswerer)
    rag.config = _Cfg()
    rag.query_cache = _NoCache()
    rag.tenant_auth = None
    rag._decide_answer_path = lambda q, forced_system="auto": {"system": "RAG", "decision_path": "rag"}
    rag._persist_to_cache = lambda *a, **k: None
    rag._attach_decision_meta = lambda *a, **k: None

    monkeypatch.setattr("src.rag_answerer.should_escalate_to_management", lambda q: False)
    monkeypatch.setattr("src.rag_answerer.load_kb_documents_for_fast_path", lambda c: [])
    monkeypatch.setattr("src.rag_answerer.try_kb_fast_path", lambda q, c, d: type("F", (), {"kind": "none"})())
    monkeypatch.setattr("src.rag_answerer.RAGAnswerer._hierarchical_search", _no_hier)

    ans = rag.answer("私の家賃はいくらですか")

    assert called["h"] == 0
    assert ans.items[0].citation == "individual_contract_handoff"
    assert "所定" in (ans.summary or "")
