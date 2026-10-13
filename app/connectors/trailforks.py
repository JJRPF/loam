import datetime
import uuid
from typing import Dict, Any, List, Optional
from app.config import settings
from app.connectors.base import BaseConnector
from app.connectors.encryption import encrypt_token, decrypt_token
from app.db import (
    get_user_connected_service,
    save_user_connected_service,
    delete_user_connected_service
)

class TrailforksConnector(BaseConnector):
    """
    Trailforks metadata and condition provider.
    Strict Invariants per Project Brief:
    1. Credit '© Trailforks' wherever its data appears.
    2. Respect rate limits; never feed proprietary data into OpenStreetMap.
    3. Session tokens are encrypted at rest using AES Fernet encryption.
    """

    @property
    def name(self) -> str:
        return "trailforks"

    @property
    def display_name(self) -> str:
        return "Trailforks"

    @property
    def description(self) -> str:
        return "Trail condition reports, difficulty ratings, and trailhead status (© Trailforks). Free product tier; respect rate limits."

    def is_enabled(self) -> bool:
        return settings.enable_trailforks_connector

    def get_status(self, user_id: str) -> Dict[str, Any]:
        enabled = self.is_enabled()
        service_record = get_user_connected_service(user_id, self.name)
        connected = bool(service_record and service_record.get("is_active"))
        last_sync = service_record.get("last_synced_at") if service_record else None

        return {
            "name": self.name,
            "display_name": self.display_name,
            "enabled": enabled,
            "connected": connected,
            "last_synced_at": last_sync.isoformat() if isinstance(last_sync, datetime.datetime) else (str(last_sync) if last_sync else None),
            "description": self.description
        }

    async def authenticate(self, user_id: str, **credentials) -> Dict[str, Any]:
        # Loam has no Trailforks API access (no app key, terms not confirmed), so nothing can
        # be connected. The interface stays so the connector can be switched on later.
        return {
            "success": False,
            "error": "Trailforks isn't available yet: Loam doesn't have Trailforks API access.",
        }

    async def fetch_activities(self, user_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        return []

    async def sync_activities(self, user_id: str, import_to_heat: bool = True) -> Dict[str, Any]:
        return {
            "connector": self.name,
            "status": "unavailable",
            "activities_imported": 0,
            "message": "Trailforks isn't available yet: Loam doesn't have Trailforks API access.",
        }

    async def disconnect(self, user_id: str) -> bool:
        return delete_user_connected_service(user_id, self.name)
