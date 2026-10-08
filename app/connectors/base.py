from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional

class BaseConnector(ABC):
    """
    Abstract interface for swappable third-party activity data connectors (Strava, Garmin, Trailforks).
    Ensures all external integrations are strictly decoupled, independently toggleable via feature flags,
    and swappable without touching core routing logic.
    """
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Machine identifier (e.g. 'strava', 'garmin', 'trailforks')."""
        pass

    @property
    @abstractmethod
    def display_name(self) -> str:
        """User-friendly name (e.g. 'Strava', 'Garmin Connect')."""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """Summary of what the connector does and terms/privacy notes."""
        pass

    @abstractmethod
    def is_enabled(self) -> bool:
        """Returns True if the connector's feature flag is enabled in settings."""
        pass

    @abstractmethod
    async def authenticate(self, user_id: str, **credentials) -> Dict[str, Any]:
        """
        Authenticates or exchanges credentials/code for encrypted session tokens.
        INVARIANT: Passwords must NEVER be stored, logged, or retained.
        """
        pass

    @abstractmethod
    async def fetch_activities(self, user_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Fetches raw activity payloads or GPS tracks from the third-party service."""
        pass

    @abstractmethod
    async def sync_activities(self, user_id: str) -> Dict[str, Any]:
        """Syncs and ingests recent activities into Loam's activity table."""
        pass

    @abstractmethod
    async def disconnect(self, user_id: str) -> bool:
        """Purges stored tokens/sessions and unlinks the account."""
        pass

    @abstractmethod
    def get_status(self, user_id: str) -> Dict[str, Any]:
        """Returns connection status, last sync timestamp, and feature flag state."""
        pass
