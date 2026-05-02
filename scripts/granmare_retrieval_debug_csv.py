"""Emit retrieval debug rows (from AnswerSchema.search_debug_info) for granmare YAML cases."""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--fixture",
        choices=("contract", "juyo"),
        default="contract",
        help="Which granmare YAML fixture to scan",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=ROOT / "tests" / "outputs" / "granmare_retrieval_debug.csv",
    )
    args = parser.parse_args()

    from dotenv import load_dotenv, dotenv_values

    load_dotenv(ROOT / ".env", override=False)
    lg = ROOT.parent / "LangGraph" / "code" / ".env"
    k = (dotenv_values(lg).get("OPENAI_API_KEY") or "").strip()
    if k and not k.startswith("your_"):
        os.environ["OPENAI_API_KEY"] = k
    if not os.environ.get("OPENAI_API_KEY") or os.environ["OPENAI_API_KEY"].startswith("your_"):
        print("ERROR: Set OPENAI_API_KEY", file=sys.stderr)
        sys.exit(1)

    import src.config as cfgmod

    cfgmod._config = None
    from src.config import load_config
    from src.rag_eval_utils import keyword_eval_flags
    from src.tenant_auth import TenantAuth
    from src.vector_store_manager import VectorStoreManager
    from src.query_cache import QueryCache
    from src.rag_answerer import RAGAnswerer

    fixture_path = (
        ROOT / "tests" / "fixtures" / "granmare_contract_all_article_cases.yaml"
        if args.fixture == "contract"
        else ROOT / "tests" / "fixtures" / "granmare_important_matters_cases.yaml"
    )
    data = yaml.safe_load(fixture_path.read_text(encoding="utf-8"))
    cases = data["cases"]
    eval_defaults = data.get("eval_defaults") or {}

    config = load_config(force_reload=True)
    rag = RAGAnswerer(config, VectorStoreManager(config), QueryCache(config), TenantAuth(config))

    buf = io.StringIO()
    w = csv.writer(buf, quoting=csv.QUOTE_MINIMAL, lineterminator="\n")
    w.writerow(
        [
            "case_id",
            "query",
            "answer_route",
            "required_ok",
            "rank",
            "filename",
            "doc_kind",
            "article_number",
            "section_id",
            "section_label",
            "intent",
            "used_for_answer",
            "dropped_reason",
            "boost_trace_json",
        ]
    )

    _NullOut = type("_NullOut", (), {"write": lambda self, s="": None, "flush": lambda self: None})()
    old_out, old_err = sys.stdout, sys.stderr

    for i, c in enumerate(cases, 1):
        q = " ".join((c.get("question") or "").split())
        sys.stdout, sys.stderr = _NullOut, _NullOut
        try:
            ans = rag.answer(q, tenant_contract_id="CONTRACT001", persist_cache=False)
            dbg = getattr(ans, "search_debug_info", None) or {}
            cand = dbg.get("retrieval_candidates") or []
            boost = dbg.get("master_metadata_boost") or []
            flags = keyword_eval_flags(ans, c, eval_defaults)
            req_ok = "1" if flags["required_ok"] else "0"
            route = getattr(ans, "decision_path", "") or ""
            if not cand:
                w.writerow([c["id"], q, route, req_ok, "", "", "", "", "", "", "", "", "", json.dumps(boost, ensure_ascii=False)])
            for row in cand:
                w.writerow(
                    [
                        c["id"],
                        q,
                        route,
                        req_ok,
                        row.get("rank", ""),
                        row.get("filename", ""),
                        row.get("doc_kind", ""),
                        row.get("article_number", ""),
                        row.get("section_id", ""),
                        row.get("section_label", ""),
                        row.get("intent", ""),
                        "1" if row.get("used_for_answer") else "0",
                        row.get("dropped_reason", ""),
                        json.dumps(boost, ensure_ascii=False),
                    ]
                )
        finally:
            sys.stdout, sys.stderr = old_out, old_err
        print(f"[{i}/{len(cases)}] {c['id']}", file=old_err, flush=True)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(buf.getvalue(), encoding="utf-8")
    print(str(args.output))


if __name__ == "__main__":
    main()
