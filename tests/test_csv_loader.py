"""Tests for CSV loader robustness."""

import csv
import tempfile
from pathlib import Path
import pytest
from src.config import Config
from src.csv_qa_loader import load_faq_csv


def test_faq_csv_with_special_characters():
    """Test FAQ CSV loading with special characters."""
    config = Config(
        openai_api_key="test_key",
        faq_csv_path="test_faq.csv"
    )
    
    # Create test CSV with special characters
    with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['intent', 'category', 'keywords', 'answer', 'escalation', 'priority', 'notes'])
        writer.writerow([
            'test_intent',
            'test_category',
            'keyword1, keyword2',
            'Answer with "quotes" and\nnewlines',
            'management_required',
            'high',
            'Notes with, commas'
        ])
        temp_path = f.name
    
    try:
        config.faq_csv_path = temp_path
        docs = load_faq_csv(config)
        
        assert len(docs) == 1
        assert docs[0].metadata['intent'] == 'test_intent'
        assert 'quotes' in docs[0].page_content
        assert 'newlines' in docs[0].page_content
        
    finally:
        Path(temp_path).unlink()


