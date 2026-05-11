"""Tests for LINE handler reply audit logging."""

import json
import logging

from src.interfaces.line.handler import _log_line_reply_audit


def test_line_reply_masked_log(caplog):
    """返信時にreply_maskedとreply_lenが構造化ログに出る"""
    reply_text = "これは返信本文の長さが30文字を超えるケースを確認するためのテキストです。"

    with caplog.at_level(logging.INFO, logger="line_handler"):
        _log_line_reply_audit(reply_text, source="rag_answerer")

    log_entries = [
        json.loads(r.message)
        for r in caplog.records
        if r.name == "line_handler"
        and r.message.startswith("{")
        and json.loads(r.message).get("event") == "line_reply"
    ]
    assert len(log_entries) >= 1
    entry = log_entries[0]
    assert "reply_masked" in entry
    assert "reply_len" in entry
    assert len(entry["reply_masked"]) <= 33
