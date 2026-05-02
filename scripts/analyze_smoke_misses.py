#!/usr/bin/env python3
"""Smoke eval miss analysis: eval_results.jsonl -> CSV + summary markdown."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List

# Add parent directory for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.eval_smoke_analysis import build_summary_md, row_to_analysis


def _root() -> Path:
    return Path(__file__).resolve().parent.parent


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze smoke eval misses from eval_results.jsonl")
    parser.add_argument("--input", type=Path, default=None)
    parser.add_argument("--csv-out", type=Path, default=None)
    parser.add_argument("--summary-out", type=Path, default=None)
    args = parser.parse_args()
    root = _root()
    in_path = args.input or (root / "data" / "eval" / "eval_results.jsonl")
    csv_out = args.csv_out or (root / "data" / "eval" / "smoke_miss_analysis.csv")
    summary_out = args.summary_out or (root / "data" / "eval" / "smoke_miss_summary.md")

    if not in_path.is_file():
        print(f"Input not found: {in_path}", file=sys.stderr)
        return 1

    rows_out: List[Dict[str, Any]] = []
    with open(in_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if not row.get("success", False):
                continue
            rows_out.append(row_to_analysis(row))

    if not rows_out:
        print("No successful rows.", file=sys.stderr)
        return 1

    bucket_counts: Counter[str] = Counter(r["failure_bucket"] for r in rows_out)
    csv_out.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows_out[0].keys())
    with open(csv_out, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows_out)

    with open(summary_out, "w", encoding="utf-8") as f:
        f.write(build_summary_md(rows_out, bucket_counts))

    print(f"Wrote {len(rows_out)} rows -> {csv_out}")
    print(f"Wrote summary -> {summary_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
