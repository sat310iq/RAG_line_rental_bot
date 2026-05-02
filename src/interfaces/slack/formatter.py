"""Slack notification formatter."""

from datetime import datetime
from typing import Any, Dict


def build_slack_payload(
    sender: str,
    question: str,
    answer: str,
    timestamp: datetime,
) -> Dict[str, Any]:
    ts = timestamp.strftime("%Y-%m-%d %H:%M:%S UTC")
    return {
        "text": "LINE問い合わせ通知",
        "blocks": [
            {"type": "section", "text": {"type": "mrkdwn", "text": "*LINE問い合わせ通知*"}},
            {"type": "section", "text": {"type": "mrkdwn", "text": f"*送信者*: `{sender}`"}},
            {"type": "section", "text": {"type": "mrkdwn", "text": f"*質問*: {question}"}},
            {"type": "section", "text": {"type": "mrkdwn", "text": f"*回答*: {answer}"}},
            {"type": "context", "elements": [{"type": "mrkdwn", "text": f"*時刻*: {ts}"}]},
        ],
    }
