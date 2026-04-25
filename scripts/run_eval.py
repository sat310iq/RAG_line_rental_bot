#!/usr/bin/env python3
"""Lightweight eval runner: CSV in -> JSONL out (Amplifier-style, no Metrics v2).

Future: plug in Ragas or Amplifier batch steps by post-processing eval/runs/*.jsonl.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple

from collections import defaultdict

# Project root = rental_rag_poc/
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.config import load_config  # noqa: E402
from src.query_cache import QueryCache  # noqa: E402
from src.rag_answerer import AnswerSchema, RAGAnswerer, render_answer_text  # noqa: E402
from src.tenant_auth import TenantAuth  # noqa: E402
from src.vector_store_manager import VectorStoreManager  # noqa: E402


def _parse_bool(s: str) -> bool:
    return str(s).strip().lower() in ("1", "true", "yes", "y")


def load_dataset(path: Path) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    with open(path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows


def build_retrieved_sources(answer: AnswerSchema) -> List[Dict[str, str]]:
    """Minimal source list: prefer RAGAnswerer.retrieved_doc_meta when present."""
    meta = getattr(answer, "retrieved_doc_meta", None) or []
    out: List[Dict[str, str]] = []
    for m in meta:
        if not isinstance(m, dict):
            continue
        sid = str(m.get("doc_id") or m.get("source_id") or "")
        out.append(
            {
                "source_type": str(m.get("source_type") or "unknown"),
                "source_id": sid,
                "snippet": "",
            }
        )
    if out:
        return out
    for ev in answer.evidence or []:
        if not ev:
            continue
        out.append(
            {
                "source_type": "evidence",
                "source_id": str(ev),
                "snippet": "",
            }
        )
    return out


def compute_fallback_used(config, answer: AnswerSchema, answer_text: str) -> bool:
    if not answer.evidence:
        return True
    fm = (config.fallback_message or "").strip()
    if fm and fm in answer_text:
        return True
    return False


def estimate_cost_usd(decision_path: str) -> float:
    """Rough relative cost model for A/B comparison."""
    if decision_path == "rag":
        return 0.002
    if decision_path == "rule":
        return 0.0003
    return 0.0001


def _escalation_from_answer(answer: AnswerSchema) -> bool:
    """True if answer carries non-bot_only escalation metadata."""
    ed = getattr(answer, "escalation_data", None)
    if isinstance(ed, dict):
        et = str(ed.get("escalation_type") or "").strip()
        if et and et.lower() != "bot_only":
            return True
    return False


def infer_actual_route(
    eval_mode: Literal["auto", "kb_only", "rag"],
    answer: AnswerSchema,
    question: str,
    config,
) -> str:
    """Normalize **offline-estimated** routing vs CSV ``expected_route`` (not production trace).

    * ``rag`` leg of A/B → always ``rag`` (forced full retrieval).
    * ``kb_only`` leg → ``fast_path`` vs ``rule`` proxy from query length (same
      threshold as auto ``direct`` vs deeper KB path); does not model LINE fast path.
    * ``auto`` → ``escalation`` if metadata says so; else map ``decision_path``.

    ``clarification`` is not produced by this offline harness (use LINE tests).
    """
    if eval_mode == "rag":
        return "rag"
    if eval_mode == "kb_only":
        q = (question or "").strip()
        short_len = int(getattr(config, "kb_fast_path_short_max_len", 10) or 10)
        if len(q) <= max(2, short_len // 2):
            return "fast_path"
        return "rule"
    if _escalation_from_answer(answer):
        return "escalation"
    dp = str(getattr(answer, "decision_path", "") or "")
    if dp == "direct":
        return "fast_path"
    if dp == "rag":
        return "rag"
    if dp == "rule":
        return "rule"
    return "unknown"


def route_match_relaxed(expected: str, actual: str) -> bool:
    """Treat ``fast_path`` and ``rule`` as equivalent non-RAG layers."""
    if not expected:
        return False
    if expected == actual:
        return True
    layer = {"fast_path", "rule"}
    return expected in layer and actual in layer


def _kpi_rate_dict(
    numerator: int,
    denominator: int,
    *,
    definition: str,
) -> Dict[str, Any]:
    if denominator <= 0:
        return {
            "numerator": 0,
            "denominator": 0,
            "rate": None,
            "definition": definition,
        }
    return {
        "numerator": numerator,
        "denominator": denominator,
        "rate": round(numerator / denominator, 4),
        "definition": definition,
    }


def compute_router_kpis(
    all_records: List[Dict[str, object]],
    d_auto_samples: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Purpose-specific KPIs (not raw A/B harness aggregate route_match)."""
    a_kb = [
        r
        for r in all_records
        if r.get("ab_group") == "A"
        and str((r.get("debug_trace") or {}).get("mode") or "") == "kb_only"
    ]
    num_a = sum(1 for r in a_kb if str(r.get("actual_route") or "") in ("fast_path", "rule"))
    a_kpi = _kpi_rate_dict(
        num_a,
        len(a_kb),
        definition="A group, kb_only mode, actual_route in {fast_path, rule} (non-RAG proxy).",
    )

    b_rag = [
        r
        for r in all_records
        if r.get("ab_group") == "B"
        and str((r.get("debug_trace") or {}).get("mode") or "") == "rag"
    ]
    num_b = sum(1 for r in b_rag if str(r.get("actual_route") or "") == "rag")
    b_kpi = _kpi_rate_dict(
        num_b,
        len(b_rag),
        definition="B group, rag forced leg, actual_route == rag.",
    )

    c_kpi: Dict[str, Any] = {
        "rate": None,
        "numerator": None,
        "denominator": None,
        "source": "line_e2e_required",
        "note": "Offline RAGAnswerer harness does not reproduce LINE clarification state.",
    }

    d_denom = len(d_auto_samples)
    d_num = sum(1 for s in d_auto_samples if str(s.get("actual_route") or "") == "escalation")
    d_kpi = _kpi_rate_dict(
        d_num,
        d_denom,
        definition="D-group questions, forced_system=auto, cache_namespace=eval:auto_router; actual_route==escalation.",
    )
    d_kpi["source"] = "auto_extra_run"
    d_kpi["extra_run_count"] = d_denom

    return {
        "A_non_rag_rate": a_kpi,
        "B_rag_rate": b_kpi,
        "C_clarification_rate": c_kpi,
        "D_escalation_rate": d_kpi,
    }


def _legacy_route_match_block(all_records: List[Dict[str, object]], *, max_examples: int = 25) -> Dict[str, Any]:
    """A/B harness aggregate route_match (auxiliary; do not use as primary router KPI)."""
    evaluated: List[Dict[str, object]] = [r for r in all_records if r.get("expected_route")]
    total = len(evaluated)
    strict_hits = sum(1 for r in evaluated if r.get("route_match") is True)
    relaxed_hits = sum(1 for r in evaluated if r.get("route_match_relaxed") is True)

    by_group: defaultdict[str, Dict[str, int]] = defaultdict(
        lambda: {"n": 0, "strict_hits": 0, "relaxed_hits": 0}
    )
    by_mode: defaultdict[str, Dict[str, int]] = defaultdict(
        lambda: {"n": 0, "strict_hits": 0, "relaxed_hits": 0}
    )
    for r in evaluated:
        g = str(r.get("ab_group") or "") or "_"
        mode = str((r.get("debug_trace") or {}).get("mode") or "unknown")
        by_group[g]["n"] += 1
        by_mode[mode]["n"] += 1
        if r.get("route_match") is True:
            by_group[g]["strict_hits"] += 1
            by_mode[mode]["strict_hits"] += 1
        if r.get("route_match_relaxed") is True:
            by_group[g]["relaxed_hits"] += 1
            by_mode[mode]["relaxed_hits"] += 1

    mismatches: List[Dict[str, Any]] = []
    for r in evaluated:
        if r.get("route_match") is True:
            continue
        if len(mismatches) >= max_examples:
            break
        mismatches.append(
            {
                "question": r.get("question"),
                "ab_group": r.get("ab_group"),
                "mode": (r.get("debug_trace") or {}).get("mode"),
                "expected_route": r.get("expected_route"),
                "actual_route": r.get("actual_route"),
                "decision_path": r.get("decision_path"),
            }
        )

    def _rates(hits: int, n: int) -> Dict[str, float]:
        if n <= 0:
            return {"match_rate": 0.0, "mismatch_rate": 0.0}
        return {
            "match_rate": round(hits / n, 4),
            "mismatch_rate": round(1.0 - hits / n, 4),
        }

    group_rates: Dict[str, Any] = {}
    for g, s in by_group.items():
        st = _rates(s["strict_hits"], s["n"])
        rl = _rates(s["relaxed_hits"], s["n"])
        group_rates[g] = {
            "n": s["n"],
            "strict_match_rate": st["match_rate"],
            "strict_mismatch_rate": st["mismatch_rate"],
            "relaxed_match_rate": rl["match_rate"],
        }

    mode_rates: Dict[str, Any] = {}
    for m, s in by_mode.items():
        st = _rates(s["strict_hits"], s["n"])
        rl = _rates(s["relaxed_hits"], s["n"])
        mode_rates[m] = {
            "n": s["n"],
            "strict_match_rate": st["match_rate"],
            "strict_mismatch_rate": st["mismatch_rate"],
            "relaxed_match_rate": rl["match_rate"],
        }

    overall_strict = _rates(strict_hits, total)["match_rate"] if total else 0.0
    overall_relaxed = _rates(relaxed_hits, total)["match_rate"] if total else 0.0

    return {
        "description": "A/B compare harness aggregate; not equal to production router performance.",
        "notes": (
            "kb_only leg uses length-based fast_path vs rule proxy; "
            "clarification not observed offline; escalation only when auto + escalation_data."
        ),
        "records_with_expected_route": total,
        "route_match_rate_strict": overall_strict,
        "route_match_rate_relaxed": overall_relaxed,
        "route_mismatch_rate_strict": round(1.0 - overall_strict, 4) if total else 0.0,
        "strict_matches": strict_hits,
        "relaxed_matches": relaxed_hits,
        "by_ab_group": group_rates,
        "by_mode": mode_rates,
        "route_mismatch_examples": mismatches,
    }


def build_route_metrics(
    all_records: List[Dict[str, object]],
    *,
    max_examples: int = 25,
    d_auto_samples: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Build route_metrics for ab_summary.json (schema_version 2)."""
    legacy = _legacy_route_match_block(all_records, max_examples=max_examples)
    kpis = compute_router_kpis(all_records, d_auto_samples or [])
    return {
        "schema_version": 2,
        "notes": (
            "Primary KPIs: router_kpis. A/B harness aggregate: legacy_route_match. "
            "A/B compare log vs router improvement use different slices."
        ),
        "router_kpis": kpis,
        "legacy_route_match": legacy,
    }


def run_single(
    rag: RAGAnswerer,
    *,
    question: str,
    tenant_contract_id: str | None,
    forced_system: Literal["auto", "kb_only", "rag"],
    allow_semantic_cache: bool,
    cache_namespace: Optional[str] = None,
) -> Tuple[AnswerSchema, float]:
    t0 = time.perf_counter()
    ns = cache_namespace if cache_namespace else f"eval:{forced_system}"
    answer = rag.answer(
        question,
        tenant_contract_id=tenant_contract_id,
        forced_system=forced_system,
        cache_namespace=ns,
        allow_semantic_cache=allow_semantic_cache,
    )
    latency_ms = (time.perf_counter() - t0) * 1000.0
    return answer, latency_ms


def main() -> None:
    parser = argparse.ArgumentParser(description="Run lightweight LINE RAG eval (JSONL).")
    parser.add_argument(
        "--dataset",
        type=Path,
        default=PROJECT_ROOT / "eval" / "datasets" / "line_rag_eval_router_abcd_v1.csv",
        help="Path to eval CSV (see docs/eval/RAG_ROUTING_AND_AB_REDESIGN.md; legacy: line_rag_eval_v1.csv)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output JSONL path (default: eval/runs/run_<timestamp>.jsonl)",
    )
    parser.add_argument(
        "--tenant-contract-id",
        default=None,
        help="Optional tenant contract id passed to RAGAnswerer.answer()",
    )
    parser.add_argument(
        "--ab-compare",
        action="store_true",
        help="Run both KB_only and RAG modes for each question",
    )
    parser.add_argument(
        "--summary-output",
        type=Path,
        default=PROJECT_ROOT / "data" / "eval" / "ab_summary.json",
        help="Summary JSON output path",
    )
    parser.add_argument(
        "--disable-semantic-cache",
        action="store_true",
        help="Disable semantic cache during evaluation for cleaner A/B separation",
    )
    args = parser.parse_args()

    dataset_path = args.dataset if args.dataset.is_absolute() else PROJECT_ROOT / args.dataset
    if not dataset_path.exists():
        print(f"Dataset not found: {dataset_path}", file=sys.stderr)
        sys.exit(1)

    try:
        config = load_config()
    except ValueError as e:
        print(f"Configuration error: {e}", file=sys.stderr)
        sys.exit(1)

    run_id = uuid.uuid4().hex
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = args.output
    if out_path is None:
        out_dir = PROJECT_ROOT / "eval" / "runs"
        out_dir.mkdir(parents=True, exist_ok=True)
        prefix = "ab_compare" if args.ab_compare else "run"
        out_path = out_dir / f"{prefix}_{ts}.jsonl"
    else:
        out_path = out_path if out_path.is_absolute() else PROJECT_ROOT / out_path
        out_path.parent.mkdir(parents=True, exist_ok=True)

    rows = load_dataset(dataset_path)
    print(f"Loaded {len(rows)} rows from {dataset_path}")
    print(f"run_id={run_id} -> {out_path}")

    tenant_auth = TenantAuth(config)
    vector_store_manager = VectorStoreManager(config)
    query_cache = QueryCache(config)
    query_cache.clear()
    rag = RAGAnswerer(config, vector_store_manager, query_cache, tenant_auth)

    summary = {
        "run_id": run_id,
        "dataset": str(dataset_path),
        "total_rows": len(rows),
        "systems": {},
    }

    all_records: List[Dict[str, object]] = []
    with open(out_path, "w", encoding="utf-8") as out_f:
        for i, row in enumerate(rows, 1):
            question = (row.get("question") or "").strip()
            category = (row.get("category") or "").strip()
            expected_behavior = (row.get("expected_behavior") or "").strip()
            expected_source = (row.get("expected_source") or "").strip()
            should_escalate = _parse_bool(row.get("should_escalate") or "false")
            ab_group = (row.get("ab_group") or "").strip()
            expected_route = (row.get("expected_route") or "").strip()

            modes: List[Literal["auto", "kb_only", "rag"]]
            if args.ab_compare:
                modes = ["kb_only", "rag"]
            else:
                modes = ["auto"]

            for mode in modes:
                answer, latency_ms = run_single(
                    rag,
                    question=question,
                    tenant_contract_id=args.tenant_contract_id,
                    forced_system=mode,
                    allow_semantic_cache=not args.disable_semantic_cache,
                )
                answer_text = render_answer_text(answer).strip()
                fb = compute_fallback_used(config, answer, answer_text)
                sources = build_retrieved_sources(answer)
                decision_path = str(getattr(answer, "decision_path", "rag"))
                system = str(getattr(answer, "system", "RAG" if mode == "rag" else "KB_only"))
                cost = estimate_cost_usd(decision_path)
                fix_required = bool(fb) or len(sources) == 0
                actual_route = infer_actual_route(mode, answer, question, config)
                exp_rt = expected_route or ""
                route_strict = bool(exp_rt) and actual_route == exp_rt
                route_relaxed = bool(exp_rt) and route_match_relaxed(exp_rt, actual_route)
                rec = {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "run_id": run_id,
                    "question": question,
                    "raw_text": question,
                    "resolved_text": question,
                    "category": category,
                    "expected_behavior": expected_behavior,
                    "expected_source": expected_source,
                    "should_escalate": should_escalate,
                    "ab_group": ab_group or None,
                    "expected_route": expected_route or None,
                    "actual_route": actual_route,
                    "route_match": route_strict if exp_rt else None,
                    "route_match_relaxed": route_relaxed if exp_rt else None,
                    "system": system,
                    "decision_path": decision_path,
                    "retrieval_used": bool(getattr(answer, "retrieval_used", len(sources) > 0)),
                    "answer": answer_text,
                    "retrieved_sources": sources,
                    "latency_ms": round(latency_ms, 3),
                    "fallback_used": fb,
                    "match_tier": "needs_review",
                    "hallucination": False,
                    "cost": cost,
                    "debug_trace": {
                        "mode": mode,
                        "evidence_count": len(answer.evidence or []),
                        "source_count": len(sources),
                    },
                    "fix_required": fix_required,
                    "failure_tags": [],
                    "pass_fail": "needs_review",
                    "reviewer_note": "",
                }
                all_records.append(rec)
                out_f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                sys_summary = summary["systems"].setdefault(
                    system,
                    {"count": 0, "latency_ms": [], "cost_total": 0.0, "fallback_count": 0},
                )
                sys_summary["count"] += 1
                sys_summary["latency_ms"].append(rec["latency_ms"])
                sys_summary["cost_total"] += cost
                if fb:
                    sys_summary["fallback_count"] += 1

            print(f"  [{i}/{len(rows)}] {question[:48]}... modes={','.join(modes)}")

    d_auto_samples: List[Dict[str, Any]] = []
    if args.ab_compare:
        d_rows = [row for row in rows if (row.get("ab_group") or "").strip() == "D"]
        if d_rows:
            print(f"Router KPI: D-group auto extra runs ({len(d_rows)}), cache_namespace=eval:auto_router")
        for row in d_rows:
            q = (row.get("question") or "").strip()
            if not q:
                continue
            answer, lat_ms = run_single(
                rag,
                question=q,
                tenant_contract_id=args.tenant_contract_id,
                forced_system="auto",
                allow_semantic_cache=False,
                cache_namespace="eval:auto_router",
            )
            ar = infer_actual_route("auto", answer, q, config)
            d_auto_samples.append(
                {
                    "question": q,
                    "actual_route": ar,
                    "latency_ms": round(lat_ms, 3),
                }
            )

    def infer_observed_source(sources: List[Dict[str, str]]) -> str:
        if not sources:
            return "none"
        types = {str(s.get("source_type") or "") for s in sources}
        has_deal = "deal" in types
        has_master = "master" in types
        if has_deal and has_master:
            return "multi"
        if has_deal:
            return "deal_only"
        if has_master:
            return "master_only"
        # evidence-only fallback (legacy path) is ambiguous; do not over-penalize.
        return "unknown"

    behavior_stopwords = {
        "FAQ", "KB", "CSV", "PDF", "RAG", "案内", "説明", "連絡先", "確認", "手順",
        "基づき", "基づく", "する", "すること", "述べる", "促す", "対応", "管理会社",
        "一般論", "必要", "不足", "検索", "列挙",
    }

    def behavior_hit_count(expected_behavior: str, answer: str) -> int:
        tokens = re.findall(r"[A-Za-z一-龥ぁ-んァ-ン]{2,}", expected_behavior or "")
        filtered = [t for t in tokens if t not in behavior_stopwords]
        uniq = []
        for t in filtered:
            if t not in uniq:
                uniq.append(t)
        return sum(1 for t in uniq if t in (answer or ""))

    def classify_match_tier(rec: Dict[str, object]) -> str:
        exp_source = str(rec.get("expected_source") or "")
        obs_source = infer_observed_source(rec.get("retrieved_sources") or [])
        ans = str(rec.get("answer") or "")
        fb = bool(rec.get("fallback_used"))
        hit = behavior_hit_count(str(rec.get("expected_behavior") or ""), ans)

        source_strict = (obs_source == exp_source)
        source_soft = source_strict or obs_source == "unknown"
        if exp_source == "none" and fb:
            source_soft = True
            source_strict = True

        if source_strict and hit >= 2 and not fb:
            return "strict"
        if source_soft and hit >= 1 and not fb:
            return "normalized"
        if source_soft and fb and exp_source in ("none", "master_only"):
            return "normalized"
        return "miss"

    # Overwrite match_tier with lightweight auto score and write scored summary
    for rec in all_records:
        rec["match_tier"] = classify_match_tier(rec)

    with open(out_path, "w", encoding="utf-8") as out_f:
        for rec in all_records:
            out_f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    # Diff report: questions where KB-only and RAG answers diverge
    by_q: Dict[str, Dict[str, Dict[str, object]]] = {}
    for rec in all_records:
        q = str(rec.get("question") or "")
        mode = str((rec.get("debug_trace") or {}).get("mode") or "")
        by_q.setdefault(q, {})[mode] = rec

    diff_path = PROJECT_ROOT / "data" / "eval" / "ab_diff_report.jsonl"
    with open(diff_path, "w", encoding="utf-8") as df:
        for q, group in by_q.items():
            kb = group.get("kb_only")
            rg = group.get("rag")
            if not kb or not rg:
                continue
            if str(kb.get("answer") or "").strip() == str(rg.get("answer") or "").strip():
                continue
            rec = {
                "question": q,
                "expected_behavior": kb.get("expected_behavior") or rg.get("expected_behavior"),
                "expected_source": kb.get("expected_source") or rg.get("expected_source"),
                "ab_group": kb.get("ab_group") or rg.get("ab_group"),
                "expected_route": kb.get("expected_route") or rg.get("expected_route"),
                "kb_only_answer": kb.get("answer", ""),
                "rag_answer": rg.get("answer", ""),
                "kb_only_decision_path": kb.get("decision_path", ""),
                "rag_decision_path": rg.get("decision_path", ""),
            }
            df.write(json.dumps(rec, ensure_ascii=False) + "\n")

    for system, s in summary["systems"].items():
        lat = sorted(s["latency_ms"])
        if lat:
            p50 = lat[int(0.50 * (len(lat) - 1))]
            p95 = lat[int(0.95 * (len(lat) - 1))]
        else:
            p50 = 0.0
            p95 = 0.0
        s["latency_p50_ms"] = p50
        s["latency_p95_ms"] = p95
        s["cost_per_1000_requests"] = (s["cost_total"] / max(1, s["count"])) * 1000.0
        del s["latency_ms"]

    # scored summary by mode
    scored: Dict[str, Dict[str, object]] = {}
    for rec in all_records:
        mode = str((rec.get("debug_trace") or {}).get("mode") or "unknown")
        scored.setdefault(mode, {"count": 0, "strict": 0, "normalized": 0, "miss": 0})
        scored[mode]["count"] += 1
        tier = str(rec.get("match_tier") or "miss")
        if tier in ("strict", "normalized", "miss"):
            scored[mode][tier] += 1
    scored_path = PROJECT_ROOT / "data" / "eval" / "ab_scored_summary.json"
    with open(scored_path, "w", encoding="utf-8") as sf:
        json.dump({"run_id": run_id, "scored": scored}, sf, ensure_ascii=False, indent=2)

    summary["route_metrics"] = build_route_metrics(all_records, d_auto_samples=d_auto_samples)
    rm = summary["route_metrics"]
    mismatch_report_path = PROJECT_ROOT / "data" / "eval" / "route_mismatch_report.jsonl"
    mismatch_report_path.parent.mkdir(parents=True, exist_ok=True)
    mismatch_rows = 0
    with open(mismatch_report_path, "w", encoding="utf-8") as mf:
        for r in all_records:
            if not r.get("expected_route"):
                continue
            if r.get("route_match") is True:
                continue
            row = {
                "question": r.get("question"),
                "ab_group": r.get("ab_group"),
                "mode": (r.get("debug_trace") or {}).get("mode"),
                "expected_route": r.get("expected_route"),
                "actual_route": r.get("actual_route"),
                "decision_path": r.get("decision_path"),
                "system": r.get("system"),
                "route_match_relaxed": r.get("route_match_relaxed"),
            }
            mf.write(json.dumps(row, ensure_ascii=False) + "\n")
            mismatch_rows += 1
    rm["route_mismatch_report"] = "data/eval/route_mismatch_report.jsonl"
    rm["route_mismatch_report_rows"] = mismatch_rows

    summary_path = args.summary_output if args.summary_output.is_absolute() else PROJECT_ROOT / args.summary_output
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    with open(summary_path, "w", encoding="utf-8") as sf:
        json.dump(summary, sf, ensure_ascii=False, indent=2)

    print(f"Summary written: {summary_path}")
    print(f"Diff report written: {diff_path}")
    print(f"Scored summary written: {scored_path}")
    print(f"Route mismatch report written: {mismatch_report_path} ({mismatch_rows} rows)")
    rk = rm.get("router_kpis") or {}
    a_nr = rk.get("A_non_rag_rate") or {}
    b_rr = rk.get("B_rag_rate") or {}
    d_er = rk.get("D_escalation_rate") or {}
    print(
        "Router KPIs: "
        f"A_non_rag_rate={a_nr.get('rate')} ({a_nr.get('numerator')}/{a_nr.get('denominator')}), "
        f"B_rag_rate={b_rr.get('rate')} ({b_rr.get('numerator')}/{b_rr.get('denominator')}), "
        f"D_escalation_rate={d_er.get('rate')} ({d_er.get('numerator')}/{d_er.get('denominator')}, "
        f"extra_runs={d_er.get('extra_run_count', 0)}), "
        "C_clarification_rate=null (line_e2e_required)"
    )
    leg = rm.get("legacy_route_match") or {}
    if leg.get("records_with_expected_route"):
        print(
            "Legacy route_match (aux): "
            f"strict={leg.get('route_match_rate_strict')} relaxed={leg.get('route_match_rate_relaxed')} "
            f"(n={leg.get('records_with_expected_route')})"
        )
    print("Done.")


if __name__ == "__main__":
    main()
