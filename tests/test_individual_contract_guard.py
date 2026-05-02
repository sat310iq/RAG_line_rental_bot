"""individual_contract_guard heuristics and handoff short-circuit."""

from src.individual_contract_guard import (
    INDIVIDUAL_CONTRACT_HANDOFF_MESSAGE,
    should_handoff_individual_contract_terms,
)


def test_handoff_self_rent() -> None:
    assert should_handoff_individual_contract_terms("私の家賃はいくらですか")


def test_no_handoff_contract_source_article() -> None:
    assert not should_handoff_individual_contract_terms(
        "本文第4条では、賃料の支払いと日割りについてどう書かれていますか。"
    )


def test_no_handoff_head_tosho() -> None:
    assert not should_handoff_individual_contract_terms(
        "契約書の頭書（3）に賃料はいくらと記載されていますか。"
    )


def test_handoff_ikura_chinryo_without_doc_anchor() -> None:
    assert should_handoff_individual_contract_terms("家賃はいくらですか")


def test_no_handoff_ikura_chinryo_with_kiyaku() -> None:
    assert not should_handoff_individual_contract_terms(
        "契約書に家賃はいくらと記載されていますか"
    )


def test_handoff_message_has_no_forbidden_substrings() -> None:
    body = INDIVIDUAL_CONTRACT_HANDOFF_MESSAGE
    assert "管理会社へお問い合わせください" not in body
    assert "管理会社にお問い合わせください" not in body


def test_flood_hazard_not_handoff_without_rent_keywords() -> None:
    assert not should_handoff_individual_contract_terms("この物件は洪水区域ですか")


def test_handoff_party_name_pii() -> None:
    assert should_handoff_individual_contract_terms("貸主の氏名を教えてください")


def test_no_handoff_party_when_contract_wording() -> None:
    assert not should_handoff_individual_contract_terms(
        "契約書の頭書では貸主はどのように記載されていますか"
    )


def test_no_handoff_mokutekibutsu_document_lookup() -> None:
    assert not should_handoff_individual_contract_terms(
        "目的物の所在地は頭書にどのように記載されていますか"
    )

