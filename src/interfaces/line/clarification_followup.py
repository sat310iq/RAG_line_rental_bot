"""Per-user clarification follow-up (instance-local; PoC).

Cross-instance LINE routing does not share this map. Main disambiguation for
「ガス → お湯が出ない」is short-bypass in kb_fast_path; this module only helps
when the same intent repeats a short follow-up after we already sent clarification.

The stored ``normalized_query`` is the **user message text normalized the same
way as kb_fast_path** (`normalize_for_match`), i.e. the input **immediately before**
we sent the last clarification reply for this user.

``numeric_queries`` holds one rewrite string per numbered clarification option
(same order as ``1.`` / ``2.`` in the bot message) so replies like ``1`` / ``2``
can be expanded before fast path / RAG.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from src.kb_fast_path import normalize_for_match

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_state: Dict[str, Tuple[str, str, Tuple[str, ...], float]] = {}
_TTL_SEC = 900  # 15 minutes


@dataclass(frozen=True)
class PriorClarification:
    intent: str
    normalized_query: str
    numeric_queries: Tuple[str, ...]


def _cleanup() -> None:
    now = time.time()
    dead = [k for k, (_, _, _, ts) in _state.items() if now - ts > _TTL_SEC]
    for k in dead:
        del _state[k]


def peek_prior_clarification(user_id: str) -> Optional[PriorClarification]:
    """Return last clarification context for this user if still within TTL."""
    if not (user_id or "").strip():
        return None
    with _lock:
        _cleanup()
        t = _state.get(user_id.strip())
        if not t:
            return None
        intent, q_norm, numeric_queries, ts = t
        if time.time() > ts + _TTL_SEC:
            del _state[user_id.strip()]
            return None
        intent_s = (intent or "").strip()
        if not intent_s:
            return None
        return PriorClarification(
            intent=intent_s,
            normalized_query=(q_norm or "").strip(),
            numeric_queries=tuple(numeric_queries) if numeric_queries else (),
        )


def record_clarification_intent(
    user_id: str,
    intent: str,
    normalized_query: str,
    numeric_queries: Sequence[str],
) -> None:
    """Remember intent, normalized user text, and per-option rewrite strings."""
    if not (user_id or "").strip():
        return
    with _lock:
        _cleanup()
        nq = tuple((x or "").strip() for x in numeric_queries if (x or "").strip())
        _state[user_id.strip()] = (
            (intent or "").strip(),
            (normalized_query or "").strip(),
            nq,
            time.time(),
        )


def clear_clarification_intent(user_id: str) -> None:
    if not (user_id or "").strip():
        return
    with _lock:
        _state.pop(user_id.strip(), None)


def resolve_numeric_clarification_reply(
    raw_text: str,
    prior_numeric_queries: Sequence[str] | None,
    *,
    line_user_id: Optional[str] = None,
) -> Optional[str]:
    """If raw_text is a single digit 1-9 and prior has matching slot, return rewrite string."""
    if not prior_numeric_queries:
        return None
    qn = normalize_for_match(raw_text or "")
    if not qn or not re.fullmatch(r"[1-9]", qn):
        return None
    n = int(qn, 10)
    if n < 1 or n > len(prior_numeric_queries):
        return None
    resolved = (prior_numeric_queries[n - 1] or "").strip()
    if not resolved:
        return None
    logger.info(
        "clarification_numeric_resolved %s",
        json.dumps(
            {
                "event": "clarification_numeric_resolved",
                "line_user_id": line_user_id,
                "raw_text": (raw_text or "")[:200],
                "resolved_text": resolved[:500],
            },
            ensure_ascii=False,
        ),
    )
    return resolved
