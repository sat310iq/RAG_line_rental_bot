"""Load granmare_important_matters_cases.yaml and write RAG answers to CSV (UTF-8)."""

from __future__ import annotations

import argparse
import csv
import io
import os
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_FIXTURE = ROOT / "tests" / "fixtures" / "granmare_important_matters_cases.yaml"
_OUT = ROOT / "tests" / "outputs" / "granmare_important_matters_rag_answers.csv"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run important-matters YAML cases through RAGAnswerer.")
    parser.add_argument(
        "--with-eval-columns",
        action="store_true",
        help="Add required_ok, forbidden_ok, contract_source_q, answer_body (truncated) columns",
    )
    args = parser.parse_args()

    from dotenv import load_dotenv, dotenv_values

    load_dotenv(ROOT / ".env", override=False)
    lg = ROOT.parent / "LangGraph" / "code" / ".env"
    k = (dotenv_values(lg).get("OPENAI_API_KEY") or "").strip()
    if k and not k.startswith("your_"):
        os.environ["OPENAI_API_KEY"] = k
    if not os.environ.get("OPENAI_API_KEY") or os.environ["OPENAI_API_KEY"].startswith("your_"):
        print("ERROR: Set OPENAI_API_KEY (e.g. in .env)", file=sys.stderr)
        sys.exit(1)

    import src.config as cfgmod

    cfgmod._config = None
    from src.config import load_config
    from src.rag_eval_utils import answer_body_text, keyword_eval_flags
    from src.tenant_auth import TenantAuth
    from src.vector_store_manager import VectorStoreManager
    from src.query_cache import QueryCache
    from src.rag_answerer import RAGAnswerer, render_answer_text

    data = yaml.safe_load(_FIXTURE.read_text(encoding="utf-8"))
    cases = data["cases"]
    eval_defaults = data.get("eval_defaults") or {}

    config = load_config(force_reload=True)
    rag = RAGAnswerer(config, VectorStoreManager(config), QueryCache(config), TenantAuth(config))

    _OutFilter = type(
        "_OutFilter",
        (),
        {
            "write": lambda self, s="": None,
            "flush": lambda self: None,
        },
    )()

    buf = io.StringIO()
    w = csv.writer(buf, quoting=csv.QUOTE_ALL, lineterminator="\n")
    base_cols = ["id", "group", "label", "question", "answer_full"]
    if args.with_eval_columns:
        base_cols.extend(
            ["required_ok", "forbidden_ok", "contract_source_q", "answer_body_400"]
        )
    w.writerow(base_cols)

    old_out, old_err = sys.stdout, sys.stderr
    for i, c in enumerate(cases, 1):
        q = " ".join((c.get("question") or "").split())
        sys.stdout, sys.stderr = _OutFilter, _OutFilter
        try:
            ans = rag.answer(q, tenant_contract_id="CONTRACT001", persist_cache=False)
            full = render_answer_text(ans)
        finally:
            sys.stdout, sys.stderr = old_out, old_err
        row = [c["id"], c.get("group", ""), c.get("label", ""), q, full]
        if args.with_eval_columns:
            flags = keyword_eval_flags(ans, c, eval_defaults)
            csq = bool(getattr(ans, "contract_source_q", False))
            body = answer_body_text(ans)[:400]
            row.extend(
                [
                    "1" if flags["required_ok"] else "0",
                    "1" if flags["forbidden_ok"] else "0",
                    "1" if csq else "0",
                    body,
                ]
            )
        w.writerow(row)
        print(f"[{i}/{len(cases)}] {c['id']}", file=old_err, flush=True)

    _OUT.parent.mkdir(parents=True, exist_ok=True)
    _OUT.write_text(buf.getvalue(), encoding="utf-8")
    print(str(_OUT))


if __name__ == "__main__":
    main()
