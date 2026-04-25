"""Regression tests for question term extraction and content keyword match."""

from __future__ import annotations

import pytest

from src.config import QUESTION_TERM_SYNONYMS_RAG_DEFAULT
from src.utils.question_terms import (
    DEFAULT_STOPWORDS,
    extract_question_terms,
    has_content_keyword_hit,
)


def test_extract_includes_浸水_risk_phrase():
    terms = extract_question_terms("浸水リスクはありますか")
    assert "浸水リスク" in terms or "浸水" in terms


def test_extract_includes_抵当権():
    terms = extract_question_terms("抵当権が執行されたらどうなりますか")
    assert "抵当権" in terms or any("抵当" in t for t in terms)


def test_stopword_only_does_not_hit():
    content = "契約上の定め"
    # 「について」等だけでは extract が空に近づく; 2文字以上の有意語が無ければ hit しない
    assert has_content_keyword_hit("について", content) is False


def test_has_content_hit_when_term_in_haystack():
    # 「浸水の心配」は単一トークンになり substring 照合に効かないため、抽出が分かれる文にする
    assert has_content_keyword_hit("浸水は心配です", "本物件の浸水履歴について") is True


def test_synonym_links_浸水_to_content_with_水害():
    custom_syn = {"浸水": ["水害", "洪水"]}
    assert has_content_keyword_hit(
        "浸水は危険ですか",
        "水害保険の対象外となる場合がございます",
        stopwords=DEFAULT_STOPWORDS,
        synonyms=custom_syn,
    ) is True


def test_rag_default_synonym_map_has_浸水_and_抵当権():
    assert "浸水" in QUESTION_TERM_SYNONYMS_RAG_DEFAULT
    assert "水害" in QUESTION_TERM_SYNONYMS_RAG_DEFAULT["浸水"]
    assert "抵当権" in QUESTION_TERM_SYNONYMS_RAG_DEFAULT
    assert "競売" in QUESTION_TERM_SYNONYMS_RAG_DEFAULT["抵当権"]


def test_has_content_uses_rag_default_synonyms():
    assert has_content_keyword_hit(
        "浸水は危険ですか",
        "水害区域の図面は添付のとおりです。",
        stopwords=DEFAULT_STOPWORDS,
        synonyms=QUESTION_TERM_SYNONYMS_RAG_DEFAULT,
    ) is True
    assert has_content_keyword_hit(
        "抵当権について教えて",
        "仮差押と競売の手続について",
        stopwords=DEFAULT_STOPWORDS,
        synonyms=QUESTION_TERM_SYNONYMS_RAG_DEFAULT,
    ) is True
