"""KB fast path: normalized keyword scoring before full RAG.

Query cache policy: fast path hit/clarification must not populate QueryCache (see LINE handler).
RAG answers may be cached separately to avoid mixing KB plain text with structured RAG outputs.
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional, Tuple

from langchain_core.documents import Document

from src.config import Config
from src.kb_loader import load_kb_csv

logger = logging.getLogger(__name__)

WEIGHT_PRIMARY = 3
WEIGHT_SECONDARY = 1
WEIGHT_SYNONYM = 1
WEIGHT_EXCLUDE = 5

DEFAULT_CLARIFICATION_FALLBACK = (
    "いくつかの案内が考えられます。料金・契約のこと、設備トラブル、どちらに近いか教えてください。"
)

AMBIGUOUS_TOPIC_PATTERNS = (
    "水道の件",
    "修繕について",
    "契約について",
    "更新の件",
    "騒音のことで",
)
AMBIGUOUS_TOPIC_TERMS = ("水道", "修繕", "契約", "更新", "騒音", "ガス", "証明書")


@dataclass
class KBFastPathResult:
    kind: Literal["miss", "hit", "clarification"]
    text: Optional[str] = None
    intent: Optional[str] = None
    normalized_query: str = ""
    match_detail: Dict[str, Any] = field(default_factory=dict)


def normalize_for_match(text: str) -> str:
    t = unicodedata.normalize("NFKC", text or "")
    t = t.lower()
    t = re.sub(r"[\s　]+", " ", t)
    t = re.sub(r"[!?！？、。,.·…:：;；\[\]（）()]+", " ", t)
    return t.strip()


def _split_terms(s: str) -> List[str]:
    if not s or not str(s).strip():
        return []
    raw = str(s).replace(",", "|")
    return [p.strip() for p in raw.split("|") if p.strip()]


def _split_pipe_field(s: str) -> List[str]:
    if not s or not str(s).strip():
        return []
    raw = str(s).replace(",", "|")
    return [p.strip() for p in raw.split("|") if p.strip()]


def clarification_numeric_queries(options: List[str], examples: List[str]) -> List[str]:
    """One rewrite string per clarification option (for 1/2 numeric replies)."""
    if not options:
        return []
    out: List[str] = []
    for i in range(len(options)):
        if i < len(examples):
            out.append(examples[i])
        else:
            out.append(options[i])
    return out


def build_clarification_message(
    prompt: str,
    options: List[str],
    examples: List[str],
    *,
    fallback: str = DEFAULT_CLARIFICATION_FALLBACK,
) -> str:
    """Build LINE-ready clarification: prompt, numbered options, example lines."""
    p = (prompt or "").strip()
    lines: List[str] = []
    if p:
        lines.append(p)
    if options:
        if lines:
            lines.append("")
        for i, opt in enumerate(options, 1):
            lines.append(f"{i}. {opt}")
        lines.append("")
        n = len(options)
        lines.append(f"上の 1〜{n} の番号だけでも返信できます。")
    if examples:
        if lines:
            lines.append("")
        lines.append("そのまま次のように送ってください。")
        for ex in examples:
            lines.append(f"- {ex}")
    if not lines:
        return fallback
    return "\n".join(lines)


def _term_matches(term: str, q_norm: str) -> bool:
    tn = normalize_for_match(term)
    if not tn:
        return False
    return tn in q_norm or q_norm in tn


def _count_group_hits(terms: List[str], q_norm: str) -> Tuple[int, List[str]]:
    hits = 0
    matched: List[str] = []
    for term in terms:
        if _term_matches(term, q_norm):
            hits += 1
            matched.append(term)
    return hits, matched


def _meta_bool(meta: Dict[str, Any], key: str, default: bool = False) -> bool:
    v = meta.get(key, default)
    if isinstance(v, bool):
        return v
    if v is None:
        return default
    s = str(v).strip().lower()
    if s in ("true", "1", "yes", "y"):
        return True
    if s in ("false", "0", "no", "n", ""):
        return False
    return default


def _is_ambiguous_topic_query(question: str, q_norm: str, detail: Dict[str, Any]) -> bool:
    q = (question or "").strip()
    if not q:
        return False
    if any(p in q for p in AMBIGUOUS_TOPIC_PATTERNS):
        return True

    has_topic_suffix = any(x in q for x in ("の件", "について", "のことで"))
    topic_hits = sum(1 for t in AMBIGUOUS_TOPIC_TERMS if t in q)
    primary_hits = int(detail.get("primary_hits") or 0)
    secondary_hits = int(detail.get("secondary_hits") or 0)
    exact_bonus = int(detail.get("exact_primary_bonus") or 0)
    weak_signal = (primary_hits + secondary_hits) <= 1 and exact_bonus == 0
    return has_topic_suffix and topic_hits == 1 and weak_signal


def _legal_skip(question: str, config: Config) -> bool:
    raw = (config.kb_fast_path_legal_skip_substrings or "").strip()
    if not raw:
        return False
    subs = [x.strip() for x in raw.split(",") if x.strip()]
    for sub in subs:
        if sub in question:
            return True
    return False


def score_document(meta: Dict[str, Any], q_norm: str) -> Tuple[float, Dict[str, Any]]:
    primary = _split_terms(str(meta.get("keywords_primary") or ""))
    secondary = _split_terms(str(meta.get("keywords_secondary") or ""))
    synonyms = _split_terms(str(meta.get("synonyms") or ""))
    exclude_fp = _split_terms(str(meta.get("exclude_keywords") or ""))
    exclude_legacy = _split_terms(str(meta.get("negative_keywords") or ""))
    exclude_terms = exclude_fp if exclude_fp else exclude_legacy

    ph, pm = _count_group_hits(primary, q_norm)
    sh, sm = _count_group_hits(secondary, q_norm)
    yh, ym = _count_group_hits(synonyms, q_norm)
    eh, em = _count_group_hits(exclude_terms, q_norm)

    exact_bonus = 0
    for term in primary:
        if normalize_for_match(term) == q_norm:
            exact_bonus = WEIGHT_PRIMARY
            break

    score = (
        WEIGHT_PRIMARY * ph
        + WEIGHT_SECONDARY * sh
        + WEIGHT_SYNONYM * yh
        - WEIGHT_EXCLUDE * eh
        + exact_bonus
    )
    detail = {
        "primary_hits": ph,
        "primary_matched": pm,
        "secondary_hits": sh,
        "secondary_matched": sm,
        "synonym_hits": yh,
        "synonym_matched": ym,
        "exclude_hits": eh,
        "exclude_matched": em,
        "exact_primary_bonus": exact_bonus,
        "score": score,
    }
    return float(score), detail


def try_kb_fast_path(
    question: str,
    config: Config,
    kb_documents: Optional[List[Document]] = None,
    *,
    prior_clarification_intent: Optional[str] = None,
    prior_clarification_normalized_query: Optional[str] = None,
    line_user_id: Optional[str] = None,
    user_text_for_prior_match: Optional[str] = None,
) -> KBFastPathResult:
    if not (config.kb_fast_path_enabled and (question or "").strip()):
        return KBFastPathResult(kind="miss", match_detail={"reason": "disabled_or_empty"})

    if _legal_skip(question, config):
        logger.info(
            "kb_fast_path_miss legal_guard query_preview=%s",
            question[:80],
        )
        return KBFastPathResult(
            kind="miss",
            normalized_query=normalize_for_match(question),
            match_detail={"reason": "legal_skip"},
        )

    q_norm = normalize_for_match(question)
    if not q_norm:
        return KBFastPathResult(kind="miss", match_detail={"reason": "empty_normalized"})

    q_norm_prior = (
        normalize_for_match(user_text_for_prior_match)
        if (user_text_for_prior_match or "").strip()
        else q_norm
    )

    docs = kb_documents if kb_documents is not None else load_kb_csv(config)
    candidates: List[Tuple[float, Dict[str, Any], Document]] = []

    for doc in docs:
        meta = dict(doc.metadata or {})
        if not _meta_bool(meta, "fast_path_enabled", False):
            continue
        sc, det = score_document(meta, q_norm)
        if sc <= 0 and det["exclude_hits"] > 0:
            continue
        candidates.append((sc, det, doc))

    candidates.sort(key=lambda x: x[0], reverse=True)
    threshold = config.kb_fast_path_score_threshold
    delta = config.kb_fast_path_ambiguity_delta
    short = len(q_norm) <= config.kb_fast_path_short_max_len

    if not candidates or candidates[0][0] < threshold:
        if candidates:
            top_score, top_det, top_doc = candidates[0]
            top_meta = dict(top_doc.metadata or {})
            clar_prompt = (top_meta.get("clarification_prompt") or "").strip()
            clar_options = _split_pipe_field(str(top_meta.get("clarification_options") or ""))
            clar_examples = _split_pipe_field(str(top_meta.get("clarification_examples") or ""))
            if (
                top_score > 0
                and clar_prompt
                and _is_ambiguous_topic_query(question, q_norm, top_det)
            ):
                clar_reason = "ambiguous_topic"
                clar_numeric = clarification_numeric_queries(clar_options, clar_examples)
                text = build_clarification_message(clar_prompt, clar_options, clar_examples)
                return KBFastPathResult(
                    kind="clarification",
                    text=text,
                    intent=str(top_meta.get("intent") or ""),
                    normalized_query=q_norm,
                    match_detail={
                        "reason": clar_reason,
                        "clarification_reason": clar_reason,
                        "top_score": top_score,
                        "threshold": threshold,
                        "clarification_numeric_queries": clar_numeric,
                    },
                )
        logger.info(
            "kb_fast_path_miss normalized=%s top_score=%s threshold=%s",
            json.dumps(q_norm[:200], ensure_ascii=False),
            candidates[0][0] if candidates else None,
            threshold,
        )
        return KBFastPathResult(
            kind="miss",
            normalized_query=q_norm,
            match_detail={
                "reason": "below_threshold",
                "top_score": candidates[0][0] if candidates else None,
            },
        )

    top_score, top_det, top_doc = candidates[0]
    second_score = candidates[1][0] if len(candidates) > 1 else -1.0
    top_meta = dict(top_doc.metadata or {})
    intent = str(top_meta.get("intent") or "")
    clar_prompt = (top_meta.get("clarification_prompt") or "").strip()
    answer = (top_meta.get("answer") or "").strip()
    needs_short_clar = _meta_bool(top_meta, "needs_clarification_when_short", False)
    clar_options = _split_pipe_field(str(top_meta.get("clarification_options") or ""))
    clar_examples = _split_pipe_field(str(top_meta.get("clarification_examples") or ""))

    if prior_clarification_intent and prior_clarification_intent == intent:
        # After clarification for this intent: default is to relax "short" so concrete
        # follow-ups (e.g. ガス→お湯が出ない) can hit. Exception: same vague short repeat
        # (same normalized text) should stay in clarification, not hit on duplicate ガス.
        #
        # prior_clarification_normalized_query is None: legacy behavior for callers not
        # yet passing normalized text (migration only—remove once all paths supply it).
        short_max = config.kb_fast_path_short_max_len
        if prior_clarification_normalized_query is None:
            short = False
        elif (
            prior_clarification_normalized_query == q_norm_prior
            and len(q_norm_prior) <= short_max
        ):
            pass  # keep short as len-based; do not force short=False
        else:
            short = False

    ambiguous = second_score >= threshold and (top_score - second_score) <= delta

    exact_b = int(top_det.get("exact_primary_bonus") or 0)
    ph = int(top_det.get("primary_hits") or 0)
    min_len = config.kb_fast_path_short_bypass_min_len
    bypass_score = config.kb_fast_path_short_bypass_score
    is_specific_even_if_short = (exact_b > 0 and len(q_norm) >= min_len) or (
        len(q_norm) >= min_len and (top_score >= bypass_score or ph >= 2)
    )

    log_payload: Dict[str, Any] = {
        "event": "kb_fast_path",
        "normalized_query": q_norm,
        "intent": intent,
        "line_user_id": line_user_id,
        "top_score": top_score,
        "second_score": second_score,
        "threshold": threshold,
        "ambiguous": ambiguous,
        "short": short,
        "match_detail": top_det,
        "primary_match_count": ph,
        "exact_primary_bonus": exact_b,
        "is_specific_even_if_short": is_specific_even_if_short,
    }

    clar_numeric = clarification_numeric_queries(clar_options, clar_examples)
    ambiguous_topic = (
        bool(clar_prompt)
        and _is_ambiguous_topic_query(question, q_norm, top_det)
        and not is_specific_even_if_short
    )
    log_payload["ambiguous_topic"] = ambiguous_topic

    if ambiguous_topic:
        clar_reason = "ambiguous_topic"
        log_payload["clarification_reason"] = clar_reason
        log_payload["clarification_numeric_queries"] = clar_numeric
        text = build_clarification_message(clar_prompt, clar_options, clar_examples)
        logger.info(
            "kb_fast_path_clarification %s",
            json.dumps({**log_payload, "event": "kb_fast_path_clarification"}, ensure_ascii=False),
        )
        return KBFastPathResult(
            kind="clarification",
            text=text,
            intent=intent,
            normalized_query=q_norm,
            match_detail={**log_payload, "reason": clar_reason},
        )

    if ambiguous:
        clar_reason = "ambiguity"
        log_payload["clarification_reason"] = clar_reason
        log_payload["clarification_numeric_queries"] = clar_numeric
        text = build_clarification_message(clar_prompt, clar_options, clar_examples)
        logger.info(
            "kb_fast_path_clarification %s",
            json.dumps({**log_payload, "event": "kb_fast_path_clarification"}, ensure_ascii=False),
        )
        return KBFastPathResult(
            kind="clarification",
            text=text,
            intent=intent,
            normalized_query=q_norm,
            match_detail={**log_payload, "reason": clar_reason},
        )

    if short and needs_short_clar and clar_prompt and not is_specific_even_if_short:
        clar_reason = "short_query"
        log_payload["clarification_reason"] = clar_reason
        log_payload["clarification_numeric_queries"] = clar_numeric
        text = build_clarification_message(clar_prompt, clar_options, clar_examples)
        logger.info(
            "kb_fast_path_clarification %s",
            json.dumps({**log_payload, "event": "kb_fast_path_clarification"}, ensure_ascii=False),
        )
        return KBFastPathResult(
            kind="clarification",
            text=text,
            intent=intent,
            normalized_query=q_norm,
            match_detail={**log_payload, "reason": clar_reason},
        )

    if not answer:
        logger.info("kb_fast_path_miss reason=no_answer intent=%s", intent)
        return KBFastPathResult(
            kind="miss",
            normalized_query=q_norm,
            match_detail={"reason": "no_answer", "intent": intent},
        )

    logger.info(
        "kb_fast_path_hit %s",
        json.dumps({**log_payload, "event": "kb_fast_path_hit"}, ensure_ascii=False),
    )
    return KBFastPathResult(
        kind="hit",
        text=answer,
        intent=intent,
        normalized_query=q_norm,
        match_detail=log_payload,
    )


def load_kb_documents_for_fast_path(config: Config) -> List[Document]:
    return load_kb_csv(config)
