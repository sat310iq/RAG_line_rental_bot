"""Tests for LINE webhook idempotency — Firestore path (mocked) and in-memory path."""
from __future__ import annotations

import os
import time
from unittest.mock import MagicMock

import pytest

import src.interfaces.line.idempotency as idm

# ---------------------------------------------------------------------------
# Fake Firestore helpers
# ---------------------------------------------------------------------------


def _snap(*, exists: bool = True, status: str = "processing", age: float = 0.0) -> MagicMock:
    s = MagicMock()
    s.exists = exists
    s.to_dict.return_value = (
        {"status": status, "timestamp": time.time() - age} if exists else {}
    )
    return s


def _make_fs(snap: MagicMock):
    """Minimal fake google.cloud.firestore module.

    transactional is a simple pass-through decorator (no retry logic).
    Returns (fs_module, ref_mock, transaction_mock).
    """
    fs = MagicMock()

    def transactional(fn):
        def wrapper(txn):
            return fn(txn)
        return wrapper

    fs.transactional = transactional

    db = MagicMock()
    fs.Client.return_value = db

    ref = MagicMock()
    db.collection.return_value.document.return_value = ref
    ref.get.return_value = snap

    txn = MagicMock()
    db.transaction.return_value = txn

    return fs, ref, txn


# ---------------------------------------------------------------------------
# _firestore_mark_aborted — transaction correctness (TASK-010 core)
# ---------------------------------------------------------------------------


class TestFirestoreMarkAborted:
    def _run(self, snap: MagicMock, monkeypatch):
        fs, ref, txn = _make_fs(snap)
        monkeypatch.setitem(__import__("sys").modules, "google.cloud.firestore", fs)
        idm._firestore_mark_aborted("msg-abc")
        return ref, txn

    def test_processing_deletes_via_transaction(self, monkeypatch):
        """status=processing → transaction.delete が呼ばれる（ref.delete は呼ばれない）。"""
        snap = _snap(status="processing")
        ref, txn = self._run(snap, monkeypatch)

        txn.delete.assert_called_once_with(ref)
        ref.delete.assert_not_called()

    def test_completed_not_deleted(self, monkeypatch):
        """status=completed → 削除しない（completed エントリを保護する）。"""
        snap = _snap(status="completed")
        _, txn = self._run(snap, monkeypatch)

        txn.delete.assert_not_called()

    def test_nonexistent_no_op(self, monkeypatch):
        """ドキュメントが存在しない → 何もしない。"""
        snap = _snap(exists=False)
        _, txn = self._run(snap, monkeypatch)

        txn.delete.assert_not_called()


# ---------------------------------------------------------------------------
# _firestore_try_begin — claim logic
# ---------------------------------------------------------------------------


class TestFirestoreTryBegin:
    def _run(self, snap: MagicMock, monkeypatch) -> bool:
        fs, ref, txn = _make_fs(snap)
        monkeypatch.setitem(__import__("sys").modules, "google.cloud.firestore", fs)
        return idm._firestore_try_begin("msg-xyz")

    def test_new_message_claimed(self, monkeypatch):
        """存在しないドキュメント → True（claim 成功）。"""
        assert self._run(_snap(exists=False), monkeypatch) is True

    def test_recent_processing_not_claimed(self, monkeypatch):
        """status=processing かつ TTL 内 → False（重複）。"""
        assert self._run(_snap(status="processing", age=10), monkeypatch) is False

    def test_completed_not_claimed(self, monkeypatch):
        """status=completed → False（返信済み）。"""
        assert self._run(_snap(status="completed"), monkeypatch) is False

    def test_stale_processing_reclaimed(self, monkeypatch):
        """status=processing だが TTL 超過 → True（クラッシュ後の再試行を許容）。"""
        stale_age = idm._TTL_SEC + 1
        assert self._run(_snap(status="processing", age=stale_age), monkeypatch) is True


# ---------------------------------------------------------------------------
# In-memory fallback path
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_memory_state():
    """各テスト前後にインメモリ状態をリセット。"""
    with idm._lock:
        idm._completed.clear()
        idm._processing.clear()
    yield
    with idm._lock:
        idm._completed.clear()
        idm._processing.clear()


class TestMemoryPath:
    def test_first_call_claimed(self):
        assert idm._memory_try_begin("m1") is True

    def test_duplicate_while_processing(self):
        idm._memory_try_begin("m2")
        assert idm._memory_try_begin("m2") is False

    def test_completed_blocks_retry(self):
        idm._memory_try_begin("m3")
        idm._memory_mark_completed("m3")
        assert idm._memory_try_begin("m3") is False

    def test_aborted_allows_retry(self):
        idm._memory_try_begin("m4")
        idm._memory_mark_aborted("m4")
        assert idm._memory_try_begin("m4") is True

    def test_expired_completed_claimable(self, monkeypatch):
        """TTL 超過した completed エントリは _cleanup_completed で除去されて再 claim 可能。"""
        with idm._lock:
            idm._completed["m5"] = time.time() - idm._TTL_SEC - 1
        assert idm._memory_try_begin("m5") is True


# ---------------------------------------------------------------------------
# Public API — Firestore 障害時のインメモリ fallback
# ---------------------------------------------------------------------------


class TestPublicApiFallback:
    def test_firestore_error_falls_back_to_memory(self, monkeypatch):
        """Firestore が例外を上げたとき in-memory fallback で True を返す。"""
        monkeypatch.setenv("FIRESTORE_IDEMPOTENCY_ENABLED", "true")

        fs = MagicMock()
        fs.Client.side_effect = RuntimeError("Firestore unavailable")
        monkeypatch.setitem(__import__("sys").modules, "google.cloud.firestore", fs)

        result = idm.try_begin_message("fallback-msg")
        assert result is True

    def test_firestore_disabled_uses_memory(self, monkeypatch):
        """FIRESTORE_IDEMPOTENCY_ENABLED=false のとき Firestore は呼ばれない。"""
        monkeypatch.setenv("FIRESTORE_IDEMPOTENCY_ENABLED", "false")

        fs = MagicMock()
        monkeypatch.setitem(__import__("sys").modules, "google.cloud.firestore", fs)

        result = idm.try_begin_message("mem-only-msg")
        assert result is True
        fs.Client.assert_not_called()

    def test_empty_message_id_always_true(self, monkeypatch):
        """空 message_id は常に True（LINE の内部イベント等で ID が欠落する場合）。"""
        monkeypatch.setenv("FIRESTORE_IDEMPOTENCY_ENABLED", "true")
        assert idm.try_begin_message("") is True
        assert idm.try_begin_message(None) is True  # type: ignore[arg-type]
