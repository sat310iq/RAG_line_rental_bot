"""Question term extraction utilities."""

from __future__ import annotations

import re
from typing import Dict, Iterable, List, Optional


DEFAULT_STOPWORDS = {
    "について",
    "とは",
    "など",
    "のこと",
    "こと",
    "の",
    "を",
    "は",
    "が",
    "か",
    "です",
    "ます",
    "ください",
    "どこ",
    "どれ",
}

DEFAULT_SYNONYMS: Dict[str, List[str]] = {
    "保証人": ["連帯保証人", "連帯"],
    "禁止": ["禁止事項", "禁ずる", "禁止される"],
}


def _normalize_token(token: str) -> str:
    trimmed = re.sub(r"(について|とは|など|のこと|の|を|は|が|か)$", "", token)
    return trimmed


def _split_by_particles(token: str) -> List[str]:
    parts = re.split(r"(?:について|とは|など|のこと)|[はがをにとでへもや]", token)
    return [part for part in parts if part]


def extract_question_terms(
    question: str,
    *,
    stopwords: Optional[Iterable[str]] = None,
    synonyms: Optional[Dict[str, List[str]]] = None,
) -> List[str]:
    """Extract meaningful terms from a question with simple rules."""
    if not question:
        return []
    stopword_set = set(stopwords) if stopwords is not None else DEFAULT_STOPWORDS
    synonym_map = synonyms or DEFAULT_SYNONYMS

    raw_tokens = re.findall(r"[一-龥ぁ-んァ-ヶA-Za-z0-9]{2,}", question)
    terms = set()
    for token in raw_tokens:
        for part in _split_by_particles(token):
            normalized = _normalize_token(part)
            if not normalized or normalized in stopword_set:
                continue
            if len(normalized) >= 2:
                terms.add(normalized)
            if normalized.endswith("事項") and len(normalized) > 2:
                terms.add(normalized[:-2])
            for syn in synonym_map.get(normalized, []):
                if syn and syn not in stopword_set:
                    terms.add(syn)
    return list(terms)


def count_pipe_field_hits(question: str, pipe_field: str) -> int:
    """Count how many | or whitespace-separated tokens from pipe_field appear as substrings in question."""
    if not question or not pipe_field:
        return 0
    score = 0
    tokens = [t for t in re.split(r"[\s|]+", str(pipe_field)) if t]
    for token in tokens:
        if token and token in question:
            score += 1
    return score


def count_distinct_pipe_tokens_in_question(question: str, *pipe_fields: str) -> int:
    """Union of tokens across one or more |-separated fields that appear as substrings in question."""
    if not question:
        return 0
    matched: set[str] = set()
    for pipe_field in pipe_fields:
        if not pipe_field:
            continue
        for token in [t for t in re.split(r"[\s|]+", str(pipe_field)) if t]:
            if token in question:
                matched.add(token)
    return len(matched)


def has_content_keyword_hit(
    question: str,
    content: str,
    *,
    stopwords: Optional[Iterable[str]] = None,
    synonyms: Optional[Dict[str, List[str]]] = None,
) -> bool:
    """Check if question terms appear in content."""
    if not question or not content:
        return False
    for term in extract_question_terms(question, stopwords=stopwords, synonyms=synonyms):
        if term and term in content:
            return True
    return False
