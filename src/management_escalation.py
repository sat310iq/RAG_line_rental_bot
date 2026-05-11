"""Early escalation to management for legal / monetary judgment questions (no RAG)."""

from __future__ import annotations

import json
import logging
from typing import Final

from src.kb_fast_path import normalize_for_match

logger = logging.getLogger(__name__)

MANAGEMENT_ESCALATION_MESSAGE: Final[str] = (
    "ご質問の内容は、契約条件や個別の状況によって判断が異なる可能性があります。\n\n"
    "トラブルを避けるためにも、管理会社へ直接ご相談いただくことをおすすめします。"
)

LEGAL_JUDGMENT_KEYWORDS: Final[tuple[str, ...]] = (
    "法的",
    "違法",
    "訴え",
    "裁判",
    "勝てますか",
    "責任",
    "損害賠償",
    "慰謝料",
    "違反ですか",
    "違法ですか",
    "契約違反",
    "対応しない場合",
    "大家負担",
    "全部大家",
    "契約違反かどうか",
    "判断してもらえ",
    "権利",
    "義務",
    "無効",
    "合法",
)

MONEY_CLAIM_KEYWORDS: Final[tuple[str, ...]] = (
    # 汎用「請求できますか」は賠償・原状回復などRAG説明ケースと衝突するため使わない（家賃減額など具体語でカバー）
    "減額できますか",
    "減額請求",
    "返金させ",
    "返金できますか",
    "返金させられますか",
    "相殺できますか",
    "払わなくていい",
    "払わなくてもいい",
    "払わない方法",
    "拒否できますか",
    "家賃減額",
    "家賃減額を請求できますか",
    "賃料減額を請求できますか",
    "支払わない",
    "払わない",
)

JUDGMENT_PHRASES: Final[tuple[str, ...]] = (
    "できますか",
    "できるか",
    "勝てますか",
    "違反ですか",
    "違法ですか",
    "無効ですか",
    "合法ですか",
    "必要ですか",
    "されますか",
    "られますか",
    "でしょうか",
    "ありますか",
    "ですよね",
    "いいですか",
    "判断してもらえ",
)

CONTRACT_REFERENCE_KEYWORDS: Final[tuple[str, ...]] = (
    "契約書",
    "重要事項説明書",
    "重説",
    "特約",
    "第",
    "条",
    "条項",
    "別表",
)


def _mask_question_snippet(q: str, *, max_len: int = 20) -> str:
    if len(q) <= max_len:
        return q
    return q[:max_len] + "..."


def should_escalate_to_management(question: str) -> bool:
    """True if question asks for legal/money judgment and should not be answered by RAG."""
    q = normalize_for_match(question)

    legal_hit = any(k in q for k in LEGAL_JUDGMENT_KEYWORDS)
    money_hit = any(k in q for k in MONEY_CLAIM_KEYWORDS)
    judgment_hit = any(k in q for k in JUDGMENT_PHRASES)
    contract_ref_hit = any(k in q for k in CONTRACT_REFERENCE_KEYWORDS)

    escalate: bool
    reason: str

    if not q:
        escalate = False
        reason = "empty_question"
    elif contract_ref_hit and not judgment_hit:
        # 条項説明の導線（特約・第◯条・別表など）はRAG側で根拠提示を優先する。
        escalate = False
        reason = "contract_ref"
    elif (legal_hit or money_hit) and judgment_hit:
        escalate = True
        reason = "legal_assertion"
    elif not (legal_hit or money_hit):
        escalate = False
        reason = "no_legal_or_money_keyword"
    else:
        escalate = False
        reason = "no_judgment_phrase"

    logger.info(
        json.dumps(
            {
                "event": "escalation_check",
                "question_masked": _mask_question_snippet(q),
                "contract_ref_hit": contract_ref_hit,
                "legal_hit": legal_hit,
                "money_hit": money_hit,
                "judgment_hit": judgment_hit,
                "escalate": escalate,
                "reason": reason,
            },
            ensure_ascii=False,
        )
    )

    return escalate
