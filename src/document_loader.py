"""Master document loaders: TXT sources for the vector index (PDF ingestion disabled)."""

import re
from pathlib import Path
from typing import Any, Dict, List, Tuple
from langchain_core.documents import Document
from src.config import Config
from src.citation_metadata import (
    parse_article_seq_from_heading_line,
    split_preliminary_sections,
)
from src.document_txt_splitters import (
    default_txt_splitter,
    split_contract_txt_to_documents,
    split_important_matters_txt_to_documents,
    split_generic_txt_to_documents,
)


def _sanitize_text(text: str) -> str:
    """Sanitize text to remove suspicious patterns.
    
    Args:
        text: Input text
        
    Returns:
        Sanitized text
    """
    # Remove HTML tags
    text = re.sub(r'<[^>]+>', '', text)
    
    # Remove scripts and style blocks
    text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
    
    # Remove suspicious control characters (keep normal whitespace)
    text = re.sub(r'[\x00-\x08\x0B-\x0C\x0E-\x1F\x7F]', '', text)
    
    # Normalize excessive whitespace
    text = re.sub(r'\s{3,}', ' ', text)
    
    return text.strip()


def _detect_suspicious_patterns(text: str) -> List[str]:
    """Detect suspicious patterns that might indicate malicious content.
    
    Args:
        text: Input text
        
    Returns:
        List of detected suspicious patterns
    """
    suspicious = []
    
    # Long runs of whitespace (might hide invisible text)
    if re.search(r'\s{20,}', text):
        suspicious.append("excessive_whitespace")
    
    # Odd control characters
    if re.search(r'[\x00-\x08\x0B-\x0C\x0E-\x1F]', text):
        suspicious.append("control_characters")
    
    # HTML/script tags
    if re.search(r'<[^>]+>', text):
        suspicious.append("html_tags")
    
    # Suspicious instruction patterns (basic detection)
    suspicious_phrases = [
        r'ignore\s+all\s+prior\s+instructions',
        r'ignore\s+previous',
        r'forget\s+everything',
        r'new\s+instructions',
    ]
    for pattern in suspicious_phrases:
        if re.search(pattern, text, re.IGNORECASE):
            suspicious.append(f"suspicious_phrase: {pattern}")
    
    return suspicious


def _split_by_article(
    text: str, *, loose: bool = False
) -> List[Tuple[str, str, Dict[str, Any]]]:
    """Split text into (heading, body, section_meta) sections.

    TXTの賃貸借契約書は ``## 第N条`` で区切り、別表内の「第17条関係」や法令の「第90条」
    参照を誤って条の境界にしない。見出しが無いTXT（重要事項説明書等）は空を返し全文チャンク化する。

    前文（最初の ``## 第N条`` より前）は ``#`` 見出しでサブ分割し、``article_seq`` を付けない。

    PDF向けに ``loose=True`` のときのみ、従来の「第N条」単純マッチにフォールバックする。
    """
    pat_md = re.compile(r"(?m)^(##\s*第[0-9一二三四五六七八九十百千]+条[^\n]*)")
    matches = list(pat_md.finditer(text))
    if matches:
        sections: List[Tuple[str, str, Dict[str, Any]]] = []
        if matches[0].start() > 0:
            pre = text[: matches[0].start()].strip()
            if pre:
                for _title, block, meta in split_preliminary_sections(pre):
                    display_head = (meta.get("cite_label") or "前文")[:120]
                    sections.append((display_head, block, dict(meta)))
        for idx, match in enumerate(matches):
            start = match.start()
            end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
            header = re.sub(r"^#+\s*", "", match.group(1).strip()).strip()
            body = text[start:end].strip()
            art = parse_article_seq_from_heading_line(match.group(1))
            meta = {
                "cite_kind": "article",
                "cite_label": f"第{art}条" if art is not None else None,
                "article_seq": art,
            }
            sections.append((header, body, meta))
        return sections

    if not loose:
        return []

    pattern = re.compile(r"(第[0-9一二三四五六七八九十百千]+条[^\n]*)")
    matches = list(pattern.finditer(text))
    if not matches:
        return []

    sections_loose: List[Tuple[str, str, Dict[str, Any]]] = []
    for idx, match in enumerate(matches):
        start = match.start()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        header = match.group(1).strip()
        body = text[start:end].strip()
        art = parse_article_seq_from_heading_line(header)
        meta = {
            "cite_kind": "article",
            "cite_label": f"第{art}条" if art is not None else header[:80],
            "article_seq": art,
        }
        sections_loose.append((header, body, meta))
    return sections_loose


def load_pdf_documents(config: Config) -> List[Document]:
    """PDF ingestion is disabled; use ``load_txt_documents`` for the master corpus."""
    return []


def load_txt_documents(config: Config) -> List[Document]:
    """Load master TXT documents into the same schema as indexed master chunks.

    Args:
        config: Application configuration

    Returns:
        List of Document objects with metadata
    """
    txt_dir = config.get_pdf_documents_dir()
    filenames = config.get_master_txt_files()
    if not txt_dir.exists() or not filenames:
        return []

    documents = []
    text_splitter = default_txt_splitter(config)

    for filename in filenames:
        txt_path = txt_dir / filename
        if not txt_path.exists():
            print(f"Warning: TXT file not found: {filename}")
            continue
        try:
            raw_text = txt_path.read_text(encoding="utf-8")
            sanitized_text = _sanitize_text(raw_text)

            suspicious = _detect_suspicious_patterns(sanitized_text)
            if suspicious:
                print(f"Warning: Suspicious patterns detected in {txt_path.name}: {suspicious}")

            if "契約書" in txt_path.name:
                doc_kind = "contract"
            elif "重要事項" in txt_path.name:
                doc_kind = "important_matters"
            else:
                doc_kind = "txt"

            if doc_kind == "important_matters":
                documents.extend(
                    split_important_matters_txt_to_documents(
                        sanitized_text=sanitized_text,
                        txt_path=txt_path,
                        doc_kind=doc_kind,
                        text_splitter=text_splitter,
                    )
                )
            elif doc_kind == "contract":
                documents.extend(
                    split_contract_txt_to_documents(
                        sanitized_text=sanitized_text,
                        txt_path=txt_path,
                        doc_kind=doc_kind,
                        text_splitter=text_splitter,
                        split_by_article_fn=_split_by_article,
                    )
                )
            else:
                documents.extend(
                    split_generic_txt_to_documents(
                        sanitized_text=sanitized_text,
                        txt_path=txt_path,
                        doc_kind=doc_kind,
                        text_splitter=text_splitter,
                    )
                )
        except Exception as e:
            print(f"Error loading TXT {txt_path.name}: {e}")

    return documents
