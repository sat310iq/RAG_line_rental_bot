"""Knowledge base CSV loader with 15-column schema plus optional metadata."""

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

# Optional columns for hierarchical RAG (defaulted when missing/blank)
OPTIONAL_COLUMNS = [
    "contract_id",
    "topic",
    "precedence",
    "override_flag",
    "citations",
    "fallback_to_master",
    "answer_complete",
    "effective_date",
    "version",
    "negative_keywords",
    "negative_penalty",
    # KB fast path (must be listed or CSV columns are silently ignored)
    "canonical_question",
    "keywords_primary",
    "keywords_secondary",
    "synonyms",
    "exclude_keywords",
    "fast_path_enabled",
    "needs_clarification_when_short",
    "clarification_prompt",
    "clarification_options",
    "clarification_examples",
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


def parse_bool(value: Optional[str], default: bool) -> bool:
    """Parse boolean-like string to bool with default."""
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in ("true", "1", "yes", "y"):
        return True
    if normalized in ("false", "0", "no", "n"):
        return False
    return default


def load_kb_csv(config: Config) -> List[Document]:
    """Load 15-column knowledge base CSV with optional metadata columns.
    
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
            
            extra_columns = actual_columns - required_columns_set - set(OPTIONAL_COLUMNS)
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
                    
                    # Optional metadata for hierarchical RAG
                    contract_id = (row.get('contract_id') or '').strip()
                    topic = (row.get('topic') or '').strip() or "unknown"
                    precedence_str = (row.get('precedence') or '').strip()
                    try:
                        precedence = int(precedence_str) if precedence_str else 100
                    except ValueError:
                        precedence = 100
                    override_flag = (row.get('override_flag') or '').strip() or "addition"
                    citations = (row.get('citations') or '').strip()
                    fallback_to_master = parse_bool(row.get('fallback_to_master'), True)
                    answer_complete = parse_bool(row.get('answer_complete'), False)
                    effective_date = (row.get('effective_date') or '').strip()
                    version = (row.get('version') or '').strip()
                    negative_keywords = (row.get('negative_keywords') or '').strip()
                    negative_penalty = (row.get('negative_penalty') or '').strip()
                    canonical_question = (row.get('canonical_question') or '').strip()
                    keywords_primary = (row.get('keywords_primary') or '').strip()
                    keywords_secondary = (row.get('keywords_secondary') or '').strip()
                    synonyms_kw = (row.get('synonyms') or '').strip()
                    exclude_keywords_fp = (row.get('exclude_keywords') or '').strip()
                    fast_path_enabled = parse_bool(row.get('fast_path_enabled'), False)
                    needs_clarification_when_short = parse_bool(
                        row.get('needs_clarification_when_short'), False
                    )
                    clarification_prompt = (row.get('clarification_prompt') or '').strip()
                    clarification_options = (row.get('clarification_options') or '').strip()
                    clarification_examples = (row.get('clarification_examples') or '').strip()

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
                            'contract_id': contract_id,
                            'topic': topic,
                            'precedence': precedence,
                            'override_flag': override_flag,
                            'citations': citations,
                            'fallback_to_master': fallback_to_master,
                            'answer_complete': answer_complete,
                            'effective_date': effective_date,
                            'version': version,
                            'negative_keywords': negative_keywords,
                            'negative_penalty': negative_penalty,
                            'canonical_question': canonical_question,
                            'keywords_primary': keywords_primary,
                            'keywords_secondary': keywords_secondary,
                            'synonyms': synonyms_kw,
                            'exclude_keywords': exclude_keywords_fp,
                            'fast_path_enabled': 'true' if fast_path_enabled else 'false',
                            'needs_clarification_when_short': (
                                'true' if needs_clarification_when_short else 'false'
                            ),
                            'clarification_prompt': clarification_prompt,
                            'clarification_options': clarification_options,
                            'clarification_examples': clarification_examples,
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
