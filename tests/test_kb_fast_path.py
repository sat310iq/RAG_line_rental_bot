"""Tests for KB fast path scoring and clarification."""

from __future__ import annotations

import os

import pytest

from src.config import load_config, reset_config
from src.kb_fast_path import normalize_for_match, try_kb_fast_path
from src.kb_loader import load_kb_csv


@pytest.fixture
def cfg():
    reset_config()
    os.environ.setdefault("OPENAI_API_KEY", os.environ.get("OPENAI_API_KEY", "sk-test-dummy"))
    c = load_config(force_reload=True)
    return c


def test_gas_fee_specific_hits(cfg):
    docs = load_kb_csv(cfg)
    r = try_kb_fast_path("ガス料金を知りたいのですが", cfg, docs)
    assert r.kind == "hit"
    assert r.intent == "生活_ガス料金"
    assert "ダイプロ" in (r.text or "")


def test_gas_fault_hits(cfg):
    docs = load_kb_csv(cfg)
    r = try_kb_fast_path("ガス給湯器が故障したようです", cfg, docs)
    assert r.kind == "hit"
    assert r.intent == "設備_ガス故障"


def test_gas_water_heater_no_hot_water_is_hit_not_short_clarification_loop(cfg):
    """Production bug: len(norm)==12 with short_max_len=12 treated query as 'short' → clarification loop."""
    docs = load_kb_csv(cfg)
    r = try_kb_fast_path("ガス給湯器のお湯が出ない", cfg, docs)
    assert r.kind == "hit"
    assert r.intent == "設備_ガス故障"
    assert r.text and "ダイプロ" in r.text


def test_smoking_parity(cfg):
    docs = load_kb_csv(cfg)
    r1 = try_kb_fast_path("喫煙は可能ですか", cfg, docs)
    r2 = try_kb_fast_path("タバコを吸っても良いですか", cfg, docs)
    assert r1.kind == "hit"
    assert r2.kind == "hit"
    assert r1.intent == "生活_喫煙"
    assert r2.intent == "生活_喫煙"


def test_gas_short_clarification(cfg):
    docs = load_kb_csv(cfg)
    r = try_kb_fast_path("ガス", cfg, docs)
    assert r.kind == "clarification"
    assert r.text and "どれ" in r.text
    assert "1." in r.text and "そのまま次のように送ってください。" in r.text
    assert "上の 1〜3 の番号だけでも返信できます。" in (r.text or "")
    assert r.match_detail.get("clarification_reason") == "short_query"
    nq = r.match_detail.get("clarification_numeric_queries")
    assert isinstance(nq, list) and len(nq) == 3


def test_certificate_short_clarification(cfg):
    docs = load_kb_csv(cfg)
    r = try_kb_fast_path("証明書", cfg, docs)
    assert r.kind == "clarification"
    assert "1." in (r.text or "") and "- " in (r.text or "")


def test_hot_water_short_phrase_is_hit(cfg):
    docs = load_kb_csv(cfg)
    r = try_kb_fast_path("お湯が出ない", cfg, docs)
    assert r.kind == "hit"
    assert r.intent == "設備_ガス故障"
    assert r.match_detail.get("is_specific_even_if_short") is True


def test_certificate_full_sentence_is_hit(cfg):
    docs = load_kb_csv(cfg)
    r = try_kb_fast_path("証明書を発行したい", cfg, docs)
    assert r.kind == "hit"
    assert r.intent == "契約_証明書"
    assert "To You" in (r.text or "") or "0978" in (r.text or "")


def test_prior_clarification_same_vague_short_repeat_stays_clarification(cfg):
    """Same intent + same normalized short text: do not relax short → stay clarification."""
    docs = load_kb_csv(cfg)
    r = try_kb_fast_path(
        "ガス",
        cfg,
        docs,
        prior_clarification_intent="生活_ガス料金",
        prior_clarification_normalized_query=normalize_for_match("ガス"),
    )
    assert r.kind == "clarification"
    assert r.intent == "生活_ガス料金"
    assert r.match_detail.get("clarification_reason") == "short_query"


def test_prior_clarification_legacy_none_normalized_still_relaxes_short(cfg):
    """Migration: prior normalized_query omitted → legacy hit on repeat ガス (remove when unused)."""
    docs = load_kb_csv(cfg)
    r = try_kb_fast_path(
        "ガス",
        cfg,
        docs,
        prior_clarification_intent="生活_ガス料金",
        prior_clarification_normalized_query=None,
    )
    assert r.kind == "hit"
    assert r.intent == "生活_ガス料金"


def test_prior_clarification_same_intent_different_norm_hits(cfg):
    """Concrete follow-up after ガス clarification: different normalized text → hit."""
    docs = load_kb_csv(cfg)
    r = try_kb_fast_path(
        "ガス料金を知りたいのですが",
        cfg,
        docs,
        prior_clarification_intent="生活_ガス料金",
        prior_clarification_normalized_query=normalize_for_match("ガス"),
    )
    assert r.kind == "hit"
    assert r.intent == "生活_ガス料金"


def test_legal_skip_misses(cfg):
    docs = load_kb_csv(cfg)
    r = try_kb_fast_path("これは違法ではないですか", cfg, docs)
    assert r.kind == "miss"


def test_fast_path_disabled(cfg):
    docs = load_kb_csv(cfg)
    cfg.kb_fast_path_enabled = False
    r = try_kb_fast_path("ガス料金を知りたい", cfg, docs)
    assert r.kind == "miss"
