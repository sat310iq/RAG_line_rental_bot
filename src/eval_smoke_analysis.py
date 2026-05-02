"""Shared helpers for smoke miss analysis (used by scripts/analyze_smoke_misses.py and tests)."""

from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List, Sequence


def as_list(val: Any) -> List[str]:
    if val is None:
        return []
    if isinstance(val, list):
        return [str(x).strip() for x in val if str(x).strip()]
    if isinstance(val, str) and val.strip():
        return [x.strip() for x in val.split(",") if x.strip()]
    return []


def preview(text: str, max_len: int = 200) -> str:
    t = (text or "").replace("\n", " ").strip()
    if len(t) <= max_len:
        return t
    return t[: max_len - 3] + "..."


def hits_at_k(
    retrieved: Sequence[str],
    expected_normalized: Sequence[str],
    k: int,
) -> bool:
    if not expected_normalized:
        return False
    top = set(retrieved[:k])
    return any(e in top for e in expected_normalized)


def infer_failure_bucket(
    row: Dict[str, Any],
    *,
    top1_hit: bool,
    top3_hit: bool,
    top5_hit: bool,
) -> str:
    """Heuristic failure bucket for triage."""
    answer_text = (row.get("answer_text") or "")
    a = row.get("answer") if isinstance(row.get("answer"), dict) else {}
    ans = (a.get("summary") or "") if a else ""
    preview_text = answer_text or ans
    retrieved = as_list(row.get("retrieved_ids"))
    exp_n = as_list(row.get("expected_doc_ids"))
    match_tier = (row.get("match_tier") or "").strip()
    fallback_phrase = "該当する情報が見つからない" in preview_text

    if exp_n == ["none"] or (len(exp_n) == 1 and str(exp_n[0]).lower() == "none"):
        return "policy_or_metric_noise"

    if not retrieved and fallback_phrase:
        return "fallback_or_threshold_issue"

    if match_tier == "normalized_only":
        return "id_mismatch_only"

    if match_tier in ("miss", "unknown"):
        if top3_hit and not top1_hit:
            return "rerank_or_selection_issue"
        if not top5_hit:
            return "retrieval_miss"
        u = float(row.get("hallucination_unsourced_claim") or 0.0)
        o = float(row.get("hallucination_overreach") or 0.0)
        if u > 0.5 or o > 0.5:
            return "policy_or_metric_noise"

    if match_tier == "strict_hit" and not top1_hit:
        return "rerank_or_selection_issue"

    return "unknown"


def row_to_analysis(row: Dict[str, Any]) -> Dict[str, Any]:
    retrieved = as_list(row.get("retrieved_ids"))
    exp_n = as_list(row.get("expected_doc_ids"))
    exp_s = as_list(row.get("expected_doc_ids_strict"))
    a = row.get("answer") if isinstance(row.get("answer"), dict) else {}
    summary = (a.get("summary") or "") if a else ""

    top1_hit = hits_at_k(retrieved, exp_n, 1)
    top3_hit = hits_at_k(retrieved, exp_n, 3)
    top5_hit = hits_at_k(retrieved, exp_n, 5)

    bucket = infer_failure_bucket(
        row,
        top1_hit=top1_hit,
        top3_hit=top3_hit,
        top5_hit=top5_hit,
    )

    def top_slot(i: int) -> str:
        return retrieved[i] if i < len(retrieved) else ""

    return {
        "question_id": row.get("question_id", ""),
        "question": row.get("question", ""),
        "question_type": row.get("question_type", ""),
        "match_tier": row.get("match_tier", ""),
        "failure_bucket": bucket,
        "top1_hit": int(top1_hit),
        "top3_hit": int(top3_hit),
        "top5_hit": int(top5_hit),
        "recall_at_5": row.get("recall_at_5", ""),
        "recall_at_5_strict": row.get("recall_at_5_strict", ""),
        "expected_doc_ids_strict": "|".join(exp_s),
        "expected_doc_ids": "|".join(exp_n),
        "retrieved_ids": "|".join(retrieved),
        "retrieved_top1": top_slot(0),
        "retrieved_top3": "|".join([top_slot(i) for i in range(min(3, len(retrieved)))]),
        "answer_summary": preview(summary or row.get("answer_text", "")),
        "contains_pii": int(bool(row.get("contains_pii"))),
        "pii_true_leak_suspected": int(bool(row.get("pii_true_leak_suspected"))),
        "pii_policy_allowed_contact": int(bool(row.get("pii_policy_allowed_contact"))),
        "pii_false_positive_prone": int(bool(row.get("pii_false_positive_prone"))),
        "hallucination_fact_error": row.get("hallucination_fact_error", ""),
        "hallucination_unsourced_claim": row.get("hallucination_unsourced_claim", ""),
        "hallucination_overreach": row.get("hallucination_overreach", ""),
    }


def build_summary_md(rows: List[Dict[str, Any]], bucket_counts: Counter[str]) -> str:
    lines = [
        "# Smoke miss / failure analysis summary",
        "",
        "## failure_bucket counts",
        "",
        "| bucket | count |",
        "|--------|-------|",
    ]
    for k, v in sorted(bucket_counts.items(), key=lambda x: (-x[1], x[0])):
        lines.append(f"| {k} | {v} |")
    lines.extend(
        [
            "",
            "## selection vs retrieval (normalized expected)",
            "",
        ]
    )
    sel = sum(1 for r in rows if r.get("top3_hit") == 1 and r.get("top1_hit") == 0)
    lines.append(f"- top3_hit & not top1_hit: **{sel}** (rerank / selection / penalty candidate)")
    lines.append(
        f"- top5_hit false: **{sum(1 for r in rows if r.get('top5_hit') == 0)}** (retrieval / KB candidate)"
    )
    lines.append("")
    return "\n".join(lines)
