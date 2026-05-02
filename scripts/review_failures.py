#!/usr/bin/env python3
"""Extract non-pass rows for manual review (reviewer_note editable in CSV).

Includes rows where ``pass_fail`` is empty, null, or anything other than ``pass``
(Phase 1: most rows are ``needs_review``).
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def load_jsonl(path: Path) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            out.append(json.loads(line))
    return out


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Filter eval JSONL for review (pass_fail != pass). "
            "優先度付き改善バックログは: python3 scripts/failure_backlog.py --input <jsonl>"
        )
    )
    parser.add_argument("jsonl", type=Path, nargs="?", help="Input JSONL")
    parser.add_argument(
        "--format",
        choices=("jsonl", "csv"),
        default="csv",
        help="Output format (default: csv)",
    )
    parser.add_argument("-o", "--output", type=Path, default=None, help="Output file (default: stdout)")
    args = parser.parse_args()

    if args.jsonl:
        path = args.jsonl if args.jsonl.is_absolute() else PROJECT_ROOT / args.jsonl
    else:
        runs_dir = PROJECT_ROOT / "eval" / "runs"
        candidates = sorted(runs_dir.glob("run_*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not candidates:
            print("No run_*.jsonl in eval/runs", file=sys.stderr)
            sys.exit(1)
        path = candidates[0]

    recs = [r for r in load_jsonl(path) if (r.get("pass_fail") or "") != "pass"]
    if not recs:
        print("No records with pass_fail != pass")
        return

    out_f = open(args.output, "w", encoding="utf-8", newline="") if args.output else sys.stdout
    try:
        if args.format == "jsonl":
            for r in recs:
                out_f.write(json.dumps(r, ensure_ascii=False) + "\n")
        else:
            fieldnames = [
                "timestamp",
                "run_id",
                "category",
                "question",
                "expected_behavior",
                "should_escalate",
                "fallback_used",
                "pass_fail",
                "reviewer_note",
                "answer",
            ]
            w = csv.DictWriter(out_f, fieldnames=fieldnames, extrasaction="ignore")
            w.writeheader()
            for r in recs:
                row = {k: r.get(k, "") for k in fieldnames}
                w.writerow(row)
    finally:
        if args.output:
            out_f.close()

    if args.output:
        print(f"Wrote {len(recs)} rows to {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
