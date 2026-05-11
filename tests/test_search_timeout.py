"""Tests for VectorStoreManager.search() timeout and error handling (TASK-007)."""
from __future__ import annotations

import logging
import time
from unittest.mock import MagicMock, patch

import pytest

from src.config import Config
from src.vector_store_manager import VectorStoreManager


# ---------------------------------------------------------------------------
# Helper: build a VectorStoreManager stub without touching Chroma on disk
# ---------------------------------------------------------------------------

def _vsm(timeout: float = 5.0) -> VectorStoreManager:
    config = Config(openai_api_key="test_key", rag_search_timeout_sec=timeout)
    vsm = VectorStoreManager.__new__(VectorStoreManager)
    vsm.config = config
    vsm.deal_vector_store = MagicMock()
    vsm.deal_bm25 = MagicMock()
    vsm.master_vector_store = MagicMock()
    vsm.master_bm25 = MagicMock()
    return vsm


# ---------------------------------------------------------------------------
# Normal path
# ---------------------------------------------------------------------------


def test_search_returns_results_on_success():
    vsm = _vsm(timeout=5.0)
    fake_docs = [{"document": MagicMock(), "score": 0.9, "source": "deal", "retriever": "vector"}]

    with patch.object(vsm, "_search_collection_scored", return_value=fake_docs):
        results = vsm.search("test query", sources=["deal"])

    assert "deal" in results
    assert len(results["deal"]) == 1


def test_search_ok_emits_debug_log(caplog):
    vsm = _vsm(timeout=5.0)

    with patch.object(vsm, "_search_collection_scored", return_value=[]):
        with caplog.at_level(logging.DEBUG, logger="src.vector_store_manager"):
            vsm.search("query", sources=["deal"])

    debug_msgs = [r.message for r in caplog.records if r.levelno == logging.DEBUG]
    assert any("rag_search_ok" in m for m in debug_msgs)


# ---------------------------------------------------------------------------
# Timeout path
# ---------------------------------------------------------------------------


def _slow_search(*_args, **_kwargs):
    time.sleep(5)
    return []


def test_search_timeout_returns_empty_list():
    """FutureTimeoutError → results[source] = [] (graceful degradation)."""
    vsm = _vsm(timeout=0.05)

    with patch.object(vsm, "_search_collection_scored", side_effect=_slow_search):
        results = vsm.search("query", sources=["deal"])

    assert results["deal"] == []


def test_search_timeout_logs_warning(caplog):
    """タイムアウト時は rag_search_timeout が WARNING ログに出る。"""
    vsm = _vsm(timeout=0.05)

    with patch.object(vsm, "_search_collection_scored", side_effect=_slow_search):
        with caplog.at_level(logging.WARNING, logger="src.vector_store_manager"):
            vsm.search("query", sources=["deal"])

    warn_msgs = [r.message for r in caplog.records if r.levelno == logging.WARNING]
    assert any("rag_search_timeout" in m for m in warn_msgs), warn_msgs


def test_search_timeout_log_contains_elapsed(caplog):
    """タイムアウトログに elapsed_sec フィールドが含まれる。"""
    vsm = _vsm(timeout=0.05)

    with patch.object(vsm, "_search_collection_scored", side_effect=_slow_search):
        with caplog.at_level(logging.WARNING, logger="src.vector_store_manager"):
            vsm.search("query", sources=["deal"])

    warn_msgs = [r.message for r in caplog.records if r.levelno == logging.WARNING]
    assert any("elapsed_sec" in m for m in warn_msgs), warn_msgs


def test_search_both_sources_timeout_independently():
    """deal と master がそれぞれタイムアウトしても両方 [] を返す。"""
    vsm = _vsm(timeout=0.05)

    with patch.object(vsm, "_search_collection_scored", side_effect=_slow_search):
        results = vsm.search("query", sources=["deal", "master"])

    assert results["deal"] == []
    assert results["master"] == []


# ---------------------------------------------------------------------------
# Error path
# ---------------------------------------------------------------------------


def test_search_exception_returns_empty_list():
    """_search_collection_scored が例外を上げても search() は [] を返す。"""
    vsm = _vsm(timeout=5.0)

    with patch.object(vsm, "_search_collection_scored", side_effect=RuntimeError("db error")):
        results = vsm.search("query", sources=["deal"])

    assert results["deal"] == []


def test_search_exception_logs_error(caplog):
    """例外時は rag_search_error が ERROR ログに出る。"""
    vsm = _vsm(timeout=5.0)

    with patch.object(vsm, "_search_collection_scored", side_effect=RuntimeError("db error")):
        with caplog.at_level(logging.ERROR, logger="src.vector_store_manager"):
            vsm.search("query", sources=["deal"])

    err_msgs = [r.message for r in caplog.records if r.levelno == logging.ERROR]
    assert any("rag_search_error" in m for m in err_msgs), err_msgs


# ---------------------------------------------------------------------------
# Config default
# ---------------------------------------------------------------------------


def test_default_timeout_is_10_seconds():
    """rag_search_timeout_sec のデフォルトが 10.0 秒になっている。"""
    config = Config(openai_api_key="test_key")
    assert config.rag_search_timeout_sec == 10.0
