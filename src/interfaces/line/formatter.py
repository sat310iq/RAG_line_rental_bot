"""LINE output formatter."""

from typing import Optional

from src.rag_answerer import AnswerSchema


def build_line_message_from_plain_text(text: str, urgent: bool = False) -> str:
    """Format KB fast path or clarification replies without building AnswerSchema."""
    summary = (text or "").strip()
    if not summary:
        summary = "該当する情報が見つからないため管理会社にお問い合わせください。"
    if urgent:
        if summary.startswith("【緊急・注意】"):
            return summary
        return f"【緊急・注意】\n{summary}"
    return summary


_MGMT_FOOTER = "※詳細・不明点は管理会社にお問い合わせください。"


def build_line_message(answer: AnswerSchema, urgent: bool = False) -> str:
    """Format LINE reply message from AnswerSchema.

    - summaryを優先
    - summaryが空ならitemsを連結
    - urgent時は先頭に【緊急・注意】
    - RAG回答末尾に管理会社確認フッターを付与
    """
    summary_source = "answer_text_raw" if getattr(answer, "answer_text_raw", "") else "summary"
    summary = (getattr(answer, "answer_text_raw", "") or answer.summary or "").strip()
    if not summary and answer.items:
        summary = "\n".join([f"{i + 1}. {item.text}" for i, item in enumerate(answer.items)])
    summary = summary.strip() if summary else "該当する情報が見つからないため管理会社にお問い合わせください。"

    # Append management company confirmation footer (skip if already present)
    if _MGMT_FOOTER not in summary:
        summary += f"\n\n{_MGMT_FOOTER}"

    if urgent:
        if summary.startswith("【緊急・注意】"):
            return summary
        return f"【緊急・注意】\n{summary}"
    return summary
