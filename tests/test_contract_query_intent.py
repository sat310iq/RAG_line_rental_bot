from src.contract_query_intent import (
    detect_article_reference,
    detect_contract_source_intent,
    detect_usage_purpose_intent,
)


def test_detect_article_reference() -> None:
    assert detect_article_reference("本文第17条について") == 17
    assert detect_article_reference("第4条の記載") == 4
    assert detect_article_reference("条番号なし") is None


def test_detect_usage_purpose_intent() -> None:
    assert detect_usage_purpose_intent("この契約の使用目的は何ですか？")
    assert detect_usage_purpose_intent("賃貸借の用途を教えてください")
    assert not detect_usage_purpose_intent("用途地域の説明をしてください")


def test_detect_contract_source_intent() -> None:
    assert detect_contract_source_intent("本文第10条の禁止事項は？")
    assert detect_contract_source_intent("この契約の使用目的は何ですか？")
    assert not detect_contract_source_intent("契約更新したいです")
