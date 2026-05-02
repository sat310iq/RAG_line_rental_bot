"""契約書特約①〜⑫の全項目に対応する質問フィクスチャの整合テスト。

RAG のルーティング結果は別途（統合テスト・手動スモーク）で確認する。
ここでは「質問が参照する条項が契約テキストに存在する」ことをオフラインで保証する。
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "granmare_ob_airport_contract_clause_cases.yaml"
_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _load_cases():
    data = yaml.safe_load(_FIXTURE.read_text(encoding="utf-8"))
    rel = data["contract_document"]
    contract_path = _PROJECT_ROOT / rel
    cases = data["cases"]
    return contract_path, cases


_CONTRACT_PATH, _CASES = _load_cases()


def test_fixture_lists_all_twelve_clauses():
    assert len(_CASES) == 12
    seqs = {c["sequence"] for c in _CASES}
    assert seqs == set(range(1, 13))


@pytest.mark.parametrize("case", _CASES, ids=[c["id"] for c in _CASES])
def test_each_question_expected_snippets_exist_in_contract(case):
    contract_path = _CONTRACT_PATH
    assert contract_path.is_file(), f"Missing contract file: {contract_path}"
    text = contract_path.read_text(encoding="utf-8")
    missing = [s for s in case["expected_snippets"] if s not in text]
    assert not missing, f"{case['id']}: snippets not in contract: {missing}"


def test_questions_are_non_empty_contract_style():
    for c in _CASES:
        q = (c.get("question") or "").strip()
        assert len(q) >= 20
        assert "契約" in q or "条項" in q or "特約" in q
