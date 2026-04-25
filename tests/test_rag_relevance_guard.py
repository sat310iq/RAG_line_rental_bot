"""Regression tests for RAG non-FAQ relevance guard (fail-closed); behavior matches production."""

from __future__ import annotations

import copy
from unittest.mock import MagicMock

import pytest
from langchain_core.documents import Document

from src.config import QUESTION_TERM_SYNONYMS_RAG_DEFAULT
from src.rag_answerer import RAGAnswerer


@pytest.fixture
def ra_guard():
    c = MagicMock()
    c.question_term_stopwords = None
    c.question_term_synonyms = None
    r = RAGAnswerer.__new__(RAGAnswerer)
    r.config = c
    return r


@pytest.fixture
def ra_guard_with_default_synonyms():
    c = MagicMock()
    c.question_term_stopwords = None
    c.question_term_synonyms = copy.deepcopy(QUESTION_TERM_SYNONYMS_RAG_DEFAULT)
    r = RAGAnswerer.__new__(RAGAnswerer)
    r.config = c
    return r


def test_relevance_non_faq_no_question_terms_in_content_true(ra_guard):
    """A: 非FAQ文書に質問語が無い -> low_relevance_signal True."""
    q = "修繕について教えてください"
    d = Document(
        page_content="薬物使用、暴力団排除、禁止事項について記載。",
        metadata={"type": "master", "filename": "lease.pdf", "page": 1},
    )
    d2 = ra_guard._relevance_guard_detail(q, [d])
    assert d2["low_relevance_signal"] is True
    assert d2.get("skip_reason") != "only_kb_faq"
    assert d2.get("inspected_non_faq_docs", 0) >= 1
    assert ra_guard._has_low_relevance_signal(q, [d]) is True


def test_relevance_non_faq_hits_content_false(ra_guard):
    """B: 非FAQ文書に質問語に対応する語がある -> low_relevance_signal False."""
    # 語が分離して抽出されることで 浸水 / 心配 等が根拠文に乗る
    q = "浸水は心配です。リスクを教えて"
    d = Document(
        page_content="本物件周辺の洪水浸水想定区域及び心配事項、水害に関する説明が記載されています。",
        metadata={"type": "master", "filename": "hazard.txt"},
    )
    d2 = ra_guard._relevance_guard_detail(q, [d])
    assert d2["low_relevance_signal"] is False
    assert ra_guard._has_low_relevance_signal(q, [d]) is False


def test_relevance_faq_only_skips_false(ra_guard):
    """C: kb_faq のみ -> ガード対象外（low_relevance_signal False）。"""
    d = Document(
        page_content="清掃費は契約に従います。",
        metadata={"type": "kb_faq", "intent": "契約_退去清掃費"},
    )
    d2 = ra_guard._relevance_guard_detail("清掃費は？", [d])
    assert d2["low_relevance_signal"] is False
    assert d2.get("skip_reason") == "only_kb_faq"
    assert ra_guard._has_low_relevance_signal("清掃費は？", [d]) is False


def test_relevance_empty_docs_true(ra_guard):
    """D: 現仕様 — docs 空 -> low_relevance_signal True（高リスク＝fail-closed 側）。"""
    d2 = ra_guard._relevance_guard_detail("任意の質問", [])
    assert d2["low_relevance_signal"] is True
    assert d2.get("skip_reason") == "no_docs"
    assert ra_guard._has_low_relevance_signal("任意の質問", []) is True


def test_relevance_mixed_faq_plus_master_checks_master_leg(ra_guard):
    """先頭2件の非FAQのみを検査; FAQ+PDF混在は非FAQ分を使う。"""
    faq = Document(
        page_content="ゴミ出し",
        metadata={"type": "kb_faq", "intent": "ゴミ出し_ルール"},
    )
    master = Document(
        page_content="全く無関係な条文",
        metadata={"type": "master", "filename": "a.pdf", "page": 1},
    )
    d2 = ra_guard._relevance_guard_detail("抵当権実行", [faq, master])
    assert d2.get("inspected_non_faq_docs") == 1
    assert d2["low_relevance_signal"] is True


def test_relevance_config_synonym_抵当_and_競売_in_content(ra_guard_with_default_synonyms):
    """Config 既定同義で、質問に 抵当権 ・根拠に 競売 だけでも関連扱い。"""
    d = Document(
        page_content="仮差押えや競売の流れに関する一般的な記載。",
        metadata={"type": "master", "filename": "legal.pdf"},
    )
    ra = ra_guard_with_default_synonyms
    d2 = ra._relevance_guard_detail("抵当権のことで教えてください", [d])
    assert d2["low_relevance_signal"] is False


def test_relevance_config_synonym_浸水_and_水害_in_content(ra_guard_with_default_synonyms):
    """浸水 -> 水害/洪水: 根拠に 水害 のみでヒット（「浸水」を別トークンにする）。"""
    d = Document(
        page_content="洪水・水害リスクの地域区分について。",
        metadata={"type": "master", "filename": "hazard.txt"},
    )
    ra = ra_guard_with_default_synonyms
    d2 = ra._relevance_guard_detail("浸水は心配です", [d])
    assert d2["low_relevance_signal"] is False
