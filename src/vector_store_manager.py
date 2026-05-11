"""Vector store manager with Hybrid Retrieval (BM25 + Vector) and RRF Fusion."""

import json
import logging
import re
import time
from datetime import date, datetime
from pathlib import Path
from typing import List, Dict, Optional, Set, Any
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from langchain_openai import OpenAIEmbeddings
from langchain_chroma import Chroma
from langchain_community.retrievers import BM25Retriever
from langchain_core.retrievers import BaseRetriever
from langchain_core.documents import Document
from langchain_classic.retrievers import EnsembleRetriever
from src.config import Config
from src.utils.doc_id import doc_key
from src.vector_store_manifest import load_vector_store_manifest

logger = logging.getLogger(__name__)


class VectorStoreCollectionError(RuntimeError):
    """Raised when a required Chroma collection is missing or unreadable."""


def _invoke_retriever(retriever: Any, query: str) -> List[Document]:
    """LangChain 1.x retrievers expose invoke(); legacy get_relevant_documents is gone."""
    docs = retriever.invoke(query)
    if docs is None:
        return []
    if isinstance(docs, list):
        return docs
    return [docs]


def _load_bm25_corpus(corpus_path: Path) -> List[Document]:
    """Load BM25 corpus from JSONL file.
    
    Args:
        corpus_path: Path to JSONL file
        
    Returns:
        List of Document objects
    """
    if not corpus_path.exists():
        return []
    
    documents = []
    with open(corpus_path, 'r', encoding='utf-8') as f:
        for line in f:
            record = json.loads(line)
            doc = Document(
                page_content=record['page_content'],
                metadata=record.get('metadata', {})
            )
            documents.append(doc)
    
    return documents


def _deduplicate_documents(documents: List[Document]) -> List[Document]:
    """Remove duplicate documents based on stable_id or content hash.
    
    Args:
        documents: List of Document objects
        
    Returns:
        Deduplicated list of Document objects
    """
    seen: Set[str] = set()
    unique_docs = []
    
    for doc in documents:
        # Try stable_id first
        stable_id = doc.metadata.get('stable_id')
        if stable_id:
            if stable_id in seen:
                continue
            seen.add(stable_id)
            unique_docs.append(doc)
            continue
        
        # Fallback to content hash
        content_hash = hash(doc.page_content)
        if content_hash in seen:
            continue
        seen.add(content_hash)
        unique_docs.append(doc)
    
    return unique_docs


def _doc_key(doc: Document) -> str:
    """Create a stable key for matching documents across retrievers."""
    return doc_key(doc)


def _score_from_distance(distance: float) -> float:
    """Convert distance to similarity score (0-1, higher is better)."""
    if distance is None:
        return 0.0
    return 1.0 / (1.0 + max(distance, 0.0))


def _keyword_score(query: str, keywords: str) -> float:
    """Compute simple keyword match score (0-1)."""
    if not keywords:
        return 0.0
    tokens = [token for token in re.split(r"[\s|]+", keywords) if token]
    if not tokens:
        return 0.0
    matches = sum(1 for token in tokens if token in query)
    return matches / max(1, len(tokens))


def is_effective(metadata: Dict[str, Any], today: Optional[date] = None) -> bool:
    """Check if document is effective based on effective_from/to dates.
    
    Rules:
    - effective_from > today → False (exclude)
    - effective_to < today → False (exclude)
    - None → True (always effective)
    
    Args:
        metadata: Document metadata dictionary
        today: Current date (defaults to today if None)
        
    Returns:
        True if document is currently effective, False otherwise
    """
    if today is None:
        today = date.today()
    
    # Parse effective_from
    effective_from_str = metadata.get('effective_from')
    if effective_from_str:
        try:
            if isinstance(effective_from_str, str):
                effective_from = datetime.strptime(effective_from_str, "%Y-%m-%d").date()
            else:
                effective_from = effective_from_str
            if effective_from > today:
                return False  # Not yet effective
        except (ValueError, TypeError):
            pass  # Invalid date, ignore
    
    # Parse effective_to
    effective_to_str = metadata.get('effective_to')
    if effective_to_str:
        try:
            if isinstance(effective_to_str, str):
                effective_to = datetime.strptime(effective_to_str, "%Y-%m-%d").date()
            else:
                effective_to = effective_to_str
            if effective_to < today:
                return False  # Expired
        except (ValueError, TypeError):
            pass  # Invalid date, ignore
    
    return True  # Effective (no date restrictions or within range)


def filter_effective_documents(documents: List[Document], today: Optional[date] = None) -> List[Document]:
    """Filter documents to only include those that are currently effective.
    
    Args:
        documents: List of Document objects
        today: Current date (defaults to today if None)
        
    Returns:
        Filtered list of effective documents
    """
    if today is None:
        today = date.today()
    
    return [doc for doc in documents if is_effective(doc.metadata, today)]


class VectorStoreManager:
    """Manages vector stores and hybrid retrieval."""
    
    def __init__(self, config: Config):
        """Initialize vector store manager.
        
        Args:
            config: Application configuration
        """
        self.config = config
        self.embeddings = OpenAIEmbeddings(model=config.openai_embedding_model)
        self.persist_directory = config.get_vector_store_path()
        
        # Initialize vector stores
        self.deal_vector_store: Optional[Chroma] = None
        self.master_vector_store: Optional[Chroma] = None
        
        # Initialize BM25 retrievers
        self.deal_bm25: Optional[BM25Retriever] = None
        self.master_bm25: Optional[BM25Retriever] = None
        
        # Load BM25 corpora
        self._load_bm25_retrievers()
        
        # Initialize vector retrievers
        self._initialize_vector_stores()
        # Log document counts for troubleshooting (e.g. empty store on Cloud Run)
        try:
            counts = self.get_collection_counts()
            manifest = load_vector_store_manifest(self.persist_directory)
            kb_sha = (manifest or {}).get("kb_sha256") or ""
            kb_short = kb_sha[:16] + "..." if len(kb_sha) > 16 else kb_sha
            logger.info(
                "Vector store initialized: deal=%s master=%s path=%s manifest_kb_sha256=%s",
                counts.get("deal", 0),
                counts.get("master", 0),
                self.persist_directory,
                kb_short or "none",
            )
            if counts.get("deal", 0) == 0 and counts.get("master", 0) == 0:
                logger.warning(
                    "Vector store has 0 documents. Run reindex before deploy: python scripts/reindex_vector_db.py"
                )
        except Exception as e:
            logger.warning("Could not get collection counts: %s", e)

    def _load_bm25_retrievers(self) -> None:
        """Load BM25 retrievers from saved corpora."""
        bm25_dir = self.persist_directory / "bm25_corpora"
        
        # Deal CSV BM25
        deal_corpus = _load_bm25_corpus(bm25_dir / "kb_deal_csv.jsonl")
        if deal_corpus:
            self.deal_bm25 = BM25Retriever.from_documents(deal_corpus)
            self.deal_bm25.k = self.config.rag_retrieval_k
        
        # Master PDF BM25
        master_corpus = _load_bm25_corpus(bm25_dir / "kb_master_pdf.jsonl")
        if master_corpus:
            self.master_bm25 = BM25Retriever.from_documents(master_corpus)
            self.master_bm25.k = self.config.rag_retrieval_k
        
    
    def _initialize_vector_stores(self) -> None:
        """Initialize Chroma vector stores."""
        try:
            self.deal_vector_store = Chroma(
                collection_name="kb_deal_csv",
                embedding_function=self.embeddings,
                persist_directory=str(self.persist_directory),
            )
        except Exception as e:
            logger.exception("Failed to initialize deal Chroma (kb_deal_csv): %s", e)
            self.deal_vector_store = None

        try:
            self.master_vector_store = Chroma(
                collection_name="kb_master_pdf",
                embedding_function=self.embeddings,
                persist_directory=str(self.persist_directory),
            )
        except Exception as e:
            logger.exception("Failed to initialize master Chroma (kb_master_pdf): %s", e)
            self.master_vector_store = None

    def healthcheck_collections(self) -> None:
        """Verify Chroma collections exist and are readable; raise if not."""
        import chromadb

        path = self.persist_directory.resolve()
        if not path.is_dir():
            raise VectorStoreCollectionError(f"Vector store directory missing: {path}")
        client = chromadb.PersistentClient(path=str(path))
        names = {c.name for c in client.list_collections()}
        missing = [n for n in ("kb_deal_csv", "kb_master_pdf") if n not in names]
        if missing:
            raise VectorStoreCollectionError(
                f"Missing Chroma collections {missing}; have {sorted(names)} at {path}"
            )
        
    
    def _create_hybrid_retriever(
        self,
        vector_store: Optional[Chroma],
        bm25_retriever: Optional[BM25Retriever],
        collection_name: str
    ) -> Optional[EnsembleRetriever]:
        """Create hybrid retriever (BM25 + Vector) using EnsembleRetriever.
        
        Args:
            vector_store: Chroma vector store
            bm25_retriever: BM25 retriever
            collection_name: Name of collection (for error messages)
            
        Returns:
            EnsembleRetriever if both retrievers are available, None otherwise
        """
        retrievers = []
        
        if bm25_retriever:
            retrievers.append(bm25_retriever)
        
        if vector_store:
            vector_retriever = vector_store.as_retriever(
                search_kwargs={"k": self.config.rag_retrieval_k}
            )
            retrievers.append(vector_retriever)
        
        if len(retrievers) == 0:
            return None
        
        if len(retrievers) == 1:
            # Only one retriever available, return it wrapped
            return retrievers[0]
        
        # Use EnsembleRetriever for RRF fusion
        return EnsembleRetriever(
            retrievers=retrievers,
            weights=[0.5, 0.5]  # Equal weights for BM25 and Vector
        )
    
    def _search_collection_scored(
        self,
        query: str,
        collection_name: str,
        vector_store: Optional[Chroma],
        bm25_retriever: Optional[BM25Retriever]
    ) -> List[Dict[str, Any]]:
        """Search a single collection and return scored documents."""
        scored_map: Dict[str, Dict[str, Any]] = {}
        
        # Vector search with scores
        if vector_store:
            try:
                vector_results = vector_store.similarity_search_with_score(
                    query,
                    k=self.config.rag_retrieval_k
                )
                for doc, distance in vector_results:
                    key = _doc_key(doc)
                    score = _score_from_distance(distance)
                    scored_map[key] = {
                        "document": doc,
                        "score": score,
                        "source": collection_name,
                        "retriever": "vector",
                    }
            except Exception as e:
                logger.error("rag_search_error collection=%s retriever=vector error=%s", collection_name, e)

        # BM25 search (keyword score)
        if bm25_retriever:
            try:
                bm25_docs = _invoke_retriever(bm25_retriever, query)
                for doc in bm25_docs:
                    key = _doc_key(doc)
                    bm25_score = _keyword_score(query, doc.metadata.get("keywords", ""))
                    existing = scored_map.get(key)
                    if existing:
                        # Keep higher score
                        if bm25_score > existing["score"]:
                            existing["score"] = bm25_score
                            existing["retriever"] = "bm25"
                    else:
                        scored_map[key] = {
                            "document": doc,
                            "score": bm25_score,
                            "source": collection_name,
                            "retriever": "bm25",
                        }
            except Exception as e:
                logger.error("rag_search_error collection=%s retriever=bm25 error=%s", collection_name, e)
        
        scored_list = list(scored_map.values())
        scored_list.sort(key=lambda x: x["score"], reverse=True)
        return scored_list
    
    def search(
        self,
        query: str,
        sources: Optional[List[str]] = None
    ) -> Dict[str, List[Document]]:
        """Search across collections in parallel.
        
        Args:
            query: Search query
            sources: List of source types to search ('deal', 'master').
                    If None, search all sources.
            
        Returns:
            Dictionary mapping source names to lists of Document objects
        """
        if sources is None:
            sources = ['deal', 'master']
        
        results: Dict[str, List[Dict[str, Any]]] = {}
        timeout = self.config.rag_search_timeout_sec

        # Execute searches in parallel with timeout
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures: Dict[str, Any] = {}
            start_times: Dict[str, float] = {}

            if 'deal' in sources:
                start_times['deal'] = time.time()
                futures['deal'] = executor.submit(
                    self._search_collection_scored,
                    query,
                    'deal',
                    self.deal_vector_store,
                    self.deal_bm25
                )

            if 'master' in sources:
                start_times['master'] = time.time()
                futures['master'] = executor.submit(
                    self._search_collection_scored,
                    query,
                    'master',
                    self.master_vector_store,
                    self.master_bm25
                )

            # Collect results with per-source timeout
            for source, future in futures.items():
                elapsed = time.time() - start_times[source]
                remaining = max(timeout - elapsed, 0.0)
                try:
                    docs = future.result(timeout=remaining if remaining > 0 else timeout)
                    results[source] = docs
                    logger.debug("rag_search_ok collection=%s docs=%d", source, len(docs))
                except FutureTimeoutError:
                    elapsed_total = time.time() - start_times[source]
                    logger.warning(
                        "rag_search_timeout collection=%s timeout_sec=%.1f elapsed_sec=%.2f",
                        source, timeout, elapsed_total,
                    )
                    results[source] = []
                except Exception as e:
                    logger.error("rag_search_error collection=%s error=%s", source, e)
                    results[source] = []
        
        # Deduplicate results
        for source in results:
            # Deduplicate by document key, keep highest score
            deduped: Dict[str, Dict[str, Any]] = {}
            for item in results[source]:
                doc = item["document"]
                key = _doc_key(doc)
                existing = deduped.get(key)
                if not existing or item["score"] > existing["score"]:
                    deduped[key] = item
            results[source] = list(deduped.values())
            results[source].sort(key=lambda x: x["score"], reverse=True)
        
        return results
    
    def get_collection_counts(self) -> Dict[str, int]:
        """Get document counts for each collection.
        
        Returns:
            Dictionary mapping collection names to counts
        """
        counts = {}
        
        try:
            if self.deal_vector_store:
                counts['deal'] = self.deal_vector_store._collection.count()
            else:
                counts['deal'] = 0
        except Exception:
            counts['deal'] = 0

        try:
            if self.master_vector_store:
                counts['master'] = self.master_vector_store._collection.count()
            else:
                counts['master'] = 0
        except Exception:
            counts['master'] = 0
        
        return counts
