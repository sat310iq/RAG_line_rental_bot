"""FastAPI app for LINE webhook."""

from __future__ import annotations

import logging
import os
import threading
from contextlib import asynccontextmanager
import uvicorn
from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from src.config import bootstrap_dotenv, load_config
from src.config_summary import log_config_summary
from src.interfaces.line.handler import (
    handle_line_webhook,
    try_send_fallback_to_events,
    verify_line_webhook_signature,
)

# RAG stack is built in lifespan (see rag_app_state.initialize_rag). Imports stay local where
# needed to avoid circular deps; Cloud Run startup waits for lifespan before serving.

bootstrap_dotenv()

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(level=logging.INFO)
    config = load_config()
    if config.rag_skip_startup_checks:
        logger.warning(
            "RAG_SKIP_STARTUP_CHECKS is true: skipping run_startup_checks in lifespan. "
            "Use GET /ready for vector store and RAG dependency checks."
        )
    else:
        from src.startup_check import StartupCheckError, run_startup_checks

        try:
            run_startup_checks(config, probe_embeddings=True)
        except StartupCheckError as e:
            logger.error("Startup check failed: %s", e)
            raise
    log_config_summary(config)
    logger.info("rag_startup_init_begin")
    try:
        from src import rag_app_state

        rag_app_state.initialize_rag(config)
        logger.info("rag_startup_init_complete")
    except Exception:
        logger.exception("rag_startup_init_failed")
        from src import rag_app_state

        rag_app_state.set_init_failed("initialize_rag raised (see logs)")
    yield


app = FastAPI(title="LINE Webhook", lifespan=lifespan)


@app.get("/")
async def root_health():
    """Health check for Cloud Run (legacy path)."""
    return {"status": "ok", "service": "line-webhook"}


@app.get("/health")
async def health():
    """Liveness: process is up. Does not verify vector store or OpenAI (use GET /ready)."""
    return {"status": "ok", "service": "line-webhook"}


@app.get("/ready")
async def ready():
    """Readiness: Chroma/KB paths, RAG bundle, QueryCache probe (see readiness_status_with_rag)."""
    from src.config import get_config
    from src.startup_check import readiness_status_with_rag

    config = get_config()
    ok, msg, details = readiness_status_with_rag(config)
    if not ok:
        return JSONResponse(
            status_code=503,
            content={"status": msg, "details": details},
        )
    return {"status": "ready", "service": "line-webhook"}


@app.get("/debug/config")
async def debug_config():
    """Non-secret config snapshot for local vs Cloud Run comparison (ENABLE_DEBUG_RAG_ENDPOINT=true)."""
    from src.config import get_config
    from src.config_summary import public_config_snapshot

    config = get_config()
    if not config.enable_debug_rag_endpoint:
        return JSONResponse(status_code=404, content={"detail": "debug endpoint disabled"})
    return {"status": "ok", "config": public_config_snapshot(config)}


class RAGDebugBody(BaseModel):
    question: str = Field(..., min_length=1)


@app.post("/debug/rag")
async def debug_rag(body: RAGDebugBody):
    """Optional smoke endpoint; requires ENABLE_DEBUG_RAG_ENDPOINT=true."""
    from src.config import get_config
    from src.query_cache import QueryCache
    from src.rag_answerer import RAGAnswerer
    from src.rag_app_state import get_rag_bundle
    from src.tenant_auth import TenantAuth
    from src.vector_store_manager import VectorStoreManager

    config = get_config()
    if not config.enable_debug_rag_endpoint:
        return JSONResponse(status_code=404, content={"detail": "debug endpoint disabled"})
    bundle = get_rag_bundle()
    if bundle is not None:
        answer = bundle.rag_answerer.answer(body.question, None)
    else:
        tenant_auth = TenantAuth(config)
        vector_store_manager = VectorStoreManager(config)
        query_cache = QueryCache(config)
        rag = RAGAnswerer(config, vector_store_manager, query_cache, tenant_auth)
        answer = rag.answer(body.question, None)
    return {
        "summary": answer.summary,
        "evidence": answer.evidence,
        "next_action": answer.next_action,
        "caveats": answer.caveats,
    }


@app.post("/webhook")
async def line_webhook(
    request: Request,
    x_line_signature: str = Header(default="", alias="X-Line-Signature"),
    skip_verify: bool = False,
):
    """Respond quickly with 200 so LINE does not time out; RAG + Reply API run in a worker thread."""
    body = await request.body()
    if not skip_verify and not verify_line_webhook_signature(body, x_line_signature):
        return JSONResponse(
            status_code=401,
            content={"status": "error", "message": "Invalid signature"},
        )

    def process_line_event() -> None:
        try:
            result = handle_line_webhook(body, "", skip_verify=True)
            if not result.get("ok"):
                logger.warning("LINE webhook handler returned: %s", result)
        except Exception as e:
            logger.exception("LINE webhook background failed: %s", e)
            try_send_fallback_to_events(body)

    # Thread (not Starlette BackgroundTasks): more reliable after HTTP 200 on Cloud Run.
    threading.Thread(
        target=process_line_event,
        name="line-webhook-rag",
        daemon=False,
    ).start()
    return {"status": "ok"}


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8080"))
    uvicorn.run("src.interfaces.line.main:app", host="0.0.0.0", port=port, reload=False)
