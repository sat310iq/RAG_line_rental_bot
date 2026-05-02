"""Integration: RAG answers for granmare contract cases vs required/forbidden keywords.

Run: RUN_CONTRACT_RAG_INTEGRATION=1 python3 -m pytest tests/test_granmare_contract_rag_keywords.py -m integration

Optional: RUN_CONTRACT_RAG_INTEGRATION_MAX=12 (default 8) limits case count.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.integration

_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "granmare_contract_all_article_cases.yaml"
_ROOT = Path(__file__).resolve().parent.parent


def _fixture_data():
    raw = yaml.safe_load(_FIXTURE.read_text(encoding="utf-8"))
    return raw.get("eval_defaults") or {}, raw.get("cases") or []


@pytest.fixture(scope="module")
def rag_module():
    if os.environ.get("RUN_CONTRACT_RAG_INTEGRATION") != "1":
        pytest.skip("Set RUN_CONTRACT_RAG_INTEGRATION=1 to run live RAG keyword tests")
    if not os.environ.get("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY required for integration")

    from dotenv import load_dotenv

    load_dotenv(_ROOT / ".env", override=False)
    lg = _ROOT.parent / "LangGraph" / "code" / ".env"
    if lg.is_file():
        from dotenv import dotenv_values

        k = (dotenv_values(lg).get("OPENAI_API_KEY") or "").strip()
        if k and not k.startswith("your_"):
            os.environ["OPENAI_API_KEY"] = k

    import src.config as cfgmod

    cfgmod._config = None
    from src.config import load_config
    from src.query_cache import QueryCache
    from src.rag_answerer import RAGAnswerer
    from src.tenant_auth import TenantAuth
    from src.vector_store_manager import VectorStoreManager

    config = load_config(force_reload=True)
    return RAGAnswerer(config, VectorStoreManager(config), QueryCache(config), TenantAuth(config))


def test_granmare_contract_cases_keyword_gates(rag_module):
    from src.rag_answerer import render_answer_text
    from src.rag_eval_utils import answer_body_text, default_required_keywords, merged_forbidden_keywords

    defaults, cases = _fixture_data()
    max_n = int(os.environ.get("RUN_CONTRACT_RAG_INTEGRATION_MAX", "8"))
    failures: list[str] = []

    for case in cases[:max_n]:
        q = " ".join((case.get("question") or "").split())
        ans = rag_module.answer(q, tenant_contract_id="CONTRACT001", persist_cache=False)
        body = answer_body_text(ans)
        render_answer_text(ans)  # smoke: full render path

        for forbidden in merged_forbidden_keywords(case, defaults):
            if forbidden in body:
                failures.append(f"{case['id']}: forbidden {forbidden!r} in answer body")

        for req in default_required_keywords(case):
            if req and req not in body:
                failures.append(f"{case['id']}: missing required {req!r} in body")

    assert not failures, "\n".join(failures)
