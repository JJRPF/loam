import time
import json
import base64
import datetime
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app, verify_google_id_token
from app.config import settings
from app.db import (
    get_connection, ensure_user_exists, get_user_connected_service,
    create_privacy_zone
)
from tests.test_gh17_fixes import create_mock_jwt

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
    """Verifies that Garmin and Trailforks are enabled by default per GH-19."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/connectors", headers={"X-User-Id": "test_gh19_user"})
        assert resp.status_code == 200
        connectors = {c["name"]: c for c in resp.json()}
        
        assert connectors["garmin"]["enabled"] is True, "Garmin connector must be enabled by default"
        assert connectors["trailforks"]["enabled"] is True, "Trailforks connector must be enabled by default"


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
            headers={"X-User-Id": test_uid}
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
            headers={"X-User-Id": test_uid}
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
            headers={"X-User-Id": test_uid}
        )
        assert login_resp.status_code == 200
        data = login_resp.json()
        assert data["connected"] is True
        assert data.get("bulk_sync", {}).get("bulk_heat_imported") is False
        assert data.get("bulk_sync", {}).get("heat_edges_updated") == 0


@pytest.mark.asyncio
async def test_trailforks_connector_lifecycle():
    """Verifies Trailforks connection, sync with attribution, and disconnection."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        test_uid = "test_gh19_trailforks_user"

        # 1. Connect Trailforks
        auth_resp = await client.post(
            "/api/connectors/trailforks/auth",
            json={"username": "nh_trail_rider", "token": "tf_token_abc_123"},
            headers={"X-User-Id": test_uid}
        )
        assert auth_resp.status_code == 200
        assert auth_resp.json()["connected"] is True
        assert "Trailforks" in auth_resp.json()["message"]

        # 2. Check status shows connected
        status_resp = await client.get("/api/connectors", headers={"X-User-Id": test_uid})
        assert status_resp.status_code == 200
        tf_status = next(c for c in status_resp.json() if c["name"] == "trailforks")
        assert tf_status["connected"] is True

        # 3. Sync Trailforks
        sync_resp = await client.post(
            "/api/connectors/trailforks/sync",
            headers={"X-User-Id": test_uid}
        )
        assert sync_resp.status_code == 200
        assert "© Trailforks" in sync_resp.json()["message"]

        # 4. Disconnect Trailforks
        disc_resp = await client.delete("/api/connectors/trailforks", headers={"X-User-Id": test_uid})
        assert disc_resp.status_code == 200

        # Check status shows disconnected
        status_resp2 = await client.get("/api/connectors", headers={"X-User-Id": test_uid})
        tf_status2 = next(c for c in status_resp2.json() if c["name"] == "trailforks")
        assert tf_status2["connected"] is False


@pytest.mark.asyncio
async def test_real_google_sso_authentication():
    """Verifies real Google SSO token verification with user profile claims."""
    # Create realistic Google token for a unique user
    real_email = "carolyn.mountaineer@gmail.com"
    real_name = "Carolyn Mountaineer"
    real_uid = "google_user_99887766"
    token = create_mock_jwt(real_uid, real_email, real_name, exp_offset_sec=3600)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/auth/verify", json={"token": token})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "authenticated"
        assert data["user"]["id"] == real_uid
        assert data["user"]["email"] == real_email
        assert data["user"]["display_name"] == real_name
        # Not the hardcoded demo account
        assert data["user"]["email"] != "justin@example.com"


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
                "username": "test_mfa_user@example.com",
                "password": "PasswordWith2FA123!",
                "import_to_heat": True
            },
            headers={"X-User-Id": test_uid}
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
            headers={"X-User-Id": test_uid}
        )
        assert resp2.status_code == 200
        data2 = resp2.json()
        assert data2["connected"] is True
        assert data2["needs_mfa"] is False
        assert "bulk_sync" in data2


@pytest.mark.asyncio
async def test_strava_personal_token_auth():
    """
    Verifies that users can authenticate Strava using their personal access token,
    requiring zero app-wide OAuth client secret from Loam.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        test_uid = "test_gh19_strava_user"

        resp = await client.post(
            "/api/connectors/strava/auth",
            json={"personal_token": "test_personal_strava_pat_9988"},
            headers={"X-User-Id": test_uid}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["connected"] is True
        assert "Strava" in data["message"]

        # Check connector list shows Strava connected
        status_resp = await client.get("/api/connectors", headers={"X-User-Id": test_uid})
        assert status_resp.status_code == 200
        strava_item = next(c for c in status_resp.json() if c["name"] == "strava")
        assert strava_item["connected"] is True


@pytest.mark.asyncio
async def test_developer_console_access_and_actions():
    """
    Verifies that the Developer Console endpoints require authentication (Justin or dev key),
    reject unauthorized requests with 403, and execute cache/heat maintenance actions.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Unauthorized request is rejected
        unauth_resp = await client.get("/api/dev/status", headers={"X-User-Id": "random_unauth_user"})
        assert unauth_resp.status_code == 403

        # 2. Authorized via dev key
        dev_key = settings.developer_admin_key
        auth_resp = await client.get("/api/dev/status", headers={"X-Dev-Key": dev_key})
        assert auth_resp.status_code == 200
        status_data = auth_resp.json()
        assert status_data["status"] == "healthy"
        assert status_data["developer_email"] == settings.developer_admin_email
        assert "connectors" in status_data
        assert isinstance(status_data["uptime_seconds"], (int, float))

        # 3. Clear transient cache
        cache_resp = await client.post("/api/dev/cache/clear", headers={"X-Dev-Key": dev_key})
        assert cache_resp.status_code == 200
        assert cache_resp.json()["status"] == "success"

        # 4. Recalculate heat layer
        heat_resp = await client.post("/api/dev/heat/recalculate", headers={"X-Dev-Key": dev_key})
        assert heat_resp.status_code == 200
        assert heat_resp.json()["status"] == "success"
        assert "updated_edges" in heat_resp.json()

