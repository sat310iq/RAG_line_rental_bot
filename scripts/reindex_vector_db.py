"""Reindex all vector stores (3 collections) and save BM25 corpora."""

import json
import sys
from pathlib import Path
from langchain_openai import OpenAIEmbeddings
from langchain_chroma import Chroma
from langchain_community.retrievers import BM25Retriever
from langchain_core.documents import Document

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import load_config
from src.document_loader import load_pdf_documents
from src.csv_qa_loader import load_faq_csv, load_ops_log_csv


def save_bm25_corpus(documents: list[Document], output_path: Path) -> None:
    """Save documents for BM25 retriever as JSONL.
    
    Args:
        documents: List of Document objects
        output_path: Path to save JSONL file
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, 'w', encoding='utf-8') as f:
        for doc in documents:
            # Save minimal info needed for BM25
            record = {
                'page_content': doc.page_content,
                'metadata': doc.metadata,
            }
            f.write(json.dumps(record, ensure_ascii=False) + '\n')


def reindex_collection(
    collection_name: str,
    documents: list[Document],
    embeddings: OpenAIEmbeddings,
    persist_directory: Path,
    bm25_corpus_path: Path
) -> int:
    """Reindex a single collection.
    
    Args:
        collection_name: Name of the Chroma collection
        documents: List of Document objects to index
        embeddings: Embeddings model
        persist_directory: ChromaDB persist directory
        bm25_corpus_path: Path to save BM25 corpus
        
    Returns:
        Number of documents indexed
    """
    print(f"\n=== Reindexing {collection_name} ===")
    
    if not documents:
        print(f"No documents to index for {collection_name}")
        return 0
    
    # Delete existing collection if it exists
    try:
        existing_collection = Chroma(
            collection_name=collection_name,
            embedding_function=embeddings,
            persist_directory=str(persist_directory),
        )
        # Try to get count - if it fails, collection doesn't exist
        try:
            count = existing_collection._collection.count()
            if count > 0:
                print(f"Deleting existing collection with {count} documents...")
                # Delete by recreating with same name (Chroma will overwrite)
        except:
            pass
    except:
        pass
    
    # Create new collection
    vector_store = Chroma(
        collection_name=collection_name,
        embedding_function=embeddings,
        persist_directory=str(persist_directory),
    )
    
    # Add documents
    print(f"Adding {len(documents)} documents...")
    vector_store.add_documents(documents)
    
    # Verify count
    count = vector_store._collection.count()
    print(f"Indexed {count} documents in {collection_name}")
    
    # Save BM25 corpus
    print(f"Saving BM25 corpus to {bm25_corpus_path}")
    save_bm25_corpus(documents, bm25_corpus_path)
    
    return count


def main():
    """Main reindexing function."""
    try:
        config = load_config()
    except ValueError as e:
        print(f"Configuration error: {e}", file=sys.stderr)
        sys.exit(1)
    
    print("=== Vector Store Reindexing ===")
    print(f"Vector store path: {config.rag_vector_store_path}")
    print(f"Embedding model: {config.openai_embedding_model}")
    print()
    
    # Initialize embeddings
    embeddings = OpenAIEmbeddings(model=config.openai_embedding_model)
    
    # Prepare paths
    persist_directory = config.get_vector_store_path()
    persist_directory.mkdir(parents=True, exist_ok=True)
    
    bm25_dir = persist_directory / "bm25_corpora"
    bm25_dir.mkdir(parents=True, exist_ok=True)
    
    # Load documents from all sources
    print("Loading documents...")
    
    # PDF documents
    pdf_docs = load_pdf_documents(config)
    print(f"Loaded {len(pdf_docs)} PDF documents")
    
    # FAQ CSV
    faq_docs = load_faq_csv(config)
    print(f"Loaded {len(faq_docs)} FAQ documents")
    
    # Operations log CSV (no tenant filtering during indexing)
    ops_docs = load_ops_log_csv(config, tenant_room=None)
    print(f"Loaded {len(ops_docs)} operations log documents")
    
    # Reindex each collection
    total_docs = 0
    
    # FAQ collection
    faq_count = reindex_collection(
        collection_name="rental_qa_faq",
        documents=faq_docs,
        embeddings=embeddings,
        persist_directory=persist_directory,
        bm25_corpus_path=bm25_dir / "rental_qa_faq.jsonl"
    )
    total_docs += faq_count
    
    # PDF collection
    pdf_count = reindex_collection(
        collection_name="rental_qa_pdf",
        documents=pdf_docs,
        embeddings=embeddings,
        persist_directory=persist_directory,
        bm25_corpus_path=bm25_dir / "rental_qa_pdf.jsonl"
    )
    total_docs += pdf_count
    
    # Operations log collection
    ops_count = reindex_collection(
        collection_name="rental_qa_ops",
        documents=ops_docs,
        embeddings=embeddings,
        persist_directory=persist_directory,
        bm25_corpus_path=bm25_dir / "rental_qa_ops.jsonl"
    )
    total_docs += ops_count
    
    print("\n=== Reindexing Complete ===")
    print(f"Total documents indexed: {total_docs}")
    print(f"  - FAQ: {faq_count}")
    print(f"  - PDF: {pdf_count}")
    print(f"  - Operations Log: {ops_count}")


if __name__ == "__main__":
    main()
