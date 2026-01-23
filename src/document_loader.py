"""PDF document loader with security measures."""

import re
from pathlib import Path
from typing import List
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document
from src.config import Config


def _sanitize_text(text: str) -> str:
    """Sanitize text to remove suspicious patterns.
    
    Args:
        text: Input text
        
    Returns:
        Sanitized text
    """
    # Remove HTML tags
    text = re.sub(r'<[^>]+>', '', text)
    
    # Remove scripts and style blocks
    text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
    
    # Remove suspicious control characters (keep normal whitespace)
    text = re.sub(r'[\x00-\x08\x0B-\x0C\x0E-\x1F\x7F]', '', text)
    
    # Normalize excessive whitespace
    text = re.sub(r'\s{3,}', ' ', text)
    
    return text.strip()


def _detect_suspicious_patterns(text: str) -> List[str]:
    """Detect suspicious patterns that might indicate malicious content.
    
    Args:
        text: Input text
        
    Returns:
        List of detected suspicious patterns
    """
    suspicious = []
    
    # Long runs of whitespace (might hide invisible text)
    if re.search(r'\s{20,}', text):
        suspicious.append("excessive_whitespace")
    
    # Odd control characters
    if re.search(r'[\x00-\x08\x0B-\x0C\x0E-\x1F]', text):
        suspicious.append("control_characters")
    
    # HTML/script tags
    if re.search(r'<[^>]+>', text):
        suspicious.append("html_tags")
    
    # Suspicious instruction patterns (basic detection)
    suspicious_phrases = [
        r'ignore\s+all\s+prior\s+instructions',
        r'ignore\s+previous',
        r'forget\s+everything',
        r'new\s+instructions',
    ]
    for pattern in suspicious_phrases:
        if re.search(pattern, text, re.IGNORECASE):
            suspicious.append(f"suspicious_phrase: {pattern}")
    
    return suspicious


def load_pdf_documents(config: Config) -> List[Document]:
    """Load all PDF documents from the configured directory.
    
    Args:
        config: Application configuration
        
    Returns:
        List of Document objects with metadata
    """
    pdf_dir = config.get_pdf_documents_dir()
    
    if not pdf_dir.exists():
        pdf_dir.mkdir(parents=True, exist_ok=True)
        return []
    
    documents = []
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=200,
        separators=['\n\n', '\n', '。', '．', '；', ';', '、', ' ', '']
    )
    
    pdf_files = list(pdf_dir.glob("*.pdf"))
    if not pdf_files:
        return documents
    
    for pdf_path in pdf_files:
        try:
            loader = PyPDFLoader(str(pdf_path))
            pages = loader.load()
            
            # Combine all pages
            combined_text = "\n".join([page.page_content for page in pages])
            
            # Sanitize text
            sanitized_text = _sanitize_text(combined_text)
            
            # Detect suspicious patterns
            suspicious = _detect_suspicious_patterns(sanitized_text)
            if suspicious:
                print(f"Warning: Suspicious patterns detected in {pdf_path.name}: {suspicious}")
                # Continue processing but log the warning
            
            # Split into chunks
            chunks = text_splitter.split_text(sanitized_text)
            
            # Create Document objects with metadata
            for idx, chunk in enumerate(chunks):
                doc = Document(
                    page_content=chunk,
                    metadata={
                        'type': 'pdf',
                        'source': str(pdf_path),
                        'filename': pdf_path.name,
                        'page': idx + 1,
                        'total_pages': len(chunks),
                    }
                )
                documents.append(doc)
                
        except Exception as e:
            print(f"Error loading PDF {pdf_path.name}: {e}")
            # Continue with other PDFs
    
    return documents
