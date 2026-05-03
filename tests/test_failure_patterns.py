"""Regression tests for failure analysis / telemetry helpers."""

from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path

import pytest

import csv
from pathlib import Path

from src.metrics import (
    MATCH_TIER_TO_CODE,
    build_semantic_equivalence_map,
    compute_rag_aggregate_health,
    match_tier_to_code,
    semantic_neighbor_hit,
)
from src.eval_smoke_analysis import hits_at_k, infer_failure_bucket
from langchain_core.documents import Document

from src.config import load_config
from src.rag_answerer import RAGAnswerer


def test_csv_keyword_override_mid_term_kaiyaku_uses_kaiyaku_token_flow() -> None:
    """中途解約は解約キーワード行と同じオーバーライド扱い（KB に専用トークンを増やさない）。"""
    rag = RAGAnswerer.__new__(RAGAnswerer)
    rag.config = load_config()
    min_h = int(rag.config.csv_keyword_override_min_hits or 2)
    doc = Document(
        page_content="x",
        metadata={
            "keywords": "解約|退去|退去届",
            "keywords_primary": "退去|解約|解約したい",
        },
    )
    q = "中途解約について知りたいです"
    assert RAGAnswerer._csv_keyword_override_hit_count(rag, q, doc) >= min_h
    assert RAGAnswerer._csv_keyword_override_hit_count(rag, "途中解約の手続き", doc) >= min_h
    other = Document(page_content="x", metadata={"keywords": "ペット|禁止", "keywords_primary": ""})
    assert RAGAnswerer._csv_keyword_override_hit_count(rag, q, other) < min_h


def test_csv_keyword_override_tai_kyo_shitai_spaced_matches_tai_kyo_flow() -> None:
    """「退去 したい」は連続せずトークン数が 1 になりうるが、退去キーワード行は同一フローで min_hits に届く。"""
    rag = RAGAnswerer.__new__(RAGAnswerer)
    rag.config = load_config()
    min_h = int(rag.config.csv_keyword_override_min_hits or 2)
    doc = Document(
        page_content="x",
        metadata={
            "keywords": "解約|退去|退去届",
            "keywords_primary": "退去|解約|退去したい",
        },
    )
    spaced = "退去 したいのですが"
    assert RAGAnswerer._csv_keyword_override_hit_count(rag, spaced, doc) >= min_h
    assert RAGAnswerer._csv_keyword_override_hit_count(rag, "退去希望です", doc) >= min_h
    other = Document(page_content="x", metadata={"keywords": "ペット|禁止", "keywords_primary": ""})
    assert RAGAnswerer._csv_keyword_override_hit_count(rag, spaced, other) < min_h


def test_match_tier_code_table_matches_metrics() -> None:
    assert match_tier_to_code("strict_hit") == 0
    assert match_tier_to_code("normalized_only") == 1
    assert match_tier_to_code("miss") == 2
    assert match_tier_to_code("unknown") == 3
    assert match_tier_to_code(None) == 3
    assert match_tier_to_code("nope") == 3
    assert set(MATCH_TIER_TO_CODE.values()) == {0, 1, 2, 3}


def test_semantic_neighbor_hit() -> None:
    eq = build_semantic_equivalence_map(
        [{"anchor": "doc_a", "neighbors": ["doc_b", "doc_c"]}]
    )
    assert semantic_neighbor_hit(["doc_b"], ["doc_a"], eq) is True
    assert semantic_neighbor_hit(["doc_x"], ["doc_a"], eq) is False


def test_compute_rag_aggregate_health_gates() -> None:
    m = {
        "avg_recall_at_5": 0.5,
        "fact_error_rate": 0.0,
        "match_tier_miss_rate": 0.4,
    }
    compute_rag_aggregate_health(m)
    assert m["rag_health_pass"] == 1.0
    assert "rag_health_score" in m

    m2 = {"avg_recall_at_5": 0.3, "fact_error_rate": 0.0, "match_tier_miss_rate": 0.4}
    compute_rag_aggregate_health(m2)
    assert m2["rag_health_pass"] == 0.0


def test_infer_failure_bucket_fallback() -> None:
    row = {
        "match_tier": "miss",
        "retrieved_ids": [],
        "expected_doc_ids": ["x"],
        "answer_text": "該当する情報が見つからないため管理会社にお問い合わせください。",
    }
    b = infer_failure_bucket(row, top1_hit=False, top3_hit=False, top5_hit=False)
    assert b == "fallback_or_threshold_issue"


def test_hits_at_k_top3_not_top1() -> None:
    assert hits_at_k(["a", "b", "exp"], ["exp"], 1) is False
    assert hits_at_k(["a", "b", "exp"], ["exp"], 3) is True


def test_faq_keyword_restoration_beats_termination_for_restoration_question() -> None:
    """Regression: 原状回復の質問で 契約_原状回復 のキーワードスコアが 契約_退去解約 以上。"""
    root = Path(__file__).resolve().parent.parent
    faq = root / "data" / "faq_kb.csv"
    by_intent: dict = {}
    with open(faq, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            by_intent[r["intent"]] = r
    q = "退去時の原状回復の基本方針は？"
    s_rest = RAGAnswerer._keyword_score(None, q, by_intent["契約_原状回復"]["keywords"])
    s_can = RAGAnswerer._keyword_score(None, q, by_intent["契約_退去解約"]["keywords"])
    assert s_rest >= s_can


def test_faq_keyword_renewal_row_exists() -> None:
    root = Path(__file__).resolve().parent.parent
    faq = root / "data" / "faq_kb.csv"
    with open(faq, encoding="utf-8") as f:
        text = f.read()
    assert "契約_更新" in text
    assert "契約更新|更新手続き" in text


def test_analyze_failure_patterns_script(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parent.parent
    jl = tmp_path / "one.jsonl"
    row = {
        "success": True,
        "question": "q?",
        "question_id": "Q001",
        "match_tier": "miss",
        "retrieved_ids": ["a", "b", "expected"],
        "expected_doc_ids": ["expected"],
        "expected_doc_ids_strict": ["strict_only"],
    }
    jl.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
    out = tmp_path / "out.csv"
    subprocess.run(
        [sys.executable, str(root / "scripts" / "analyze_failure_patterns.py"), "--input", str(jl), "--output", str(out)],
        check=True,
        cwd=str(root),
    )
    with open(out, newline="", encoding="utf-8") as f:
        r = list(csv.DictReader(f))
    assert len(r) == 1
    assert r[0]["hit_at_1"] == "0"
    assert r[0]["hit_at_3"] == "1"
    assert r[0]["hit_at_5"] == "1"
    tags = set((r[0].get("failure_tags") or "").split("|"))
    assert "should_escalate_but_answered" not in tags


def test_analyze_failure_patterns_preserves_custom_failure_tags(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parent.parent
    jl = tmp_path / "one.jsonl"
    row = {
        "question": "q?",
        "match_tier": "miss",
        "retrieved_sources": [],
        "expected_route": "clarification",
        "actual_route": "rule",
        "decision_path": "rule",
        "fallback_used": True,
        "failure_tags": ["wrong_intent_match"],
    }
    jl.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
    out = tmp_path / "out.csv"
    subprocess.run(
        [sys.executable, str(root / "scripts" / "analyze_failure_patterns.py"), "--input", str(jl), "--output", str(out)],
        check=True,
        cwd=str(root),
    )
    with open(out, newline="", encoding="utf-8") as f:
        r = list(csv.DictReader(f))
    tags = set((r[0].get("failure_tags") or "").split("|"))
    assert "wrong_intent_match" in tags
    assert "fallback_as_rule" in tags
    assert "needs_clarification" in tags
