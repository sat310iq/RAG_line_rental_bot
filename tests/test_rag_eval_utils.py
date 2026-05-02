"""Tests for rag_eval_utils keyword evaluation."""

from __future__ import annotations

from src.rag_answerer import AnswerItem, AnswerSchema
from src.rag_eval_utils import required_keyword_pass, keyword_eval_flags


def test_required_keyword_pass_any_of_one_group_matches() -> None:
    case = {
        "required_keywords": {
            "any_of": [
                ["6ヶ月以内", "3ヶ月分"],
                ["foo", "bar"],
            ]
        }
    }
    body = "特約④では6ヶ月以内は賃料3ヶ月分の違約金と記載されています。"
    assert required_keyword_pass(case, body) is True


def test_required_keyword_pass_any_of_no_match() -> None:
    case = {
        "required_keywords": {
            "any_of": [
                ["6ヶ月以内", "3ヶ月分"],
            ]
        }
    }
    assert required_keyword_pass(case, "退去連絡は書面でお願いします。") is False


def test_required_keyword_pass_legacy_and() -> None:
    case = {"expected_snippets": ["alpha", "beta"]}
    assert required_keyword_pass(case, "alpha beta gamma") is True
    assert required_keyword_pass(case, "alpha only") is False


def test_keyword_eval_flags_any_of() -> None:
    ans = AnswerSchema(
        items=[AnswerItem(text="6ヶ月以内は3ヶ月分です。", citation="x")],
        summary="要約",
        evidence=[],
        next_action="",
        caveats="",
    )
    case = {
        "required_keywords": {
            "any_of": [["6ヶ月以内", "3ヶ月分"]],
        }
    }
    flags = keyword_eval_flags(ans, case, eval_defaults={})
    assert flags["required_ok"] is True
