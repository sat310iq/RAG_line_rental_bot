"""Regression checks for KB negatives, keyword override union scoring, and eval routing."""

from __future__ import annotations

import csv
import importlib.util
from pathlib import Path

from src.utils.question_terms import count_distinct_pipe_tokens_in_question


def _faq_row_intent(path: Path, intent: str) -> dict[str, str]:
    with open(path, encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            if (row.get("intent") or "").strip() == intent:
                return row
    raise AssertionError(f"intent not found: {intent}")


def test_faq_water_leak_has_negative_keywords():
    root = Path(__file__).resolve().parent.parent
    kb_path = root / "data" / "faq_kb.csv"
    row = _faq_row_intent(kb_path, "設備_水漏れ")
    neg = (row.get("negative_keywords") or "").strip()
    assert "修繕" in neg
    assert "大家負担" in neg
    assert "水道の" not in (row.get("keywords") or "")
    assert "ガス料金" in neg or "家賃減額" in neg


def test_faq_gas_fee_has_cross_domain_negative_keywords():
    root = Path(__file__).resolve().parent.parent
    row = _faq_row_intent(root / "data" / "faq_kb.csv", "生活_ガス料金")
    neg = (row.get("negative_keywords") or "").strip()
    assert "水道" in neg or "ゴミ" in neg
    assert "家賃" in neg


def test_faq_noise_row_has_legal_negative():
    root = Path(__file__).resolve().parent.parent
    kb_path = root / "data" / "faq_kb.csv"
    row = _faq_row_intent(kb_path, "生活_騒音")
    neg = (row.get("negative_keywords") or "").strip()
    assert "訴訟" in neg or "弁護士" in neg


def test_distinct_keyword_union_counts_once():
    q = "水漏れがひどいです"
    n = count_distinct_pipe_tokens_in_question(q, "水漏れ|漏水", "水漏れ|蛇口")
    assert n == 1
    q2 = "蛇口から水漏れと漏水が両方出ています"
    n2 = count_distinct_pipe_tokens_in_question(q2, "水漏れ|漏水", "水漏れ|蛇口")
    assert n2 >= 3


def test_infer_actual_route_maps_fallback():
    path = Path(__file__).resolve().parent.parent / "scripts" / "run_eval.py"
    spec = importlib.util.spec_from_file_location("run_eval_under_test", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    from types import SimpleNamespace

    from src.rag_answerer import AnswerItem, AnswerSchema

    ans = AnswerSchema(
        items=[AnswerItem(text="x", citation="")],
        summary="x",
        evidence=[""],
        next_action="",
        caveats="",
    )
    object.__setattr__(ans, "decision_path", "fallback")
    cfg = SimpleNamespace(kb_fast_path_short_max_len=10)
    assert mod.infer_actual_route("auto", ans, "test", cfg) == "fallback"


def test_estimate_cost_usd_includes_fallback():
    path = Path(__file__).resolve().parent.parent / "scripts" / "run_eval.py"
    spec = importlib.util.spec_from_file_location("run_eval_cost", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.estimate_cost_usd("fallback") < mod.estimate_cost_usd("rag")
