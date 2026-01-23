"""Query result caching with semantic similarity matching."""

import time
import hashlib
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
from sentence_transformers import SentenceTransformer
import numpy as np
from src.config import Config


@dataclass
class CacheEntry:
    """Cache entry with timestamp and result."""
    query_hash: str
    query_embedding: np.ndarray
    result: Any
    timestamp: float
    ttl: float


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
        
        # Cache storage
        self._cache: Dict[str, CacheEntry] = {}
        
        # Initialize sentence transformer for semantic similarity
        if self.enabled:
            try:
                # Use a lightweight model for similarity matching
                self.similarity_model = SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')
            except Exception as e:
                print(f"Warning: Could not load similarity model: {e}")
                print("Cache will use exact hash matching only.")
                self.similarity_model = None
        else:
            self.similarity_model = None
    
    def _hash_query(self, query: str) -> str:
        """Generate hash for query.
        
        Args:
            query: Query string
            
        Returns:
            Hash string
        """
        return hashlib.sha256(query.encode('utf-8')).hexdigest()
    
    def _embed_query(self, query: str) -> Optional[np.ndarray]:
        """Generate embedding for query.
        
        Args:
            query: Query string
            
        Returns:
            Embedding vector or None if model not available
        """
        if not self.similarity_model:
            return None
        
        try:
            return self.similarity_model.encode(query, convert_to_numpy=True)
        except Exception as e:
            print(f"Warning: Could not embed query: {e}")
            return None
    
    def _cosine_similarity(self, vec1: np.ndarray, vec2: np.ndarray) -> float:
        """Calculate cosine similarity between two vectors.
        
        Args:
            vec1: First vector
            vec2: Second vector
            
        Returns:
            Cosine similarity score (0-1)
        """
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
    
    def get(self, query: str, similarity_threshold: float = 0.85) -> Optional[Any]:
        """Get cached result for query.
        
        Args:
            query: Query string
            similarity_threshold: Minimum similarity score for cache hit (0-1)
            
        Returns:
            Cached result if found, None otherwise
        """
        if not self.enabled:
            return None
        
        # Cleanup expired entries
        self._cleanup_expired()
        
        # Try exact match first
        query_hash = self._hash_query(query)
        if query_hash in self._cache:
            entry = self._cache[query_hash]
            if time.time() - entry.timestamp <= entry.ttl:
                return entry.result
        
        # Try semantic similarity match
        if self.similarity_model:
            query_embedding = self._embed_query(query)
            if query_embedding is not None:
                best_match: Optional[CacheEntry] = None
                best_similarity = 0.0
                
                for entry in self._cache.values():
                    if time.time() - entry.timestamp > entry.ttl:
                        continue
                    
                    if entry.query_embedding is not None:
                        similarity = self._cosine_similarity(
                            query_embedding,
                            entry.query_embedding
                        )
                        
                        if similarity > best_similarity and similarity >= similarity_threshold:
                            best_similarity = similarity
                            best_match = entry
                
                if best_match:
                    return best_match.result
        
        return None
    
    def set(self, query: str, result: Any, ttl: Optional[float] = None) -> None:
        """Cache query result.
        
        Args:
            query: Query string
            result: Result to cache
            ttl: Time to live in seconds (uses config default if None)
        """
        if not self.enabled:
            return
        
        query_hash = self._hash_query(query)
        query_embedding = self._embed_query(query) if self.similarity_model else None
        
        entry = CacheEntry(
            query_hash=query_hash,
            query_embedding=query_embedding,
            result=result,
            timestamp=time.time(),
            ttl=ttl if ttl is not None else self.ttl_sec
        )
        
        self._cache[query_hash] = entry
    
    def clear(self) -> None:
        """Clear all cache entries."""
        self._cache.clear()
    
    def size(self) -> int:
        """Get number of cache entries.
        
        Returns:
            Number of entries in cache
        """
        self._cleanup_expired()
        return len(self._cache)
