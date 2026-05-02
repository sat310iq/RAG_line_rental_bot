"""重要事項説明書ケースの expected_snippets 整合テスト。"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "granmare_important_matters_cases.yaml"
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_EXPECTED_TOTAL = 12


def _load():
    data = yaml.safe_load(_FIXTURE.read_text(encoding="utf-8"))
    path = _PROJECT_ROOT / data["contract_document"]
    return path, data["cases"], data.get("eval_defaults") or {}


_DOC_PATH, _CASES, _EVAL_DEFAULTS = _load()


def test_fixture_has_expected_case_count():
    assert len(_CASES) == _EXPECTED_TOTAL


def test_fixture_has_eval_defaults():
    assert "forbidden_keywords" in _EVAL_DEFAULTS
    assert isinstance(_EVAL_DEFAULTS["forbidden_keywords"], list)
    assert _EVAL_DEFAULTS["forbidden_keywords"]


@pytest.mark.parametrize("case", _CASES, ids=[c["id"] for c in _CASES])
def test_question_snippets_exist_in_doc(case):
    assert _DOC_PATH.is_file(), f"Missing: {_DOC_PATH}"
    text = _DOC_PATH.read_text(encoding="utf-8")
    missing = [s for s in case["expected_snippets"] if s not in text]
    assert not missing, f"{case['id']}: not in doc: {missing}"


def test_each_case_has_question_and_metadata():
    for c in _CASES:
        assert c.get("group") == "重要事項説明書"
        assert c.get("label")
        q = (c.get("question") or "").strip()
        assert len(q) >= 15
        assert any(k in q for k in ("重要事項", "重説", "特約", "契約", "賃料"))
