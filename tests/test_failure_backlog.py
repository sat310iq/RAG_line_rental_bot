"""Unit tests for scripts/failure_backlog.py (no API)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_fb():
    p = ROOT / "scripts" / "failure_backlog.py"
    spec = importlib.util.spec_from_file_location("failure_backlog", p)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _base_rec(**overrides):
    d = {
        "question": "Q",
        "ab_group": "A",
        "expected_route": "escalation",
        "actual_route": "rule",
        "answer": "x" * 400,
        "failure_tags": [],
        "debug_trace": {"mode": "auto"},
    }
    d.update(overrides)
    return d


def test_merge_failure_tags_adds_wrong_intent() -> None:
    fb = _load_fb()
    rec = {
        "failure_tags": [],
        "question": "家賃減額を請求できますか？",
        "answer": "ガス料金のお問い合わせはプロパン会社へ。",
    }
    tags = fb.merge_failure_tags(rec)
    assert "wrong_intent_match" in tags


def test_priority_p0_auto_escalation() -> None:
    fb = _load_fb()
    p, n = fb.assign_priority(
        {"should_escalate_but_answered"},
        "auto",
        "何か？",
        "答え",
    )
    assert p == "P0" and n == 0


def test_priority_p2_forced_leg_no_wrong_p0() -> None:
    fb = _load_fb()
    p, n = fb.assign_priority(
        {"should_escalate_but_answered"},
        "kb_only",
        "一般的な相談",
        "通常回答です。",
    )
    assert p == "P2" and n == 2


def test_build_backlog_root_cause_auto_escalation() -> None:
    fb = _load_fb()
    rows = [
        _base_rec(
            failure_tags=["should_escalate_but_answered"],
            debug_trace={"mode": "auto"},
            question="管理会社に連絡すべき？",
        )
    ]
    out = fb.build_backlog_rows(rows, top_n=10)
    assert len(out) == 1
    assert out[0]["root_cause"] == "missing_escalation_pattern"
    assert out[0]["fix_type"] == "escalation_pattern"
    assert out[0]["priority"] == "P0"


def test_build_backlog_forced_leg_knowledge() -> None:
    fb = _load_fb()
    rows = [
        _base_rec(
            failure_tags=["should_escalate_but_answered"],
            debug_trace={"mode": "kb_only"},
            question="x",
        )
    ]
    out = fb.build_backlog_rows(rows, top_n=10)
    assert out[0]["root_cause"] == "forced_leg_bypasses_auto_escalation"
    assert out[0]["priority"] == "P2"


def test_cli_writes_jsonl(tmp_path: Path) -> None:
    fb = _load_fb()
    jsonl = tmp_path / "in.jsonl"
    r = _base_rec(
        failure_tags=["should_escalate_but_answered"],
        debug_trace={"mode": "auto"},
    )
    jsonl.write_text(json.dumps(r, ensure_ascii=False) + "\n", encoding="utf-8")
    jout = tmp_path / "out.jsonl"
    mout = tmp_path / "out.md"
    # simulate main with argparse — call helpers instead
    rows = fb.load_jsonl(jsonl)
    backlog = fb.build_backlog_rows(rows, 10)
    jout.write_text(
        "\n".join(json.dumps(x, ensure_ascii=False) for x in backlog) + "\n"
    )
    assert backlog[0]["rank"] == 1
    fb.write_summary_md(mout, jsonl, backlog, rows, 10)
    text = mout.read_text(encoding="utf-8")
    assert "Router KPI vs forced legs" in text
    assert "Recommended next commit" in text
