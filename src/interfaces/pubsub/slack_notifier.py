"""Slack notifier for Pub/Sub events: reuses slack formatter and client."""

from datetime import datetime, timezone
from typing import Any, Dict

from src.interfaces.slack.formatter import build_slack_payload
from src.interfaces.slack.client import post_to_slack


def _parse_timestamp(ts: str) -> datetime:
    """Parse ISO timestamp string to datetime (UTC)."""
    if not ts:
        return datetime.now(timezone.utc)
    s = ts.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return datetime.now(timezone.utc)


def notify_slack_from_event(payload: Dict[str, Any]) -> None:
    """
    Build Slack payload from Pub/Sub event and send.
    Expects payload keys: line_user_id, message, answer_summary, timestamp (optional).
    No-op if SLACK_WEBHOOK_URL is not set.
    """
    sender = payload.get("line_user_id", "unknown")
    question = payload.get("message", "")
    answer = payload.get("answer_summary", "")
    ts = _parse_timestamp(payload.get("timestamp", ""))
    slack_payload = build_slack_payload(
        sender=sender,
        question=question,
        answer=answer,
        timestamp=ts,
    )
    post_to_slack(slack_payload)
