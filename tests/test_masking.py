"""Tests for PII masking and tenant filtering."""

import pytest
from src.csv_qa_loader import _mask_room_number, _remove_pii_from_content
from src.tenant_auth import TenantAuth
from src.config import Config


def test_mask_room_number():
    """Test room number masking."""
    text = "101号室で水漏れが発生しました。202号室も確認が必要です。"
    
    # Mask all room numbers
    masked = _mask_room_number(text, tenant_room=None)
    assert '101号室' not in masked
    assert '202号室' not in masked
    assert '個別住戸' in masked
    
    # Keep tenant's own room
    masked_keep = _mask_room_number(text, tenant_room='101')
    assert '101号室' in masked_keep
    assert '202号室' not in masked_keep


def test_remove_pii_from_content():
    """Test PII removal from content."""
    text = "2024-01-01に101号室で、090-1234-5678に連絡。test@example.comにもメール送信。"
    
    cleaned = _remove_pii_from_content(text)
    
    assert '2024-01-01' not in cleaned
    assert '090-1234-5678' not in cleaned
    assert 'test@example.com' not in cleaned
    assert '[日付]' in cleaned or '[電話番号]' in cleaned or '[メールアドレス]' in cleaned


def test_tenant_auth():
    """Test tenant authentication."""
    config = Config(
        openai_api_key="test_key",
        tenant_master_csv="test_tenants.csv"
    )
    
    # Create sample tenant master
    import csv
    import tempfile
    from pathlib import Path
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=['contract_id', 'room_number', 'name', 'pin', 'phone', 'email'])
        writer.writeheader()
        writer.writerow({
            'contract_id': 'TEST001',
            'room_number': '101',
            'name': 'テスト 太郎',
            'pin': '1234',
            'phone': '090-1234-5678',
            'email': 'test@example.com'
        })
        temp_path = f.name
    
    try:
        config.tenant_master_csv = temp_path
        tenant_auth = TenantAuth(config)
        
        # Test authentication
        tenant_info = tenant_auth.authenticate('TEST001', '1234')
        assert tenant_info is not None
        assert tenant_info['room_number'] == '101'
        assert tenant_info['name'] == 'テスト 太郎'
        
        # Test failed authentication
        failed = tenant_auth.authenticate('TEST001', 'wrong')
        assert failed is None
        
    finally:
        Path(temp_path).unlink()
