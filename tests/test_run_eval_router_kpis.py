"""Unit tests for run_eval router KPI helpers (no API calls)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


def _load_run_eval():
    path = Path(__file__).resolve().parent.parent / "scripts" / "run_eval.py"
    spec = importlib.util.spec_from_file_location("run_eval_under_test", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def re():
    return _load_run_eval()


def _rec(ab_group: str, mode: str, actual_route: str, expected_route: str = "x") -> dict:
    return {
        "ab_group": ab_group,
        "expected_route": expected_route,
        "actual_route": actual_route,
        "route_match": actual_route == expected_route,
        "route_match_relaxed": False,
        "debug_trace": {"mode": mode},
    }


def test_compute_router_kpis_a_non_rag_and_b_rag(re):
    all_records = [
        _rec("A", "kb_only", "rule"),
        _rec("A", "kb_only", "fast_path"),
        _rec("A", "rag", "rag"),
        _rec("B", "rag", "rag"),
        _rec("B", "rag", "rag"),
        _rec("B", "kb_only", "rule"),
    ]
    kpis = re.compute_router_kpis(all_records, d_auto_samples=[])
    a = kpis["A_non_rag_rate"]
    assert a["denominator"] == 2
    assert a["numerator"] == 2
    assert a["rate"] == 1.0
    b = kpis["B_rag_rate"]
    assert b["denominator"] == 2
    assert b["numerator"] == 2
    assert b["rate"] == 1.0
    assert kpis["C_clarification_rate"]["rate"] is None
    assert kpis["C_clarification_rate"]["source"] == "line_e2e_required"
    d = kpis["D_escalation_rate"]
    assert d["denominator"] == 0
    assert d["rate"] is None
    assert d["extra_run_count"] == 0


def test_compute_router_kpis_d_escalation(re):
    all_records = []
    d_samples = [
        {"question": "q1", "actual_route": "escalation"},
        {"question": "q2", "actual_route": "rag"},
    ]
    kpis = re.compute_router_kpis(all_records, d_auto_samples=d_samples)
    d = kpis["D_escalation_rate"]
    assert d["numerator"] == 1
    assert d["denominator"] == 2
    assert d["rate"] == 0.5
    assert d["extra_run_count"] == 2


def test_build_route_metrics_schema_v2_legacy_present(re):
    all_records = [
        _rec("A", "kb_only", "rule", expected_route="rule"),
    ]
    out = re.build_route_metrics(all_records, d_auto_samples=[])
    assert out["schema_version"] == 2
    assert "router_kpis" in out
    assert "legacy_route_match" in out
    leg = out["legacy_route_match"]
    assert "route_match_rate_strict" in leg
    assert "by_ab_group" in leg


def test_infer_actual_route_fallback_used_is_fallback(re):
    from src.rag_answerer import AnswerItem, AnswerSchema

    ans = AnswerSchema(
        items=[AnswerItem(text="x", citation="")],
        summary="x",
        evidence=[],
        next_action="",
        caveats="",
    )
    object.__setattr__(ans, "fallback_used", True)
    cfg = type("Cfg", (), {"kb_fast_path_short_max_len": 10, "fallback_message": "fallback"})()
    assert re.infer_actual_route("auto", ans, "q", cfg) == "fallback"


def test_infer_failure_tags_core_cases(re):
    rec = {
        "expected_route": "escalation",
        "actual_route": "rule",
        "decision_path": "rule",
        "question": "家賃減額を請求できますか？",
        "answer": "ガス料金・請求についてご案内します",
        "fallback_used": True,
        "expected_source": "master_only",
    }
    tags = re.infer_failure_tags(rec)
    assert "should_escalate_but_answered" in tags
    assert "fallback_as_rule" in tags
    assert "wrong_intent_match" in tags
    assert "overbroad_rule" in tags
