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

class StravaConnector(BaseConnector):
    """
    Strava API connector.
    Strict Invariants:
    1. Isolated behind an abstract interface so it can be unlinked or disabled instantly.
    2. Off by default per Project Plan Section 13 (patent and Strava Terms of Service compliance).
    3. User activity tokens encrypted at rest.
    4. Data never used for unauthorized AI/ML model ingestion.
    """

    @property
    def name(self) -> str:
        return "strava"

    @property
    def display_name(self) -> str:
        return "Strava"

    @property
    def description(self) -> str:
        return "Connect your personal Strava API token from your Strava account (strava.com/settings/api). Zero app token required. Encrypted at rest."

    def is_enabled(self) -> bool:
        return settings.enable_strava_connector

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
        if not self.is_enabled():
            return {
                "success": False,
                "error": "Strava connector is disabled by configuration (ENABLE_STRAVA_CONNECTOR=false)."
            }

        personal_token = (credentials.get("personal_token") or "").strip()
        if not personal_token:
            return {"success": False, "error": "A Strava personal access token is required."}

        try:
            status_code, data = await self._fetch_athlete(personal_token)
        except Exception:
            return {"success": False, "error": "Could not reach Strava. Try again later."}
        if status_code == 401:
            return {"success": False, "error": "Invalid Strava Personal Access Token. Please verify at strava.com/settings/api."}
        if status_code != 200:
            return {"success": False, "error": f"Strava rejected the token ({status_code})."}

        athlete_name = f"{data.get('firstname', '')} {data.get('lastname', '')}".strip()
        save_user_connected_service(
            user_id=user_id,
            provider=self.name,
            encrypted_token=encrypt_token(personal_token),
            expires_at=datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=365)
        )
        return {
            "success": True,
            "connected": True,
            "message": f"Connected to Strava ({athlete_name}). Activity import isn't available yet." if athlete_name
            else "Connected to Strava. Activity import isn't available yet."
        }

    async def _fetch_athlete(self, token: str):
        """GET /athlete with the token: (status code, JSON body or {})."""
        import httpx
        async with httpx.AsyncClient(timeout=6.0) as client:
            resp = await client.get(
                "https://www.strava.com/api/v3/athlete",
                headers={"Authorization": f"Bearer {token}", "User-Agent": settings.user_agent}
            )
        return resp.status_code, (resp.json() if resp.status_code == 200 else {})

    async def fetch_activities(self, user_id: str, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        # Strava activity import isn't built; nothing is returned rather than placeholder rides.
        return []

    async def sync_activities(self, user_id: str, import_to_heat: bool = True) -> Dict[str, Any]:
        if not self.is_enabled():
            return {
                "connector": self.name,
                "status": "disabled",
                "activities_imported": 0,
                "message": "Strava connector is disabled by configuration."
            }

        return {
            "connector": self.name,
            "status": "unavailable",
            "activities_imported": 0,
            "message": "Strava activity import isn't available yet."
        }

    async def disconnect(self, user_id: str) -> bool:
        return delete_user_connected_service(user_id, self.name)
