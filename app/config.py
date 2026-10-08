import os
from pydantic import BaseModel

class Settings(BaseModel):
    app_name: str = "Loam Trail Route Builder"
    app_version: str = "0.1.0"
    
    # GraphHopper service URL
    graphhopper_url: str = os.getenv("GRAPHHOPPER_URL", "http://localhost:8989")
    
    # PostGIS database URL
    database_url: str = os.getenv("DATABASE_URL", "postgresql://loam:loam_dev_pw@localhost:5432/loam")
    
    # Elevation Provider
    elevation_provider: str = os.getenv("ELEVATION_PROVIDER", "usgs_3dep")
    
    # Port & Host
    host: str = os.getenv("HOST", "0.0.0.0")
    port: int = int(os.getenv("PORT", "8080"))

    # Feature Flags & Connector Configuration (Enabled per GH-19)
    enable_strava_connector: bool = os.getenv("ENABLE_STRAVA_CONNECTOR", "false").lower() in ("true", "1")
    enable_garmin_connector: bool = os.getenv("ENABLE_GARMIN_LOGIN_CONNECTOR", "true").lower() in ("true", "1")
    enable_trailforks_connector: bool = os.getenv("ENABLE_TRAILFORKS_CONNECTOR", "true").lower() in ("true", "1")
    connector_secret_key: str = os.getenv("CONNECTOR_SECRET_KEY", "loam_dev_secret_key_32bytes_min_len!")

settings = Settings()

