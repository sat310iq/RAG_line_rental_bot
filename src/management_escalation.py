"""Early escalation to management for legal / monetary judgment questions (no RAG)."""

from __future__ import annotations

from typing import Final

from src.kb_fast_path import normalize_for_match

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
    "必要ですか",
    "されますか",
    "られますか",
    "でしょうか",
    "ありますか",
    "ですよね",
    "いいですか",
    "判断してもらえ",
)


def should_escalate_to_management(question: str) -> bool:
    """True if question asks for legal/money judgment and should not be answered by RAG."""
    q = normalize_for_match(question)
    if not q:
        return False

    legal_hit = any(k in q for k in LEGAL_JUDGMENT_KEYWORDS)
    money_hit = any(k in q for k in MONEY_CLAIM_KEYWORDS)
    judgment_hit = any(k in q for k in JUDGMENT_PHRASES)

    return (legal_hit or money_hit) and judgment_hit
