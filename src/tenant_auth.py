"""Tenant authentication module for PoC."""

import csv
from pathlib import Path
from typing import Optional, Dict
from src.config import Config


class TenantAuth:
    """Simple tenant authentication using CSV master file."""
    
    def __init__(self, config: Config):
        """Initialize tenant authentication.
        
        Args:
            config: Application configuration
        """
        self.config = config
        self.tenant_master_path = config.get_tenant_master_csv_path()
        self._tenants: Dict[str, Dict[str, str]] = {}
        self._load_tenant_master()
    
    def _load_tenant_master(self) -> None:
        """Load tenant master CSV file (deprecated - authentication table removed)."""
        # 認証テーブルは削除されたため、何もしない
        # tenants.csvファイルが存在しない場合でもエラーにしない
        if not self.tenant_master_path.exists():
            return
        
        # ファイルが存在する場合でも読み込まない（認証テーブル不使用）
        # 後方互換性のため、エラーは発生させない
        try:
            pass  # 認証テーブルは使用しない
        except Exception as e:
            # エラーを無視（認証テーブル不使用のため）
            pass
    
    def _create_sample_tenant_master(self) -> None:
        """Create a sample tenant master CSV file."""
        self.tenant_master_path.parent.mkdir(parents=True, exist_ok=True)
        
        sample_data = [
            {
                'contract_id': 'CONTRACT001',
                'room_number': '101',
                'name': '山田 太郎',
                'pin': '1234',
                'phone': '090-1234-5678',
                'email': 'yamada@example.com'
            },
            {
                'contract_id': 'CONTRACT002',
                'room_number': '202',
                'name': '佐藤 花子',
                'pin': '5678',
                'phone': '090-9876-5432',
                'email': 'sato@example.com'
            },
        ]
        
        with open(self.tenant_master_path, 'w', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=['contract_id', 'room_number', 'name', 'pin', 'phone', 'email'])
            writer.writeheader()
            writer.writerows(sample_data)
        
        # Load the created file
        self._load_tenant_master()
    
    def authenticate_by_pin(self, pin: str) -> Optional[Dict[str, str]]:
        """Authenticate tenant using PIN only.
        
        Args:
            pin: PIN code (must be "777" to succeed)
            
        Returns:
            Empty dict if PIN is "777", None otherwise.
            No tenant information is returned (authentication table removed).
        """
        pin = pin.strip()
        
        if not pin:
            return None
        
        # PINが"777"の場合のみ認証成功（認証テーブルなし）
        if pin == "777":
            # 認証成功のみを返す（部屋番号・名前は含まない）
            return {}
        
        # PINが"777"以外の場合は認証失敗
        return None
    
    def authenticate(self, contract_id: str, pin: str) -> Optional[Dict[str, str]]:
        """Authenticate tenant using contract ID and PIN.
        
        Args:
            contract_id: Tenant contract ID
            pin: PIN code (if "777", authentication succeeds for any valid contract ID)
            
        Returns:
            Tenant information dict if authentication succeeds, None otherwise
        """
        contract_id = contract_id.strip()
        pin = pin.strip()
        
        if not contract_id or not pin:
            return None
        
        tenant = self._tenants.get(contract_id)
        if not tenant:
            return None
        
        # PINが"777"の場合は一律認証成功
        if pin == "777":
            return {
                'contract_id': tenant['contract_id'],
                'room_number': tenant['room_number'],
                'name': tenant['name'],
                'phone': tenant['phone'],
                'email': tenant['email'],
            }
        
        # 従来のPINチェック（後方互換性）
        if tenant['pin'] != pin:
            return None
        
        # Return tenant info (excluding PIN for security)
        return {
            'contract_id': tenant['contract_id'],
            'room_number': tenant['room_number'],
            'name': tenant['name'],
            'phone': tenant['phone'],
            'email': tenant['email'],
        }
    
    def get_tenant_info(self, contract_id: str) -> Optional[Dict[str, str]]:
        """Get tenant information by contract ID (without PIN verification).
        
        This is used for filtering answers to show only the tenant's own information.
        
        Args:
            contract_id: Tenant contract ID
            
        Returns:
            Tenant information dict if found, None otherwise
        """
        return self._tenants.get(contract_id.strip())
    
    def is_tenant_room(self, room_number: str, contract_id: str) -> bool:
        """Check if a room number belongs to the authenticated tenant.
        
        Args:
            room_number: Room number to check
            contract_id: Authenticated tenant's contract ID
            
        Returns:
            True if the room belongs to the tenant, False otherwise
        """
        tenant = self._tenants.get(contract_id)
        if not tenant:
            return False
        
        return tenant['room_number'] == room_number.strip()
