"""Tests for CSV loader robustness."""

import csv
import tempfile
from pathlib import Path
import pytest
from src.config import Config
from src.csv_qa_loader import load_faq_csv, load_ops_log_csv


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


def test_ops_log_csv_masking():
    """Test operations log CSV masking."""
    config = Config(
        openai_api_key="test_key",
        ops_log_csv_path="test_ops.csv"
    )
    
    # Create test CSV with room numbers
    with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['対応日', '対応箇所', '内容カテゴリ', '対応内容（要約）', '担当区分', '緊急度', '備考'])
        writer.writerow([
            '2024-01-01',
            '101号室',
            '水漏れ',
            '対応完了',
            '管理会社対応',
            '高',
            '備考なし'
        ])
        temp_path = f.name
    
    try:
        config.ops_log_csv_path = temp_path
        docs = load_ops_log_csv(config, tenant_room=None)
        
        assert len(docs) == 1
        # Check that room number is masked in page_content
        assert '101号室' not in docs[0].page_content
        assert '個別住戸' in docs[0].page_content
        # But kept in metadata
        assert docs[0].metadata.get('tenant_room') == '101号室'
        
    finally:
        Path(temp_path).unlink()
