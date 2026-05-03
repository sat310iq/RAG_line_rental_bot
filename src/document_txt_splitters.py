"""Split master TXT into chunks: contract articles vs important-matters numbered sections."""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Callable, Dict, List, Tuple

from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document

from src.citation_metadata import (
    chunk_paragraph_assignment,
    paragraph_boundaries_in_article_body,
)
from src.config import Config
from src.topic_classifier import classify_topic

# Important matters use "## 12. タイトル" (Arabic numerals + dot), not "## 第N条".
SECTION_HEADING_RE = re.compile(
    r"(?m)^(##\s*)([0-9０-９]+)([\.．]\s*)([^\n]*)$",
)


def _section_id_normalize(sec_raw: str) -> str:
    s = unicodedata.normalize("NFKC", sec_raw or "")
    return "".join(c for c in s if c.isdigit())


def split_contract_txt_to_documents(
    *,
    sanitized_text: str,
    txt_path,
    doc_kind: str,
    text_splitter: RecursiveCharacterTextSplitter,
    split_by_article_fn: Callable[..., List[Tuple[str, str, Dict[str, Any]]]],
) -> List[Document]:
    """Contract-style TXT: ## 第N条 headings (delegates to split_by_article_fn)."""
    article_sections = split_by_article_fn(sanitized_text, loose=False)
    documents: List[Document] = []
    if not article_sections:
        return split_generic_txt_to_documents(
            sanitized_text=sanitized_text,
            txt_path=txt_path,
            doc_kind=doc_kind,
            text_splitter=text_splitter,
        )

    for _heading, article_text, sec_meta in article_sections:
        topic = classify_topic(article_text)
        sub_chunks = text_splitter.split_text(article_text)
        art_seq = sec_meta.get("article_seq")
        art_num = f"第{art_seq}条" if art_seq is not None else None
        search_from = 0
        for sub_idx, chunk in enumerate(sub_chunks, start=1):
            pos = article_text.find(chunk, search_from)
            if pos < 0:
                pos = article_text.find(chunk)
            search_from = max(search_from, pos + 1)
            pseq: int | None = None
            pconf = "unknown"
            if art_seq is not None:
                bounds = paragraph_boundaries_in_article_body(article_text)
                pseq, pconf = chunk_paragraph_assignment(
                    pos, pos + len(chunk), bounds
                )
            cite_label = (sec_meta.get("cite_label") or "").strip()
            if art_seq is not None and pseq is not None and pconf in (
                "high",
                "inferred",
            ):
                cite_label = f"第{art_seq}条第{pseq}項"
            elif art_seq is not None:
                cite_label = f"第{art_seq}条"
            else:
                cite_label = cite_label or "該当箇所"
            documents.append(
                Document(
                    page_content=chunk,
                    metadata={
                        "type": "master_txt",
                        "source": str(txt_path),
                        "filename": txt_path.name,
                        "doc_id": txt_path.stem,
                        "article_number": art_num,
                        "article_seq": art_seq,
                        "paragraph_seq": pseq,
                        "paragraph_seq_confidence": pconf,
                        "cite_kind": sec_meta.get("cite_kind"),
                        "cite_label": cite_label,
                        "topic": topic,
                        "page": sub_idx,
                        "total_pages": len(sub_chunks),
                        "effective_date": None,
                        "version": None,
                        "doc_kind": doc_kind,
                        "section_id": None,
                        "section_label": None,
                    },
                )
            )
    return documents


def split_important_matters_txt_to_documents(
    *,
    sanitized_text: str,
    txt_path,
    doc_kind: str,
    text_splitter: RecursiveCharacterTextSplitter,
) -> List[Document]:
    """Important matters: split on ## N. section headings; attach section_id / section_label."""
    sections = _split_important_matters_sections(sanitized_text)
    documents: List[Document] = []
    if not sections:
        return split_generic_txt_to_documents(
            sanitized_text=sanitized_text,
            txt_path=txt_path,
            doc_kind=doc_kind,
            text_splitter=text_splitter,
        )

    for section_id, section_label, section_body in sections:
        topic = classify_topic(section_body)
        sub_chunks = text_splitter.split_text(section_body)
        sl = (section_label or "")[:200] or None
        sec_cite = f"§{section_id} {sl}" if (section_id and sl) else (f"§{section_id}" if section_id else sl)
        for sub_idx, chunk in enumerate(sub_chunks, start=1):
            documents.append(
                Document(
                    page_content=chunk,
                    metadata={
                        "type": "master_txt",
                        "source": str(txt_path),
                        "filename": txt_path.name,
                        "doc_id": txt_path.stem,
                        "article_number": None,
                        "article_seq": None,
                        "paragraph_seq": None,
                        "paragraph_seq_confidence": None,
                        "cite_kind": "important_matters_section",
                        "cite_label": sec_cite,
                        "topic": topic,
                        "page": sub_idx,
                        "total_pages": len(sub_chunks),
                        "effective_date": None,
                        "version": None,
                        "doc_kind": doc_kind,
                        "section_id": section_id,
                        "section_label": sl,
                    },
                )
            )
    return documents


def split_generic_txt_to_documents(
    *,
    sanitized_text: str,
    txt_path,
    doc_kind: str,
    text_splitter: RecursiveCharacterTextSplitter,
) -> List[Document]:
    """Fallback: no structured headings."""
    chunks = text_splitter.split_text(sanitized_text)
    documents: List[Document] = []
    for idx, chunk in enumerate(chunks):
        topic = classify_topic(chunk)
        documents.append(
            Document(
                page_content=chunk,
                metadata={
                    "type": "master_txt",
                    "source": str(txt_path),
                    "filename": txt_path.name,
                    "doc_id": txt_path.stem,
                    "article_number": None,
                    "topic": topic,
                    "page": idx + 1,
                    "total_pages": len(chunks),
                    "effective_date": None,
                    "version": None,
                    "doc_kind": doc_kind,
                    "section_id": None,
                    "section_label": None,
                },
            )
        )
    return documents


def _split_important_matters_sections(text: str) -> List[Tuple[str, str, str]]:
    """Return list of (section_id, section_label, body) using SECTION_HEADING_RE."""
    matches = list(SECTION_HEADING_RE.finditer(text))
    if not matches:
        return []

    sections: List[Tuple[str, str, str]] = []
    for idx, match in enumerate(matches):
        sec_raw = match.group(2).strip()
        section_id = _section_id_normalize(sec_raw)
        header_line = match.group(0).strip()
        label = header_line.replace("#", "").strip()
        start = match.start()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        sections.append((section_id, label, body))

    return sections


def default_txt_splitter(config: Config) -> RecursiveCharacterTextSplitter:
    _ = config
    return RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=200,
        separators=["\n\n", "\n", "。", "．", "；", ";", "、", " ", ""],
    )
