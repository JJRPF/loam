import os
from pydantic import BaseModel

DEFAULT_CONNECTOR_SECRET_KEY = "loam_dev_secret_key_32bytes_min_len!"


def _csv(value: str) -> list:
    return [v.strip() for v in value.split(",") if v.strip()]


class Settings(BaseModel):
    app_name: str = "Loam Trail Route Builder"
    app_version: str = "0.1.0"

    # production | development | test
    loam_env: str = os.getenv("LOAM_ENV", "development").strip().lower()

    # GraphHopper service URL
    graphhopper_url: str = os.getenv("GRAPHHOPPER_URL", "http://localhost:8989")

    # PostGIS database URL
    database_url: str = os.getenv("DATABASE_URL", "postgresql://loam:loam_dev_pw@localhost:5432/loam")

    # Elevation Provider
    elevation_provider: str = os.getenv("ELEVATION_PROVIDER", "usgs_3dep")

    # Port & Host
    host: str = os.getenv("HOST", "0.0.0.0")
    port: int = int(os.getenv("PORT", "8080"))

    # Authentication (Firebase Auth on GCP project `thepfisters`)
    firebase_project_id: str = os.getenv("FIREBASE_PROJECT_ID", "thepfisters")
    admin_emails: list = _csv(os.getenv("ADMIN_EMAILS", ""))
    cors_origins: list = _csv(os.getenv(
        "CORS_ORIGINS",
        "https://core-node.tailcd5892.ts.net,http://localhost:5173",
    ))

    # Feature Flags & Connector Configuration
    enable_strava_connector: bool = os.getenv("ENABLE_STRAVA_CONNECTOR", "true").lower() in ("true", "1")
    enable_garmin_connector: bool = os.getenv("ENABLE_GARMIN_LOGIN_CONNECTOR", "true").lower() in ("true", "1")
    enable_trailforks_connector: bool = os.getenv("ENABLE_TRAILFORKS_CONNECTOR", "true").lower() in ("true", "1")
    enable_cubetrek_connector: bool = os.getenv("ENABLE_CUBETREK_CONNECTOR", "true").lower() in ("true", "1")
    connector_secret_key: str = os.getenv("CONNECTOR_SECRET_KEY", DEFAULT_CONNECTOR_SECRET_KEY)


settings = Settings()


def check_production_config(s: Settings = settings) -> None:
    """Refuses to start a production server with development secrets."""
    if s.loam_env != "production":
        return
    if s.connector_secret_key == DEFAULT_CONNECTOR_SECRET_KEY:
        raise RuntimeError(
            "CONNECTOR_SECRET_KEY is the in-code development default; set a real key in the production .env"
        )
