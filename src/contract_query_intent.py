"""Shared intent detection for contract-source question handling."""

from __future__ import annotations

import re
import unicodedata
from typing import Optional

_RE_ARTICLE_INDEX = re.compile(r"(?:本文)?第\s*(\d+)\s*条")
_USAGE_PURPOSE_TERMS: tuple[str, ...] = ("使用目的", "居住目的", "居住のみを目的", "用途")
_CONTRACT_CONTEXT_TERMS: tuple[str, ...] = ("契約", "契約書", "本物件", "賃貸借")
_CONTRACT_SOURCE_META_TERMS: tuple[str, ...] = ("記載", "書いて", "書かれ", "定め", "規定")


def normalize_question(question: str) -> str:
    return unicodedata.normalize("NFKC", question or "")


def detect_article_reference(question: str) -> Optional[int]:
    q = normalize_question(question)
    m = _RE_ARTICLE_INDEX.search(q)
    if not m:
        return None
    try:
        return int(m.group(1))
    except ValueError:
        return None


def detect_usage_purpose_intent(question: str) -> bool:
    q = normalize_question(question)
    if not q.strip():
        return False
    has_usage_term = any(term in q for term in _USAGE_PURPOSE_TERMS)
    has_contract_context = any(term in q for term in _CONTRACT_CONTEXT_TERMS)
    return has_usage_term and has_contract_context


def detect_contract_source_intent(question: str) -> bool:
    q = normalize_question(question)
    if not q.strip():
        return False
    if detect_article_reference(q) is not None:
        return True
    if detect_usage_purpose_intent(q):
        return True
    if "契約書" in q and any(term in q for term in _CONTRACT_SOURCE_META_TERMS):
        return True
    return False
