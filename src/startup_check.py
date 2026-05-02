"""Startup and readiness checks (fail fast in Cloud Run)."""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import List, Tuple

from langchain_chroma import Chroma
from langchain_openai import OpenAIEmbeddings

from src.config import Config
from src.vector_store_manifest import load_vector_store_manifest, manifest_path_for_vector_root

logger = logging.getLogger(__name__)

MIN_PYTHON = (3, 11)


class StartupCheckError(RuntimeError):
    """Fatal misconfiguration or missing data for RAG."""


def assert_python_version() -> None:
    if sys.version_info[:2] < MIN_PYTHON:
        raise StartupCheckError(
            f"Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ required (Cloud Run image uses 3.11); "
            f"got {sys.version_info.major}.{sys.version_info.minor}"
        )


def resolve_project_path(config: Config, p: str) -> Path:
    """Resolve paths relative to cwd (container: /app)."""
    path = Path(p)
    if path.is_absolute():
        return path
    return Path.cwd() / path


def verify_manifest_and_paths(config: Config) -> None:
    vs = resolve_project_path(config, config.rag_vector_store_path)
    if not vs.is_dir():
        raise StartupCheckError(f"Missing vector store directory: {vs}")

    manifest = load_vector_store_manifest(vs)
    mp = manifest_path_for_vector_root(vs)
    if manifest is None:
        raise StartupCheckError(
            f"Missing or unreadable vector store manifest {mp}. Run: python scripts/reindex_vector_db.py"
        )

    kb = resolve_project_path(config, config.kb_csv_path)
    if not kb.is_file():
        raise StartupCheckError(f"Missing KB CSV: {kb}")

    bm25_deal = vs / "bm25_corpora" / "kb_deal_csv.jsonl"
    bm25_master = vs / "bm25_corpora" / "kb_master_pdf.jsonl"
    for p in (bm25_deal, bm25_master):
        if not p.is_file() or p.stat().st_size == 0:
            raise StartupCheckError(f"Missing or empty BM25 corpus: {p}")

    kb_hash = manifest.get("kb_sha256")
    if kb_hash:
        from src.vector_store_manifest import sha256_file

        current = sha256_file(kb)
        if current != kb_hash:
            raise StartupCheckError(
                f"KB SHA256 does not match manifest (run reindex): manifest={kb_hash[:16]}... "
                f"current={current[:16]}... file={kb}"
            )


def probe_chroma_collections(config: Config) -> None:
    """Ensure Chroma collections exist and are non-empty (uses local DB + embedding client init)."""
    vs = resolve_project_path(config, config.rag_vector_store_path)
    persist = str(vs.resolve())
    embeddings = OpenAIEmbeddings(model=config.openai_embedding_model)
    for name in ("kb_deal_csv", "kb_master_pdf"):
        store = Chroma(
            collection_name=name,
            embedding_function=embeddings,
            persist_directory=persist,
        )
        count = store._collection.count()
        if count < 1:
            raise StartupCheckError(f"Chroma collection {name} is empty under {persist}")


def probe_chroma_collections_light(config: Config) -> None:
    """Chroma collections exist and are non-empty via chromadb only (no OpenAI / LangChain Chroma).

    Used by GET /ready so small Cloud Run instances do not OOM from embedding client init.
    Strict startup (run_startup_checks) still uses probe_chroma_collections when enabled.
    """
    import chromadb

    vs = resolve_project_path(config, config.rag_vector_store_path)
    persist = str(vs.resolve())
    client = chromadb.PersistentClient(path=persist)
    names = {c.name for c in client.list_collections()}
    for name in ("kb_deal_csv", "kb_master_pdf"):
        if name not in names:
            raise StartupCheckError(
                f"Chroma collection {name} missing (have {sorted(names)}) under {persist}"
            )
        coll = client.get_collection(name)
        count = coll.count()
        if count < 1:
            raise StartupCheckError(f"Chroma collection {name} is empty under {persist}")


def run_startup_checks(config: Config, *, probe_embeddings: bool = True) -> None:
    """Run all startup validations; raise StartupCheckError on failure."""
    assert_python_version()
    verify_manifest_and_paths(config)
    if probe_embeddings:
        probe_chroma_collections(config)


def readiness_status(config: Config) -> Tuple[bool, str, List[str]]:
    """Return (ok, message, detail lines) without raising."""
    errors: List[str] = []
    try:
        assert_python_version()
    except StartupCheckError as e:
        return False, str(e), [str(e)]

    vs = resolve_project_path(config, config.rag_vector_store_path)
    if not vs.is_dir():
        return False, "not_ready", [f"vector store missing: {vs}"]

    if load_vector_store_manifest(vs) is None:
        return False, "not_ready", [f"manifest missing under {vs}"]

    kb = resolve_project_path(config, config.kb_csv_path)
    if not kb.is_file():
        return False, "not_ready", [f"KB missing: {kb}"]

    try:
        probe_chroma_collections_light(config)
    except Exception as e:
        return False, "not_ready", [f"chroma probe failed: {e}"]

    return True, "ready", []


def readiness_status_with_rag(config: Config) -> Tuple[bool, str, List[str]]:
    """Chroma/KB paths plus RAG bundle from lifespan (QueryCache probe, no extra OpenAI calls)."""
    ok, msg, details = readiness_status(config)
    if not ok:
        logger.info("ready_check_ng base_checks details=%s", details)
        return ok, msg, details

    from src import rag_app_state

    err = rag_app_state.get_rag_init_error()
    if err:
        d = details + [f"rag_init_error: {err}"]
        logger.info("ready_check_ng rag_init_error")
        return False, "not_ready", d

    bundle = rag_app_state.get_rag_bundle()
    if bundle is None or getattr(bundle, "rag_answerer", None) is None:
        logger.info("ready_check_ng rag_bundle_missing")
        return False, "not_ready", details + ["rag_bundle_missing"]

    snap = (getattr(bundle, "query_cache_version_snapshot", None) or "").strip()
    if not snap:
        logger.info("ready_check_ng query_cache_version_snapshot_empty")
        return False, "not_ready", details + ["query_cache_version_snapshot_empty"]

    logger.info("ready_check_ok")
    return True, "ready", details
