"""Vector store manager with Hybrid Retrieval (BM25 + Vector) and RRF Fusion."""

import json
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
from langchain.retrievers import EnsembleRetriever
from src.config import Config


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
        self.faq_vector_store: Optional[Chroma] = None
        self.pdf_vector_store: Optional[Chroma] = None
        self.ops_vector_store: Optional[Chroma] = None
        
        # Initialize BM25 retrievers
        self.faq_bm25: Optional[BM25Retriever] = None
        self.pdf_bm25: Optional[BM25Retriever] = None
        self.ops_bm25: Optional[BM25Retriever] = None
        
        # Load BM25 corpora
        self._load_bm25_retrievers()
        
        # Initialize vector retrievers
        self._initialize_vector_stores()
    
    def _load_bm25_retrievers(self) -> None:
        """Load BM25 retrievers from saved corpora."""
        bm25_dir = self.persist_directory / "bm25_corpora"
        
        # FAQ BM25
        faq_corpus = _load_bm25_corpus(bm25_dir / "rental_qa_faq.jsonl")
        if faq_corpus:
            self.faq_bm25 = BM25Retriever.from_documents(faq_corpus)
            self.faq_bm25.k = self.config.rag_retrieval_k
        
        # PDF BM25
        pdf_corpus = _load_bm25_corpus(bm25_dir / "rental_qa_pdf.jsonl")
        if pdf_corpus:
            self.pdf_bm25 = BM25Retriever.from_documents(pdf_corpus)
            self.pdf_bm25.k = self.config.rag_retrieval_k
        
        # OPS BM25
        ops_corpus = _load_bm25_corpus(bm25_dir / "rental_qa_ops.jsonl")
        if ops_corpus:
            self.ops_bm25 = BM25Retriever.from_documents(ops_corpus)
            self.ops_bm25.k = self.config.rag_retrieval_k
    
    def _initialize_vector_stores(self) -> None:
        """Initialize Chroma vector stores."""
        try:
            self.faq_vector_store = Chroma(
                collection_name="rental_qa_faq",
                embedding_function=self.embeddings,
                persist_directory=str(self.persist_directory),
            )
        except:
            pass
        
        try:
            self.pdf_vector_store = Chroma(
                collection_name="rental_qa_pdf",
                embedding_function=self.embeddings,
                persist_directory=str(self.persist_directory),
            )
        except:
            pass
        
        try:
            self.ops_vector_store = Chroma(
                collection_name="rental_qa_ops",
                embedding_function=self.embeddings,
                persist_directory=str(self.persist_directory),
            )
        except:
            pass
    
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
    
    def _search_collection(
        self,
        query: str,
        collection_name: str,
        vector_store: Optional[Chroma],
        bm25_retriever: Optional[BM25Retriever]
    ) -> List[Document]:
        """Search a single collection with timeout.
        
        Args:
            query: Search query
            collection_name: Name of collection
            vector_store: Chroma vector store
            bm25_retriever: BM25 retriever
            timeout: Timeout in seconds
            
        Returns:
            List of retrieved Document objects
        """
        try:
            hybrid_retriever = self._create_hybrid_retriever(
                vector_store, bm25_retriever, collection_name
            )
            
            if not hybrid_retriever:
                return []
            
            # Execute retrieval with timeout
            start_time = time.time()
            results = hybrid_retriever.get_relevant_documents(query)
            elapsed = time.time() - start_time
            
            if elapsed > self.config.rag_search_timeout_sec:
                print(f"Warning: {collection_name} search took {elapsed:.2f}s (timeout: {self.config.rag_search_timeout_sec}s)")
            
            return results
            
        except Exception as e:
            print(f"Error searching {collection_name}: {e}")
            return []
    
    def search(
        self,
        query: str,
        sources: Optional[List[str]] = None
    ) -> Dict[str, List[Document]]:
        """Search across collections in parallel.
        
        Args:
            query: Search query
            sources: List of source types to search ('faq', 'pdf', 'ops').
                    If None, search all sources.
            
        Returns:
            Dictionary mapping source names to lists of Document objects
        """
        if sources is None:
            sources = ['faq', 'pdf', 'ops']
        
        results: Dict[str, List[Document]] = {}
        
        # Execute searches in parallel with timeout
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = {}
            
            if 'faq' in sources:
                futures['faq'] = executor.submit(
                    self._search_collection,
                    query,
                    'faq',
                    self.faq_vector_store,
                    self.faq_bm25
                )
            
            if 'pdf' in sources:
                futures['pdf'] = executor.submit(
                    self._search_collection,
                    query,
                    'pdf',
                    self.pdf_vector_store,
                    self.pdf_bm25
                )
            
            if 'ops' in sources:
                futures['ops'] = executor.submit(
                    self._search_collection,
                    query,
                    'ops',
                    self.ops_vector_store,
                    self.ops_bm25
                )
            
            # Collect results with timeout
            for source, future in futures.items():
                try:
                    docs = future.result(timeout=self.config.rag_search_timeout_sec)
                    results[source] = docs
                except FutureTimeoutError:
                    print(f"Timeout searching {source} collection")
                    results[source] = []
                except Exception as e:
                    print(f"Error retrieving from {source}: {e}")
                    results[source] = []
        
        # Deduplicate results
        for source in results:
            results[source] = _deduplicate_documents(results[source])
        
        return results
    
    def get_collection_counts(self) -> Dict[str, int]:
        """Get document counts for each collection.
        
        Returns:
            Dictionary mapping collection names to counts
        """
        counts = {}
        
        try:
            if self.faq_vector_store:
                counts['faq'] = self.faq_vector_store._collection.count()
        except:
            counts['faq'] = 0
        
        try:
            if self.pdf_vector_store:
                counts['pdf'] = self.pdf_vector_store._collection.count()
        except:
            counts['pdf'] = 0
        
        try:
            if self.ops_vector_store:
                counts['ops'] = self.ops_vector_store._collection.count()
        except:
            counts['ops'] = 0
        
        return counts
