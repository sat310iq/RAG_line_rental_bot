"""重要事項説明書（重説）まわりのルーティング検知テスト。

`docs/testing/LINE_TEST_CHECKLIST.md` の B カテゴリ（重説ベース）や
`granmare_important_matters_cases.yaml` の質問表現と整合するよう、
`is_important_matters_question` / `extract_important_matters_section_id` /
`is_contract_source_question` の境界を固定する。
"""

from __future__ import annotations

import pytest

from src.contract_query_router import (
    extract_contract_article_index,
    extract_important_matters_section_id,
    is_contract_source_question,
    is_important_matters_question,
    prefers_contract_master_chunks,
)


@pytest.mark.parametrize(
    "question,expected",
    [
        # 文書名・重説
        ("重要事項説明書の3番では家賃や共益費はいくらと記載されていますか", True),
        ("重要事項説明書に抵当権の補足説明はどう書いてありますか", True),
        ("重説の16番の利用制限はどう書いてありますか", True),
        ("重説の特約②では振込手数料は誰負担ですか", True),
        # 宅建表現（重要事項）
        ("宅建の重要事項で更新料は何ヶ月分と記載されていますか", True),
        # ハザード系（IMPORTANT_MATTERS_HINTS）
        ("この物件は洪水区域ですか", True),
        ("ハザードマップで何か注意点は？", True),
        ("重要事項説明書では洪水浸水想定区域と高潮浸水想定区域はどう記載されていますか", True),
        # LINE checklist B-18 / B-19 に近い表現（重説接頭で contract source も True になるもの）
        ("重説の抵当権が実行されたらどうなる？", True),
        ("重要事項説明書の抵当権が実行されたらどうなる？", True),
        # 否定例（一般相談・重説語なし）
        ("契約更新したいです", False),
        ("月々の支払いは合計いくら？", False),
        ("抵当権が実行されたらどうなる？", False),
        ("友人を住まわせてもいいですか？", False),
    ],
)
def test_is_important_matters_question(question: str, expected: bool) -> None:
    assert is_important_matters_question(question) is expected


@pytest.mark.parametrize(
    "question,expected_section",
    [
        ("重要事項の12では洪水は", "12"),
        ("重要事項説明書の3番では家賃や共益費はいくらと記載されていますか", "3"),
        # 「重説の16番」は _RE_SECTION_NUM_BARE の境界文字に「の」を含めたため "16" を返す。
        ("重説の16番の利用制限はどう書いてありますか", "16"),
        ("重説 16番の利用制限はどう書いてありますか", "16"),
        ("宅建の重要事項で更新料は何ヶ月分と記載されていますか", "2"),  # 更新料 → §2（契約期間及び更新）
        # PR-1a: 「重説のN項目」「重要事項のN項目」形式（全角数字・項目サフィックス対応）
        ("重説の３項目・家賃について教えて", "3"),
        ("重要事項説明書の３項目では家賃はいくらですか", "3"),
        ("重要事項の1項目目は？", "1"),
        # Sprint 3 #2: 洪水/ハザード keyword → §12, 津波/土砂 → §11
        ("ハザードマップで何か注意点は？", "12"),
        ("この物件は洪水のリスクはありますか？", "12"),
        ("高潮浸水エリアに入りますか", "12"),
        ("津波の危険はありますか", "11"),
        ("土砂災害警戒区域ですか", "11"),
        # Sprint 3 #3: 水道料/月額費用 keyword → §3（賃料及び賃料以外に授受される金額）
        ("重要事項説明書では、賃料・共益費・水道料はいくらと記載されていますか。", "3"),
        ("月額費用の内訳を教えてください", "3"),
        # 「重要事項」文脈なし・ハザード系キーワードなし → None
        ("月々の支払いは合計いくら？", None),
        ("重説について詳しく教えてください", None),
    ],
)
def test_extract_important_matters_section_id(question: str, expected_section: str | None) -> None:
    assert extract_important_matters_section_id(question) == expected_section


@pytest.mark.parametrize(
    "question,expected_contract_source",
    [
        # 重説・重要事項説明書の「記載を問う」系はマスター参照
        ("重要事項説明書の3番では家賃や共益費はいくらと記載されていますか", True),
        ("重説の16番の利用制限はどう書いてありますか", True),
        ("重要事項説明書では洪水浸水想定区域と高潮浸水想定区域はどう記載されていますか", True),
        ("重説の抵当権が実行されたらどうなる？", True),
        # 重説語なしでは契約ソースに入らない（B-19 単体文言の切り分け用）
        ("抵当権が実行されたらどうなる？", False),
        # 一般相談
        ("契約更新したいです", False),
        # 「重」抜けタイポ（要事項説明書）もマスター参照として扱う
        ("要事項説明書の3番では家賃はいくらですか", True),
    ],
)
def test_is_contract_source_question_for_juyo(question: str, expected_contract_source: bool) -> None:
    assert is_contract_source_question(question) is expected_contract_source


@pytest.mark.parametrize(
    "question,expected",
    [
        # MH-04 系: 床材損傷 → 原状回復（第17条）への seed routing
        ("家具でフローリングがへこんだ、費用は誰負担ですか。", True),
        ("フローリングに傷がついた場合の費用は？", True),
        ("フローリングが剥がれてきた", True),
        ("畳がへこんでしまった、どうすればいい？", True),
        # 否定例: 一般的な質問・KB 対象
        ("クロスの費用負担はどう決まる？", False),   # KB fast path 対象（KB 優先）
        ("水道代はいくら？", False),
        ("月々の支払いは合計いくら？", False),
    ],
)
def test_is_contract_source_question_flooring_damage(question: str, expected: bool) -> None:
    """MH-04 系: フローリング損傷パターンが contract_source_q=True を返すこと。"""
    assert is_contract_source_question(question) is expected


def test_prefers_contract_when_honbun_article_not_important_matters_only() -> None:
    assert prefers_contract_master_chunks("本文第11条の修繕は誰の負担ですか") is True


def test_extract_contract_article_index_flooring() -> None:
    """フローリング keyword → article 17 (原状回復)."""
    assert extract_contract_article_index("家具でフローリングがへこんだ、費用は誰負担ですか。") == 17
    assert extract_contract_article_index("原状回復の費用について") == 17


def test_prefers_contract_false_for_hazard_only_without_article() -> None:
    """ハザードのみで条文・頭書・特約を指さない場合は契約チャンク優先しない。"""
    assert prefers_contract_master_chunks("ハザードマップで何か注意点は？") is False
