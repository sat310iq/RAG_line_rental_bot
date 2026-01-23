"""CSV loaders for FAQ and operations log with PII masking."""

import csv
import re
import hashlib
from pathlib import Path
from typing import List, Dict, Optional
from langchain_core.documents import Document
from src.config import Config


def _mask_room_number(text: str, tenant_room: Optional[str] = None) -> str:
    """Mask room numbers in text, except for the tenant's own room.
    
    Args:
        text: Input text
        tenant_room: Tenant's room number (if provided, don't mask this one)
        
    Returns:
        Text with room numbers masked
    """
    # Pattern to match room numbers (e.g., "101号室", "202", "A101")
    patterns = [
        r'\d{1,4}号室',
        r'\d{1,4}号',
        r'[A-Z]?\d{2,4}号室',
        r'[A-Z]?\d{2,4}号',
    ]
    
    masked_text = text
    for pattern in patterns:
        def replace_func(match):
            matched = match.group(0)
            # If this matches the tenant's room, keep it
            if tenant_room and tenant_room in matched:
                return matched
            return "個別住戸"
        
        masked_text = re.sub(pattern, replace_func, masked_text)
    
    return masked_text


def _detect_pii_patterns(text: str) -> List[str]:
    """Detect PII patterns in text.
    
    Args:
        text: Input text
        
    Returns:
        List of detected PII types
    """
    pii_types = []
    
    # Phone numbers (Japanese format)
    if re.search(r'0\d{1,4}-\d{1,4}-\d{4}', text):
        pii_types.append("phone")
    
    # Email addresses
    if re.search(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', text):
        pii_types.append("email")
    
    # Dates (YYYY-MM-DD, YYYY/MM/DD, etc.)
    if re.search(r'\d{4}[-/]\d{1,2}[-/]\d{1,2}', text):
        pii_types.append("date")
    
    # Room numbers (if not already masked)
    if re.search(r'\d{1,4}号室', text):
        pii_types.append("room_number")
    
    return pii_types


def _remove_pii_from_content(text: str, tenant_room: Optional[str] = None) -> str:
    """Remove PII from content while preserving structure.
    
    Args:
        text: Input text
        tenant_room: Tenant's room number (if provided, keep this one)
        
    Returns:
        Text with PII removed
    """
    # Mask room numbers first
    text = _mask_room_number(text, tenant_room)
    
    # Remove phone numbers
    text = re.sub(r'0\d{1,4}-\d{1,4}-\d{4}', '[電話番号]', text)
    
    # Remove email addresses
    text = re.sub(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', '[メールアドレス]', text)
    
    # Remove dates (YYYY-MM-DD format)
    text = re.sub(r'\d{4}[-/]\d{1,2}[-/]\d{1,2}', '[日付]', text)
    
    return text


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


def load_ops_log_csv(config: Config, tenant_room: Optional[str] = None) -> List[Document]:
    """Load operations log CSV file with PII masking.
    
    Expected CSV format:
    対応日,対応箇所,内容カテゴリ,対応内容（要約）,担当区分,緊急度,備考
    
    Args:
        config: Application configuration
        tenant_room: Tenant's room number (if provided, don't mask this one)
        
    Returns:
        List of Document objects with PII masked
    """
    csv_path = config.get_ops_log_csv_path()
    
    if not csv_path.exists():
        return []
    
    documents = []
    
    try:
        with open(csv_path, 'r', encoding='utf-8', newline='') as f:
            reader = csv.DictReader(f)
            
            for row in reader:
                # Extract fields
                date = row.get('対応日', '').strip()
                location = row.get('対応箇所', '').strip()
                category = row.get('内容カテゴリ', '').strip()
                summary = row.get('対応内容（要約）', '').strip()
                assignee = row.get('担当区分', '').strip()
                priority = row.get('緊急度', '').strip()
                notes = row.get('備考', '').strip()
                
                # Mask location (room numbers)
                masked_location = _mask_room_number(location, tenant_room)
                
                # Build page_content (without PII like dates)
                page_content = f"内容カテゴリ: {category}\n場所: {masked_location}\n対応: {summary}"
                
                # Map escalation
                escalation_map = {
                    '管理会社対応': 'management_required',
                    'オーナー対応': 'owner_required',
                    '情報提供のみ': 'bot_only',
                }
                escalation = escalation_map.get(assignee, assignee)
                
                # Generate stable_id
                stable_id_input = f"{category}:{summary}"
                stable_id = hashlib.sha1(stable_id_input.encode('utf-8')).hexdigest()[:16]
                
                # Store original room number in metadata (for tenant filtering later)
                original_room_match = re.search(r'\d{1,4}号室', location)
                tenant_room_original = original_room_match.group(0) if original_room_match else None
                
                doc = Document(
                    page_content=page_content,
                    metadata={
                        'type': 'ops_log',
                        'category': category,
                        'escalation': escalation,
                        'priority': priority,
                        'assignee': assignee,
                        'date': date,  # Keep in metadata but not in page_content
                        'source': str(csv_path),
                        'stable_id': stable_id,
                        'tenant_room': tenant_room_original,  # Original room number for filtering
                    }
                )
                documents.append(doc)
                
    except Exception as e:
        print(f"Error loading operations log CSV {csv_path}: {e}")
    
    return documents
