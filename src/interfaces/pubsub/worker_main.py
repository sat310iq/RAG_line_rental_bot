"""Cloud Run entrypoint: receive Pub/Sub Push, send Slack notification."""

import base64
import json
import logging
import os

from fastapi import FastAPI, Request, Response

from src.interfaces.pubsub.slack_notifier import notify_slack_from_event

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="LINE events Worker (Slack)")


@app.post("/")
async def pubsub_push(request: Request) -> Response:
    """
    Handle Pub/Sub Push. Body shape: { "message": { "data": "<base64-encoded JSON>" } }.
    Decode message.data and call notify_slack_from_event; return 200 to ack.
    """
    try:
        body = await request.json()
    except Exception as e:
        logger.warning("Invalid JSON body: %s", e)
        return Response(status_code=400, content="Invalid JSON")

    message = body.get("message") if isinstance(body, dict) else None
    if not message or "data" not in message:
        logger.warning("Missing message.data in Pub/Sub payload")
        return Response(status_code=200, content="OK")  # ack to avoid redelivery

    try:
        raw = base64.b64decode(message["data"]).decode("utf-8")
        payload = json.loads(raw)
    except Exception as e:
        logger.warning("Failed to decode message.data: %s", e)
        return Response(status_code=200, content="OK")

    if not os.getenv("SLACK_WEBHOOK_URL", "").strip():
        logger.info("SLACK_WEBHOOK_URL not set, skipping Slack send")
        return Response(status_code=200, content="OK")

    try:
        notify_slack_from_event(payload)
        logger.info("Slack notification sent for line_user_id=%s", payload.get("line_user_id"))
    except Exception as e:
        logger.exception("Slack send failed: %s", e)
        return Response(status_code=500, content="Slack send failed")

    return Response(status_code=200, content="OK")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
