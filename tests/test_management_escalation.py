"""Tests for management escalation guard (no API)."""

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
