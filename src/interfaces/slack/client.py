"""Slack notification client."""

import os
from typing import Any, Dict

import requests


def post_to_slack(payload: Dict[str, Any]) -> None:
    webhook_url = os.getenv("SLACK_WEBHOOK_URL", "").strip()
    if not webhook_url:
        return
    requests.post(webhook_url, json=payload, timeout=10)
