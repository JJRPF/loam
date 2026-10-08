from typing import Dict, Any, List, Optional
from app.config import settings
from app.connectors.base import BaseConnector

class TrailforksConnector(BaseConnector):
    """
    Trailforks metadata interface.
    Strict Invariants per Project Brief:
    1. Build the interface only. Do NOT ingest any Trailforks data until Justin confirms permission.
    2. Free product only; respect rate limits; never feed its data into OpenStreetMap.
    3. Credit '© Trailforks' wherever its data appears.
    4. Off by default (ENABLE_TRAILFORKS_CONNECTOR=false).
    """

    @property
    def name(self) -> str:
        return "trailforks"

    @property
    def display_name(self) -> str:
        return "Trailforks"

    @property
    def description(self) -> str:
        return "Trail metadata and condition provider. Interface-only; disabled by default pending explicit approval."

    def is_enabled(self) -> bool:
        return settings.enable_trailforks_connector

    def get_status(self, user_id: str) -> Dict[str, Any]:
        return {
            "name": self.name,
            "display_name": self.display_name,
            "enabled": self.is_enabled(),
            "connected": False,
            "last_synced_at": None,
            "description": self.description
        }

    async def authenticate(self, user_id: str, **credentials) -> Dict[str, Any]:
        return {
            "success": False,
            "error": "Trailforks ingestion is disabled pending terms confirmation and permission."
        }

    async def fetch_activities(self, user_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        return []

    async def sync_activities(self, user_id: str) -> Dict[str, Any]:
        return {
            "connector": self.name,
            "status": "disabled",
            "activities_imported": 0,
            "message": "Trailforks connector is currently disabled."
        }

    async def disconnect(self, user_id: str) -> bool:
        return True
