"""Detect questions that ask for tenant-specific contract terms (not template/clause wording)."""

from __future__ import annotations

from typing import Final

from src.contract_query_router import is_contract_source_question
from src.kb_fast_path import normalize_for_match

# Body text avoids eval forbidden substrings (summary/items): no 「管理会社へ/に…お問い合わせ」
INDIVIDUAL_CONTRACT_HANDOFF_MESSAGE: Final[str] = (
    "貸主・借主・入居者・連帯保証人等に関する個人情報、ならびに契約期間・賃料・敷金・礼金等、"
    "お客様個別に確定する内容については、個人情報保護の観点から本サービスではお答えできません。\n\n"
    "正確な内容は、入居手続・管理の所定窓口へ、ご契約に紐づく内容として個別にお問い合わせください。"
)

_OP_EXCEPTION_TERMS: Final[tuple[str, ...]] = (
    "ゴミ",
    "ゴミ出し",
    "鍵",
    "水漏れ",
    "故障",
    "修理",
    "連絡先",
    "電話",
    "停電",
)

_SELF_TERMS: Final[tuple[str, ...]] = (
    "私の",
    "自分の",
    "うちの",
    "我が家",
    "当方",
    "入居者として",
    "私は",
    "当該",
    "この部屋",
    "こちらの部屋",
    "今の部屋",
)

_TERM_TERMS: Final[tuple[str, ...]] = (
    "家賃",
    "賃料",
    "共益費",
    "管理費",
    "水道料",
    "水道代",
    "敷金",
    "礼金",
    "保証金",
    "更新料",
    "更新費",
    "契約期間",
    "いつから",
    "いつまで",
    "明け渡",
    "退去",
    "解約",
    "違約金",
)

_DOC_ANCHOR_TERMS: Final[tuple[str, ...]] = (
    "契約書",
    "記載",
    "書いて",
    "書かれ",
    "条",
    "頭書",
    "別表",
    "特約",
    "目的物",
    "専有部分",
    "重説",
    "重要事項",
    "説明書",
    "ハザード",
    "洪水",
    "高潮",
    "浸水",
    "水防法",
    "土砂",
    "津波",
)

# 当事者の個人情報を直接求める問い（マスター条文・記載箇所の説明ではない）
_PII_PARTY_TERMS: Final[tuple[str, ...]] = (
    "貸主",
    "借主",
    "賃借人",
    "連帯保証人",
    "保証人",
)
_PII_ATTR_TERMS: Final[tuple[str, ...]] = (
    "氏名",
    "住所",
    "誰が",
    "誰です",
    "どなた",
    "電話",
    "メール",
    "連絡先",
)


def should_handoff_individual_contract_terms(question: str) -> bool:
    """True when the user seeks individual deal terms without citing contract/clause wording.

    When True, ``is_contract_source_question`` is always False (caller should not duplicate-check).
    """
    if is_contract_source_question(question):
        return False
    q = normalize_for_match(question)
    if not q or len(q.strip()) < 2:
        return False

    # Operational / facility topics: do not steal FAQ-style queries
    if any(x in q for x in _OP_EXCEPTION_TERMS) and not any(
        x in q for x in ("家賃", "賃料", "敷金", "礼金", "契約期間", "更新")
    ):
        return False

    has_doc_anchor = any(a in q for a in _DOC_ANCHOR_TERMS)

    if any(s in q for s in _SELF_TERMS) and any(t in q for t in _TERM_TERMS):
        return True

    if any(p in q for p in _PII_PARTY_TERMS) and any(a in q for a in _PII_ATTR_TERMS):
        return True
    if ("入居者" in q or "同居人" in q) and any(a in q for a in _PII_ATTR_TERMS):
        return True

    if ("いくら" in q or "幾ら" in q) and any(
        t in q for t in ("家賃", "賃料", "敷金", "礼金", "更新料", "保証金", "共益費", "管理費")
    ):
        if has_doc_anchor:
            return False
        return True

    if "契約期間" in q and not has_doc_anchor:
        if any(x in q for x in ("いつ", "から", "まで", "何年", "何ヶ月", "何カ月")):
            return True

    return False
