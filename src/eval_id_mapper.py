"""ID mapping utility for evaluation.

This module provides functions to map expected document IDs to actual document IDs
used in the RAG system. It handles different ID formats for FAQ, OPS logs, and PDFs.
"""

import hashlib
import csv
from pathlib import Path
from typing import List, Dict, Optional
from src.config import Config


class EvalIDMapper:
    """Maps expected document IDs to actual document IDs."""
    
    def __init__(self, config: Config):
        """Initialize ID mapper.
        
        Args:
            config: Application configuration
        """
        self.config = config
        self._faq_intents: Dict[str, str] = {}
        self._ops_stable_ids: Dict[str, str] = {}
        self._load_faq_intents()
        self._load_ops_stable_ids()
    
    def _load_faq_intents(self) -> None:
        """Load FAQ intent mappings from CSV."""
        csv_path = self.config.get_faq_csv_path()
        if not csv_path.exists():
            return
        
        try:
            with open(csv_path, 'r', encoding='utf-8', newline='') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    intent = row.get('intent', '').strip()
                    if intent:
                        # Map intent to itself (actual ID format)
                        self._faq_intents[intent] = intent
        except Exception as e:
            print(f"Warning: Failed to load FAQ intents: {e}")
    
    def _load_ops_stable_ids(self) -> None:
        """Load OPS log stable_id mappings from CSV."""
        csv_path = self.config.get_ops_log_csv_path()
        if not csv_path.exists():
            return
        
        try:
            with open(csv_path, 'r', encoding='utf-8', newline='') as f:
                reader = csv.DictReader(f)
                for idx, row in enumerate(reader):
                    category = row.get('内容カテゴリ', '').strip()
                    summary = row.get('対応内容（要約）', '').strip()
                    stable_id_input = f"{category}:{summary}"
                    stable_id = hashlib.sha1(stable_id_input.encode('utf-8')).hexdigest()[:16]
                    
                    # Map LOG{index} format to stable_id
                    log_id = f"LOG{idx + 1}"
                    self._ops_stable_ids[log_id] = stable_id
                    # Also map stable_id to itself
                    self._ops_stable_ids[stable_id] = stable_id
        except Exception as e:
            print(f"Warning: Failed to load OPS stable IDs: {e}")
    
    def map_expected_id(self, expected_id: str, source_type: Optional[str] = None) -> List[str]:
        """Map expected ID to actual document ID(s).
        
        Args:
            expected_id: Expected document ID (from eval_questions.csv)
            source_type: Source type hint (faq, ops, pdf, multi)
            
        Returns:
            List of actual document IDs
        """
        if not expected_id or not expected_id.strip():
            return []
        
        expected_id = expected_id.strip()
        
        # Check if it's already in the correct format
        # PDF format: "filename p{page}"
        if ' p' in expected_id and expected_id.endswith(('p0', 'p1', 'p2', 'p3', 'p4', 'p5', 'p6', 'p7', 'p8', 'p9', 'p10', 'p11', 'p12', 'p13', 'p14', 'p15', 'p16', 'p17', 'p18', 'p19', 'p20')):
            return [expected_id]
        
        # Check if it's a stable_id (16 hex characters)
        if len(expected_id) == 16 and all(c in '0123456789abcdef' for c in expected_id):
            return [expected_id]
        
        # Check FAQ intents
        if expected_id in self._faq_intents:
            return [self._faq_intents[expected_id]]
        
        # Check OPS log mappings
        if expected_id in self._ops_stable_ids:
            return [self._ops_stable_ids[expected_id]]
        
        # Try to infer from source_type
        if source_type == 'faq':
            # Check if it's an intent name
            if expected_id in self._faq_intents:
                return [self._faq_intents[expected_id]]
        
        # If no mapping found, return as-is (might be correct already)
        return [expected_id]
    
    def map_expected_ids(self, expected_ids: List[str], source_type: Optional[str] = None) -> List[str]:
        """Map multiple expected IDs to actual document IDs.
        
        Args:
            expected_ids: List of expected document IDs
            source_type: Source type hint
            
        Returns:
            List of actual document IDs (flattened)
        """
        mapped_ids = []
        for expected_id in expected_ids:
            mapped = self.map_expected_id(expected_id, source_type)
            mapped_ids.extend(mapped)
        return mapped_ids


def create_id_mapper(config: Optional[Config] = None) -> EvalIDMapper:
    """Create an ID mapper instance.
    
    Args:
        config: Optional configuration (if None, loads from environment)
        
    Returns:
        EvalIDMapper instance
    """
    if config is None:
        from src.config import load_config
        config = load_config()
    return EvalIDMapper(config)
