"""List case ids with required_ok=0 from a granmare eval CSV (Phase 0 baseline)."""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument(
        "csv_path",
        type=Path,
        nargs="?",
        default=ROOT / "tests" / "outputs" / "granmare_all_cases_rag_answers.csv",
    )
    args = p.parse_args()
    if not args.csv_path.is_file():
        print("No CSV. Run: python3 scripts/run_granmare_contract_case_rag_answers.py --with-eval-columns", file=sys.stderr)
        sys.exit(1)
    with args.csv_path.open(encoding="utf-8") as f:
        r = csv.DictReader(f)
        if "required_ok" not in (r.fieldnames or []):
            print("CSV missing required_ok. Re-run with --with-eval-columns", file=sys.stderr)
            sys.exit(1)
        fail = [row["id"] for row in r if row.get("required_ok") == "0"]
    for i in fail:
        print(i)
    print(f"# count: {len(fail)}", file=sys.stderr)


if __name__ == "__main__":
    main()
