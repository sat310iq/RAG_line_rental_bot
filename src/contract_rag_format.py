"""B2: Master PDF / contract RAG display formatting (non-judgmental, template)."""

from __future__ import annotations

from typing import Any, List, Set

from src.citation_metadata import extract_article_seq_from_legacy_article_number

# Section headings for LINE / CLI / eval (single place for i18n later)
B2_HEADING_SOURCE = "【該当箇所】"
B2_HEADING_SUMMARY = "【内容の要約】"
B2_HEADING_CAVEAT = "【注意点】"
B2_HEADING_NEXT = "【次の対応】"

B2_FIXED_CAVEAT = (
    "この内容は契約書等の記載に基づく一般的な説明です。\n"
    "適用条件や最終的な判断は、個別の状況によって異なる可能性があります。"
)

B2_FIXED_NEXT = (
    "正確な判断については、契約書の該当箇所をご確認いただくか、管理会社へお問い合わせください。"
)

DISPLAY_FORMAT_B2 = "b2_contract_rag"


def uses_master_pdf_docs(docs: List[Any]) -> bool:
    """Return True if docs contain at least one master PDF (contract) chunk."""
    if not docs:
        return False
    for d in docs:
        meta = getattr(d, "metadata", None) or {}
        if isinstance(meta, dict) and meta.get("type") == "pdf":
            return True
    return False


def build_source_reference_line(metadata: dict) -> str:
    """Single-line citation from one document's metadata (filename + 条/項/§/cite_label)."""
    if not isinstance(metadata, dict) or metadata.get("type") != "pdf":
        return ""

    name = (metadata.get("filename") or "").strip() or (metadata.get("source") or "").strip()
    if not name:
        name = "契約関係文書"

    page = metadata.get("page")
    page_s = f" p.{page}" if page is not None and str(page) != "" else ""

    doc_kind = metadata.get("doc_kind")
    cite_label = (metadata.get("cite_label") or "").strip()

    if doc_kind == "important_matters":
        section_id = str(metadata.get("section_id") or "").strip()
        section_label = (metadata.get("section_label") or "").strip()
        if section_id and section_label:
            ref = f"§{section_id} {section_label[:80]}"
        elif cite_label:
            ref = cite_label
        else:
            ref = "重要事項説明書"
        return f"{name} {ref}{page_s}".strip()

    article_seq = metadata.get("article_seq")
    if article_seq is None and metadata.get("article_number"):
        article_seq = extract_article_seq_from_legacy_article_number(
            metadata.get("article_number")
        )

    paragraph_seq = metadata.get("paragraph_seq")
    paragraph_conf = metadata.get("paragraph_seq_confidence") or "unknown"

    if article_seq is not None:
        if (
            paragraph_seq is not None
            and str(paragraph_seq) != ""
            and paragraph_conf in ("high", "inferred")
        ):
            ref = f"第{int(article_seq)}条第{int(paragraph_seq)}項"
        else:
            ref = f"第{int(article_seq)}条"
        return f"{name} {ref}{page_s}".strip()

    if cite_label:
        return f"{name} {cite_label}{page_s}".strip()

    return f"{name} 該当箇所{page_s}".strip()


def build_source_reference(docs: List[Any]) -> str:
    """Build source lines from retrieved master chunks (deduped)."""
    if not docs:
        return "（根拠文書のメタデータが取得できませんでした）"

    parts: List[str] = []
    seen_lines: Set[str] = set()

    for d in docs:
        meta = getattr(d, "metadata", None) or {}
        if not isinstance(meta, dict) or meta.get("type") != "pdf":
            continue
        line = build_source_reference_line(meta)
        if line and line not in seen_lines:
            seen_lines.add(line)
            parts.append(line)

    if not parts:
        return "（該当箇所の特定に必要な情報が不足しています）"
    return "\n".join(parts)


def _summary_text_from_answer(answer: Any) -> str:
    s = (getattr(answer, "summary", None) or "").strip()
    if s:
        return s
    items = getattr(answer, "items", None) or []
    if items:
        lines = []
        for i, it in enumerate(items, 1):
            t = getattr(it, "text", None) or ""
            if t.strip():
                lines.append(f"{i}. {t.strip()}")
        if lines:
            return "\n".join(lines)
    return "根拠情報に基づき内容を要約できませんでした。管理会社へお問い合わせください。"


def format_b2_contract_rag_display(answer: Any) -> str:
    """Render B2 four-block user-facing text (must match design doc)."""
    ref = (getattr(answer, "source_reference", None) or "").strip() or "（参照不明）"
    body = _summary_text_from_answer(answer)
    return (
        f"{B2_HEADING_SOURCE}\n{ref}\n\n"
        f"{B2_HEADING_SUMMARY}\n{body}\n\n"
        f"{B2_HEADING_CAVEAT}\n{B2_FIXED_CAVEAT}\n\n"
        f"{B2_HEADING_NEXT}\n{B2_FIXED_NEXT}"
    )
