import pytest
import datetime
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.db import (
    get_connection, ensure_user_exists, get_user_connected_service,
    save_user_connected_service, delete_user_connected_service
)
from app.connectors.encryption import decrypt_token, encrypt_token

@pytest.fixture(autouse=True)
def clean_gh22_test_data():
    """Cleanup test data created during GH-22 test suite."""
    yield
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM user_connected_services WHERE user_id LIKE 'test_gh22_%';")
                cur.execute("DELETE FROM activity_edge_visits WHERE user_id LIKE 'test_gh22_%';")
                cur.execute("DELETE FROM activities WHERE user_id LIKE 'test_gh22_%';")
                cur.execute("DELETE FROM privacy_zones WHERE user_id LIKE 'test_gh22_%';")
                cur.execute("DELETE FROM users WHERE id LIKE 'test_gh22_%';")
                conn.commit()
    except Exception:
        pass


@pytest.mark.asyncio
async def test_garmin_connector_status_and_defaults():
    """Verifies that Garmin Connect connector is listed, enabled, and disconnected initially."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        test_uid = "test_gh22_user_init"
        resp = await client.get("/api/connectors", headers={"X-User-Id": test_uid})
        assert resp.status_code == 200
        data = resp.json()
        garmin = next((c for c in data if c["name"] == "garmin"), None)
        assert garmin is not None
        assert garmin["enabled"] is True
        assert garmin["connected"] is False
        assert "Garmin Connect" in garmin["display_name"]


@pytest.mark.asyncio
async def test_garmin_mfa_challenge_and_verification():
    """
    Verifies that when Garmin returns a 2FA requirement:
    1. /api/connectors/garmin/login returns needs_mfa=True with an mfa_session_id.
    2. /api/connectors/garmin/verify-mfa accepts the code and transitions to connected=True.
    3. Session tokens persist in PostGIS under 'Data lives once' rule.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        test_uid = "test_gh22_rider_mfa"
        raw_pw = "GarminTestPassword456!"

        # Step 1: Submit credentials, expect 2FA prompt
        login_resp = await client.post(
            "/api/connectors/garmin/login",
            json={
                "username": "test_mfa_user@example.com",
                "password": raw_pw,
                "import_to_heat": True
            },
            headers={"X-User-Id": test_uid}
        )
        assert login_resp.status_code == 200
        login_data = login_resp.json()
        assert login_data["needs_mfa"] is True
        assert login_data["connected"] is False
        assert "mfa_session_id" in login_data
        session_id = login_data["mfa_session_id"]

        # Step 2: Complete 2FA verification
        verify_resp = await client.post(
            "/api/connectors/garmin/verify-mfa",
            json={
                "mfa_session_id": session_id,
                "mfa_code": "842109",
                "import_to_heat": True
            },
            headers={"X-User-Id": test_uid}
        )
        assert verify_resp.status_code == 200
        verify_data = verify_resp.json()
        assert verify_data["connected"] is True
        assert verify_data["needs_mfa"] is False
        assert "bulk_sync" in verify_data
        assert verify_data["bulk_sync"]["status"] == "success"

        # Step 3: Verify Data lives once rule and password safety
        record = get_user_connected_service(test_uid, "garmin")
        assert record is not None
        assert record["is_active"] is True
        enc_token = record["encrypted_session_token"]
        assert enc_token != ""

        # INVARIANT: Password must NEVER appear in DB or ciphertext
        assert raw_pw not in enc_token
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM user_connected_services WHERE user_id = %s;", (test_uid,))
                row_str = str(cur.fetchone())
                assert raw_pw not in row_str, "CRITICAL: Password leaked into database!"

        # Decrypt token
        dec = decrypt_token(enc_token)
        assert "garmin_session" in dec or "di_token" in dec

        # Step 4: Disconnect purges tokens
        disc_resp = await client.delete("/api/connectors/garmin", headers={"X-User-Id": test_uid})
        assert disc_resp.status_code == 200
        post_disc_record = get_user_connected_service(test_uid, "garmin")
        assert post_disc_record is None, "Disconnect must purge stored encrypted token"


@pytest.mark.asyncio
async def test_garmin_mfa_error_handling():
    """Verifies proper error responses for invalid or expired MFA sessions."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        test_uid = "test_gh22_err_user"

        # Non-existent session
        bad_sess_resp = await client.post(
            "/api/connectors/garmin/verify-mfa",
            json={
                "mfa_session_id": "non_existent_session_id",
                "mfa_code": "123456",
                "import_to_heat": True
            },
            headers={"X-User-Id": test_uid}
        )
        assert bad_sess_resp.status_code == 400
        assert "expired or invalid" in bad_sess_resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_garmin_activity_filtering_and_classification():
    """Verifies that non-trail activities (breathwork, gym, stationary, resort ski) are excluded."""
    from app.connectors.garmin import classify_garmin_sport, GarminConnector, EXCLUDED_ACTIVITY_TYPES
    from app.connectors.manager import connector_manager

    # 1. Classification & Exclusions
    assert classify_garmin_sport("breathwork") is None
    assert classify_garmin_sport("breathing") is None
    assert classify_garmin_sport("indoor_climbing") is None
    assert classify_garmin_sport("strength_training") is None
    assert classify_garmin_sport("treadmill_running") is None
    assert classify_garmin_sport("indoor_cycling") is None
    assert classify_garmin_sport("virtual_ride") is None
    assert classify_garmin_sport("resort_skiing") is None
    assert classify_garmin_sport("golf") is None
    assert classify_garmin_sport("stop_watch") is None
    assert classify_garmin_sport("incident_detected") is None

    # 2. Included Outdoor Sports
    assert classify_garmin_sport("mountain_biking") == "mtb"
    assert classify_garmin_sport("e_bike_mountain") == "mtb"
    assert classify_garmin_sport("cycling") == "mtb"
    assert classify_garmin_sport("e_bike_fitness") == "mtb"
    assert classify_garmin_sport("trail_running") == "trail_run"
    assert classify_garmin_sport("running") == "trail_run"
    assert classify_garmin_sport("hiking") == "trail_run"
    assert classify_garmin_sport("walking") == "trail_run"

    # 3. Idempotent bulk-import test with mock connector
    test_uid = "test_gh22_idempotent_user"
    save_user_connected_service(
        user_id=test_uid,
        provider="garmin",
        encrypted_token=encrypt_token("mock_garmin_token")
    )
    garmin = connector_manager.get_connector("garmin")
    assert garmin is not None

    # First sync
    res1 = await garmin.sync_activities(test_uid, import_to_heat=True)
    assert res1["status"] == "success"
    imported1 = res1["activities_imported"]
    assert imported1 == 3

    # Second sync (idempotent, updating rather than duplicating rows)
    res2 = await garmin.sync_activities(test_uid, import_to_heat=True)
    assert res2["status"] == "success"
    assert res2["activities_imported"] == 3

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM activities WHERE user_id = %s;", (test_uid,))
            count = cur.fetchone()[0]
            assert count == 3, f"Expected 3 activities without duplicates, found {count}"
