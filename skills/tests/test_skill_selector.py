from __future__ import annotations

from skills.skill_selector import select


def test_single_match_contract_qa() -> None:
    results = select("契約書QAの参照元を修正したい")
    names = [r["name"] for r in results]
    assert "contract_qa_skill" in names


def test_multiple_match_sorted_by_trigger_count_desc() -> None:
    results = select("契約書の要件を設計したい")
    assert len(results) >= 2
    counts = [len(r["matched_triggers"]) for r in results]
    assert counts == sorted(counts, reverse=True)


def test_scope_filter_reusable_only() -> None:
    results = select("設計レビューをしたい", scope="reusable")
    assert all(r["scope"] == "reusable" for r in results)
    assert all(r["scope"] != "rental_rag_only" for r in results)


def test_no_match_returns_empty_list() -> None:
    assert select("全く関係ない入力xyz") == []
