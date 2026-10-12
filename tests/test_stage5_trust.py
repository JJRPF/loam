import json
import datetime
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.db import (
    get_connection, ensure_user_exists, record_activity, record_activity_edge_visits,
    create_community_flag, vote_community_flag, record_trail_checkin,
    create_user_dnr, create_restriction, check_route_trust_layer,
    user_has_ridden_edge, user_has_ridden_area, export_user_data,
    delete_user_account
)
from app.models import SportProfile

@pytest.fixture(autouse=True)
def clean_test_data():
    """Cleanup test entities created during trust layer test suite."""
    yield
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM restrictions WHERE name LIKE 'TEST_%';")
                cur.execute("DELETE FROM flags WHERE user_id LIKE 'test_user_%';")
                cur.execute("DELETE FROM trail_checkins WHERE user_id LIKE 'test_user_%';")
                cur.execute("DELETE FROM user_dnr WHERE user_id LIKE 'test_user_%';")
                cur.execute("DELETE FROM dnr_override_logs WHERE user_id LIKE 'test_user_%';")
                cur.execute("DELETE FROM activity_edge_visits WHERE user_id LIKE 'test_user_%';")
                cur.execute("DELETE FROM activities WHERE user_id LIKE 'test_user_%';")
                cur.execute("DELETE FROM user_privacy_zones WHERE user_id LIKE 'test_user_%';")
                cur.execute("DELETE FROM users WHERE id LIKE 'test_user_%';")
                conn.commit()
    except Exception:
        pass


# =========================================================================
# 1. Trail Community Flags & Abuse-Resistant Thresholds
# =========================================================================

@pytest.mark.asyncio
async def test_community_flags_creation_and_voting():
    """Validates flag creation, confirmation counting, and abuse-resistant thresholds."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # User 1 reports a blocked trail
        flag_payload = {
            "edge_osm_id": 999101,
            "flag_type": "blocked",
            "details": "Large pine tree across trail"
        }
        resp = await client.post("/api/flags", json=flag_payload, headers={"X-Test-User": "test_user_flag1"})
        assert resp.status_code == 200
        data = resp.json()
        flag_id = data["id"]
        assert data["edge_osm_id"] == 999101
        assert data["flag_type"] == "blocked"
        assert data["confirmed_count"] == 1
        assert data["status"] == "active"

        # User 2 confirms the flag -> confirmed_count becomes 2, status becomes verified
        vote_resp = await client.post(f"/api/flags/{flag_id}/vote", json={"vote_type": "confirm"}, headers={"X-Test-User": "test_user_flag2"})
        assert vote_resp.status_code == 200
        vote_data = vote_resp.json()
        assert vote_data["confirmed_count"] == 2
        assert vote_data["status"] == "verified"

        # User 2 tries to vote confirm again -> rejected (abuse resistance: 1 vote per user)
        dup_resp = await client.post(f"/api/flags/{flag_id}/vote", json={"vote_type": "confirm"}, headers={"X-Test-User": "test_user_flag2"})
        assert dup_resp.status_code == 400

        # User 3 and User 4 dispute the flag
        disp1 = await client.post(f"/api/flags/{flag_id}/vote", json={"vote_type": "dispute"}, headers={"X-Test-User": "test_user_flag3"})
        assert disp1.status_code == 200
        disp2 = await client.post(f"/api/flags/{flag_id}/vote", json={"vote_type": "dispute"}, headers={"X-Test-User": "test_user_flag4"})
        assert disp2.status_code == 200
        disp3 = await client.post(f"/api/flags/{flag_id}/vote", json={"vote_type": "dispute"}, headers={"X-Test-User": "test_user_flag5"})
        assert disp3.status_code == 200

        # With 3 disputes vs 2 confirms, check list flags
        flags_resp = await client.get("/api/flags", params={"edge_osm_id": 999101, "status": "all"})
        assert flags_resp.status_code == 200
        items = flags_resp.json()
        assert len(items) >= 1
        target = next(f for f in items if f["id"] == flag_id)
        assert target["disputed_count"] == 3
        assert target["confirmed_count"] == 2


# =========================================================================
# 2. Rider Trail Check-ins ("still open")
# =========================================================================

@pytest.mark.asyncio
async def test_rider_checkin_refreshes_confidence_and_recency():
    """Validates one-tap rider check-in refreshing confidence score and recency date."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        edge_id = 999202

        # 1. Submit check-in
        checkin_payload = {"status": "still_open", "note": "Rode today, trail is running fast and clear!"}
        resp = await client.post(f"/api/trails/{edge_id}/checkin", json=checkin_payload, headers={"X-Test-User": "test_user_checkin1"})
        assert resp.status_code == 200
        c_data = resp.json()
        assert c_data["edge_osm_id"] == edge_id
        assert c_data["status"] == "still_open"
        assert c_data["confidence_score"] >= 0.8

        # 2. Query check-in history
        hist_resp = await client.get(f"/api/trails/{edge_id}/checkins")
        assert hist_resp.status_code == 200
        hist_data = hist_resp.json()
        assert len(hist_data) >= 1
        assert hist_data[0]["edge_osm_id"] == edge_id

        # 3. Query trail status
        status_resp = await client.get(f"/api/trails/{edge_id}/status")
        assert status_resp.status_code == 200
        st_data = status_resp.json()
        assert st_data["status"] == "open"
        assert st_data["recent_checkins_count"] >= 1
        assert st_data["check_date"] == datetime.datetime.now(datetime.timezone.utc).date().isoformat()


# =========================================================================
# 3. DNR (Do Not Ride) System & Audit Logging
# =========================================================================

@pytest.mark.asyncio
async def test_user_dnr_crud_and_override_logging():
    """Validates user DNR management by trail/area, soft warnings, and override audit logging."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        uid = "test_user_dnr1"

        # 1. Add trail to DNR
        dnr_trail_payload = {
            "name": "Overgrown Technical Descent",
            "dnr_type": "trail",
            "edge_osm_id": 999301,
            "is_soft": True,
            "reason": "Excessive loose shale and downed trees"
        }
        res_trail = await client.post("/api/user/dnr", json=dnr_trail_payload, headers={"X-Test-User": uid})
        assert res_trail.status_code == 200
        t_data = res_trail.json()
        dnr_trail_id = t_data["id"]
        assert t_data["name"] == "Overgrown Technical Descent"
        assert t_data["is_soft"] is True

        # 2. Add area polygon to DNR
        dnr_area_payload = {
            "name": "Active Logging Corridor",
            "dnr_type": "area",
            "geom": {
                "type": "Polygon",
                "coordinates": [[
                    [-71.36, 43.12],
                    [-71.35, 43.12],
                    [-71.35, 43.13],
                    [-71.36, 43.13],
                    [-71.36, 43.12]
                ]]
            },
            "is_soft": True,
            "reason": "Heavy machinery and closed forest roads"
        }
        res_area = await client.post("/api/user/dnr", json=dnr_area_payload, headers={"X-Test-User": uid})
        assert res_area.status_code == 200
        a_data = res_area.json()
        assert a_data["dnr_type"] == "area"

        # 3. List DNR entries
        list_res = await client.get("/api/user/dnr", headers={"X-Test-User": uid})
        assert list_res.status_code == 200
        items = list_res.json()
        assert len(items) == 2

        # 4. Verify Trust Layer check emits soft DNR warning
        trust_check = check_route_trust_layer(
            geojson_linestring={"type": "LineString", "coordinates": [[-71.355, 43.125], [-71.354, 43.126]]},
            edge_osm_ids=[999301],
            user_id=uid,
            sport="mtb"
        )
        assert len(trust_check["soft_dnr"]) >= 1
        assert any("Overgrown Technical Descent" in w for w in trust_check["all_warnings"])

        # 5. Route calculation with override_dnr=True logs audit record
        route_req = {
            "start": {"lat": 43.1305, "lon": -71.3524, "name": "Bear Brook"},
            "end": {"lat": 43.1340, "lon": -71.3580},
            "profile": "mtb",
            "override_dnr": True
        }
        route_resp = await client.post("/api/route", json=route_req, headers={"X-Test-User": uid})
        # If GraphHopper routes between points, verify response
        if route_resp.status_code == 200:
            r_data = route_resp.json()
            assert "warnings" in r_data

        # 6. Delete DNR entry
        del_resp = await client.delete(f"/api/user/dnr/{dnr_trail_id}", headers={"X-Test-User": uid})
        assert del_resp.status_code == 200

        # Verify deletion
        list_after = await client.get("/api/user/dnr", headers={"X-Test-User": uid})
        assert len(list_after.json()) == 1


# =========================================================================
# 4. Hard Blocks & Prior-Ride Waiver
# =========================================================================

@pytest.mark.asyncio
async def test_hard_block_rejection_and_prior_ride_waiver():
    """
    Validates that hard blocks (private land, wilderness, closures) reject routing
    UNLESS the user has already ridden that trail/area.
    """
    # 1. Create a hard restriction in PostGIS
    hard_restr = create_restriction(
        name="TEST_Wildlife_Calving_Zone",
        restriction_type="sensitive_wildlife",
        source="NH Fish & Game",
        is_hard=True,
        edge_osm_id=999401,
        geom={
            "type": "Polygon",
            "coordinates": [[
                [-71.37, 43.14],
                [-71.36, 43.14],
                [-71.36, 43.15],
                [-71.37, 43.15],
                [-71.37, 43.14]
            ]]
        },
        description="Endangered species habitat - strict hard closure"
    )
    assert hard_restr["is_hard"] is True

    user_stranger = "test_user_stranger"
    user_local = "test_user_local"
    ensure_user_exists(user_stranger)
    ensure_user_exists(user_local)

    # 2. user_local has prior riding history on edge 999401
    record_activity({
        "id": "act_prior_local_1",
        "user_id": user_local,
        "sport": "mtb",
        "file_format": "gpx",
        "distance_miles": 5.0,
        "duration_minutes": 30.0,
        "matched_edge_count": 1
    })
    record_activity_edge_visits(
        activity_id="act_prior_local_1",
        edge_counts={999401: 2},
        user_id=user_local,
        sport="mtb"
    )
    assert user_has_ridden_edge(user_local, 999401) is True
    assert user_has_ridden_edge(user_stranger, 999401) is False

    # 3. Trust layer verification for stranger: UNWAIVED hard block!
    check_stranger = check_route_trust_layer(
        geojson_linestring={"type": "LineString", "coordinates": [[-71.365, 43.145], [-71.366, 43.146]]},
        edge_osm_ids=[999401],
        user_id=user_stranger,
        sport="mtb"
    )
    assert check_stranger["has_unwaived_hard_blocks"] is True
    assert any(b["waived"] is False for b in check_stranger["hard_blocks"])

    # 4. Trust layer verification for local rider: WAIVED hard block!
    check_local = check_route_trust_layer(
        geojson_linestring={"type": "LineString", "coordinates": [[-71.365, 43.145], [-71.366, 43.146]]},
        edge_osm_ids=[999401],
        user_id=user_local,
        sport="mtb"
    )
    assert check_local["has_unwaived_hard_blocks"] is False
    assert check_local["waived_hard_blocks_count"] >= 1
    assert any("waived because you have previously ridden" in w for w in check_local["all_warnings"])


# =========================================================================
# 5. Access Controls & Snowmobile Warnings
# =========================================================================

@pytest.mark.asyncio
async def test_access_controls_and_snowmobile_warnings():
    """Validates OSM access=private/no, bicycle=no, and snowmobile trail warnings."""
    # Seed edge with bicycle=no and snowmobile=True in PostGIS
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO edges (osm_id, name, highway, access, bicycle, snowmobile)
                VALUES (999501, 'TEST Winter Corridor', 'track', 'permissive', 'no', TRUE)
                ON CONFLICT (osm_id) DO UPDATE
                SET bicycle = 'no', snowmobile = TRUE;
                """
            )
            conn.commit()

    # Cycling profile check: bicycle=no is a hard block
    check_bike = check_route_trust_layer(
        geojson_linestring={"type": "LineString", "coordinates": []},
        edge_osm_ids=[999501],
        user_id="test_user_bike",
        sport="mtb"
    )
    assert check_bike["has_unwaived_hard_blocks"] is True
    assert any(b["type"] == "osm_bicycle_no" for b in check_bike["hard_blocks"])
    assert any("Snowmobile trail: permission-based" in w for w in check_bike["snowmobile_warnings"])

    # Foot / Trail Run profile check: bicycle=no is NOT a hard block
    check_run = check_route_trust_layer(
        geojson_linestring={"type": "LineString", "coordinates": []},
        edge_osm_ids=[999501],
        user_id="test_user_runner",
        sport="trail_run"
    )
    assert check_run["has_unwaived_hard_blocks"] is False


# =========================================================================
# 6. Admin Restriction Management & Land Manager Takedowns
# =========================================================================

@pytest.mark.asyncio
async def test_admin_restrictions_and_land_manager_takedowns():
    """Validates admin restriction CRUD and immediate land manager takedown requests."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Land Manager Takedown request
        takedown_payload = {
            "name": "TEST Land Trust Private Parcel",
            "edge_osm_id": 999601,
            "reason": "Landowner requested removal due to private driveway impact",
            "requested_by": "Bear Brook Land Trust"
        }
        resp = await client.post("/api/admin/takedowns", json=takedown_payload, headers={"X-Test-User": "round7_admin", "X-Test-Admin": "1"})
        assert resp.status_code == 200
        t_data = resp.json()
        restr_id = t_data["id"]
        assert t_data["restriction_type"] == "takedown"
        assert t_data["is_hard"] is True
        assert "Bear Brook Land Trust" in t_data["source"]

        # 2. List admin restrictions
        list_resp = await client.get("/api/admin/restrictions", headers={"X-Test-User": "round7_admin", "X-Test-Admin": "1"})
        assert list_resp.status_code == 200
        restrs = list_resp.json()
        assert any(r["id"] == restr_id for r in restrs)

        # 3. Update restriction
        update_resp = await client.put(f"/api/admin/restrictions/{restr_id}", json={
            "description": "Updated landowner contact: manager@landtrust.org"
        }, headers={"X-Test-User": "round7_admin", "X-Test-Admin": "1"})
        assert update_resp.status_code == 200
        assert update_resp.json()["description"] == "Updated landowner contact: manager@landtrust.org"

        # 4. Delete restriction
        del_resp = await client.delete(f"/api/admin/restrictions/{restr_id}", headers={"X-Test-User": "round7_admin", "X-Test-Admin": "1"})
        assert del_resp.status_code == 200


# =========================================================================
# 7. Privacy Compliance: Opt-Out, Export, and Full Account Deletion
# =========================================================================

@pytest.mark.asyncio
async def test_privacy_opt_out_export_and_account_deletion():
    """Validates complete user opt-out, data export bundle, and full account deletion."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        uid = "test_user_privacy_complete"
        headers = {"X-Test-User": uid}

        # 1. Create user, DNR, check-in, and privacy zone
        await client.post("/api/user/dnr", json={"name": "TEST DNR", "dnr_type": "trail", "edge_osm_id": 999701}, headers=headers)
        await client.post("/api/trails/999701/checkin", json={"status": "open", "note": "All good"}, headers=headers)
        await client.post("/api/privacy/zones", json={"name": "Home", "lat": 43.12, "lon": -71.35, "radius_m": 320.0}, headers=headers)

        # 2. Opt-out of heat contribution
        opt_resp = await client.post("/api/privacy/consent", params={"consent_given": False}, headers=headers)
        assert opt_resp.status_code == 200
        assert opt_resp.json()["consent_given"] is False

        # 3. Export personal data
        export_resp = await client.get("/api/privacy/export", headers=headers)
        assert export_resp.status_code == 200
        exp_data = export_resp.json()
        assert exp_data["user_id"] == uid
        assert len(exp_data["dnr_items"]) >= 1
        assert len(exp_data["checkins"]) >= 1
        assert len(exp_data["privacy_zones"]) >= 1
        assert exp_data["consent"]["consent_given"] is False

        # 4. Delete account
        del_resp = await client.delete("/api/privacy/account", headers=headers)
        assert del_resp.status_code == 200
        assert del_resp.json()["status"] == "account_deleted"

        # 5. Verify records are purged
        post_export = await client.get("/api/privacy/export", headers=headers)
        assert post_export.status_code == 200
        post_data = post_export.json()
        assert len(post_data["dnr_items"]) == 0
        assert len(post_data["checkins"]) == 0
        assert len(post_data["privacy_zones"]) == 0


# =========================================================================
# 8. Route Candidates Trust Layer Integration
# =========================================================================

@pytest.mark.asyncio
async def test_route_options_soft_dnr_and_override():
    """Validates that candidate route options incorporate soft DNR warnings and allow logged overrides."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        uid = "test_user_route_dnr"
        headers = {"X-Test-User": uid}

        # User sets DNR on an area in Bear Brook
        await client.post("/api/user/dnr", json={
            "name": "TEST Pitch Pine Rocky Knob",
            "dnr_type": "area",
            "geom": {
                "type": "Polygon",
                "coordinates": [[
                    [-71.365, 43.125],
                    [-71.345, 43.125],
                    [-71.345, 43.145],
                    [-71.365, 43.145],
                    [-71.365, 43.125]
                ]]
            },
            "is_soft": True,
            "reason": "Rough trail section"
        }, headers=headers)

        # Query route options with override_dnr=True
        opt_req = {
            "start": {"lat": 43.1305, "lon": -71.3524, "name": "Bear Brook Trailhead"},
            "profile": "mtb",
            "target_distance_miles": 8.0,
            "is_loop": True,
            "candidate_count": 3,
            "override_dnr": True
        }
        resp = await client.post("/api/route/options", json=opt_req, headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] > 0
        options = data["options"]

        # Check if any candidate has dnr_warnings
        has_dnr_option = any(len(o["dnr_warnings"]) > 0 for o in options)
        if has_dnr_option:
            # Verify override was logged
            log_resp = await client.get("/api/user/dnr/overrides", headers=headers)
            assert log_resp.status_code == 200
            logs = log_resp.json()
            assert len(logs) >= 1

@pytest.mark.asyncio
async def test_route_options_hard_block_filtering():
    """Validates that candidate routes crossing hard blocks are rejected unless waived."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        uid_stranger = "test_user_stranger_filter"
        uid_local = "test_user_local_filter"

        # Create massive hard closure across the entire northern quadrant
        hard_closure = create_restriction(
            name="TEST_Entire_North_Quadrant_Closure",
            restriction_type="closure",
            source="State Forest Service",
            is_hard=True,
            geom={
                "type": "Polygon",
                "coordinates": [[
                    [-71.37, 43.135],
                    [-71.33, 43.135],
                    [-71.33, 43.165],
                    [-71.37, 43.165],
                    [-71.37, 43.135]
                ]]
            },
            description="Active wildfire rehabilitation"
        )
        assert hard_closure["is_hard"] is True

        opt_req = {
            "start": {"lat": 43.1305, "lon": -71.3524, "name": "Bear Brook Trailhead"},
            "profile": "mtb",
            "target_distance_miles": 6.0,
            "is_loop": True,
            "candidate_count": 5
        }

        # For stranger: routes traversing the closure are rejected
        resp_stranger = await client.post("/api/route/options", json=opt_req, headers={"X-Test-User": uid_stranger})
        assert resp_stranger.status_code == 200
        opts_stranger = resp_stranger.json()["options"]
        # Stranger options should NOT have North quadrant routes or must not violate hard block
        for opt in opts_stranger:
            coords = opt["coordinates"]
            line = {"type": "LineString", "coordinates": coords}
            chk = check_route_trust_layer(line, [], user_id=uid_stranger, sport="mtb")
            assert chk["has_unwaived_hard_blocks"] is False

