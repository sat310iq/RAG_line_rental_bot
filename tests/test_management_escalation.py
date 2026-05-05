"""Tests for management escalation guard (no API)."""

import pytest

from src.management_escalation import should_escalate_to_management


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
