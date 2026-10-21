"""Test-mode auth: production code only trusts verified Firebase ID tokens.

With LOAM_ENV=test, the autouse fixture below overrides the auth dependencies so a test can act
as a user by sending `X-Test-User: <uid>` (plus `X-Test-Admin: 1` for an admin). This lives
only in the test suite; nothing in `app/` reads these headers. Tests of real token
verification use the `real_auth` fixture, which removes the overrides.
"""
import os

os.environ.setdefault("LOAM_ENV", "test")
# Data lives once, under the base clone: <dev>/loam/main/data (grove layout).
_main_data = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "main", "data")
if os.path.isdir(_main_data):
    os.environ.setdefault("DATA_DIR", _main_data)

from typing import Optional  # noqa: E402

import pytest  # noqa: E402
from fastapi import Request  # noqa: E402

from app.auth import AuthUser, get_current_user, get_optional_user  # noqa: E402
from app.config import settings  # noqa: E402
from app.db import ensure_user_exists  # noqa: E402
from app.main import app  # noqa: E402
from app.migrations import apply_migrations  # noqa: E402

def _graphhopper_up() -> bool:
    import httpx

    try:
        return httpx.get(f"{settings.graphhopper_url}/health", timeout=2).status_code == 200
    except Exception:
        return False


def _osm_graph_imported() -> bool:
    try:
        from app.db import get_connection

        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT EXISTS (SELECT 1 FROM trail_segments)")
            return bool(cur.fetchone()[0])
    except Exception:
        return False


# CI has no OSM extract, so no GraphHopper graph and no imported trail network. The checks run at
# test setup (after the migrations), not at import.
requires_graphhopper = pytest.mark.requires_graphhopper
requires_osm_graph = pytest.mark.requires_osm_graph


def pytest_configure(config):
    config.addinivalue_line("markers", "requires_graphhopper: skipped when GraphHopper is not running")
    config.addinivalue_line("markers", "requires_osm_graph: skipped when the OSM trail network is not imported")


@pytest.fixture(autouse=True)
def _skip_without_live_stack(request, _migrated_db):
    if request.node.get_closest_marker("requires_graphhopper") and not _graphhopper_up():
        pytest.skip("GraphHopper is not running")
    if request.node.get_closest_marker("requires_osm_graph") and not _osm_graph_imported():
        pytest.skip("OSM trail network not imported (python -m scripts.import_osm_graph)")


TEST_USER_HEADER = "X-Test-User"
TEST_ADMIN_HEADER = "X-Test-Admin"


def make_test_user(uid: str, admin: bool = False) -> AuthUser:
    return AuthUser(
        uid=uid,
        email=f"{uid}@test.loam",
        email_verified=True,
        name=uid,
        picture=None,
        sign_in_provider="google.com",
        is_admin=admin,
    )


def _test_optional_user(request: Request) -> Optional[AuthUser]:
    uid = request.headers.get(TEST_USER_HEADER)
    if not uid:
        return None
    user = make_test_user(uid, admin=request.headers.get(TEST_ADMIN_HEADER) == "1")
    ensure_user_exists(user.uid, email=user.email, display_name=user.name)
    return user


def _test_current_user(request: Request) -> AuthUser:
    from fastapi import HTTPException

    user = _test_optional_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Sign in required")
    return user


@pytest.fixture(scope="session", autouse=True)
def _migrated_db():
    try:
        apply_migrations()
    except Exception as e:  # DB not running: DB-backed tests fail on their own
        print(f"migrations not applied: {e}")


@pytest.fixture(autouse=True)
def _fresh_rate_limits():
    from app.ratelimit import limiter
    limiter.reset()
    yield


@pytest.fixture(autouse=True)
def _test_auth_overrides():
    assert settings.loam_env == "test", "test auth overrides need LOAM_ENV=test"
    app.dependency_overrides[get_current_user] = _test_current_user
    app.dependency_overrides[get_optional_user] = _test_optional_user
    yield
    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(get_optional_user, None)


@pytest.fixture(autouse=True)
def _no_live_garmin(monkeypatch):
    """Garmin Connect is never contacted from tests; the connector talks to tests.fakes.FakeGarmin."""
    import garminconnect

    from tests.fakes import FakeGarmin

    monkeypatch.setattr(garminconnect, "Garmin", FakeGarmin)


@pytest.fixture
def real_auth():
    """Runs a test against the production auth dependencies (no overrides)."""
    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(get_optional_user, None)
    yield


def as_user(uid: str, admin: bool = False) -> dict:
    headers = {TEST_USER_HEADER: uid}
    if admin:
        headers[TEST_ADMIN_HEADER] = "1"
    return headers
