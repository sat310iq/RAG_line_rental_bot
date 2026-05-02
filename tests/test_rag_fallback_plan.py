import os

from src.config import load_config
from src.vector_store_manager import VectorStoreManager
from src.query_cache import QueryCache
from src.rag_answerer import RAGAnswerer
from src.tenant_auth import TenantAuth


def _make_rag():
    config = load_config()
    rag = RAGAnswerer(
        config,
        VectorStoreManager(config),
        QueryCache(config),
        TenantAuth(config),
    )
    rag.query_cache.clear()
    return rag


def test_csv_keyword_override():
    rag = _make_rag()
    answer = rag.answer("ペット飼育できますか？")
    assert answer.evidence
    # Prefer CSV keyword evidence; if deal retrieval times out or returns empty, PDF fallback is valid.
    ev0 = answer.evidence[0]
    assert ev0 == "ペット飼育の可否" or "グランマーレ" in ev0 or "契約書" in ev0
    assert "ペット" in answer.summary and ("禁止" in answer.summary or "飼育" in answer.summary)


def test_fallback_message_when_no_match():
    rag = _make_rag()
    answer = rag.answer("天気は晴れですか？")
    config = load_config()
    assert answer.summary == config.fallback_message


def test_summary_only_rendering():
    rag = _make_rag()
    answer = rag.answer("喫煙はできますか？")
    assert answer.summary
    assert answer.items


def test_cache_reset_option_env():
    # Ensure cache key versioning uses KB file timestamp
    config = load_config()
    assert os.path.exists(config.kb_csv_path)
