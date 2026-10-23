import pytest
import io
import fitparse
import xml.etree.ElementTree as ET
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.gpx_export import build_gpx_track
from app.fit_export import build_fit_course
from tests.conftest import requires_graphhopper

NH_SAMPLE_COORDINATES = [
    [-71.35384, 43.128757, 185.0],
    [-71.355855, 43.129583, 192.0],
    [-71.358325, 43.130775, 204.0],
    [-71.361759, 43.132106, 218.0],
    [-71.365792, 43.134166, 230.0],
    [-71.366197, 43.147643, 245.0],
]

@pytest.mark.asyncio
async def test_garmin_gpx_export():
    """Validates GPX 1.1 structure and XML validity."""
    gpx_xml = build_gpx_track(
        name="Bear Brook Loop",
        sport="mtb",
        coordinates=NH_SAMPLE_COORDINATES,
        distance_miles=4.5,
        duration_minutes=35.0,
        elevation_gain_ft=420.0,
        elevation_loss_ft=410.0,
        waypoints=[{"lat": 43.128757, "lon": -71.35384, "name": "Podunk Trailhead"}]
    )
    # Parse XML to verify well-formedness
    root = ET.fromstring(gpx_xml)
    assert root.tag.endswith("gpx")
    assert root.attrib.get("version") == "1.1"

    # Verify track and track points
    ns = {"gpx": "http://www.topografix.com/GPX/1/1"}
    trk = root.find("gpx:trk", ns)
    assert trk is not None
    trkseg = trk.find("gpx:trkseg", ns)
    assert trkseg is not None
    trkpts = trkseg.findall("gpx:trkpt", ns)
    assert len(trkpts) == len(NH_SAMPLE_COORDINATES)
    
    # Check first point attributes and elevation
    first_pt = trkpts[0]
    assert float(first_pt.attrib["lat"]) == pytest.approx(43.128757, 0.0001)
    assert float(first_pt.attrib["lon"]) == pytest.approx(-71.35384, 0.0001)
    ele = first_pt.find("gpx:ele", ns)
    assert ele is not None
    assert float(ele.text) == pytest.approx(185.0, 0.1)

@pytest.mark.asyncio
async def test_garmin_fenix_fit_export():
    """
    Acceptance Check: Validates binary FIT Course format parseable by Garmin fenix 7 Pro.
    Verifies file_id (course), course, lap, and record messages with coordinates and altitude.
    """
    fit_bytes = build_fit_course(
        name="Bear Brook Fenix Route",
        sport="mtb",
        coordinates=NH_SAMPLE_COORDINATES,
        distance_miles=4.5,
        duration_minutes=35.0,
        elevation_gain_ft=420.0,
        elevation_loss_ft=410.0
    )

    assert len(fit_bytes) > 50
    # Header check
    assert fit_bytes[0] == 14 # 14-byte header
    assert fit_bytes[8:12] == b".FIT"

    # Parse with standard Garmin FIT parser
    fit = fitparse.FitFile(fit_bytes)
    messages = list(fit.get_messages())
    msg_names = [m.name for m in messages]
    
    assert "file_id" in msg_names
    assert "course" in msg_names
    assert "lap" in msg_names
    assert "record" in msg_names

    # Check file_id
    file_id = next(m for m in messages if m.name == "file_id")
    assert file_id.get_value("type") == "course"
    assert file_id.get_value("manufacturer") == "garmin"

    # Check course message
    course = next(m for m in messages if m.name == "course")
    assert course.get_value("sport") == "cycling"
    assert "Bear Brook" in course.get_value("name")

    # Check lap message
    lap = next(m for m in messages if m.name == "lap")
    assert lap.get_value("total_distance") > 0
    assert lap.get_value("total_ascent") > 0

    # Check record messages
    records = [m for m in messages if m.name == "record"]
    assert len(records) == len(NH_SAMPLE_COORDINATES)
    first_rec = records[0]
    assert first_rec.get_value("position_lat") is not None
    assert first_rec.get_value("position_long") is not None
    assert first_rec.get_value("altitude") is not None

@requires_graphhopper
@pytest.mark.asyncio
async def test_route_loop_mode():
    """Tests loop routing calculation when target_distance_miles and loop mode are provided."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {
            "start": {"lat": 43.1305, "lon": -71.3524},
            "is_loop": True,
            "route_mode": "loop",
            "target_distance_miles": 5.0,
            "profile": "mtb"
        }
        resp = await client.post("/api/route", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["distance_miles"] > 0.0
        assert data["match_score"] is not None
        assert "verbal_summary" in data
        assert len(data["surface_strip"]) > 0

@requires_graphhopper
@pytest.mark.asyncio
async def test_sport_profiles():
    """Tests that various MTB subtypes and trail-run profiles route correctly."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        for profile in ["mtb_hardtail", "mtb_fullsus", "mtb_gravel", "trail_run"]:
            payload = {
                "start": {"lat": 43.1305, "lon": -71.3524},
                "end": {"lat": 43.1482, "lon": -71.3651},
                "profile": profile,
                "terrain_preference": {
                    "singletrack": 0.7,
                    "doubletrack": 0.2,
                    "gravel": 0.1,
                    "paved": 0.0
                }
            }
            resp = await client.post("/api/route", json=payload)
            assert resp.status_code == 200
            data = resp.json()
            assert data["sport"] == profile
            assert data["distance_miles"] > 0

@pytest.mark.asyncio
async def test_saved_routes_crud():
    """Tests saving, listing, retrieving, and deleting routes in PostGIS."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Save a route
        save_payload = {
            "name": "Oak Hill Singletrack Loop",
            "sport": "mtb",
            "distance_miles": 6.8,
            "elevation_gain_ft": 520.0,
            "elevation_loss_ft": 515.0,
            "coordinates": NH_SAMPLE_COORDINATES,
            "surface_breakdown": {"singletrack": 75.0, "gravel": 25.0},
            "verbal_summary": "6.8 mi; 75% singletrack"
        }
        headers = {"X-Test-User": "test_user_justin"}
        create_resp = await client.post("/api/saved-routes", json=save_payload, headers=headers)
        assert create_resp.status_code == 200
        saved_id = create_resp.json()["id"]

        # List saved routes
        list_resp = await client.get("/api/saved-routes", headers=headers)
        assert list_resp.status_code == 200
        routes = list_resp.json()["routes"]
        assert any(r["id"] == saved_id for r in routes)

        # Get saved route by ID
        get_resp = await client.get(f"/api/saved-routes/{saved_id}", headers=headers)
        assert get_resp.status_code == 200
        item = get_resp.json()
        assert item["name"] == "Oak Hill Singletrack Loop"
        assert len(item["coordinates"]) > 0

        # Export saved route as GPX
        assert (await client.get(f"/api/export/gpx/{saved_id}")).status_code == 401  # owner-only since GH-42
        gpx_resp = await client.get(f"/api/export/gpx/{saved_id}", headers=headers)
        assert gpx_resp.status_code == 200
        assert "application/gpx+xml" in gpx_resp.headers["content-type"]
        assert "<trk>" in gpx_resp.text

        # Export saved route as FIT
        fit_resp = await client.get(f"/api/export/fit/{saved_id}", headers=headers)
        assert fit_resp.status_code == 200
        assert len(fit_resp.content) > 50

        # Delete saved route
        del_resp = await client.delete(f"/api/saved-routes/{saved_id}", headers=headers)
        assert del_resp.status_code == 200
        assert del_resp.json()["status"] == "deleted"

@pytest.mark.asyncio
async def test_auth_skeleton():
    """/api/auth/me returns the authenticated user and 401 without one."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        anon = await client.get("/api/auth/me")
        assert anon.status_code == 401
        me_resp = await client.get("/api/auth/me", headers={"X-Test-User": "justin_fenix_user"})
        assert me_resp.status_code == 200
        assert me_resp.json()["id"] == "justin_fenix_user"
        assert me_resp.json()["is_admin"] is False

@pytest.mark.asyncio
async def test_frontend_static_serving():
    """Validates that the built React PWA is served at /."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/")
        assert resp.status_code == 200
        assert "Loam" in resp.text
        assert "manifest.json" in resp.text
