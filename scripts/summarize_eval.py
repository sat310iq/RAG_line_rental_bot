#!/usr/bin/env python3
"""Summarize a run_eval.py JSONL file (counts, latency, categories)."""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def load_records(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def percentile(sorted_vals: List[float], p: float) -> float:
    if not sorted_vals:
        return 0.0
    k = (len(sorted_vals) - 1) * p
    f = int(k)
    c = min(f + 1, len(sorted_vals) - 1)
    if f == c:
        return sorted_vals[f]
    return sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f)


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize eval JSONL from run_eval.py")
    parser.add_argument("jsonl", type=Path, nargs="?", help="Path to JSONL (default: latest under eval/runs)")
    args = parser.parse_args()

    if args.jsonl:
        path = args.jsonl if args.jsonl.is_absolute() else PROJECT_ROOT / args.jsonl
    else:
        runs_dir = PROJECT_ROOT / "eval" / "runs"
        if not runs_dir.is_dir():
            print("No eval/runs directory.", file=sys.stderr)
            sys.exit(1)
        candidates = sorted(runs_dir.glob("run_*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not candidates:
            print("No run_*.jsonl in eval/runs", file=sys.stderr)
            sys.exit(1)
        path = candidates[0]

    recs = load_records(path)
    n = len(recs)
    if n == 0:
        print("No records.")
        return

    pf = Counter(r.get("pass_fail") or "unknown" for r in recs)
    cats = Counter((r.get("category") or "").strip() or "unknown" for r in recs)
    fb_n = sum(1 for r in recs if r.get("fallback_used"))
    latencies = sorted(float(r.get("latency_ms") or 0) for r in recs)

    mean_lat = statistics.mean(latencies)
    p50 = percentile(latencies, 0.50)
    p95 = percentile(latencies, 0.95)

    print(f"File: {path}")
    print(f"Total: {n}")
    print("pass_fail:", dict(pf))
    print("category distribution:", dict(cats))
    print(f"fallback rate: {fb_n / n:.4f} ({fb_n}/{n})")
    print(f"latency_ms: mean={mean_lat:.2f} p50={p50:.2f} p95={p95:.2f}")


if __name__ == "__main__":
    main()
