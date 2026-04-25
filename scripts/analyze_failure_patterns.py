#!/usr/bin/env python3
"""Analyze eval JSONL and extract failure patterns.

Supports legacy eval_results.jsonl and A/B compare JSONL from scripts/run_eval.py.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence


def _root() -> Path:
    return Path(__file__).resolve().parent.parent


def _as_id_list(val: Any) -> List[str]:
    if val is None:
        return []
    if isinstance(val, list):
        return [str(x).strip() for x in val if str(x).strip()]
    if isinstance(val, str) and val.strip():
        return [x.strip() for x in val.split(",") if x.strip()]
    return []


def _hit_at_k(retrieved: Sequence[str], expected: Sequence[str], k: int) -> Optional[bool]:
    if not expected:
        return None
    top = set(retrieved[:k])
    return any(e in top for e in expected)


def _failure_tags(row: Dict[str, Any]) -> List[str]:
    tags: List[str] = []
    existing = row.get("failure_tags")
    if isinstance(existing, list):
        tags.extend(str(t) for t in existing if str(t).strip())
    elif isinstance(existing, str) and existing.strip():
        tags.extend([t.strip() for t in existing.split("|") if t.strip()])
    if row.get("fallback_used"):
        tags.append("fallback_used")
    if row.get("fallback_used") and str(row.get("decision_path") or "") == "rule":
        tags.append("fallback_as_rule")
    if row.get("hallucination"):
        tags.append("hallucination")
    if str(row.get("decision_path") or "") == "rag" and bool(row.get("fallback_used")):
        tags.append("rag_irrelevant_context")
    if (row.get("expected_route") or "") == "escalation" and (row.get("actual_route") or "") != "escalation":
        tags.append("should_escalate_but_answered")
    if (row.get("expected_route") or "") == "clarification" and (row.get("actual_route") or "") in ("rule", "fast_path", "rag"):
        tags.append("needs_clarification")
    mt = str(row.get("match_tier") or "")
    if mt and mt not in ("strict", "normalized"):
        tags.append("match_miss")
    latency = float(row.get("latency_ms") or 0.0)
    if latency >= 2500:
        tags.append("latency_high")
    if not row.get("retrieved_sources"):
        tags.append("no_sources")
    return sorted(set(tags))


def main() -> int:
    parser = argparse.ArgumentParser(description="Failure pattern analysis from eval JSONL")
    parser.add_argument(
        "--input",
        type=Path,
        default=None,
        help="Path to eval JSONL (default: data/eval/eval_results.jsonl)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output CSV path (default: data/eval/failure_patterns.csv)",
    )
    parser.add_argument(
        "--priority-output",
        type=Path,
        default=None,
        help="Output JSON priority summary (default: data/eval/failure_priorities.json)",
    )
    args = parser.parse_args()
    root = _root()
    in_path = args.input or (root / "data" / "eval" / "eval_results.jsonl")
    out_path = args.output or (root / "data" / "eval" / "failure_patterns.csv")
    priority_path = args.priority_output or (root / "data" / "eval" / "failure_priorities.json")

    if not in_path.is_file():
        print(f"Input not found: {in_path}", file=sys.stderr)
        return 1

    rows_out: List[Dict[str, Any]] = []
    tag_scores: Dict[str, float] = {}
    with open(in_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            # Legacy format gate
            if "success" in row and not row.get("success", False):
                continue
            retrieved = _as_id_list(row.get("retrieved_ids"))
            if not retrieved:
                # A/B format fallback
                for src in row.get("retrieved_sources") or []:
                    sid = str((src or {}).get("source_id") or "").strip()
                    if sid:
                        retrieved.append(sid)
            expected_norm = _as_id_list(row.get("expected_doc_ids"))
            expected_strict = _as_id_list(row.get("expected_doc_ids_strict"))
            tags = _failure_tags(row)
            for t in tags:
                # Simple priority: fallback/hallucination high weight
                weight = 3.0 if t in ("hallucination", "fallback_used") else 1.0
                tag_scores[t] = tag_scores.get(t, 0.0) + weight

            h1 = _hit_at_k(retrieved, expected_norm, 1)
            h3 = _hit_at_k(retrieved, expected_norm, 3)
            h5 = _hit_at_k(retrieved, expected_norm, 5)
            h1s = _hit_at_k(retrieved, expected_strict, 1) if expected_strict else None
            h3s = _hit_at_k(retrieved, expected_strict, 3) if expected_strict else None
            h5s = _hit_at_k(retrieved, expected_strict, 5) if expected_strict else None

            def slot(i: int) -> str:
                return retrieved[i] if i < len(retrieved) else ""

            rows_out.append(
                {
                    "question_id": row.get("question_id", ""),
                    "question": row.get("question", ""),
                    "match_tier": row.get("match_tier", ""),
                    "retrieved_top1": slot(0),
                    "retrieved_top2": slot(1),
                    "retrieved_top3": slot(2),
                    "retrieved_top4": slot(3),
                    "retrieved_top5": slot(4),
                    "hit_at_1": int(h1) if h1 is not None else "",
                    "hit_at_3": int(h3) if h3 is not None else "",
                    "hit_at_5": int(h5) if h5 is not None else "",
                    "hit_at_1_strict": int(h1s) if h1s is not None else "",
                    "hit_at_3_strict": int(h3s) if h3s is not None else "",
                    "hit_at_5_strict": int(h5s) if h5s is not None else "",
                    "expected_normalized": "|".join(expected_norm),
                    "expected_strict": "|".join(expected_strict),
                    "system": row.get("system", ""),
                    "decision_path": row.get("decision_path", ""),
                    "latency_ms": row.get("latency_ms", ""),
                    "failure_tags": "|".join(tags),
                }
            )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    if not rows_out:
        print("No successful rows to write.", file=sys.stderr)
        return 0

    fieldnames = list(rows_out[0].keys())
    with open(out_path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows_out)

    priorities = sorted(tag_scores.items(), key=lambda x: x[1], reverse=True)
    top = [{"tag": tag, "score": score} for tag, score in priorities]
    priority_path.parent.mkdir(parents=True, exist_ok=True)
    with open(priority_path, "w", encoding="utf-8") as pf:
        json.dump({"top_failure_tags": top}, pf, ensure_ascii=False, indent=2)

    print(f"Wrote {len(rows_out)} rows to {out_path}")
    print(f"Wrote priority summary to {priority_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
