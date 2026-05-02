"""In-memory idempotency for LINE message IDs (per Cloud Run instance).

Duplicate webhooks with the same message id are ignored after a successful reply,
or while the first worker is still processing. If processing crashes before
mark_reply_success, a retry may be processed again.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Dict, Set

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_completed: Dict[str, float] = {}
_processing: Set[str] = set()
_TTL_SEC = 86400 * 2  # drop old ids to cap memory


def _cleanup_completed() -> None:
    now = time.time()
    expired = [k for k, ts in _completed.items() if now - ts > _TTL_SEC]
    for k in expired:
        del _completed[k]


def try_begin_message(message_id: str) -> bool:
    """Return True if this worker should handle the message; False if duplicate."""
    if not message_id:
        return True
    with _lock:
        _cleanup_completed()
        if message_id in _completed:
            logger.info("idempotent skip: message already completed message_id=%s", message_id)
            return False
        if message_id in _processing:
            logger.info("idempotent skip: message in progress message_id=%s", message_id)
            return False
        _processing.add(message_id)
        return True


def mark_reply_success(message_id: str) -> None:
    """Call after LINE reply succeeded so retries return early."""
    if not message_id:
        return
    with _lock:
        _processing.discard(message_id)
        _completed[message_id] = time.time()


def mark_reply_aborted(message_id: str) -> None:
    """Call on failure before a successful reply so a webhook retry can retry."""
    if not message_id:
        return
    with _lock:
        _processing.discard(message_id)
