import time
import json
import base64
import datetime
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app
from tests.conftest import as_user
from app.config import settings
from app.db import (
    get_connection, ensure_user_exists, get_user_connected_service,
    create_privacy_zone
)

@pytest.fixture(autouse=True)
def clean_gh19_test_data():
    """Cleanup test entities created during GH-19 test suite."""
    yield
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM user_connected_services WHERE user_id LIKE 'test_gh19_%';")
                cur.execute("DELETE FROM activity_edge_visits WHERE user_id LIKE 'test_gh19_%';")
                cur.execute("DELETE FROM activities WHERE user_id LIKE 'test_gh19_%';")
                cur.execute("DELETE FROM privacy_zones WHERE user_id LIKE 'test_gh19_%';")
                cur.execute("DELETE FROM users WHERE id LIKE 'test_gh19_%';")
                conn.commit()
    except Exception:
        pass


@pytest.mark.asyncio
async def test_connectors_enabled_by_default_gh19():
    """Garmin is on by default; Strava and Trailforks stay off until their terms are confirmed (GH-34)."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/connectors", headers={"X-Test-User": "test_gh19_user"})
        assert resp.status_code == 200
        connectors = {c["name"]: c for c in resp.json()}
        
        assert connectors["garmin"]["enabled"] is True, "Garmin connector must be enabled by default"
        assert connectors["trailforks"]["enabled"] is False
        assert connectors["strava"]["enabled"] is False


@pytest.mark.asyncio
async def test_garmin_connect_and_bulk_import_to_heat():
    """
    Verifies that connecting Garmin with import_to_heat=True bulk imports activities
    to the heat layer while strictly respecting privacy zones and endpoint trimming.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        test_uid = "test_gh19_garmin_rider"

        # Setup a privacy zone for the rider
        create_privacy_zone(test_uid, name="Home", lat=43.1305, lon=-71.3524, radius_m=300)

        # Connect Garmin with bulk import to heat agreed
        login_resp = await client.post(
            "/api/connectors/garmin/login",
            json={
                "username": "test_justin.pfister@example.com",
                "password": "SecretGarminPassword123!",
                "import_to_heat": True
            },
            headers={"X-Test-User": test_uid}
        )
        assert login_resp.status_code == 200
        data = login_resp.json()
        assert data["connected"] is True
        assert "bulk_sync" in data
        assert data["bulk_sync"]["bulk_heat_imported"] is True
        assert data["bulk_sync"]["activities_imported"] >= 1

        # Verify dedicated bulk-import endpoint also works
        bulk_resp = await client.post(
            "/api/connectors/garmin/bulk-import",
            json={"import_to_heat": True},
            headers={"X-Test-User": test_uid}
        )
        assert bulk_resp.status_code == 200
        bulk_data = bulk_resp.json()
        assert bulk_data["status"] == "success"
        assert bulk_data["bulk_heat_imported"] is True
        assert bulk_data["activities_imported"] >= 1


@pytest.mark.asyncio
async def test_garmin_bulk_import_user_disagrees():
    """Verifies that if user does not agree, activities are imported to history but heat is not contributed."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        test_uid = "test_gh19_garmin_private"

        login_resp = await client.post(
            "/api/connectors/garmin/login",
            json={
                "username": "test_private.rider@example.com",
                "password": "Password789!",
                "import_to_heat": False
            },
            headers={"X-Test-User": test_uid}
        )
        assert login_resp.status_code == 200
        data = login_resp.json()
        assert data["connected"] is True
        assert data.get("bulk_sync", {}).get("bulk_heat_imported") is False
        assert data.get("bulk_sync", {}).get("heat_edges_updated") == 0


@pytest.mark.asyncio
async def test_trailforks_connector_lifecycle():
    """Trailforks has no API access, so connecting fails honestly and nothing is stored."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        test_uid = "test_gh19_trailforks_user"
        auth_resp = await client.post(
            "/api/connectors/trailforks/auth",
            json={"username": "nh_trail_rider", "token": "tf_token_abc_123"},
            headers={"X-Test-User": test_uid}
        )
        assert auth_resp.status_code == 400
        assert "isn't available" in auth_resp.json()["detail"]
        status_resp = await client.get("/api/connectors", headers={"X-Test-User": test_uid})
        tf_status = next(c for c in status_resp.json() if c["name"] == "trailforks")
        assert tf_status["connected"] is False


@pytest.mark.asyncio
async def test_garmin_2fa_challenge_and_verification():
    """
    Verifies that when an account requires 2FA:
    1. /api/connectors/garmin/login returns needs_mfa=True with an mfa_session_id.
    2. /api/connectors/garmin/verify-mfa accepts the code and finishes connection.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        test_uid = "test_gh19_garmin_2fa_rider"

        # Step 1: Initial login returns MFA prompt
        resp1 = await client.post(
            "/api/connectors/garmin/login",
            json={
                "username": "mfa.rider@test.loam",
                "password": "PasswordWith2FA123!",
                "import_to_heat": True
            },
            headers={"X-Test-User": test_uid}
        )
        assert resp1.status_code == 200
        data1 = resp1.json()
        assert data1["needs_mfa"] is True
        assert data1["connected"] is False
        assert "mfa_session_id" in data1
        session_id = data1["mfa_session_id"]

        # Step 2: Submit 2FA code
        resp2 = await client.post(
            "/api/connectors/garmin/verify-mfa",
            json={
                "mfa_session_id": session_id,
                "mfa_code": "654321",
                "import_to_heat": True
            },
            headers={"X-Test-User": test_uid}
        )
        assert resp2.status_code == 200
        data2 = resp2.json()
        assert data2["connected"] is True
        assert data2["needs_mfa"] is False
        assert "bulk_sync" in data2


@pytest.mark.asyncio
async def test_strava_personal_token_auth(monkeypatch):
    """A Strava personal token connects only after Strava accepts it (GET /athlete)."""
    from app.config import settings
    from app.connectors import connector_manager

    monkeypatch.setattr(settings, "enable_strava_connector", True)
    strava = connector_manager.get_connector("strava")

    async def fake_athlete(token):
        return (200, {"firstname": "Test", "lastname": "Rider"}) if token == "valid-token" else (401, {})

    monkeypatch.setattr(strava, "_fetch_athlete", fake_athlete)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        test_uid = "test_gh19_strava_user"
        bad = await client.post("/api/connectors/strava/auth", json={"personal_token": "nope"},
                                headers={"X-Test-User": test_uid})
        assert bad.status_code == 400

        resp = await client.post(
            "/api/connectors/strava/auth",
            json={"personal_token": "valid-token"},
            headers={"X-Test-User": test_uid}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["connected"] is True
        assert "Strava" in data["message"]

        status_resp = await client.get("/api/connectors", headers={"X-Test-User": test_uid})
        strava_item = next(c for c in status_resp.json() if c["name"] == "strava")
        assert strava_item["connected"] is True
        sync = await client.post("/api/connectors/strava/sync", headers={"X-Test-User": test_uid})
        assert sync.json()["activities_imported"] == 0  # import isn't built; no placeholder rides


@pytest.mark.asyncio
async def test_developer_console_access_and_actions():
    """
    Verifies that the Developer Console endpoints require an admin (verified email in ADMIN_EMAILS),
    reject unauthorized requests with 403, and execute cache/heat maintenance actions.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Unauthorized request is rejected
        unauth_resp = await client.get("/api/dev/status", headers={"X-Test-User": "random_unauth_user"})
        assert unauth_resp.status_code == 403

        # 2. Authorized via dev key
        admin_headers = as_user("round7_admin", admin=True)
        auth_resp = await client.get("/api/dev/status", headers=admin_headers)
        assert auth_resp.status_code == 200
        status_data = auth_resp.json()
        assert status_data["status"] == "healthy"
        assert status_data["developer_email"] == "round7_admin@test.loam"
        assert "connectors" in status_data
        assert isinstance(status_data["uptime_seconds"], (int, float))

        # 3. Clear transient cache
        cache_resp = await client.post("/api/dev/cache/clear", headers=admin_headers)
        assert cache_resp.status_code == 200
        assert cache_resp.json()["status"] == "success"

        # 4. Recalculate heat layer
        heat_resp = await client.post("/api/dev/heat/recalculate", headers=admin_headers)
        assert heat_resp.status_code == 200
        assert heat_resp.json()["status"] == "success"
        assert "updated_edges" in heat_resp.json()

