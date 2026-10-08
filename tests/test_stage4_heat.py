import io
import datetime
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.activity_parser import parse_activity_file, TrackPoint, MAX_FILE_SIZE
from app.privacy import apply_privacy_filters, trim_ride_endpoints, exclude_privacy_zones, TRIM_METERS
from app.decay import compute_recency_weight, aggregate_edge_visits, get_grid_cell
from app.scoring import score_heat, calculate_composite_score
from app.models import SportProfile, TerrainPreference, SurfaceSegment
from app.gpx_export import build_gpx_track
from app.fit_export import build_fit_course
from app.worker import run_nightly_job

# =========================================================================
# 1. Activity Ingestion & Defensive Parsing Tests
# =========================================================================

@pytest.mark.asyncio
async def test_gpx_upload_and_ingestion():
    """Validates defensive GPX activity upload, parsing, and trimming."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Generate a realistic 2.0-mile track in Bear Brook
        pts = [
            [-71.3524 + i * 0.0005, 43.1305 + i * 0.0005]
            for i in range(50)
        ]
        gpx_content = build_gpx_track(
            name="Morning Bear Brook Ride",
            sport="mtb",
            coordinates=pts,
            distance_miles=2.0,
            duration_minutes=25.0
        )

        files = {
            "file": ("morning_ride.gpx", gpx_content.encode("utf-8"), "application/gpx+xml")
        }
        data = {
            "sport": "mtb",
            "consent_given": "true",
            "retain_file": "false"
        }
        headers = {"X-User-Id": "rider_justin_1"}

        resp = await client.post("/api/activities/upload", files=files, data=data, headers=headers)
        assert resp.status_code == 200
        res_data = resp.json()

        assert res_data["activity_id"] is not None
        assert res_data["user_id"] == "rider_justin_1"
        assert res_data["sport"] == "mtb"
        assert res_data["raw_points_count"] == 50
        assert res_data["trimmed_points_count"] < 50  # Start and end 0.2 mi trimmed
        assert res_data["consent_given"] is True
        assert res_data["raw_file_retained"] is False

@pytest.mark.asyncio
async def test_fit_upload_and_ingestion():
    """Validates Garmin FIT binary course/activity upload and parsing."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        pts = [
            [-71.3524 + i * 0.0004, 43.1305 + i * 0.0004]
            for i in range(60)
        ]
        fit_bytes = build_fit_course(
            name="Garmin Course Upload",
            sport="mtb",
            coordinates=pts,
            distance_miles=2.5,
            duration_minutes=30.0
        )

        files = {
            "file": ("garmin_activity.fit", fit_bytes, "application/octet-stream")
        }
        data = {
            "sport": "mtb",
            "consent_given": "true",
            "retain_file": "false"
        }
        headers = {"X-User-Id": "rider_justin_2"}

        resp = await client.post("/api/activities/upload", files=files, data=data, headers=headers)
        assert resp.status_code == 200
        res_data = resp.json()

        assert res_data["activity_id"] is not None
        assert res_data["raw_points_count"] == 60
        assert res_data["trimmed_points_count"] < 60
        assert res_data["consent_given"] is True

@pytest.mark.asyncio
async def test_defensive_xxe_attack_rejection():
    """Verifies that malicious GPX with XML External Entity (XXE) injection is safely rejected."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        malicious_gpx = b"""<?xml version="1.0"?>
        <!DOCTYPE replace [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>
        <gpx version="1.1">
          <trk><trkseg>
            <trkpt lat="43.1" lon="-71.3"><name>&xxe;</name></trkpt>
          </trkseg></trk>
        </gpx>"""

        files = {"file": ("malicious.gpx", malicious_gpx, "application/gpx+xml")}
        resp = await client.post("/api/activities/upload", files=files, headers={"X-User-Id": "attacker"})
        # Should be rejected with 400 Bad Request
        assert resp.status_code == 400
        assert "malformed" in resp.text.lower() or "entitiesforbidden" in resp.text.lower()

@pytest.mark.asyncio
async def test_oversized_file_rejection():
    """Verifies that payloads exceeding the 25 MB limit are rejected with 413."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Create a dummy payload exceeding 25 MB
        oversized = b"A" * (MAX_FILE_SIZE + 1024)
        files = {"file": ("huge.gpx", oversized, "application/gpx+xml")}
        resp = await client.post("/api/activities/upload", files=files)
        assert resp.status_code == 413

# =========================================================================
# 2. Privacy Trimming & Privacy Zones
# =========================================================================

def test_endpoint_trimming_distance():
    """Verifies that the first 0.2 mi (321.87 m) and last 0.2 mi are strictly stripped."""
    # 100 points along a ~5 mile track (each step ~80 meters)
    pts = [TrackPoint(lat=43.10 + i * 0.0008, lon=-71.35) for i in range(100)]
    trimmed, start_cnt, end_cnt = trim_ride_endpoints(pts, trim_distance_m=TRIM_METERS)

    assert start_cnt > 0
    assert end_cnt > 0
    assert len(trimmed) == len(pts) - start_cnt - end_cnt
    assert len(trimmed) > 0

def test_privacy_zone_exclusion():
    """Verifies that track points within a user's privacy radius are excluded."""
    # Line passing through lat 43.15, lon -71.35
    pts = [TrackPoint(lat=43.10 + i * 0.001, lon=-71.35) for i in range(100)]
    # Place privacy zone right at the middle point (i = 50 -> lat = 43.15)
    zone = [{"lat": 43.15, "lon": -71.35, "radius_m": 400.0}]

    filtered, excluded_count = exclude_privacy_zones(pts, zone)
    assert excluded_count > 0
    assert len(filtered) == 100 - excluded_count
    # Verify no remaining point is within 400m of privacy zone
    for p in filtered:
        assert abs(p.lat - 43.15) > 0.003  # safely outside

def test_short_ride_trimmed_completely():
    """Verifies that rides under 0.4 miles return empty retained points gracefully."""
    # 5 points covering only ~100 meters
    pts = [TrackPoint(lat=43.10 + i * 0.0001, lon=-71.35) for i in range(5)]
    trimmed, start_cnt, end_cnt = trim_ride_endpoints(pts, trim_distance_m=TRIM_METERS)
    assert len(trimmed) == 0

@pytest.mark.asyncio
async def test_privacy_zone_crud_and_consent_api():
    """Tests privacy zone creation, listing, deletion, and consent toggle."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        headers = {"X-User-Id": "rider_privacy_tester"}

        # 1. Create privacy zone
        zone_payload = {"name": "Home Base", "lat": 43.1305, "lon": -71.3524, "radius_m": 350.0}
        c_resp = await client.post("/api/privacy/zones", json=zone_payload, headers=headers)
        assert c_resp.status_code == 200
        z_id = c_resp.json()["id"]

        # 2. List zones
        l_resp = await client.get("/api/privacy/zones", headers=headers)
        assert l_resp.status_code == 200
        zones = l_resp.json()
        assert any(z["id"] == z_id for z in zones)

        # 3. Toggle consent to false (opt-out)
        opt_resp = await client.post("/api/privacy/consent?consent_given=false", headers=headers)
        assert opt_resp.status_code == 200
        assert opt_resp.json()["consent_given"] is False

        # 4. Check consent
        chk_resp = await client.get("/api/privacy/consent", headers=headers)
        assert chk_resp.status_code == 200
        assert chk_resp.json()["consent_given"] is False

        # 5. Delete privacy zone
        d_resp = await client.delete(f"/api/privacy/zones/{z_id}", headers=headers)
        assert d_resp.status_code == 200

# =========================================================================
# 3. Recency Decay Math & 12-Month Window Tests
# =========================================================================

def test_exponential_recency_decay_formula():
    """
    Validates exponential decay math:
    - Delta = 0 days: weight = 1.00
    - Delta = 182.5 days (6-month half life): weight = 0.50
    - Delta = 365 days (12 months): weight = 0.25
    - Delta > 365 days: weight = 0.0 (excluded from 12-month window)
    """
    now = datetime.datetime(2026, 10, 7, 12, 0, tzinfo=datetime.timezone.utc)

    # Today
    w_today = compute_recency_weight(now, now)
    assert round(w_today, 3) == 1.000

    # 182.5 days ago (~6 months)
    t_6mo = now - datetime.timedelta(days=182.5)
    w_6mo = compute_recency_weight(t_6mo, now)
    assert round(w_6mo, 2) == 0.50

    # 365 days ago (12 months)
    t_12mo = now - datetime.timedelta(days=365.0)
    w_12mo = compute_recency_weight(t_12mo, now)
    assert round(w_12mo, 2) == 0.25

    # 366 days ago (outside window)
    t_stale = now - datetime.timedelta(days=366.0)
    w_stale = compute_recency_weight(t_stale, now)
    assert w_stale == 0.0

# =========================================================================
# 4. >= 3 Unique Riders Privacy Threshold Tests
# =========================================================================

def test_unique_riders_privacy_threshold_aggregation():
    """
    Validates that:
    - 1 or 2 unique riders -> is_public = False (counts only for contributor)
    - 3 or more unique riders -> is_public = True (public heat)
    """
    now = datetime.datetime(2026, 10, 7, 12, 0, tzinfo=datetime.timezone.utc)

    # 1 Rider (10 passes by Alice)
    visits_1 = [{"user_id": "alice", "visited_at": now, "pass_count": 10}]
    agg_1 = aggregate_edge_visits(visits_1, now)
    assert agg_1["unique_riders"] == 1
    assert agg_1["is_public"] is False
    assert agg_1["contributor_ids"] == ["alice"]

    # 2 Riders (Alice and Bob)
    visits_2 = [
        {"user_id": "alice", "visited_at": now, "pass_count": 5},
        {"user_id": "bob", "visited_at": now, "pass_count": 5}
    ]
    agg_2 = aggregate_edge_visits(visits_2, now)
    assert agg_2["unique_riders"] == 2
    assert agg_2["is_public"] is False
    assert set(agg_2["contributor_ids"]) == {"alice", "bob"}

    # 3 Riders (Alice, Bob, and Charlie) -> Meets privacy threshold!
    visits_3 = [
        {"user_id": "alice", "visited_at": now, "pass_count": 2},
        {"user_id": "bob", "visited_at": now, "pass_count": 2},
        {"user_id": "charlie", "visited_at": now, "pass_count": 1}
    ]
    agg_3 = aggregate_edge_visits(visits_3, now)
    assert agg_3["unique_riders"] == 3
    assert agg_3["is_public"] is True
    assert set(agg_3["contributor_ids"]) == {"alice", "bob", "charlie"}

def test_heat_scoring_privacy_threshold():
    """
    Validates that an edge with < 3 riders influences route scoring ONLY for the contributor,
    not for public strangers.
    """
    # Edge 7001 has only 1 rider (user_A)
    heat_cache = {
        7001: {
            "edge_osm_id": 7001,
            "is_public": False,
            "contributor_ids": ["user_A"],
            "weighted_score": 5.0
        }
    }

    # Contributor user_A queries -> heat applies!
    score_contributor = score_heat([7001], "mtb", heat_cache, user_id="user_A", is_covered_region=False)
    assert score_contributor > 80.0

    # Stranger user_B queries -> privacy threshold blocks it! Counts as zero heat / neutral
    score_stranger = score_heat([7001], "mtb", heat_cache, user_id="user_B", is_covered_region=False)
    assert score_stranger == 70.0  # Neutral

    # Anonymous user queries -> privacy threshold blocks it
    score_anon = score_heat([7001], "mtb", heat_cache, user_id=None, is_covered_region=False)
    assert score_anon == 70.0

# =========================================================================
# 5. Regional Coverage & Ghost-Trail Verification (Acceptance Check)
# =========================================================================

def test_coverage_aware_zero_heat_penalty():
    """
    Validates the coverage-aware rule:
    - In an active, covered area: zero-heat edge receives heavy ghost-trail penalty (25.0).
    - In a sparse area: zero-heat edge receives neutral score (70.0, "No recent data").
    """
    # Edge with no heat in covered area (e.g. Bear Brook)
    score_covered_ghost = score_heat([8001], "mtb", {}, is_covered_region=True)
    assert score_covered_ghost == 25.0  # Penalized!

    # Edge with no heat in sparse backcountry
    score_sparse_neutral = score_heat([8001], "mtb", {}, is_covered_region=False)
    assert score_sparse_neutral == 70.0  # Neutral!

def test_ghost_trails_avoided_vs_active_trails_favored():
    """
    Acceptance Check:
    Verifies that a suite of active trails vs ghost trails in a covered region
    results in active trails heavily outscoring and being favored over ghost trails.
    """
    # 5 active trails with strong public heat (>= 3 riders)
    active_edge_ids = [9001, 9002, 9003, 9004, 9005]
    # 5 ghost trails (abandoned/overgrown paths with zero heat in covered area)
    ghost_edge_ids = [9101, 9102, 9103, 9104, 9105]

    heat_cache = {
        wid: {
            "edge_osm_id": wid,
            "is_public": True,
            "contributor_ids": ["r1", "r2", "r3"],
            "weighted_score": 8.0
        }
        for wid in active_edge_ids
    }
    # ghost trails are omitted from heat_cache or have score 0

    # Route A traverses active trails in covered area
    comp_active, breakdown_active, verbal_active = calculate_composite_score(
        distance_miles=10.0,
        target_distance_miles=10.0,
        surface_breakdown={"singletrack": 80.0, "gravel": 20.0},
        surface_strip=[SurfaceSegment(start_index=0, end_index=10, surface_type="singletrack")],
        preference=TerrainPreference(singletrack=0.8, doubletrack=0.1, gravel=0.1, paved=0.0),
        sport=SportProfile.MTB,
        repetition_ratio=0.0,
        warnings=[],
        edge_osm_ids=active_edge_ids,
        edge_heat_dict=heat_cache,
        is_covered_region=True
    )

    # Route B traverses ghost trails in covered area
    comp_ghost, breakdown_ghost, verbal_ghost = calculate_composite_score(
        distance_miles=10.0,
        target_distance_miles=10.0,
        surface_breakdown={"singletrack": 80.0, "gravel": 20.0},
        surface_strip=[SurfaceSegment(start_index=0, end_index=10, surface_type="singletrack")],
        preference=TerrainPreference(singletrack=0.8, doubletrack=0.1, gravel=0.1, paved=0.0),
        sport=SportProfile.MTB,
        repetition_ratio=0.0,
        warnings=[],
        edge_osm_ids=ghost_edge_ids,
        edge_heat_dict=heat_cache,
        is_covered_region=True
    )

    # Active route heat score should be high (>= 90)
    assert breakdown_active["heat"] >= 90.0
    # Ghost route heat score should be penalized (25.0)
    assert breakdown_ghost["heat"] == 25.0

    # Composite score difference: active route beats ghost route by >= 9 points
    assert comp_active > comp_ghost
    assert (comp_active - comp_ghost) >= 9

    # Verbal explanation indicates ghost trail penalty
    assert "Ghost trail penalty applied" in verbal_ghost
    assert "High recency heat" in verbal_active

# =========================================================================
# 6. Nightly Worker Execution Test
# =========================================================================

def test_nightly_worker_execution():
    """Validates that the nightly worker recalculation executes cleanly."""
    stats = run_nightly_job()
    assert stats["status"] == "success"
    assert "edges_updated" in stats
    assert "public_edges_count" in stats
    assert "coverage_cells_updated" in stats
    assert stats["duration_seconds"] >= 0.0

@pytest.mark.asyncio
async def test_nightly_worker_api_endpoint():
    """Validates trigger of nightly job via POST /api/jobs/recalculate-heat."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/jobs/recalculate-heat")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert "edges_updated" in data
        assert "duration_seconds" in data
