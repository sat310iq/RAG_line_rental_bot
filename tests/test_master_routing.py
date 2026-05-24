"""Phase 0 boundary tests for should_search_master() and _has_explicit_doc_trigger().

Coverage:
  True:  MH-01, MH-04, MH-05, MH-06, KW-02, XD-01, XD-03, NC-02
  False: NC-01 (deal/KB), noise queries, general contract questions
"""

import pytest

from src.contract_query_router import (
    _has_explicit_doc_trigger,
    _normalize_question,
    is_contract_source_question,
    should_search_master,
)


# ── should_search_master: True cases ────────────────────────────────────────

@pytest.mark.parametrize(
    "q,note",
    [
        # Layer A — 既存 csq ロジック継承
        ("本文第17条の原状回復についての原則は何ですか。", "MH-01: 本文第X条"),
        ("原状回復の別表（床）の負担区分を教えてください", "MH-01/02: 別表"),
        ("重要事項説明書では、賃料・共益費・水道料はいくらと記載されていますか。", "KW-02: 重要事項説明書+記載"),
        ("水道代が基準を超えたらどうなる？", "XD-01: 水道代超過"),
        ("重説の３項目では家賃はいくら", "NC-02: 重説+節番号"),
        ("家具でフローリングがへこんだ、費用は誰負担ですか。", "MH-04: _RE_FLOORING_DAMAGE"),
        ("契約書の特約④の短期解約違約金は？", "特約+違約金"),
        ("短期解約違約金はいくらですか", "短期解約違約金単独"),
        ("違約金の金額を教えてください", "違約金+金額"),
        # Layer B — Phase 2 追加（XD-03 / MH-05 / MH-06）
        ("解約の通知は何日前？", "XD-03: 解約+通知"),
        ("解約通知の期限はいつですか", "XD-03: 解約通知"),
        ("解約予告は何日前に必要ですか", "解約予告"),
        ("クロスの費用負担はどう決まる？", "MH-05: クロス+費用"),
        ("クロス張り替えの負担は誰ですか", "MH-05: クロス+負担"),
        ("退去時の清掃費はいくら？", "MH-06: 清掃費"),
        ("退去時の清掃費用について教えてください", "MH-06: 清掃+退去+費用"),
        # Layer D — strong doc-ref meta + domain
        ("原状回復の費用負担はどう規定されていますか", "Layer D: 規定+費用"),
        ("フローリング修繕の負担区分はどう書かれていますか", "Layer D: 書かれ+フローリング"),
    ],
)
def test_should_search_master_true(q: str, note: str) -> None:
    assert should_search_master(q) is True, f"Expected True for [{note}]: {q!r}"


# ── should_search_master: False cases ────────────────────────────────────────

@pytest.mark.parametrize(
    "q,note",
    [
        # NC-01 deal/KB — FAQ で十分
        ("水道費用についての連絡先", "NC-01: 連絡先 → KB"),
        # 非賃貸ノイズ
        ("コンビニを調べて", "非賃貸: ドメイン語なし"),
        ("近くのコンビニを教えてください", "非賃貸: 教えて+コンビニ"),
        # 一般的な契約相談（契約書に何が書いてあるか、ではない）
        ("契約更新したいです", "一般相談: 更新"),
        ("契約書を送ってください", "契約書単独+送って"),
        ("解約したいです", "解約意思 → FAQ"),
        ("解約の手続きを教えてください", "解約手続き → FAQ"),
        ("修繕をお願いしたい", "修繕依頼 → FAQ"),
        ("水漏れしています", "トラブル報告 → FAQ"),
    ],
)
def test_should_search_master_false(q: str, note: str) -> None:
    assert should_search_master(q) is False, f"Expected False for [{note}]: {q!r}"


# ── is_contract_source_question delegates to should_search_master ────────────

def test_is_contract_source_question_delegates() -> None:
    """is_contract_source_question must return the same value as should_search_master."""
    cases = [
        "本文第17条の原状回復についての原則は何ですか。",
        "解約の通知は何日前？",
        "クロスの費用負担はどう決まる？",
        "退去時の清掃費はいくら？",
        "水道費用についての連絡先",
        "契約更新したいです",
    ]
    for q in cases:
        assert is_contract_source_question(q) == should_search_master(q), (
            f"Mismatch between is_contract_source_question and should_search_master for {q!r}"
        )


def test_is_contract_source_question_extra_regex() -> None:
    assert is_contract_source_question("カスタムキーワードXYZ", extra_regex=["カスタムキーワード"]) is True
    assert is_contract_source_question("カスタムキーワードXYZ") is False


# ── _has_explicit_doc_trigger ─────────────────────────────────────────────────

@pytest.mark.parametrize(
    "q,expected",
    [
        ("重要事項説明書の賃料は", True),
        ("重説の費用について", True),
        ("費用はどう書かれていますか", True),    # Pattern 3: 書かれ(strong) + 費用(domain)
        ("原状回復はどう規定されていますか", True),  # 規定(strong) + 原状回復(domain)
        ("コンビニを調べて", False),             # 調べて = 弱いmeta, コンビニ = 非domain
        ("契約更新したいです", False),            # strong meta なし
        ("教えてください", False),               # 教えて = 弱いmeta, domain なし
    ],
)
def test_has_explicit_doc_trigger(q: str, expected: bool) -> None:
    nq = _normalize_question(q)
    assert _has_explicit_doc_trigger(nq) is expected, f"_has_explicit_doc_trigger({q!r}) expected {expected}"
