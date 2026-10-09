import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.scoring import classify_route_geometry, calculate_composite_score, score_penalties
from app.db import resolve_osm_trail_name, get_heat_trail_geojson, KNOWN_OSM_TRAIL_NAMES
from app.models import SportProfile


def test_classify_route_geometry_pure_loop():
    # Square loop: (0,0) -> (1,0) -> (1,1) -> (0,1) -> (0,0)
    pts = [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0], [0.0, 0.0]]
    geom, ratio = classify_route_geometry(pts, repetition_ratio=0.0)
    assert geom == "loop"
    assert ratio > 0.8


def test_classify_route_geometry_lollipop():
    # Stem: (0,0) -> (0, 0.5) -> (0, 1.0)
    # Ring: (0, 1.0) -> (1.0, 1.5) -> (0, 2.0) -> (-1.0, 1.5) -> (0, 1.0)
    # Return stem: (0, 0.5) -> (0, 0.0)
    pts = [
        [0.0, 0.0],
        [0.0, 0.5],
        [0.0, 1.0],
        [1.0, 1.5],
        [0.0, 2.0],
        [-1.0, 1.5],
        [0.0, 1.0],
        [0.0, 0.5],
        [0.0, 0.0]
    ]
    # Moderate repetition (stem traversed twice)
    geom, ratio = classify_route_geometry(pts, repetition_ratio=0.28)
    assert geom == "lollipop"


def test_classify_route_geometry_out_and_back():
    # Out and back: (0,0) -> (1,1) -> (2,2) -> (1,1) -> (0,0)
    pts = [
        [0.0, 0.0],
        [1.0, 1.0],
        [2.0, 2.0],
        [1.0, 1.0],
        [0.0, 0.0]
    ]
    geom, ratio = classify_route_geometry(pts, repetition_ratio=0.65)
    assert geom == "out_and_back"


def test_classify_route_geometry_point_to_point():
    # Ends far away: (0,0) -> (5,5)
    pts = [[0.0, 0.0], [2.0, 2.0], [5.0, 5.0]]
    geom, ratio = classify_route_geometry(pts, repetition_ratio=0.0)
    assert geom == "point_to_point"


def test_lollipop_scoring_not_penalized_as_out_and_back():
    # When is_lollipop=True, repetition penalties are relaxed for the approach stem
    score_normal = score_penalties(
        repetition_ratio=0.30,
        warnings=[],
        is_lollipop=False
    )
    score_lollipop = score_penalties(
        repetition_ratio=0.30,
        warnings=[],
        is_lollipop=True
    )
    # Lollipop score must be strictly greater than or equal to a standard out-and-back penalized score
    assert score_lollipop >= score_normal


def test_resolve_osm_trail_name_known_registry():
    # Known OSM IDs from Bear Brook & NH network
    assert resolve_osm_trail_name(42743791) == "Grandview Road"
    assert resolve_osm_trail_name(999202) == "Boulder Trail"
    assert resolve_osm_trail_name(999101) == "Boundary Trail"
    assert resolve_osm_trail_name(220551352) == "Bobcat Trail"
    assert resolve_osm_trail_name(220551345) == "Salt Lick Trail"


def test_get_heat_trail_geojson_structure():
    geojson = get_heat_trail_geojson(sport="mtb")
    assert geojson["type"] == "FeatureCollection"
    assert "features" in geojson
    assert len(geojson["features"]) > 0

    first = geojson["features"][0]
    assert first["type"] == "Feature"
    assert "geometry" in first
    assert first["geometry"]["type"] == "LineString"
    assert "properties" in first
    props = first["properties"]
    assert "osm_id" in props
    assert "name" in props
    assert "heat_score" in props
    assert "ride_count" in props


@pytest.mark.asyncio
async def test_api_heat_trails_endpoint():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/api/heat/trails")
        assert res.status_code == 200
        data = res.json()
        assert data["type"] == "FeatureCollection"
        assert len(data["features"]) > 0
        feat = data["features"][0]
        assert feat["properties"]["heat_score"] > 0
        assert feat["properties"]["name"] is not None


@pytest.mark.asyncio
async def test_api_dev_status_auth_and_anonymous_rejection():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Unauthorized request
        res_unauth = await client.get("/api/dev/status")
        assert res_unauth.status_code == 403

        # Authorized with Developer Key
        res_auth = await client.get(
            "/api/dev/status",
            headers={"X-Dev-Key": "loam_dev_admin_2026"}
        )
        assert res_auth.status_code == 200
        data = res_auth.json()
        assert data["status"] in ("healthy", "degraded")
        assert "uptime_seconds" in data
        assert "connectors" in data


@pytest.mark.asyncio
async def test_api_dev_status_google_sso_auth():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Authorized with jjrpfister@gmail.com
        res = await client.get(
            "/api/dev/status",
            headers={"X-User-Id": "jjrpfister@gmail.com"}
        )
        assert res.status_code == 200
        data = res.json()
        assert data["database_connected"] is True


@pytest.mark.asyncio
async def test_api_otm_trails_endpoint():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/api/otm/trails?sport=mtb")
        assert res.status_code == 200
        data = res.json()
        assert data["type"] == "FeatureCollection"
        assert len(data["features"]) > 0
        feat = data["features"][0]
        assert "difficulty" in feat["properties"]
        assert feat["properties"]["name"] is not None


@pytest.mark.asyncio
async def test_api_cubetrek_import_endpoint():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {
            "url_or_id": "https://cubetrek.com/view?id=99281",
            "sport": "mtb",
            "name": "Bear Brook Test Ride",
            "import_to_heat": True
        }
        res = await client.post(
            "/api/connectors/cubetrek/import",
            json=payload,
            headers={"X-User-Id": "test_cubetrek_user"}
        )
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        assert data["distance_miles"] > 0
        assert data["matched_edges"] > 0
        assert data["heat_edges_updated"] > 0


@pytest.mark.asyncio
async def test_user_export_gps_data():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Import activity first
        await client.post(
            "/api/connectors/cubetrek/import",
            json={"url_or_id": "99282", "sport": "mtb", "name": "Export GPS Test", "import_to_heat": True},
            headers={"X-User-Id": "test_export_user"}
        )
        # Export user data
        exp_res = await client.get(
            "/api/privacy/export",
            headers={"X-User-Id": "test_export_user"}
        )
        assert exp_res.status_code == 200
        data = exp_res.json()
        assert "activities" in data
        assert len(data["activities"]) > 0
        act = data["activities"][0]
        assert "visited_edges" in act
        assert "gps_coordinates" in act
        assert len(act["gps_coordinates"]) > 0
        assert "heat_trail_contributions" in data
        assert len(data["heat_trail_contributions"]) > 0
