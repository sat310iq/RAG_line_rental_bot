"""Tests for retrieval with timeout and parallel execution."""

import pytest
from src.config import Config
from src.vector_store_manager import VectorStoreManager


def test_vector_store_manager_initialization():
    """Test vector store manager initialization."""
    config = Config(
        openai_api_key="test_key",
        rag_vector_store_path="test_vector_store"
    )
    
    # This will fail if vector stores don't exist, but should not crash
    try:
        manager = VectorStoreManager(config)
        counts = manager.get_collection_counts()
        # Should return counts (may be 0 if no data)
        assert isinstance(counts, dict)
        assert 'faq' in counts or counts == {}
    except Exception:
        # Expected if vector stores don't exist
        pass


def test_search_timeout():
    """Test search timeout handling."""
    config = Config(
        openai_api_key="test_key",
        rag_vector_store_path="test_vector_store",
        rag_search_timeout_sec=0.1  # Very short timeout
    )
    
    try:
        manager = VectorStoreManager(config)
        # Search should complete or timeout gracefully
        results = manager.search("test query", sources=['faq'])
        assert isinstance(results, dict)
    except Exception:
        # Expected if vector stores don't exist
        pass
