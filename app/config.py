import os
from pydantic import BaseModel

DEFAULT_CONNECTOR_SECRET_KEY = "loam_dev_secret_key_32bytes_min_len!"


def _csv(value: str) -> list:
    return [v.strip() for v in value.split(",") if v.strip()]


def resolve_env() -> str:
    """APP_ENV and LOAM_ENV are one setting; "production" in either wins."""
    app_env, loam_env = os.getenv("APP_ENV", "").strip().lower(), os.getenv("LOAM_ENV", "").strip().lower()
    return "production" if "production" in (app_env, loam_env) else (app_env or loam_env or "development")


class Settings(BaseModel):
    app_name: str = "Loam Trail Route Builder"
    app_version: str = "0.1.0"

    # production | development | test. APP_ENV and LOAM_ENV are the same setting; "production" in either wins.
    loam_env: str = resolve_env()

    # GraphHopper service URL
    graphhopper_url: str = os.getenv("GRAPHHOPPER_URL", "http://localhost:8989")

    # PostGIS database URL
    database_url: str = os.getenv("DATABASE_URL", "postgresql://loam:loam_dev_pw@localhost:5432/loam")

    # Elevation: USGS 3DEP 1/3 arc-second tiles (scripts/fetch_3dep.py)
    elevation_provider: str = os.getenv("ELEVATION_PROVIDER", "usgs_3dep")
    dem_dir: str = os.getenv("DEM_DIR") or os.path.join(
        os.getenv("DATA_DIR", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")),
        "elevation", "3dep13")

    # "Report bad route" files GitHub issues with this fine-grained PAT (Issues read/write on one repo).
    github_feedback_token: str = os.getenv("GITHUB_FEEDBACK_TOKEN", "")
    github_feedback_repo: str = os.getenv("GITHUB_FEEDBACK_REPO", "JJRPF/loam")

    # Port & Host
    host: str = os.getenv("HOST", "0.0.0.0")
    port: int = int(os.getenv("PORT", "8080"))

    # Authentication (Firebase Auth on GCP project `thepfisters`)
    firebase_project_id: str = os.getenv("FIREBASE_PROJECT_ID", "thepfisters")
    # Local browser tests only: the Firebase Auth emulator (host:port). Never honoured in production or on a
    # server that is not bound to loopback (see check_auth_emulator_config).
    auth_emulator_host: str = os.getenv("FIREBASE_AUTH_EMULATOR_HOST", "").strip()
    admin_emails: list = _csv(os.getenv("ADMIN_EMAILS", ""))
    cors_origins: list = _csv(os.getenv(
        "CORS_ORIGINS",
        "https://loam.thepfisters.com,https://core-node.tailcd5892.ts.net,http://localhost:5173",
    ))
    # Where the web app lives (Firebase Hosting). When set, browser navigations that reach the API's own
    # public host (the Tailscale Funnel) are redirected there. Unset in dev; LAN hosts are never redirected.
    public_app_origin: str = os.getenv("PUBLIC_APP_ORIGIN", "").strip().rstrip("/")
    api_public_host: str = os.getenv("API_PUBLIC_HOST", "core-node.tailcd5892.ts.net").strip().lower()

    # Feature Flags & Connector Configuration
    # Strava and Trailforks stay off until their current terms are confirmed (plan section 10.7).
    enable_strava_connector: bool = os.getenv("ENABLE_STRAVA_CONNECTOR", "false").lower() in ("true", "1")
    enable_garmin_connector: bool = os.getenv("ENABLE_GARMIN_LOGIN_CONNECTOR", "true").lower() in ("true", "1")
    enable_trailforks_connector: bool = os.getenv("ENABLE_TRAILFORKS_CONNECTOR", "false").lower() in ("true", "1")
    enable_cubetrek_connector: bool = os.getenv("ENABLE_CUBETREK_CONNECTOR", "true").lower() in ("true", "1")
    connector_secret_key: str = os.getenv("CONNECTOR_SECRET_KEY", DEFAULT_CONNECTOR_SECRET_KEY)

    # Heat privacy: an edge's heat is public (shown to others, influences their routes) with at
    # least this many unique riders, or as seed heat (the owner's imported rides) on trail-class edges.
    heat_min_unique_riders: int = int(os.getenv("HEAT_MIN_UNIQUE_RIDERS", "3"))
    # Rate limits ("count/window seconds", per Firebase uid or client IP), env RATE_LIMIT_<NAME>.
    rate_limits: dict = {
        "route": os.getenv("RATE_LIMIT_ROUTE", "20/600"),          # route, options, stream
        "geocode": os.getenv("RATE_LIMIT_GEOCODE", "60/60"),
        "upload": os.getenv("RATE_LIMIT_UPLOAD", "30/3600"),
        "flag": os.getenv("RATE_LIMIT_FLAG", "60/3600"),           # flags, check-ins, votes
    }
    report_daily_limit_global: int = int(os.getenv("RATE_LIMIT_REPORTS_GLOBAL_DAILY", "30"))
    route_concurrency: int = int(os.getenv("ROUTE_CONCURRENCY", "2"))
    route_wait_s: float = float(os.getenv("ROUTE_WAIT_S", "20"))

    # One User-Agent for every outbound request to third parties (NWS, Overpass, Photon, GitHub, ...).
    user_agent: str = "Loam/1.0 (+https://loam.thepfisters.com; jjrpfister@gmail.com)"

    # Midpoints produce out-and-backs for now: off in production (the Pi), on for development.
    enable_midpoints: bool = os.getenv("ENABLE_MIDPOINTS", "false").lower() in ("true", "1")
    source_url: str = "https://github.com/JJRPF/loam"
    seed_heat_public: bool = os.getenv("SEED_HEAT_PUBLIC", "true").lower() in ("true", "1")


settings = Settings()


LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1")


def check_auth_emulator_config(s: Settings = settings) -> None:
    """The Auth emulator issues unsigned tokens, so it may only be on for a local, non-production server."""
    if not s.auth_emulator_host:
        return
    if s.loam_env == "production":
        raise RuntimeError("FIREBASE_AUTH_EMULATOR_HOST is set with APP_ENV=production; refusing to start")
    if s.host not in LOOPBACK_HOSTS:
        raise RuntimeError(
            "FIREBASE_AUTH_EMULATOR_HOST needs the server bound to loopback (HOST=127.0.0.1); refusing to start"
        )


def check_production_config(s: Settings = settings) -> None:
    """Refuses to start a production server with development secrets."""
    check_auth_emulator_config(s)
    if s.loam_env != "production":
        return
    if s.connector_secret_key == DEFAULT_CONNECTOR_SECRET_KEY:
        raise RuntimeError(
            "CONNECTOR_SECRET_KEY is the in-code development default; set a real key in the production .env"
        )
