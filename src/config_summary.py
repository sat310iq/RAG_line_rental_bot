"""Structured startup logging for local vs Cloud Run diff comparison."""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict

from src.config import Config, get_env_bootstrap_meta
from src.vector_store_manifest import load_vector_store_manifest

logger = logging.getLogger(__name__)


def public_config_snapshot(config: Config) -> Dict[str, Any]:
    """Safe dict for /debug/config and ops logs (no secret values)."""
    return _redact_config_snapshot(config)


def _redact_config_snapshot(config: Config) -> Dict[str, Any]:
    return {
        "openai_model": config.openai_model,
        "openai_embedding_model": config.openai_embedding_model,
        "rag_retrieval_k": config.rag_retrieval_k,
        "rag_rerank_candidates": config.rag_rerank_candidates,
        "rag_rerank_top_n": config.rag_rerank_top_n,
        "csv_score_threshold": config.csv_score_threshold,
        "pdf_score_threshold": config.pdf_score_threshold,
        "rag_vector_store_path": config.rag_vector_store_path,
        "kb_csv_path": config.kb_csv_path,
        "enable_query_cache": config.enable_query_cache,
        "OPENAI_API_KEY": "SET" if config.openai_api_key else "UNSET",
        "COMET_API_KEY": "SET" if config.comet_api_key else "UNSET",
        "LINE_CHANNEL_SECRET": "SET" if os.getenv("LINE_CHANNEL_SECRET") else "UNSET",
        "LINE_CHANNEL_ACCESS_TOKEN": "SET" if os.getenv("LINE_CHANNEL_ACCESS_TOKEN") else "UNSET",
        "ENABLE_DEBUG_RAG_ENDPOINT": config.enable_debug_rag_endpoint,
        "RAG_SKIP_STARTUP_CHECKS": config.rag_skip_startup_checks,
    }


def log_config_summary(config: Config, *, service: str = "line-webhook") -> Dict[str, Any]:
    """Emit one JSON log line for ops (no secret values)."""
    vs = Path(config.rag_vector_store_path)
    if not vs.is_absolute():
        vs = Path.cwd() / vs
    manifest = load_vector_store_manifest(vs)

    payload: Dict[str, Any] = {
        "event": "config_summary",
        "service": service,
        "python_version": sys.version,
        "runtime_cwd": str(Path.cwd()),
        "env_source": get_env_bootstrap_meta(),
        "config": _redact_config_snapshot(config),
        "manifest": manifest,
    }
    logger.info("CONFIG_SUMMARY %s", json.dumps(payload, ensure_ascii=False))
    return payload
