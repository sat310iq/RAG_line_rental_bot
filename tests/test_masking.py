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
    """Test tenant authentication.
    
    Note: Current implementation does not use authentication table.
    _load_tenant_master() is intentionally a no-op, so _tenants remains empty.
    This test verifies the current behavior where authentication table is not used.
    """
    config = Config(
        openai_api_key="test_key",
        tenant_master_csv="test_tenants.csv"
    )
    
    tenant_auth = TenantAuth(config)
    
    # Current implementation: _load_tenant_master() does nothing, so _tenants is empty
    # authenticate() method checks _tenants.get(contract_id), which returns None
    # Therefore, authenticate() will always return None unless _tenants is populated
    
    # Test that authenticate() returns None when _tenants is empty (current behavior)
    tenant_info = tenant_auth.authenticate('TEST001', '1234')
    assert tenant_info is None, "authenticate() should return None when _tenants is empty"
    
    # Test authenticate_by_pin() with PIN "777" (special case that succeeds)
    pin_auth = tenant_auth.authenticate_by_pin('777')
    assert pin_auth == {}, "authenticate_by_pin('777') should return empty dict"
    
    # Test authenticate_by_pin() with wrong PIN
    failed_pin = tenant_auth.authenticate_by_pin('1234')
    assert failed_pin is None, "authenticate_by_pin() should return None for wrong PIN"
