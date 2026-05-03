"""Reindex all vector stores (2 collections) and save BM25 corpora."""

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
from src.document_loader import load_txt_documents
from src.kb_loader import load_kb_csv
from src.vector_store_manifest import write_vector_store_manifest


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
        try:
            count = existing_collection._collection.count()
            if count > 0:
                print(f"Deleting existing collection with {count} documents...")
                existing_collection.delete_collection()
        except Exception:
            pass
    except Exception:
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
    
    # Master corpus from TXT only (no PDF ingestion)
    txt_docs = load_txt_documents(config)
    print(f"Loaded {len(txt_docs)} TXT documents")
    
    # Knowledge base CSV (15-column schema)
    try:
        kb_docs = load_kb_csv(config)
        print(f"Loaded {len(kb_docs)} KB documents")
    except ValueError as e:
        print(f"Error loading KB CSV: {e}")
        print("Falling back to legacy FAQ CSV...")
        from src.csv_qa_loader import load_faq_csv
        legacy_path = config.get_faq_csv_path()
        if not legacy_path.is_file():
            print(
                f"Legacy FAQ CSV not found: {legacy_path}. "
                "Set FAQ_CSV_PATH to an existing file or fix KB_CSV_PATH.",
                file=sys.stderr,
            )
            sys.exit(1)
        kb_docs = load_faq_csv(config)
        if not kb_docs:
            print(
                f"Legacy FAQ CSV loaded 0 documents: {legacy_path}. "
                "Abort to avoid creating an empty deal index.",
                file=sys.stderr,
            )
            sys.exit(1)
        print(f"Loaded {len(kb_docs)} legacy FAQ documents (deprecated)")
    
    
    # Reindex each collection
    total_docs = 0
    
    # Deal CSV collection
    deal_count = reindex_collection(
        collection_name="kb_deal_csv",
        documents=kb_docs,
        embeddings=embeddings,
        persist_directory=persist_directory,
        bm25_corpus_path=bm25_dir / "kb_deal_csv.jsonl"
    )
    total_docs += deal_count
    
    # Master collection (TXT chunks; Chroma name kb_master_pdf is historical)
    master_count = reindex_collection(
        collection_name="kb_master_pdf",
        documents=txt_docs,
        embeddings=embeddings,
        persist_directory=persist_directory,
        bm25_corpus_path=bm25_dir / "kb_master_pdf.jsonl"
    )
    total_docs += master_count
    
    print("\n=== Reindexing Complete ===")
    print(f"Total documents indexed: {total_docs}")
    print(f"  - Deal CSV: {deal_count}")
    print(f"  - Master TXT: {master_count}")

    kb_path = config.get_kb_csv_path()
    if not kb_path.is_file():
        kb_path = config.get_faq_csv_path()
    if not kb_path.is_file():
        print(
            f"No manifest source CSV found. KB={config.get_kb_csv_path()} "
            f"legacy={config.get_faq_csv_path()}",
            file=sys.stderr,
        )
        sys.exit(1)
    manifest = write_vector_store_manifest(
        vector_store_root=persist_directory,
        embedding_model=config.openai_embedding_model,
        kb_csv_path=kb_path,
        deal_doc_count=deal_count,
        master_doc_count=master_count,
        project_root=Path(__file__).resolve().parent.parent,
    )
    print(f"\nWrote vector store manifest: {persist_directory / 'manifest.json'}")
    print(f"  kb_sha256 prefix: {manifest.get('kb_sha256', '')[:16]}...")


if __name__ == "__main__":
    main()
