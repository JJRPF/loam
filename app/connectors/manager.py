from typing import Dict, Any, List, Optional
from app.connectors.base import BaseConnector
from app.connectors.strava import StravaConnector
from app.connectors.garmin import GarminConnector
from app.connectors.trailforks import TrailforksConnector

class ConnectorManager:
    """Registry and coordinator for external data connectors."""

    def __init__(self):
        self._connectors: Dict[str, BaseConnector] = {
            "strava": StravaConnector(),
            "garmin": GarminConnector(),
            "trailforks": TrailforksConnector(),
        }

    def get_connector(self, name: str) -> Optional[BaseConnector]:
        return self._connectors.get(name.lower())

    def list_connectors(self, user_id: str) -> List[Dict[str, Any]]:
        return [connector.get_status(user_id) for connector in self._connectors.values()]

    async def authenticate(self, provider: str, user_id: str, **kwargs) -> Dict[str, Any]:
        connector = self.get_connector(provider)
        if not connector:
            return {"success": False, "error": f"Unknown connector provider '{provider}'."}
        return await connector.authenticate(user_id, **kwargs)

    async def sync(self, provider: str, user_id: str, import_to_heat: bool = True) -> Dict[str, Any]:
        connector = self.get_connector(provider)
        if not connector:
            return {
                "connector": provider,
                "status": "failed",
                "activities_imported": 0,
                "heat_edges_updated": 0,
                "bulk_heat_imported": False,
                "message": f"Unknown connector '{provider}'."
            }
        return await connector.sync_activities(user_id, import_to_heat=import_to_heat)

    async def disconnect(self, provider: str, user_id: str) -> bool:
        connector = self.get_connector(provider)
        if not connector:
            return False
        return await connector.disconnect(user_id)

connector_manager = ConnectorManager()
