"""Deterministic ordering for master TXT chunks: article/section match, then doc_kind."""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, List, Tuple

from langchain_core.documents import Document

# T3: 番号付き特約（特約①〜⑫ または 特約1〜12）が明示されている場合は既存ロジック優先
_RE_TOKUYAKU_NUMBERED = re.compile(r"特約\s*[①②③④⑤⑥⑦⑧⑨⑩⑪⑫0-9０-９]+")
# T2: 違約金+金額系キーワード
_RE_PENALTY_AMOUNT = re.compile(r"いくら|幾ら|金額|何ヶ月|何カ月")

from src.contract_query_router import (
    extract_contract_article_index,
    extract_important_matters_section_id,
    is_important_matters_question,
    prefers_contract_master_chunks,
)
from src.contract_query_intent import detect_usage_purpose_intent


def _meta_signature(d: Document) -> Tuple[Any, ...]:
    m = d.metadata or {}
    return (
        m.get("filename"),
        m.get("article_number"),
        m.get("section_id"),
        hash((d.page_content or "")[:400]),
    )


def _is_tokuyaku_penalty_question(question: str) -> bool:
    """T2+T3: 違約金+金額 or 短期解約 かつ 番号付き特約が明示されていない場合に True。"""
    q = unicodedata.normalize("NFKC", question or "")
    if _RE_TOKUYAKU_NUMBERED.search(q):  # T3: 番号付き特約は既存ロジック優先
        return False
    if "短期解約" in q:  # T2
        return True
    if "違約金" in q and _RE_PENALTY_AMOUNT.search(q):  # T2
        return True
    return False


def _is_tokuyaku_penalty_chunk(doc: Document) -> bool:
    """特約④（短期解約違約金）を含む chunk かを content + metadata で判定。"""
    m = doc.metadata or {}
    haystack = "\n".join([
        doc.page_content or "",
        str(m.get("article_number") or ""),
        str(m.get("section_label") or ""),
        str(m.get("cite_label") or ""),
    ])
    return "短期解約違約金" in haystack or "特約④" in haystack


def _is_usage_purpose_article3_candidate(doc: Document) -> bool:
    m = doc.metadata or {}
    seq = m.get("article_seq")
    article3_by_seq = isinstance(seq, int) and seq == 3
    article3_by_label = "第3条" in str(m.get("article_number") or "")
    if not (article3_by_seq or article3_by_label):
        return False
    haystack = "\n".join(
        [
            str(m.get("article_number") or ""),
            str(m.get("section_label") or ""),
            str(m.get("cite_label") or ""),
            str(doc.page_content or ""),
        ]
    )
    return any(term in haystack for term in ("使用目的", "居住目的", "居住のみを目的", "用途"))


def apply_master_document_boost(
    question: str,
    master_docs: List[Document],
    *,
    contract_source_q: bool,
) -> Tuple[List[Document], List[Dict[str, Any]]]:
    """Reorder master chunks only (no kb_faq). Boost does not relax answer eligibility."""
    trace: List[Dict[str, Any]] = []
    if not contract_source_q or not master_docs:
        return master_docs, trace

    pool = list(master_docs)
    picked: List[Document] = []
    picked_sig = set()

    def append_if_new(doc: Document, boost_reason: str) -> None:
        sig = _meta_signature(doc)
        if sig in picked_sig:
            return
        picked.append(doc)
        picked_sig.add(sig)
        m = doc.metadata or {}
        trace.append(
            {
                "boost_reason": boost_reason,
                "filename": m.get("filename"),
                "doc_kind": m.get("doc_kind"),
                "article_number": m.get("article_number"),
                "article_seq": m.get("article_seq"),
                "section_id": m.get("section_id"),
                "section_label": (m.get("section_label") or "")[:120],
            }
        )

    n_art = extract_contract_article_index(question)
    usage_purpose_q = detect_usage_purpose_intent(question)
    if n_art is None and usage_purpose_q:
        # TODO: Replace this with heading-index retrieval (not fixed article assumptions).
        if any(_is_usage_purpose_article3_candidate(d) for d in pool):
            n_art = 3
            trace.append({"boost_reason": "usage_purpose_inferred_article:3"})
        else:
            trace.append({"boost_reason": "usage_purpose_inference_skipped:no_article3_usage_evidence"})
    if n_art is not None:
        for d in pool:
            m = d.metadata or {}
            seq = m.get("article_seq")
            if seq is not None and int(seq) == int(n_art):
                append_if_new(d, f"article_seq_exact:{n_art}")
                continue
            an = str(m.get("article_number") or "")
            if f"第{n_art}条" in an:
                append_if_new(d, f"article_exact:{n_art}")

    sid = extract_important_matters_section_id(question)
    if sid and is_important_matters_question(question):
        for d in pool:
            if str((d.metadata or {}).get("section_id") or "") == sid:
                append_if_new(d, f"section_exact:{sid}")

    if _is_tokuyaku_penalty_question(question):
        promoted = 0
        for d in pool:
            if promoted >= 2:
                break
            if _is_tokuyaku_penalty_chunk(d):
                append_if_new(d, "tokuyaku_penalty_clause")
                promoted += 1

    rest = [d for d in pool if _meta_signature(d) not in picked_sig]
    if prefers_contract_master_chunks(question):
        rest.sort(
            key=lambda d: (0 if (d.metadata or {}).get("doc_kind") == "contract" else 1)
        )
    elif is_important_matters_question(question):
        rest.sort(
            key=lambda d: (
                0 if (d.metadata or {}).get("doc_kind") == "important_matters" else 1
            )
        )

    final = picked + rest
    return final, trace
