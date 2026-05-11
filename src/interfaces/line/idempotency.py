"""Idempotency for LINE message IDs across Cloud Run instances.

Strategy (controlled by FIRESTORE_IDEMPOTENCY_ENABLED env var):
  - enabled=true  → Firestore (cross-instance, production-safe)
  - enabled=false → in-process dict (single-instance PoC fallback)

Firestore prereq: Firestore database must exist in the GCP project and the
Cloud Run service account needs roles/datastore.user.
Collection: line_message_ids / Document ID: message_id
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Dict, Set

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Firestore backend
# ---------------------------------------------------------------------------

_COLLECTION = "line_message_ids"
_TTL_SEC = 86400 * 2


def _firestore_try_begin(message_id: str) -> bool:
    """Atomically claim message_id in Firestore. Returns True if claimed."""
    from google.cloud import firestore  # type: ignore[import-untyped]

    db = firestore.Client()
    ref = db.collection(_COLLECTION).document(message_id)
    now = time.time()

    @firestore.transactional
    def _claim(transaction: firestore.Transaction) -> bool:
        snap = ref.get(transaction=transaction)
        if snap.exists:
            data = snap.to_dict() or {}
            status = data.get("status")
            ts = data.get("timestamp", 0)
            # Treat stale processing entries (> TTL) as claimable to handle crashed instances.
            if status == "completed" or (status == "processing" and now - ts < _TTL_SEC):
                return False
        transaction.set(ref, {"status": "processing", "timestamp": now})
        return True

    return _claim(db.transaction())


def _firestore_mark_completed(message_id: str) -> None:
    from google.cloud import firestore  # type: ignore[import-untyped]

    db = firestore.Client()
    db.collection(_COLLECTION).document(message_id).set(
        {"status": "completed", "timestamp": time.time()}
    )


def _firestore_mark_aborted(message_id: str) -> None:
    from google.cloud import firestore  # type: ignore[import-untyped]

    db = firestore.Client()
    ref = db.collection(_COLLECTION).document(message_id)

    @firestore.transactional
    def _abort(transaction: firestore.Transaction) -> None:
        snap = ref.get(transaction=transaction)
        # Only clear the processing flag; leave completed entries untouched.
        # Transactional read+delete prevents a race where mark_completed runs
        # between the read and delete, which would delete a completed entry.
        if snap.exists and (snap.to_dict() or {}).get("status") == "processing":
            transaction.delete(ref)

    _abort(db.transaction())


# ---------------------------------------------------------------------------
# In-process fallback (single-instance only)
# ---------------------------------------------------------------------------

_lock = threading.Lock()
_completed: Dict[str, float] = {}
_processing: Set[str] = set()


def _cleanup_completed() -> None:
    now = time.time()
    expired = [k for k, ts in _completed.items() if now - ts > _TTL_SEC]
    for k in expired:
        del _completed[k]


def _memory_try_begin(message_id: str) -> bool:
    with _lock:
        _cleanup_completed()
        if message_id in _completed or message_id in _processing:
            return False
        _processing.add(message_id)
        return True


def _memory_mark_completed(message_id: str) -> None:
    with _lock:
        _processing.discard(message_id)
        _completed[message_id] = time.time()


def _memory_mark_aborted(message_id: str) -> None:
    with _lock:
        _processing.discard(message_id)


# ---------------------------------------------------------------------------
# Public API — delegates to Firestore or in-memory based on env var
# ---------------------------------------------------------------------------

def _use_firestore() -> bool:
    return os.getenv("FIRESTORE_IDEMPOTENCY_ENABLED", "false").lower() == "true"


def try_begin_message(message_id: str) -> bool:
    """Return True if this instance should handle the message; False if duplicate."""
    if not message_id:
        return True
    if _use_firestore():
        try:
            result = _firestore_try_begin(message_id)
            if not result:
                logger.info("idempotent skip (firestore): message_id=%s", message_id)
            return result
        except Exception:
            logger.exception("Firestore idempotency check failed; falling back to in-memory")
    return _memory_try_begin(message_id)


def mark_reply_success(message_id: str) -> None:
    """Call after LINE reply succeeded so retries return early."""
    if not message_id:
        return
    if _use_firestore():
        try:
            _firestore_mark_completed(message_id)
            return
        except Exception:
            logger.exception("Firestore mark_completed failed; falling back to in-memory")
    _memory_mark_completed(message_id)


def mark_reply_aborted(message_id: str) -> None:
    """Call on failure so a webhook retry can be processed again."""
    if not message_id:
        return
    if _use_firestore():
        try:
            _firestore_mark_aborted(message_id)
            return
        except Exception:
            logger.exception("Firestore mark_aborted failed; falling back to in-memory")
    _memory_mark_aborted(message_id)
