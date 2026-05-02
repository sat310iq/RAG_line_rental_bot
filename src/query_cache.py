"""Query result caching with semantic similarity matching."""

import logging
import threading
import time
import hashlib
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
from pathlib import Path
import numpy as np
from src.config import Config
from src.vector_store_manifest import load_vector_store_manifest

logger = logging.getLogger(__name__)

# --- Process-wide singleton SentenceTransformer (thread-safe one-time load) ---
_shared_st_model: Any = None
_shared_st_lock = threading.Lock()
_shared_st_failed = False
_cache_embed_skip_logged = False


def _get_shared_sentence_transformer() -> Optional[Any]:
    """Load paraphrase-multilingual-MiniLM-L12-v2 at most once per process; never reload."""
    global _shared_st_model, _shared_st_failed
    if _shared_st_failed:
        return None
    if _shared_st_model is not None:
        return _shared_st_model
    with _shared_st_lock:
        if _shared_st_failed:
            return None
        if _shared_st_model is not None:
            return _shared_st_model
        try:
            from sentence_transformers import SentenceTransformer

            logger.info("Loading shared SentenceTransformer singleton (one-time)")
            _shared_st_model = SentenceTransformer(
                "paraphrase-multilingual-MiniLM-L12-v2"
            )
        except Exception as e:
            logger.warning("Could not load shared SentenceTransformer: %s", e)
            _shared_st_failed = True
            return None
        return _shared_st_model


@dataclass
class CacheEntry:
    """Cache entry with timestamp and result."""
    query_hash: str
    query_embedding: np.ndarray
    result: Any
    timestamp: float
    ttl: float
    version: str


class QueryCache:
    """Query result cache with semantic similarity matching."""

    def __init__(self, config: Config):
        """Initialize query cache.

        Args:
            config: Application configuration
        """
        self.config = config
        self.enabled = config.enable_query_cache
        self.ttl_sec = config.cache_ttl_sec
        self.exact_ttl_sec = config.cache_exact_ttl_sec
        self.semantic_ttl_sec = config.cache_semantic_ttl_sec
        self.semantic_threshold = config.cache_semantic_threshold

        # Cache storage
        self._cache: Dict[str, CacheEntry] = {}

        # Cache version (invalidate when KB changes)
        self._cache_version = self._compute_cache_version()

        # Legacy flags kept for tests / introspection; loading uses process singleton above.
        self._similarity_model_failed = False

    def _get_similarity_model(self) -> Any:
        """Return shared model or None (singleton load at most once)."""
        if not self.enabled:
            return None
        m = _get_shared_sentence_transformer()
        if m is None:
            self._similarity_model_failed = True
        return m

    @property
    def similarity_model(self) -> Any:
        """Backward-compatible access; prefer _get_similarity_model()."""
        return self._get_similarity_model()

    def _hash_query(self, query: str) -> str:
        """Generate hash for query.

        Args:
            query: Query string

        Returns:
            Hash string
        """
        versioned_query = f"{self._cache_version}|{query}"
        return hashlib.sha256(versioned_query.encode("utf-8")).hexdigest()

    def get_kb_version_key(self) -> str:
        """Build a version key from KB sources for cache invalidation."""

        def safe_mtime(path: Path) -> str:
            try:
                if path.exists():
                    return str(path.stat().st_mtime)
            except Exception:
                pass
            return "0"

        kb_path = Path(self.config.kb_csv_path)
        # Future: extend with additional KB paths (e.g., special clauses CSV)
        return safe_mtime(kb_path)

    def _compute_cache_version(self) -> str:
        """Compute a version string: KB mtime + manifest kb_sha256 (aligns with reindex)."""
        mtime_key = self.get_kb_version_key()
        vs = Path(self.config.rag_vector_store_path)
        if not vs.is_absolute():
            vs = Path.cwd() / vs
        manifest = load_vector_store_manifest(vs)
        sha = (manifest or {}).get("kb_sha256") or ""
        short = sha[:24] if sha else "none"
        return f"{mtime_key}|{short}"

    def _refresh_cache_version(self) -> None:
        """Refresh cache version and clear cache if KB changed."""
        new_version = self._compute_cache_version()
        if new_version != self._cache_version:
            self._cache_version = new_version
            self.clear()

    def _embed_query(self, query: str) -> Optional[np.ndarray]:
        """Generate embedding for query."""
        model = self._get_similarity_model()
        if not model:
            return None

        try:
            return model.encode(query, convert_to_numpy=True)
        except Exception as e:
            logger.warning("Could not embed query: %s", e)
            return None

    def _embed_query_if_loaded(self, query: str) -> Optional[np.ndarray]:
        """Encode only if singleton already loaded — never triggers load (safe for cache SET)."""
        global _cache_embed_skip_logged
        model = _shared_st_model
        if model is None:
            if not _cache_embed_skip_logged:
                logger.info("cache_set_skipped: embedding (similarity model not loaded)")
                _cache_embed_skip_logged = True
            return None
        try:
            return model.encode(query, convert_to_numpy=True)
        except Exception as e:
            logger.warning("cache_set_embed failed (ignored): %s", e)
            return None

    def _cosine_similarity(self, vec1: np.ndarray, vec2: np.ndarray) -> float:
        """Calculate cosine similarity between two vectors."""
        dot_product = np.dot(vec1, vec2)
        norm1 = np.linalg.norm(vec1)
        norm2 = np.linalg.norm(vec2)

        if norm1 == 0 or norm2 == 0:
            return 0.0

        return dot_product / (norm1 * norm2)

    def _cleanup_expired(self) -> None:
        """Remove expired cache entries."""
        current_time = time.time()
        expired_keys = [
            key for key, entry in self._cache.items()
            if current_time - entry.timestamp > entry.ttl
        ]
        for key in expired_keys:
            del self._cache[key]

    def get_exact(self, query: str) -> Optional[Any]:
        """Get cached result by exact hash match only."""
        if not self.enabled:
            return None

        self._refresh_cache_version()
        self._cleanup_expired()
        query_hash = self._hash_query(query)
        if query_hash in self._cache:
            entry = self._cache[query_hash]
            if entry.version == self._cache_version and time.time() - entry.timestamp <= entry.ttl:
                print(f"[DEBUG] Cache hit (exact, kb_version={self._cache_version})")
                return entry.result
        return None

    def get_semantic(self, query: str, similarity_threshold: Optional[float] = None) -> Optional[Any]:
        """Get cached result by semantic similarity only."""
        if not self.enabled:
            return None
        self._refresh_cache_version()
        self._cleanup_expired()
        threshold = similarity_threshold if similarity_threshold is not None else self.semantic_threshold
        if not self._cache:
            return None
        if self._get_similarity_model():
            query_embedding = self._embed_query(query)
            if query_embedding is not None:
                best_match: Optional[CacheEntry] = None
                best_similarity = 0.0

                for entry in self._cache.values():
                    if entry.version != self._cache_version:
                        continue
                    if time.time() - entry.timestamp > entry.ttl:
                        continue

                    if entry.query_embedding is not None:
                        similarity = self._cosine_similarity(
                            query_embedding,
                            entry.query_embedding
                        )

                        if similarity > best_similarity and similarity >= threshold:
                            best_similarity = similarity
                            best_match = entry

                if best_match:
                    print(f"[DEBUG] Cache hit (semantic, similarity={best_similarity:.2f}, kb_version={self._cache_version})")
                    return best_match.result
        return None

    def get(
        self,
        query: str,
        similarity_threshold: Optional[float] = None,
        allow_semantic: bool = True,
    ) -> Optional[Any]:
        """Get cached result (exact first, then semantic when allowed)."""
        exact = self.get_exact(query)
        if exact is not None:
            return exact
        if not allow_semantic:
            return None
        return self.get_semantic(query, similarity_threshold=similarity_threshold)

    def set(self, query: str, result: Any, ttl: Optional[float] = None, include_embedding: bool = True) -> None:
        """Cache query result. Lightweight: never loads SentenceTransformer; embed only if already loaded."""
        if not self.enabled:
            return

        self._refresh_cache_version()

        query_hash = self._hash_query(query)
        # Never call _get_similarity_model() here — that could load the model after LINE reply
        # and cause OOM under parallel requests.
        query_embedding = self._embed_query_if_loaded(query) if include_embedding else None
        effective_ttl = ttl if ttl is not None else (self.semantic_ttl_sec if include_embedding else self.exact_ttl_sec)

        entry = CacheEntry(
            query_hash=query_hash,
            query_embedding=query_embedding,
            result=result,
            timestamp=time.time(),
            ttl=effective_ttl,
            version=self._cache_version,
        )

        self._cache[query_hash] = entry

    def clear(self) -> None:
        """Clear all cache entries."""
        self._cache.clear()

    def size(self) -> int:
        """Get number of cache entries."""
        self._cleanup_expired()
        return len(self._cache)
