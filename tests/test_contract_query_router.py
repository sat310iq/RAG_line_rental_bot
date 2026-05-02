"""Unit tests for contract-source question detection."""

import pytest

from src.contract_query_router import (
    extract_contract_article_index,
    extract_important_matters_section_id,
    is_contract_source_question,
    is_important_matters_question,
    prefers_contract_master_chunks,
)


@pytest.mark.parametrize(
    "q,expected",
    [
        ("契約更新したいです", False),
        ("契約解除の手続きを教えてください", False),
        ("契約書を送ってください", False),
        ("本文第4条では賃料はどう書かれていますか", True),
        ("契約書の特約④の短期解約違約金は？", True),
        ("頭書（2）の契約期間はいつからいつまでですか", True),
        ("原状回復の別表（床）の負担区分を教えてください", True),
        ("別表にエアコンはどう書いてありますか", True),
        ("契約書本文の禁止事項は何ですか", True),
        ("契約書の頭書（3）では家賃はいくらと記載されていますか", True),
        ("退去時クリーニング費用の表では1Rの金額はどのように記載されていますか", True),
        ("例外特約のタバコ・ペットの表では何と定められていますか", True),
        ("設備の経過年数と負担割合の記載では耐用年数について何と書いてありますか", True),
        ("重要事項説明書の3番では家賃や共益費はいくらと記載されていますか", True),
        ("重要事項説明書に抵当権の補足説明はどう書いてありますか", True),
        ("宅建の重要事項で更新料は何ヶ月分と記載されていますか", True),
        ("重説の16番の利用制限はどう書いてありますか", True),
        ("賃貸借の目的物の所在地は頭書にどのように記載されていますか", True),
        ("目的物の範囲は契約書の別表にどう書いてありますか", True),
        ("この契約の使用目的は何ですか", True),
        ("契約上の用途を教えてください", True),
        ("契約の更新だけしたいです", False),
    ],
)
def test_is_contract_source_question(q: str, expected: bool) -> None:
    assert is_contract_source_question(q) is expected


def test_extract_contract_article_index() -> None:
    assert extract_contract_article_index("本文第17条の原則は") == 17
    assert extract_contract_article_index("第4条のとおり") == 4


def test_extract_important_matters_section_id() -> None:
    assert extract_important_matters_section_id("重要事項の12では洪水は") == "12"


def test_is_important_matters_question_flood() -> None:
    assert is_important_matters_question("この物件は洪水区域ですか")


def test_prefers_contract_when_honbun_article() -> None:
    assert prefers_contract_master_chunks("本文第17条について")


def test_prefers_not_contract_when_only_hazard() -> None:
    assert not prefers_contract_master_chunks("ハザードマップではどうなっていますか")
