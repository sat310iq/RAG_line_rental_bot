"""Knowledge base CSV loader with 15-column schema."""

import csv
from datetime import date, datetime
from pathlib import Path
from typing import List, Dict, Any, Optional
from langchain_core.documents import Document
from src.config import Config


# Required 15 columns
REQUIRED_COLUMNS = [
    "intent",
    "category",
    "keywords",
    "answer",
    "response_type",
    "confidence_level",
    "required_inputs",
    "urgency",
    "conditions",
    "effective_from",
    "effective_to",
    "escalation",
    "escalation_reason",
    "handoff_message",
    "notes",
]


def parse_date(date_str: Optional[str]) -> Optional[date]:
    """Parse date string (YYYY-MM-DD) to date object.
    
    Args:
        date_str: Date string in YYYY-MM-DD format or empty string
        
    Returns:
        date object or None if empty/invalid
    """
    if not date_str or not date_str.strip():
        return None
    
    try:
        return datetime.strptime(date_str.strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


def parse_required_inputs(inputs_str: Optional[str]) -> List[str]:
    """Parse required_inputs string (comma-separated) to list.
    
    Args:
        inputs_str: Comma-separated string or empty string
        
    Returns:
        List of input names, or empty list if empty
    """
    if not inputs_str or not inputs_str.strip():
        return []
    
    # Split by comma and strip whitespace
    inputs = [item.strip() for item in inputs_str.split(",")]
    # Filter out empty strings
    return [item for item in inputs if item]


def load_kb_csv(config: Config) -> List[Document]:
    """Load 15-column knowledge base CSV.
    
    Validates header, parses types, returns Documents.
    Does NOT perform date validation (that's done at retrieval time).
    
    Args:
        config: Application configuration
        
    Returns:
        List of Document objects with page_content and metadata
        
    Raises:
        ValueError: If CSV header doesn't match required 15 columns
    """
    csv_path = config.get_kb_csv_path()
    
    if not csv_path.exists():
        print(f"Warning: KB CSV file not found: {csv_path}")
        return []
    
    documents = []
    
    try:
        with open(csv_path, 'r', encoding='utf-8', newline='') as f:
            reader = csv.DictReader(f)
            
            # Validate header
            actual_columns = set(reader.fieldnames or [])
            required_columns_set = set(REQUIRED_COLUMNS)
            
            missing_columns = required_columns_set - actual_columns
            if missing_columns:
                raise ValueError(
                    f"KB CSV missing required columns: {sorted(missing_columns)}. "
                    f"Found columns: {sorted(actual_columns)}"
                )
            
            extra_columns = actual_columns - required_columns_set
            if extra_columns:
                print(f"Warning: KB CSV has extra columns (ignored): {sorted(extra_columns)}")
            
            # Process each row
            for row_idx, row in enumerate(reader, start=2):  # Start at 2 (header is row 1)
                try:
                    # Extract and parse fields (handle None values)
                    intent = (row.get('intent') or '').strip()
                    category = (row.get('category') or '').strip()
                    keywords = (row.get('keywords') or '').strip()
                    answer = (row.get('answer') or '').strip()
                    conditions = (row.get('conditions') or '').strip()
                    
                    # Build page_content from searchable fields
                    page_content = f"意図: {intent}\nカテゴリ: {category}\nキーワード: {keywords}\n回答: {answer}"
                    if conditions:
                        page_content += f"\n条件: {conditions}"
                    
                    # Parse and store metadata (handle None values)
                    response_type = (row.get('response_type') or '').strip()
                    confidence_level = (row.get('confidence_level') or '').strip()
                    required_inputs_raw = row.get('required_inputs') or ''
                    required_inputs = parse_required_inputs(required_inputs_raw)
                    urgency = (row.get('urgency') or '').strip()
                    effective_from = parse_date(row.get('effective_from') or '')
                    effective_to = parse_date(row.get('effective_to') or '')
                    escalation = (row.get('escalation') or '').strip()
                    escalation_reason = (row.get('escalation_reason') or '').strip()
                    handoff_message = (row.get('handoff_message') or '').strip()
                    notes = (row.get('notes') or '').strip()
                    
                    # ChromaDB doesn't support list types in metadata, so convert to string
                    required_inputs_str = ','.join(required_inputs) if required_inputs else ''
                    
                    doc = Document(
                        page_content=page_content,
                        metadata={
                            'type': 'kb_faq',
                            'intent': intent,
                            'category': category,
                            'keywords': keywords,
                            'answer': answer,
                            'response_type': response_type,
                            'confidence_level': confidence_level,
                            'required_inputs': required_inputs_str,  # String (comma-separated) for ChromaDB compatibility
                            'urgency': urgency,
                            'conditions': conditions,
                            'effective_from': effective_from.isoformat() if effective_from else None,
                            'effective_to': effective_to.isoformat() if effective_to else None,
                            'escalation': escalation,
                            'escalation_reason': escalation_reason,
                            'handoff_message': handoff_message,
                            'notes': notes,
                            'source': str(csv_path),
                            'row_index': row_idx,  # For citations
                        }
                    )
                    documents.append(doc)
                    
                except Exception as e:
                    print(f"Error processing row {row_idx} in KB CSV {csv_path}: {e}")
                    continue
                    
    except ValueError as e:
        # Re-raise validation errors
        raise
    except Exception as e:
        print(f"Error loading KB CSV {csv_path}: {e}")
        import traceback
        traceback.print_exc()
    
    print(f"Loaded {len(documents)} documents from KB CSV: {csv_path}")
    return documents
