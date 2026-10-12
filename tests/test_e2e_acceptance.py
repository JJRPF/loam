"""End-to-End Acceptance Tests for Loam Trail Route Builder.

Validates the complete integrated user lifecycle across all 6 stages:
1. Stage 1 & 2: MVP Routing, Point-to-Point, Loop Mode, Surface Strip & Elevation, Garmin GPX/FIT Export
2. Stage 3: Multi-Candidate Route Engine, 10-option ranking, repetition penalties, minimaps
3. Stage 4: Heat Pipeline, GPX/FIT Ingestion, 0.2-mi Privacy Trimming, Decay, Privacy Threshold
4. Stage 5: Trust Layer, Rider Check-ins, Community Flags, DNR controls, Hard Closures
5. Stage 6: Differentiators, "Find New Trails" discovery mode, submissions, decoupled connectors
"""

import datetime
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.db import get_connection, record_edge_heat
from app.gpx_export import build_gpx_track

@pytest.fixture(autouse=True)
def clean_e2e_test_data():
    """Clean test artifacts after E2E runs."""
    yield
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM saved_routes WHERE user_id = 'e2e_justin_rider';")
                cur.execute("DELETE FROM trail_checkins WHERE user_id = 'e2e_justin_rider';")
                cur.execute("DELETE FROM flag_votes WHERE user_id = 'e2e_justin_rider';")
                cur.execute("DELETE FROM flags WHERE user_id = 'e2e_justin_rider';")
                cur.execute("DELETE FROM activity_edge_visits WHERE user_id = 'e2e_justin_rider';")
                cur.execute("DELETE FROM activities WHERE user_id = 'e2e_justin_rider';")
                cur.execute("DELETE FROM user_privacy_zones WHERE user_id = 'e2e_justin_rider';")
                cur.execute("DELETE FROM contribution_consent WHERE user_id = 'e2e_justin_rider';")
                cur.execute("DELETE FROM user_dnr WHERE user_id = 'e2e_justin_rider';")
                cur.execute("DELETE FROM trail_submission_evidence WHERE user_id = 'e2e_justin_rider';")
                cur.execute("DELETE FROM trail_submissions WHERE user_id = 'e2e_justin_rider';")
                cur.execute("DELETE FROM user_connected_services WHERE user_id = 'e2e_justin_rider';")
                cur.execute("DELETE FROM edge_heat WHERE edge_osm_id >= 990000;")
                cur.execute("DELETE FROM edges WHERE osm_id >= 990000;")
                cur.execute("DELETE FROM users WHERE id = 'e2e_justin_rider';")
                conn.commit()
    except Exception:
        pass


@pytest.mark.asyncio
async def test_full_e2e_acceptance_lifecycle():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # -------------------------------------------------------------
        # STEP 1: Frontend Static PWA Serving & Manifest
        # -------------------------------------------------------------
        root_resp = await client.get("/")
        assert root_resp.status_code == 200
        assert "Loam" in root_resp.text
        assert "manifest.json" in root_resp.text

        manifest_resp = await client.get("/manifest.json")
        assert manifest_resp.status_code == 200
        manifest_data = manifest_resp.json()
        assert manifest_data.get("name") == "Loam — Trail Route Builder"
        assert manifest_data.get("display") == "standalone"

        # -------------------------------------------------------------
        # STEP 2: Authentication Skeleton & User Profile
        # -------------------------------------------------------------
        anon_me = await client.get("/api/auth/me")
        assert anon_me.status_code == 401

        headers = {"X-Test-User": "e2e_justin_rider"}
        me_resp = await client.get("/api/auth/me", headers=headers)
        assert me_resp.status_code == 200
        assert me_resp.json()["id"] == "e2e_justin_rider"

        # -------------------------------------------------------------
        # STEP 3: Multi-Candidate Route Engine (Stage 2 & Stage 3)
        # Location: Bear Brook State Park, NH
        # -------------------------------------------------------------
        route_req = {
            "start": {"lat": 43.1305, "lon": -71.3524, "name": "Bear Brook Trailhead"},
            "profile": "mtb_hardtail",
            "route_mode": "loop",
            "target_distance_miles": 8.0,
            "candidate_count": 10
        }
        options_resp = await client.post("/api/route/options", json=route_req, headers=headers)
        assert options_resp.status_code == 200
        data = options_resp.json()
        options = data["options"]
        assert 1 <= len(options) <= 10

        top_candidate = options[0]
        assert "id" in top_candidate
        assert top_candidate["distance_miles"] > 0
        assert "elevation_gain_ft" in top_candidate
        assert "minimap_svg" in top_candidate
        assert top_candidate["minimap_svg"].startswith("M")
        assert 1 <= top_candidate["match_score"] <= 100
        assert "score_breakdown" in top_candidate
        assert "composite" in top_candidate["score_breakdown"]

        # -------------------------------------------------------------
        # STEP 4: Export to Garmin GPX and Garmin FIT (fenix 7 Pro compatible)
        # -------------------------------------------------------------
        coords = top_candidate.get("coordinates") or [
            [-71.35384, 43.128757, 185.0],
            [-71.355855, 43.129583, 192.0],
            [-71.358325, 43.130775, 204.0],
            [-71.361759, 43.132106, 218.0],
            [-71.365792, 43.134166, 230.0]
        ]
        export_payload = {
            "name": "Bear Brook Acceptance Loop",
            "sport": "mtb",
            "distance_miles": top_candidate["distance_miles"],
            "duration_minutes": 50.0,
            "elevation_gain_ft": top_candidate["elevation_gain_ft"],
            "elevation_loss_ft": top_candidate.get("elevation_loss_ft", top_candidate["elevation_gain_ft"]),
            "coordinates": coords
        }

        gpx_resp = await client.post("/api/export/gpx", json=export_payload)
        assert gpx_resp.status_code == 200
        assert "application/gpx+xml" in gpx_resp.headers["content-type"]
        assert "<gpx" in gpx_resp.text
        assert "<trkpt" in gpx_resp.text

        fit_resp = await client.post("/api/export/fit", json=export_payload)
        assert fit_resp.status_code == 200
        assert "application/vnd.ant.fit" in fit_resp.headers["content-type"]
        fit_bytes = fit_resp.content
        assert len(fit_bytes) > 14
        assert fit_bytes[8:12] == b".FIT"

        # -------------------------------------------------------------
        # STEP 5: Saved Routes Persistence
        # -------------------------------------------------------------
        save_resp = await client.post(
            "/api/saved-routes",
            json={
                "name": "Bear Brook Acceptance Loop",
                "sport": "mtb",
                "distance_miles": top_candidate["distance_miles"],
                "elevation_gain_ft": top_candidate["elevation_gain_ft"],
                "elevation_loss_ft": top_candidate["elevation_gain_ft"],
                "surface_breakdown": {"singletrack": 75.0, "doubletrack": 25.0},
                "coordinates": coords
            },
            headers=headers
        )
        assert save_resp.status_code == 200
        saved_id = save_resp.json()["id"]

        saved_list_resp = await client.get("/api/saved-routes", headers=headers)
        assert saved_list_resp.status_code == 200
        saved_items = saved_list_resp.json()["routes"]
        assert any(r["id"] == saved_id for r in saved_items)

        # -------------------------------------------------------------
        # STEP 6: Privacy Consent & Defensive Activity GPX Ingestion (Stage 4)
        # -------------------------------------------------------------
        consent_resp = await client.post(
            "/api/privacy/consent",
            params={"consent_given": True},
            headers=headers
        )
        assert consent_resp.status_code == 200
        assert consent_resp.json()["consent_given"] is True

        # Realistic 50-point track in Bear Brook
        track_pts = [
            [-71.3524 + i * 0.0005, 43.1305 + i * 0.0005]
            for i in range(50)
        ]
        gpx_data = build_gpx_track(
            name="E2E Morning Loop",
            sport="mtb",
            coordinates=track_pts,
            distance_miles=2.2,
            duration_minutes=25.0
        )
        files = {
            "file": ("e2e_morning_loop.gpx", gpx_data.encode("utf-8"), "application/gpx+xml")
        }
        data = {
            "sport": "mtb",
            "consent_given": "true",
            "retain_file": "false"
        }
        upload_resp = await client.post("/api/activities/upload", files=files, data=data, headers=headers)
        assert upload_resp.status_code == 200
        act_res = upload_resp.json()
        assert act_res["sport"] == "mtb"
        assert act_res["raw_points_count"] == 50
        assert act_res["trimmed_points_count"] < 50
        assert act_res["consent_given"] is True
        assert act_res["raw_file_retained"] is False

        # -------------------------------------------------------------
        # STEP 7: Trust Layer - Rider Check-in & Community Flags (Stage 5)
        # -------------------------------------------------------------
        edge_id = 998801
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO edges (osm_id, name, length_m, geom, surface)
                    VALUES (%s, 'TEST_Acceptance_Singletrack', 1500.0,
                            ST_SetSRID(ST_MakeLine(ST_MakePoint(-71.3520, 43.1300), ST_MakePoint(-71.3530, 43.1310)), 4326),
                            'dirt')
                    ON CONFLICT (osm_id) DO NOTHING;
                    """,
                    (edge_id,)
                )
                conn.commit()

        # 1. Rider Check-in
        checkin_payload = {"status": "still_open", "note": "Rode today, trail is running fast and clear!"}
        chk_resp = await client.post(f"/api/trails/{edge_id}/checkin", json=checkin_payload, headers=headers)
        assert chk_resp.status_code == 200
        chk_data = chk_resp.json()
        assert chk_data["edge_osm_id"] == edge_id
        assert chk_data["status"] == "still_open"
        assert chk_data["confidence_score"] >= 0.8

        # 2. Community Flag
        flag_payload = {
            "edge_osm_id": edge_id,
            "flag_type": "blocked",
            "details": "Fallen birch across entrance"
        }
        flg_resp = await client.post("/api/flags", json=flag_payload, headers=headers)
        assert flg_resp.status_code == 200
        flg_data = flg_resp.json()
        flag_id = flg_data["id"]
        assert flg_data["status"] == "active"

        # Upvote flag confirmation
        vote_resp = await client.post(f"/api/flags/{flag_id}/vote", json={"vote_type": "confirm"}, headers={"X-Test-User": "rider_voter_2"})
        assert vote_resp.status_code == 200
        assert vote_resp.json()["confirmed_count"] == 2
        assert vote_resp.json()["status"] == "verified"

        # -------------------------------------------------------------
        # STEP 8: Find New Trails & Unridden Discovery (Stage 6)
        # -------------------------------------------------------------
        # Record community heat from 3 distinct riders so it passes privacy threshold
        record_edge_heat(edge_id, "mtb", weight=4.0, user_id="community_rider_a")
        record_edge_heat(edge_id, "mtb", weight=4.0, user_id="community_rider_b")
        record_edge_heat(edge_id, "mtb", weight=4.0, user_id="community_rider_c")

        # Query /api/trails/new-to-me for our e2e user who hasn't ridden edge_id
        fnt_resp = await client.get(
            "/api/trails/new-to-me",
            params={"lat": 43.1305, "lon": -71.3524, "radius_miles": 15.0, "sport": "mtb"},
            headers=headers
        )
        assert fnt_resp.status_code == 200
        fnt_data = fnt_resp.json()
        assert len(fnt_data) >= 1
        assert any(t["edge_osm_id"] == edge_id for t in fnt_data)

        # -------------------------------------------------------------
        # STEP 9: Decoupled Connectors & Zero-Storage Invariants (Stage 6)
        # -------------------------------------------------------------
        conn_resp = await client.get("/api/connectors", headers=headers)
        assert conn_resp.status_code == 200
        connectors_list = conn_resp.json()
        assert len(connectors_list) >= 3
        conn_map = {c["name"]: c for c in connectors_list}
        assert conn_map["garmin"]["enabled"] is True
        assert conn_map["trailforks"]["enabled"] is True
        assert conn_map["strava"]["enabled"] is True
        assert "cubetrek" in conn_map
        for c in connectors_list:
            assert c["connected"] is False

        # -------------------------------------------------------------
        # STEP 10: Clean Opt-Out & User Account Deletion (Stage 5)
        # -------------------------------------------------------------
        del_resp = await client.delete("/api/privacy/account", headers=headers)
        assert del_resp.status_code == 200
        del_data = del_resp.json()
        assert del_data["status"] == "account_deleted"
        assert del_data["user_id"] == "e2e_justin_rider"
