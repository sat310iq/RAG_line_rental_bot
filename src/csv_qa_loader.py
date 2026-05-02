"""CSV loader for FAQ data."""

import csv
import re
from pathlib import Path
from typing import List, Dict, Optional
from langchain_core.documents import Document
from src.config import Config


def load_faq_csv(config: Config) -> List[Document]:
    """Load FAQ CSV file.
    
    Expected CSV format:
    intent,category,keywords,answer,escalation,priority,notes
    
    Args:
        config: Application configuration
        
    Returns:
        List of Document objects
    """
    csv_path = config.get_faq_csv_path()
    
    if not csv_path.exists():
        return []
    
    documents = []
    
    try:
        with open(csv_path, 'r', encoding='utf-8', newline='') as f:
            reader = csv.DictReader(f)
            
            for row in reader:
                # Build page_content from multiple fields for better searchability
                intent = row.get('intent', '').strip()
                category = row.get('category', '').strip()
                keywords = row.get('keywords', '').strip()
                answer = row.get('answer', '').strip()
                
                page_content = f"意図: {intent}\nカテゴリ: {category}\nキーワード: {keywords}\n回答: {answer}"
                
                doc = Document(
                    page_content=page_content,
                    metadata={
                        'type': 'faq',
                        'intent': intent,
                        'category': category,
                        'keywords': keywords,
                        'escalation': row.get('escalation', '').strip(),
                        'priority': row.get('priority', '').strip(),
                        'notes': row.get('notes', '').strip(),
                        'source': str(csv_path),
                    }
                )
                documents.append(doc)
                
    except Exception as e:
        print(f"Error loading FAQ CSV {csv_path}: {e}")
    
    return documents


def _mask_room_number(text: str, tenant_room: Optional[str] = None) -> str:
    """Mask room numbers except tenant's own room."""
    if not text:
        return text
    pattern = re.compile(r"(\d{1,4})号室")

    def replace(match: re.Match) -> str:
        room = match.group(1)
        if tenant_room and room == tenant_room:
            return match.group(0)
        return "個別住戸"

    return pattern.sub(replace, text)


def _remove_pii_from_content(text: str) -> str:
    """Remove simple PII patterns from text."""
    if not text:
        return text
    cleaned = text
    # Dates like 2024-01-01
    cleaned = re.sub(r"\d{4}-\d{2}-\d{2}", "[日付]", cleaned)
    # Phone numbers like 090-1234-5678
    cleaned = re.sub(r"\d{2,4}-\d{2,4}-\d{3,4}", "[電話番号]", cleaned)
    # Emails
    cleaned = re.sub(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "[メールアドレス]", cleaned)
    return cleaned
