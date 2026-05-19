"""LINE webhook handler."""

import base64
import hashlib
import hmac
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import requests  # type: ignore[import-untyped]  # types-requests 未導入のため（TASK-005で整備）

from src.config import get_config
from src.interfaces.line.idempotency import (
    mark_reply_aborted,
    mark_reply_success,
    try_begin_message,
)
from src.interfaces.slack.client import post_to_slack
from src.interfaces.slack.formatter import build_slack_payload

logger = logging.getLogger("line_handler")


def _log_line_reply_audit(reply_text: str, *, source: str) -> None:
    """B-6 / ops audit: masked reply preview (no full text in logs)."""
    rt = reply_text or ""
    masked = rt[:30] + "..." if len(rt) > 30 else rt
    logger.info(
        "line_reply",
        extra={
            "event": "line_reply",
            "reply_source": source,
            "reply_masked": masked,
            "reply_len": len(rt),
        },
    )


def _get_env(name: str, default: Optional[str] = None) -> str:
    value = os.getenv(name, default)
    if value is None:
        raise RuntimeError(f"Missing environment variable: {name}")
    return value


def _verify_signature(body: bytes, signature: str, channel_secret: str) -> bool:
    mac = hmac.new(channel_secret.encode("utf-8"), body, hashlib.sha256).digest()
    expected = base64.b64encode(mac).decode("utf-8")
    return hmac.compare_digest(expected, signature)


def verify_line_webhook_signature(body: bytes, signature: str) -> bool:
    """True if X-Line-Signature matches body. Used to return HTTP 200 before RAG work."""
    if not signature:
        return False
    try:
        channel_secret = _get_env("LINE_CHANNEL_SECRET")
    except RuntimeError:
        return False
    return _verify_signature(body, signature, channel_secret)


def try_send_fallback_to_events(body: bytes) -> None:
    """Best-effort: parse body and send fallback to all message events with replyToken.
    Used when handle_line_webhook raises so we still attempt a reply before returning 500.
    """
    token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
    if not token:
        logger.warning("try_send_fallback_to_events: LINE_CHANNEL_ACCESS_TOKEN not set, cannot send")
        return
    try:
        payload = json.loads(body.decode("utf-8"))
    except Exception as e:
        logger.warning("try_send_fallback_to_events: invalid body: %s", e)
        return
    events = payload.get("events", [])
    msg = "申し訳ありません。エラーが発生しました。しばらくして再度お試しください。"
    for ev in events:
        if ev.get("type") != "message" or not ev.get("replyToken"):
            continue
        try:
            _reply_to_line(ev["replyToken"], msg, token)
        except Exception as e:
            logger.warning("try_send_fallback_to_events: reply failed: %s", e)


def _reply_to_line(reply_token: str, message: str, channel_access_token: str) -> bool:
    """Send LINE reply. Returns True if HTTP 200 from Reply API."""
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {channel_access_token}",
    }
    payload: Dict[str, Any] = {
        "replyToken": reply_token,
        "messages": [{"type": "text", "text": message}],
    }
    logger.info("reply_start: LINE Reply API")
    try:
        resp = requests.post(
            "https://api.line.me/v2/bot/message/reply",
            headers=headers,
            json=payload,
            timeout=10
        )
        if resp.status_code != 200:
            msg_preview = (payload.get("messages") or [{}])[0].get("text", "")[:200]
            logger.warning(
                "reply_fail: LINE Reply API status=%s body=%s payload_msg_preview=%s",
                resp.status_code, resp.text[:500], msg_preview
            )
            if resp.status_code == 400 and "invalid reply token" in (resp.text or "").lower():
                logger.warning(
                    "Reply token expired (400). Likely cold start or slow RAG. body=%s",
                    resp.text[:300],
                )
            return False
        logger.info("reply_success: LINE Reply API success: reply sent")
        return True
    except Exception as e:
        logger.exception("reply_fail: LINE Reply request failed: %s", e)
        return False


def _publish_line_event(
    line_user_id: str,
    message: str,
    answer_summary: str,
    reply_token: Optional[str] = None,
) -> None:
    """Publish LINE event to Pub/Sub for Slack notification (GCP). No-op if GCP not configured."""
    project_id = os.getenv("GCP_PROJECT_ID", "").strip()
    topic_name = os.getenv("PUBSUB_TOPIC_NAME", "").strip()
    if not project_id or not topic_name:
        return
    try:
        from google.cloud import pubsub_v1
        publisher = pubsub_v1.PublisherClient()
        topic_path = publisher.topic_path(project_id, topic_name)
        payload = {
            "line_user_id": line_user_id,
            "message": message,
            "answer_summary": answer_summary,
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        if reply_token:
            payload["reply_token"] = reply_token
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        publisher.publish(topic_path, data)
        logger.info("Published LINE event to Pub/Sub topic=%s", topic_name)
    except Exception as e:
        logger.warning("Pub/Sub publish skipped: %s", e)


def _urgent_for_fast_path_intent(intent: Optional[str]) -> bool:
    if not intent:
        return False
    return intent in (
        "設備_水漏れ",
        "鍵_紛失",
        "設備_火災警報",
        "防犯_不審者",
    )


def handle_line_webhook(
    body: bytes,
    signature: str,
    skip_verify: bool = False,
) -> Dict[str, Any]:
    try:
        payload = json.loads(body.decode("utf-8"))
    except Exception as e:
        logger.exception("Invalid webhook body: %s", e)
        return {"ok": False, "message": "Invalid body"}
    events = payload.get("events", [])
    logger.info("LINE webhook received body_len=%s events_count=%s", len(body), len(events))
    if not events:
        return {"ok": True, "message": "No events"}

    try:
        channel_secret = _get_env("LINE_CHANNEL_SECRET")
        channel_access_token = _get_env("LINE_CHANNEL_ACCESS_TOKEN")
    except RuntimeError as e:
        logger.exception("Missing env (no reply sent): %s", e)
        return {"ok": False, "message": "Configuration error"}

    if not skip_verify and not _verify_signature(body, signature, channel_secret):
        logger.warning("LINE signature verification failed (no reply sent)")
        return {"ok": False, "message": "Invalid signature"}

    try:
        fallback_message = get_config().fallback_message
        error_message = get_config().fallback_message
    except Exception as e:
        logger.exception("get_config failed, using hardcoded fallback: %s", e)
        fallback_message = error_message = "申し訳ありません。エラーが発生しました。しばらくして再度お試しください。"

    try:
        cfg = get_config()
        from src.contract_query_router import is_contract_source_question
        from src.interfaces.line import clarification_followup as cf
        from src.kb_fast_path import normalize_for_match, try_kb_fast_path
        from src.rag_app_state import get_rag_bundle

        bundle = get_rag_bundle()
        kb_docs = bundle.kb_documents if bundle else None

        for event in events:
            if event.get("type") != "message":
                continue
            message = event.get("message", {})
            if message.get("type") != "text":
                continue

            text = (message.get("text") or "").strip()
            if not text:
                continue

            try:
                from skills.skill_selector import select

                _matched = select(query=text, scope="rental_rag_only")
                if _matched:
                    logger.info(
                        "[SkillSelector] query=%r → %s (triggers=%s)",
                        text,
                        _matched[0]["name"],
                        _matched[0]["matched_triggers"],
                    )
                else:
                    logger.info("[SkillSelector] query=%r → no match", text)
            except Exception as _e:
                logger.warning("[SkillSelector] skipped: %s", _e)

            line_user_id = (event.get("source") or {}).get("userId", "") or "unknown"

            message_id = (message.get("id") or "").strip()
            if not try_begin_message(message_id):
                continue

            reply_token = event.get("replyToken")
            logger.info(
                "Processing LINE message: line_user_id=%s text_preview=%s has_reply_token=%s message_id=%s",
                line_user_id,
                text[:50] if text else "",
                bool(reply_token),
                message_id or "(none)",
            )
            if not reply_token:
                logger.warning("LINE message event has no replyToken; cannot send reply")
                mark_reply_aborted(message_id)
                continue

            # prior_* : auxiliary (instance-local). Same vague short repeat does not relax "short".
            prior = (
                cf.peek_prior_clarification(line_user_id)
                if line_user_id != "unknown"
                else None
            )
            prior_intent = prior.intent if prior else None
            prior_norm = prior.normalized_query if prior else None
            prior_numeric = prior.numeric_queries if prior else None
            resolved = cf.resolve_numeric_clarification_reply(
                text,
                prior_numeric,
                line_user_id=line_user_id,
            )
            effective_text = resolved or text

            # Contract source questions (条文・重説・違約金額 etc.) must bypass KB fast path
            # and reach RAGAnswerer so Master TXT is searched. KB fast path only handles FAQ.
            _is_contract_q = is_contract_source_question(effective_text)
            if not _is_contract_q:
                fp = try_kb_fast_path(
                    effective_text,
                    cfg,
                    kb_docs,
                    prior_clarification_intent=prior_intent,
                    prior_clarification_normalized_query=prior_norm,
                    line_user_id=line_user_id,
                    user_text_for_prior_match=text,
                )
            else:
                from src.kb_fast_path import KBFastPathResult
                fp = KBFastPathResult(kind="miss", match_detail={"reason": "contract_source_bypass"})
            logger.info(
                "routing_decision",
                extra={
                    "event": "routing_decision",
                    "query": text[:200],
                    "contract_source_q": _is_contract_q,
                    "fast_path_kind": fp.kind,
                    "fast_path_intent": fp.intent,
                    "decision_path": (
                        "kb_fast_path" if fp.kind in ("hit", "clarification")
                        else "contract_rag" if _is_contract_q
                        else "rag"
                    ),
                    "line_user_id": line_user_id,
                },
            )
            if fp.kind in ("hit", "clarification"):
                if fp.kind == "clarification":
                    nq = fp.match_detail.get("clarification_numeric_queries") or []
                    cf.record_clarification_intent(
                        line_user_id,
                        fp.intent or "",
                        normalize_for_match(text),
                        nq if isinstance(nq, list) else list(nq),
                    )
                else:
                    cf.clear_clarification_intent(line_user_id)
                from src.interfaces.line.formatter import build_line_message_from_plain_text

                urgent = _urgent_for_fast_path_intent(fp.intent)
                line_message = build_line_message_from_plain_text(fp.text or "", urgent=urgent)
                logger.info("before_reply: KB fast path kind=%s len=%s", fp.kind, len(line_message))
                _log_line_reply_audit(line_message, source="kb_fast_path")
                ok = _reply_to_line(reply_token, line_message, channel_access_token)
                logger.info("after_reply: LINE send attempted ok=%s", ok)
                if ok:
                    mark_reply_success(message_id)
                else:
                    mark_reply_aborted(message_id)
                project_id = os.getenv("GCP_PROJECT_ID", "").strip()
                topic_name = os.getenv("PUBSUB_TOPIC_NAME", "").strip()
                if project_id and topic_name:
                    _publish_line_event(
                        line_user_id=line_user_id,
                        message=text,
                        answer_summary=line_message,
                        reply_token=reply_token,
                    )
                elif os.getenv("SLACK_NOTIFY", "false").lower() == "true":
                    slack_payload = build_slack_payload(
                        sender=line_user_id,
                        question=text,
                        answer=line_message,
                        timestamp=datetime.utcnow(),
                    )
                    post_to_slack(slack_payload)
                continue

            cf.clear_clarification_intent(line_user_id)

            if bundle is None or bundle.rag_answerer is None:
                logger.warning("RAG bundle unavailable (init failed or not started); fallback reply")
                ok = _reply_to_line(reply_token, error_message, channel_access_token)
                if ok:
                    mark_reply_success(message_id)
                else:
                    mark_reply_aborted(message_id)
                continue

            try:
                logger.info("before_reply: RAG answer starting")
                response = bundle.rag_answerer.answer(
                    effective_text,
                    persist_cache=False,
                    prior_clarification_intent=prior_intent,
                    prior_clarification_normalized_query=prior_norm,
                    prior_clarification_numeric_queries=prior_numeric,
                )
            except Exception as e:
                logger.exception("RAG answer failed for query=%s: %s", text[:100], e)
                ok = _reply_to_line(reply_token, error_message, channel_access_token)
                if ok:
                    mark_reply_success(message_id)
                else:
                    mark_reply_aborted(message_id)
                continue

            line_message = fallback_message
            try:
                answer = response.answer if hasattr(response, "answer") else response
                if answer is None:
                    line_message = fallback_message
                    urgent = False
                else:
                    from src.interfaces.line.formatter import build_line_message

                    urgent = bool(getattr(answer, "caveats", None) and "緊急度: high" in (answer.caveats or ""))
                    line_message = build_line_message(answer, urgent=urgent)
            except Exception as e:
                logger.exception("LINE reply build failed for query=%s: %s", text[:100], e)
                line_message = error_message

            logger.info("before_reply: sending LINE text len=%s", len(line_message))
            _log_line_reply_audit(line_message, source="rag_answerer")
            ok = _reply_to_line(reply_token, line_message, channel_access_token)
            logger.info("after_reply: LINE send attempted ok=%s", ok)
            if ok:
                mark_reply_success(message_id)
            else:
                mark_reply_aborted(message_id)

            logger.info("cache_set_start")
            try:
                bundle.query_cache.set(effective_text, response)
            except Exception as e:
                logger.warning("cache set failed, ignored: %s", e)

            project_id = os.getenv("GCP_PROJECT_ID", "").strip()
            topic_name = os.getenv("PUBSUB_TOPIC_NAME", "").strip()
            if project_id and topic_name:
                _publish_line_event(
                    line_user_id=line_user_id,
                    message=text,
                    answer_summary=line_message,
                    reply_token=reply_token,
                )
            elif os.getenv("SLACK_NOTIFY", "false").lower() == "true":
                slack_payload = build_slack_payload(
                    sender=line_user_id,
                    question=text,
                    answer=line_message,
                    timestamp=datetime.utcnow(),
                )
                post_to_slack(slack_payload)

    except Exception as e:
        logger.exception("Unhandled error in handle_line_webhook: %s", e)
        token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
        if token:
            for ev in events:
                if ev.get("type") == "message" and ev.get("replyToken"):
                    _reply_to_line(ev["replyToken"], error_message, token)
        return {"ok": False, "message": str(e)}

    return {"ok": True, "message": "Processed"}
