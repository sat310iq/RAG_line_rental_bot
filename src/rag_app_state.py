"""Process-wide RAG bundle (VectorStoreManager, QueryCache, RAGAnswerer) for LINE app."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, List, Optional

from langchain_core.documents import Document

from src.config import Config
from src.kb_fast_path import load_kb_documents_for_fast_path
from src.query_cache import QueryCache
from src.rag_answerer import RAGAnswerer
from src.vector_store_manager import VectorStoreManager

logger = logging.getLogger(__name__)

_bundle: Optional["RAGBundle"] = None
_rag_init_error: Optional[str] = None


@dataclass
class RAGBundle:
    vector_store_manager: VectorStoreManager
    query_cache: QueryCache
    rag_answerer: RAGAnswerer
    kb_documents: List[Document]
    #: Computed once at init (KB mtime + manifest sha); /ready reads this only — no per-probe I/O.
    query_cache_version_snapshot: str = ""


def get_rag_init_error() -> Optional[str]:
    return _rag_init_error


def get_rag_bundle() -> Optional[RAGBundle]:
    return _bundle


def initialize_rag(config: Config) -> RAGBundle:
    """Build RAG stack once. Raises on failure (caller logs rag_startup_init_failed)."""
    global _bundle, _rag_init_error
    _rag_init_error = None
    logger.info("RAG init: VectorStoreManager starting")
    vector_store_manager = VectorStoreManager(config)
    logger.info("RAG init: QueryCache starting")
    query_cache = QueryCache(config)
    query_cache_version_snapshot = query_cache._compute_cache_version()
    logger.info("RAG init: RAGAnswerer starting")
    rag_answerer = RAGAnswerer(config, vector_store_manager, query_cache)
    logger.info("RAG init: loading KB documents for fast path")
    kb_documents = load_kb_documents_for_fast_path(config)
    _bundle = RAGBundle(
        vector_store_manager=vector_store_manager,
        query_cache=query_cache,
        rag_answerer=rag_answerer,
        kb_documents=kb_documents,
        query_cache_version_snapshot=query_cache_version_snapshot,
    )
    logger.info("RAG init: complete")
    return _bundle


def set_init_failed(message: str) -> None:
    global _bundle, _rag_init_error
    _bundle = None
    _rag_init_error = message


def reset_rag_state_for_tests() -> None:
    global _bundle, _rag_init_error
    _bundle = None
    _rag_init_error = None
