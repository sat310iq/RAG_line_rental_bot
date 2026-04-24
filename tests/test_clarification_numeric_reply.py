"""Numeric reply resolution after KB fast path clarification."""

from __future__ import annotations

import os

import pytest

from src.config import load_config, reset_config
from src.interfaces.line import clarification_followup as cf
from src.kb_fast_path import clarification_numeric_queries, normalize_for_match, try_kb_fast_path
from src.kb_loader import load_kb_csv


@pytest.fixture
def cfg():
    reset_config()
    os.environ.setdefault("OPENAI_API_KEY", os.environ.get("OPENAI_API_KEY", "sk-test-dummy"))
    c = load_config(force_reload=True)
    return c


def test_resolve_numeric_second_choice():
    assert (
        cf.resolve_numeric_clarification_reply(
            "2",
            ["電気料金を知りたい", "停電しました"],
            line_user_id="Utest",
        )
        == "停電しました"
    )


def test_resolve_numeric_fullwidth_digit():
    assert (
        cf.resolve_numeric_clarification_reply("２", ["a", "b"], line_user_id=None) == "b"
    )


def test_resolve_numeric_no_prior_returns_none():
    assert cf.resolve_numeric_clarification_reply("1", None) is None
    assert cf.resolve_numeric_clarification_reply("1", []) is None


def test_clarification_numeric_queries_fallback_when_fewer_examples():
    assert clarification_numeric_queries(["opt1", "opt2"], ["only"]) == ["only", "opt2"]


def test_electric_short_then_digit_two_hit(cfg):
    """電気 → clarification → user sends 2 → expanded query hits 生活_電気."""
    docs = load_kb_csv(cfg)
    r1 = try_kb_fast_path("電気", cfg, docs)
    assert r1.kind == "clarification"
    assert r1.intent == "生活_電気"
    nq = r1.match_detail.get("clarification_numeric_queries")
    assert isinstance(nq, list) and len(nq) == 2
    assert "停電したようなので確認したい" in nq[1]

    r2 = try_kb_fast_path(
        nq[1],
        cfg,
        docs,
        prior_clarification_intent=r1.intent,
        prior_clarification_normalized_query=normalize_for_match("電気"),
        user_text_for_prior_match="2",
    )
    assert r2.kind == "hit"
    # 停電系の例文は 設備_停電 が先に取れることがある（いずれも fast path hit でよい）
    assert r2.intent in ("生活_電気", "設備_停電")
    assert r2.text
