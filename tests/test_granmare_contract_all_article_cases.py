"""契約書全文（頭書・別表・特約①〜⑫・本文第1〜26条）に対応する質問フィクスチャの整合テスト。

各ケースは「質問が参照する記載が契約テキストに存在する」ことを expected_snippets で保証する。
RAG の実回答ルーティングは別途検証する。
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "granmare_contract_all_article_cases.yaml"
_PROJECT_ROOT = Path(__file__).resolve().parent.parent

_EXPECTED_TOTAL = 47


def _load():
    data = yaml.safe_load(_FIXTURE.read_text(encoding="utf-8"))
    path = _PROJECT_ROOT / data["contract_document"]
    return path, data["cases"], data.get("eval_defaults") or {}


_CONTRACT_PATH, _CASES, _EVAL_DEFAULTS = _load()


def test_fixture_has_expected_case_count():
    assert len(_CASES) == _EXPECTED_TOTAL


def test_fixture_has_eval_defaults():
    assert "forbidden_keywords" in _EVAL_DEFAULTS
    assert isinstance(_EVAL_DEFAULTS["forbidden_keywords"], list)
    assert _EVAL_DEFAULTS["forbidden_keywords"]


@pytest.mark.parametrize("case", _CASES, ids=[c["id"] for c in _CASES])
def test_question_snippets_exist_in_contract(case):
    assert _CONTRACT_PATH.is_file(), f"Missing: {_CONTRACT_PATH}"
    text = _CONTRACT_PATH.read_text(encoding="utf-8")
    missing = [s for s in case["expected_snippets"] if s not in text]
    assert not missing, f"{case['id']}: not in contract: {missing}"


def test_each_case_has_question_and_metadata():
    groups = {"頭書", "原状回復別表", "例外特約", "退去時クリーニング", "設備経過年数", "特約", "本文"}
    for c in _CASES:
        assert c.get("group") in groups
        assert c.get("label")
        q = (c.get("question") or "").strip()
        assert len(q) >= 15
        assert any(
            k in q
            for k in ("契約", "特約", "頭書", "本文", "原状", "例外", "退去", "設備", "重要事項")
        )
