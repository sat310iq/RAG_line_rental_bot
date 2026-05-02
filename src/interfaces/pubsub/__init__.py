"""Pub/Sub worker for LINE events (Slack notification)."""

from src.interfaces.pubsub.slack_notifier import notify_slack_from_event

__all__ = ["notify_slack_from_event"]
