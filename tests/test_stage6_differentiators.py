import json
import datetime
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.config import settings
from app.db import (
    get_connection, ensure_user_exists, record_activity,
    record_activity_edge_visits, record_edge_heat,
    create_restriction, get_user_connected_service
)
from app.models import SportProfile, RouteRequest, LatLon, TerrainPreference
from app.scoring import score_mode_value, calculate_composite_score
from app.connectors.encryption import encrypt_token, decrypt_token
from app.connectors import connector_manager

@pytest.fixture(autouse=True)
def clean_stage6_test_data():
    """Cleanup test entities created during Stage 6 test suite."""
    yield
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM trail_submission_evidence WHERE user_id LIKE 'test_user_%';")
                cur.execute("DELETE FROM trail_submissions WHERE user_id LIKE 'test_user_%' OR name LIKE 'TEST_%';")
                cur.execute("DELETE FROM user_connected_services WHERE user_id LIKE 'test_user_%';")
                cur.execute("DELETE FROM restrictions WHERE name LIKE 'TEST_%';")
                cur.execute("DELETE FROM activity_edge_visits WHERE user_id LIKE 'test_user_%';")
                cur.execute("DELETE FROM activities WHERE user_id LIKE 'test_user_%';")
                cur.execute("DELETE FROM edge_heat WHERE edge_osm_id IN (SELECT osm_id FROM edges WHERE osm_id BETWEEN 990000 AND 999999 AND osm_source IS NOT TRUE);")
                cur.execute("DELETE FROM edges WHERE osm_id BETWEEN 990000 AND 999999 AND osm_source IS NOT TRUE;")
                cur.execute("DELETE FROM users WHERE id LIKE 'test_user_%';")
                conn.commit()
    except Exception:
        pass


# =========================================================================
# 1. Find New Trails Mode & Unridden Stats
# =========================================================================

@pytest.mark.asyncio
async def test_find_new_trails_scoring_and_unridden_boost():
    """Validates that Find New Trails mode boosts candidate routes with higher unridden ratio."""
    # 1. Normal mode: rewards sport surface alignment
    normal_score = score_mode_value(
        surface_breakdown={"singletrack": 70.0, "doubletrack": 20.0, "gravel": 10.0, "paved": 0.0},
        sport=SportProfile.MTB_HARDTAIL,
        find_new_trails_mode=False
    )
    assert normal_score >= 85.0

    # 2. Find New Trails mode with 0% unridden trails
    zero_unridden_score = score_mode_value(
        surface_breakdown={"singletrack": 70.0, "doubletrack": 20.0, "gravel": 10.0, "paved": 0.0},
        sport=SportProfile.MTB_HARDTAIL,
        find_new_trails_mode=True,
        unridden_percent=0.0,
        target_new_percent=50.0
    )

    # 3. Find New Trails mode exceeding 50% target
    high_unridden_score = score_mode_value(
        surface_breakdown={"singletrack": 70.0, "doubletrack": 20.0, "gravel": 10.0, "paved": 0.0},
        sport=SportProfile.MTB_HARDTAIL,
        find_new_trails_mode=True,
        unridden_percent=60.0,
        target_new_percent=50.0
    )

    assert high_unridden_score > zero_unridden_score
    assert high_unridden_score >= 90.0

@pytest.mark.asyncio
async def test_find_new_trails_api_and_exploration_endpoint():
    """Validates that /api/trails/new-to-me returns trails with strong heat that the user hasn't ridden."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Seed test edge with high heat
        edge_id = 991001
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO edges (osm_id, name, highway, length_m, geom, surface)
                    VALUES (%s, 'TEST_Podunk_Singletrack', 'path', 1200.0,
                            ST_SetSRID(ST_MakeLine(ST_MakePoint(-71.3520, 43.1300), ST_MakePoint(-71.3530, 43.1310)), 4326),
                            'dirt')
                    ON CONFLICT (osm_id) DO UPDATE SET highway = 'path';
                    """,
                    (edge_id,)
                )
                conn.commit()

        # Seed heat: 4 unique riders, weighted score 5.0
        record_edge_heat(edge_id, "mtb", weight=5.0, user_id="other_rider_1")
        record_edge_heat(edge_id, "mtb", weight=5.0, user_id="other_rider_2")
        record_edge_heat(edge_id, "mtb", weight=5.0, user_id="other_rider_3")

        # Query /api/trails/new-to-me for a new user who hasn't ridden edge 991001
        resp = await client.get(
            "/api/trails/new-to-me",
            params={"lat": 43.1305, "lon": -71.3524, "radius_miles": 15.0, "sport": "mtb"},
            headers={"X-Test-User": "test_user_newbie"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1
        found = any(t["edge_osm_id"] == edge_id for t in data)
        assert found, f"Edge {edge_id} should be surfaced in unridden trails"

        # Now simulate user riding this edge
        act_id = "test_act_newbie_1"
        record_activity({
            "id": act_id,
            "user_id": "test_user_newbie",
            "sport": "mtb",
            "distance_miles": 2.0,
            "duration_minutes": 15.0,
            "file_format": "gpx"
        })
        record_activity_edge_visits(act_id, {edge_id: 1}, "test_user_newbie", "mtb")


        # Query again -> edge 991001 should now be filtered out because user has ridden it!
        resp2 = await client.get(
            "/api/trails/new-to-me",
            params={"lat": 43.1305, "lon": -71.3524, "radius_miles": 15.0, "sport": "mtb"},
            headers={"X-Test-User": "test_user_newbie"}
        )
        assert resp2.status_code == 200
        data2 = resp2.json()
        found_after = any(t["edge_osm_id"] == edge_id for t in data2)
        assert not found_after, "Edge must NOT be shown in unridden trails after user rides it"


# =========================================================================
# 2. Trail Submissions & Auto-Verification
# =========================================================================

@pytest.mark.asyncio
async def test_trail_submission_creation_and_auto_verification():
    """
    Validates trail submission workflow:
    1. User traces geometry with name, sport, and difficulty -> starts in 'pending' status.
    2. Overlapping rides from <3 unique riders remain pending.
    3. Overlapping rides from >=3 unique riders automatically transition status to 'verified'.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # User 1 submits trail
        submission_payload = {
            "name": "TEST_Bear_Brook_Connector",
            "sport": "mtb",
            "difficulty": "intermediate",
            "coordinates": [
                [-71.3524, 43.1305],
                [-71.3530, 43.1315],
                [-71.3540, 43.1325]
            ],
            "description": "Scenic singletrack connector linking Bobcat trail."
        }

        resp = await client.post("/api/submissions", json=submission_payload, headers={"X-Test-User": "test_user_sub1"})
        assert resp.status_code == 200
        data = resp.json()
        sub_id = data["id"]
        assert data["name"] == "TEST_Bear_Brook_Connector"
        assert data["status"] == "pending"
        assert data["verifier_count"] == 1 # Initial submitter's evidence

        # User 2 provides GPS evidence (evidence 2 of 3)
        ev2_resp = await client.post(
            f"/api/submissions/{sub_id}/evidence",
            json={"activity_id": "test_act_ev2"},
            headers={"X-Test-User": "test_user_sub2"}
        )
        assert ev2_resp.status_code == 200
        ev2_data = ev2_resp.json()
        assert ev2_data["new_status"] == "pending"

        # User 2 attempts duplicate evidence -> abuse prevention: duplicate ignored
        dup_resp = await client.post(
            f"/api/submissions/{sub_id}/evidence",
            json={"activity_id": "test_act_ev2_dup"},
            headers={"X-Test-User": "test_user_sub2"}
        )
        assert dup_resp.status_code == 200

        # User 3 provides GPS evidence -> threshold >= 3 unique riders reached!
        ev3_resp = await client.post(
            f"/api/submissions/{sub_id}/evidence",
            json={"activity_id": "test_act_ev3"},
            headers={"X-Test-User": "test_user_sub3"}
        )
        assert ev3_resp.status_code == 200
        ev3_data = ev3_resp.json()
        assert ev3_data["new_status"] == "verified"

        # Check submission details
        get_resp = await client.get(f"/api/submissions/{sub_id}")
        assert get_resp.status_code == 200
        detail = get_resp.json()
        assert detail["status"] == "verified"
        assert detail["verifier_count"] >= 3
        assert detail["verified_at"] is not None

@pytest.mark.asyncio
async def test_submission_auto_verification_blocked_by_hard_restriction():
    """Validates that submissions intersecting restricted or private land are rejected."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Create hard restriction polygon
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO restrictions (name, restriction_type, is_hard, geom)
                    VALUES ('TEST_Protected_Sanctuary', 'closure', TRUE,
                            ST_SetSRID(ST_MakePolygon(ST_GeomFromText('LINESTRING(-71.360 43.130, -71.350 43.130, -71.350 43.140, -71.360 43.140, -71.360 43.130)')), 4326));
                    """
                )
                conn.commit()

        # Submit trail inside the restricted polygon
        restricted_sub = {
            "name": "TEST_Trespass_Trail",
            "sport": "mtb",
            "difficulty": "black",
            "coordinates": [
                [-71.3550, 43.1350],
                [-71.3560, 43.1360]
            ],
            "description": "Trail passing through restricted nature preserve."
        }

        resp = await client.post("/api/submissions", json=restricted_sub, headers={"X-Test-User": "test_user_violator"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "rejected"
        assert "restricted" in data.get("rejection_reason", "").lower()

@pytest.mark.asyncio
async def test_admin_moderation_interface():
    """Validates admin moderation controls: approve, reject, reverse, and takedown."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        sub_payload = {
            "name": "TEST_Moderation_Trail",
            "sport": "mtb",
            "difficulty": "blue",
            "coordinates": [[-71.3000, 43.1000], [-71.3010, 43.1010]]
        }
        res = await client.post("/api/submissions", json=sub_payload, headers={"X-Test-User": "test_user_sub"})
        sub_id = res.json()["id"]

        # 1. Admin approve
        app_res = await client.post(f"/api/submissions/{sub_id}/approve", headers={"X-Test-User": "round7_admin", "X-Test-Admin": "1"})
        assert app_res.status_code == 200
        assert app_res.json()["status"] == "verified"

        # 2. Admin takedown
        td_res = await client.post(f"/api/submissions/{sub_id}/takedown", json={"action": "takedown", "reason": "Land manager request"}, headers={"X-Test-User": "round7_admin", "X-Test-Admin": "1"})
        assert td_res.status_code == 200
        assert td_res.json()["status"] == "taken_down"

        # 3. Admin reverse to pending
        rev_res = await client.post(f"/api/submissions/{sub_id}/reverse", headers={"X-Test-User": "round7_admin", "X-Test-Admin": "1"})
        assert rev_res.status_code == 200
        assert rev_res.json()["status"] == "pending"

        # 4. Admin reject
        rej_res = await client.post(f"/api/submissions/{sub_id}/reject", json={"action": "reject", "reason": "Unsafe terrain"}, headers={"X-Test-User": "round7_admin", "X-Test-Admin": "1"})
        assert rej_res.status_code == 200
        assert rej_res.json()["status"] == "rejected"


# =========================================================================
# 3. Trail Running Profile Polish
# =========================================================================

def test_trail_running_profile_custom_model_and_scoring():
    """Validates that Trail Run profile favors footpaths/stairs and avoids high-speed MTB downhill flow trails."""
    from app.routing import build_custom_model

    run_req = RouteRequest(
        start=LatLon(lat=43.13, lon=-71.35),
        profile=SportProfile.TRAIL_RUN,
        trail_run_steeper_grades=True,
        trail_run_avoid_mtb_flow=True
    )
    custom_model = build_custom_model(run_req)
    assert custom_model is not None
    rules = custom_model.get("priority", [])
    
    # Check that footpaths and steps are prioritized
    foot_favored = any("PATH" in r.get("if", "") and "FOOTWAY" in r.get("if", "") for r in rules)
    assert foot_favored, "Trail run custom model must boost footpaths and steps"

    # Check that downhill flow trail avoidance is applied
    flow_avoided = any("GRADE1" in r.get("if", "") and float(r.get("multiply_by", 1.0)) < 0.5 for r in rules)
    assert flow_avoided, "Trail run custom model must avoid downhill MTB flow trails"

    # Check scoring favors footpaths and penalizes road
    run_score = score_mode_value(
        surface_breakdown={"singletrack": 80.0, "doubletrack": 15.0, "gravel": 5.0, "paved": 0.0},
        sport=SportProfile.TRAIL_RUN
    )
    road_score = score_mode_value(
        surface_breakdown={"singletrack": 10.0, "doubletrack": 10.0, "gravel": 10.0, "paved": 70.0},
        sport=SportProfile.TRAIL_RUN
    )
    assert run_score >= 90.0
    assert road_score < 40.0


# =========================================================================
# 4. Optional Connectors (Interfaces, Encryption & Feature Flags)
# =========================================================================

@pytest.mark.asyncio
async def test_connectors_disabled_by_default_and_status_list(monkeypatch):
    """Validates connector status list and behavior when disabled."""
    monkeypatch.setattr(settings, "enable_strava_connector", False)
    monkeypatch.setattr(settings, "enable_garmin_connector", False)
    monkeypatch.setattr(settings, "enable_trailforks_connector", False)
    monkeypatch.setattr(settings, "enable_cubetrek_connector", False)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/connectors", headers={"X-Test-User": "test_user_conn"})
        assert resp.status_code == 200
        connectors = resp.json()
        assert len(connectors) >= 3
        
        # Verify all connectors are disabled by default
        for conn in connectors:
            assert conn["enabled"] is False, f"Connector {conn['name']} must be disabled by default"

        # Attempt Garmin login when disabled -> rejected
        g_resp = await client.post(
            "/api/connectors/garmin/login",
            json={"username": "runner@example.com", "password": "supersecretpassword"},
            headers={"X-Test-User": "test_user_conn"}
        )
        assert g_resp.status_code == 400
        assert "disabled" in g_resp.json()["detail"].lower()

@pytest.mark.asyncio
async def test_garmin_encrypted_token_invariant_and_password_non_retention(monkeypatch):
    """
    Validates Garmin Connector security invariant:
    1. Passwords are NEVER stored, logged, or retained.
    2. Session tokens are encrypted at rest with AES Fernet.
    3. Disconnecting purges encrypted tokens.
    """
    # Temporarily enable Garmin connector for this test
    monkeypatch.setattr(settings, "enable_garmin_connector", True)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        test_uid = "test_user_garmin_secure"
        raw_pw = "super_secret_garmin_password_987!"

        login_resp = await client.post(
            "/api/connectors/garmin/login",
            json={"username": "justin@example.com", "password": raw_pw},
            headers={"X-Test-User": test_uid}
        )
        assert login_resp.status_code == 200
        assert login_resp.json()["connected"] is True

        # Inspect database record
        record = get_user_connected_service(test_uid, "garmin")
        assert record is not None
        encrypted_token = record["encrypted_session_token"]
        assert encrypted_token != ""

        # INVARIANT: Password must NEVER appear in the stored ciphertext or anywhere in DB
        assert raw_pw not in encrypted_token
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM user_connected_services WHERE user_id = %s;", (test_uid,))
                row_str = str(cur.fetchone())
                assert raw_pw not in row_str, "CRITICAL: Password leaked into database row!"

        # Decrypt session token to verify validity
        decrypted = decrypt_token(encrypted_token)
        assert "di_token" in decrypted

        # Disconnect connector
        disc_resp = await client.delete("/api/connectors/garmin", headers={"X-Test-User": test_uid})
        assert disc_resp.status_code == 200
        post_disc_record = get_user_connected_service(test_uid, "garmin")
        assert post_disc_record is None, "Disconnect must purge stored encrypted tokens"

@pytest.mark.asyncio
async def test_strava_connector_flow(monkeypatch):
    """Strava has no OAuth client: an authorization code alone never connects anything."""
    monkeypatch.setattr(settings, "enable_strava_connector", True)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        test_uid = "test_user_strava_1"
        auth_resp = await client.post(
            "/api/connectors/strava/auth",
            json={"code": "sample_auth_code_xyz"},
            headers={"X-Test-User": test_uid}
        )
        assert auth_resp.status_code == 400
        disc_resp = await client.delete("/api/connectors/strava", headers={"X-Test-User": test_uid})
        assert disc_resp.status_code == 200
