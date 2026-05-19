"""Tests for LINE handler reply audit logging."""

import logging

from src.interfaces.line.handler import _log_line_reply_audit


def test_line_reply_masked_log(caplog):
    """返信時にreply_maskedとreply_lenが構造化ログに出る"""
    reply_text = "これは返信本文の長さが30文字を超えるケースを確認するためのテキストです。"

    with caplog.at_level(logging.INFO, logger="line_handler"):
        _log_line_reply_audit(reply_text, source="rag_answerer")

    records = [r for r in caplog.records if r.name == "line_handler" and r.getMessage() == "line_reply"]
    assert len(records) >= 1
    r = records[0]
    assert r.event == "line_reply"
    assert hasattr(r, "reply_masked")
    assert hasattr(r, "reply_len")
    assert len(r.reply_masked) <= 33
