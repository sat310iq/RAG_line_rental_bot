"""Tests for management escalation guard (no API)."""

import json
import logging

import pytest

from src.management_escalation import should_escalate_to_management


def _collect_escalation_logs(records):
    return [
        json.loads(r.message)
        for r in records
        if r.name == "src.management_escalation" and r.message.startswith("{")
    ]


def test_should_escalate_legal_or_monetary_judgment():
    assert should_escalate_to_management("家賃減額を請求できますか？")
    assert should_escalate_to_management("訴えたら勝てますか？")
    assert should_escalate_to_management("法的に違反ですか？")


def test_should_not_escalate_normal_faq():
    assert not should_escalate_to_management("水道代はいくらですか？")
    assert not should_escalate_to_management("タバコは吸えますか？")
    assert not should_escalate_to_management("ゴミ出しのルールは？")


def test_should_not_escalate_eval_b_borderlines():
    """B群（RAG期待）が誤ってエスカレーションしないこと。"""
    assert not should_escalate_to_management("水漏れで家具が壊れた場合、大家に賠償請求できますか？")
    assert not should_escalate_to_management("騒音がひどい場合、引っ越し費用を請求できますか？")
    assert not should_escalate_to_management("更新料は支払わないといけませんか？")


def test_should_escalate_eval_d_expanded():
    assert should_escalate_to_management("家賃を払わなくてもいいケースってありますか？")
    assert should_escalate_to_management("大家が対応しない場合どうすればいいですか？")
    assert should_escalate_to_management("水漏れって大家負担ですよね？")
    assert should_escalate_to_management("契約違反かどうか判断してもらえますか？")
    assert should_escalate_to_management("原状回復費用を払わない方法はありますか？")


@pytest.mark.parametrize(
    "question",
    [
        "第12条に規定があります",
        "特約⑥に記載があります",
        "別表Iをご確認ください",
        "第17条の原状回復規定について",
        "重説の§1に抵当権補足があります",
        "契約書の特約①をご確認ください",
        "別表IIの部位別負担に記載があります",
        "重要事項説明書の§12をご参照ください",
    ],
)
def test_contract_reference_does_not_escalate(question: str):
    """条項参照・根拠提示はescalationしない（B-6合格条件）"""
    assert should_escalate_to_management(question) is False


@pytest.mark.parametrize(
    "question",
    [
        "敷金を返してもらう権利はありますか",
        "大家が修繕しないのは違法ですか",
        "賃料減額を請求できますか",
        "退去する義務がありますか",
        "この特約は無効ですか",
        "契約解除は合法ですか",
    ],
)
def test_legal_assertion_escalates(question: str):
    """法的断定要求はescalationする（B-6ブロック条件）"""
    assert should_escalate_to_management(question) is True


def test_b20_contract_ref_logged(caplog):
    """B-20: 特約参照はescalate=False・reason=contract_refがログに出る"""
    with caplog.at_level(logging.INFO, logger="src.management_escalation"):
        result = should_escalate_to_management("特約⑥は無効じゃないですか？")

    assert result is False

    log_entries = _collect_escalation_logs(caplog.records)
    assert len(log_entries) >= 1
    entry = log_entries[-1]
    assert entry["event"] == "escalation_check"
    assert entry["contract_ref_hit"] is True
    assert entry["escalate"] is False
    assert entry["reason"] == "contract_ref"


def test_b22_legal_assertion_logged(caplog):
    """B-22: 法的断定要求はescalate=True・reason=legal_assertionがログに出る"""
    with caplog.at_level(logging.INFO, logger="src.management_escalation"):
        result = should_escalate_to_management("大家が修繕してくれない、法的に請求できますか？")

    assert result is True

    log_entries = _collect_escalation_logs(caplog.records)
    assert len(log_entries) >= 1
    entry = log_entries[-1]
    assert entry["event"] == "escalation_check"
    assert entry["legal_hit"] is True
    assert entry["escalate"] is True
    assert entry["reason"] == "legal_assertion"


@pytest.mark.parametrize(
    "question,expected_reason",
    [
        ("この特約は消費者契約法に違反しませんか？", "contract_ref"),
        ("賃料減額を請求する権利はありますか？", "legal_assertion"),
        ("抵当権実行で出て行く義務はありますか？", "legal_assertion"),
    ],
)
def test_b6_remaining_log_entries(question, expected_reason, caplog):
    """B-21/B-23/B-24のログ出力確認"""
    with caplog.at_level(logging.INFO, logger="src.management_escalation"):
        should_escalate_to_management(question)

    log_entries = _collect_escalation_logs(caplog.records)
    assert len(log_entries) >= 1
    entry = log_entries[-1]
    assert entry["reason"] == expected_reason
