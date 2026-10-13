import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app
from tests.conftest import as_user
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


TEST_HEAT_EDGE = 991901


def _seed_public_heat_edge():
    """A test-only trail edge with public heat (test fixture data, never shipped)."""
    from app.db import get_connection
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO edges (osm_id, name, highway, length_m, geom)
                VALUES (%s, 'TEST heat edge', 'path', 150.0,
                        ST_SetSRID(ST_MakeLine(ST_MakePoint(-71.3600, 43.1300), ST_MakePoint(-71.3590, 43.1310)), 4326))
                ON CONFLICT (osm_id) DO NOTHING;
                INSERT INTO edge_heat (edge_osm_id, sport, unique_riders_12mo, total_passes_12mo, weighted_score, is_public)
                VALUES (%s, 'mtb', 3, 5, 4.0, TRUE)
                ON CONFLICT (edge_osm_id, sport) DO UPDATE SET is_public = TRUE, weighted_score = 4.0;
                """,
                (TEST_HEAT_EDGE, TEST_HEAT_EDGE),
            )
        conn.commit()


def test_resolve_osm_trail_name_known_registry():
    # Names verified against the OSM extract (Round 7 audit); unknown ways have no invented name.
    assert resolve_osm_trail_name(42743791) == "Grandview Road"
    assert resolve_osm_trail_name(220551352) == "Bobcat Trail"
    assert resolve_osm_trail_name(220551345) == "Salt Lick Trail"
    assert resolve_osm_trail_name(999202) is None


def test_get_heat_trail_geojson_structure():
    _seed_public_heat_edge()
    geojson = get_heat_trail_geojson(sport="mtb")
    assert geojson["type"] == "FeatureCollection"
    feats = [f for f in geojson["features"] if f["properties"]["osm_id"] == TEST_HEAT_EDGE]
    assert len(feats) == 1
    first = feats[0]
    assert first["type"] == "Feature"
    assert first["geometry"]["type"] == "LineString"
    props = first["properties"]
    assert props["heat_score"] == 4.0
    assert props["ride_count"] == 5
    assert "name" in props


def test_heat_geojson_hides_private_heat():
    """Heat below the rider threshold (is_public = FALSE) is never on the shared heat layer."""
    from app.db import get_connection
    _seed_public_heat_edge()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE edge_heat SET is_public = FALSE WHERE edge_osm_id = %s", (TEST_HEAT_EDGE,))
        conn.commit()
    geojson = get_heat_trail_geojson(sport="mtb")
    assert not any(f["properties"]["osm_id"] == TEST_HEAT_EDGE for f in geojson["features"])


@pytest.mark.asyncio
async def test_api_heat_trails_endpoint():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        _seed_public_heat_edge()
        res = await client.get("/api/heat/trails")
        assert res.status_code == 200
        data = res.json()
        assert data["type"] == "FeatureCollection"
        feat = next(f for f in data["features"] if f["properties"]["osm_id"] == TEST_HEAT_EDGE)
        assert feat["properties"]["heat_score"] > 0
        assert feat["properties"]["name"] == "TEST heat edge"


@pytest.mark.asyncio
async def test_api_dev_status_auth_and_anonymous_rejection():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res_anon = await client.get("/api/dev/status")
        assert res_anon.status_code == 401

        res_rider = await client.get("/api/dev/status", headers=as_user("plain_rider"))
        assert res_rider.status_code == 403

        res_admin = await client.get("/api/dev/status", headers=as_user("round3_admin", admin=True))
        assert res_admin.status_code == 200
        data = res_admin.json()
        assert data["status"] in ("healthy", "degraded")
        assert data["database_connected"] is True
        assert "uptime_seconds" in data
        assert "connectors" in data


@pytest.mark.asyncio
async def test_api_otm_trails_endpoint():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        _seed_public_heat_edge()
        res = await client.get("/api/otm/trails", params={
            "min_lat": 43.12, "min_lon": -71.37, "max_lat": 43.14, "max_lon": -71.35, "sport": "mtb"})
        assert res.status_code == 200
        data = res.json()
        assert data["type"] == "FeatureCollection"
        feat = next(f for f in data["features"] if f["properties"]["osm_id"] == TEST_HEAT_EDGE)
        assert feat["properties"]["difficulty"] == "unknown"  # no mtb:scale tag -> not rated, not guessed
        assert feat["properties"]["name"] == "TEST heat edge"


@pytest.mark.asyncio
async def test_api_cubetrek_import_endpoint(monkeypatch):
    """When CubeTrek can't be reached, the import fails visibly; nothing is invented."""
    import httpx
    from app.connectors.cubetrek import httpx as cubetrek_httpx

    class Offline(httpx.AsyncClient):
        async def get(self, *args, **kwargs):
            raise httpx.ConnectError("offline")

    monkeypatch.setattr(cubetrek_httpx, "AsyncClient", Offline)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post(
            "/api/connectors/cubetrek/import",
            json={"url_or_id": "https://cubetrek.com/view?id=99281", "sport": "mtb", "import_to_heat": True},
            headers={"X-Test-User": "test_cubetrek_user"}
        )
        assert res.status_code == 400
        assert "Could not load CubeTrek track" in res.json()["detail"]


@pytest.mark.asyncio
async def test_user_export_gps_data():
    from app.db import record_activity, record_activity_edge_visits
    _seed_public_heat_edge()
    uid = "test_export_user"
    record_activity({"id": "test_export_act_1", "user_id": uid, "sport": "mtb",
                     "distance_miles": 1.0, "duration_minutes": 10.0, "file_format": "gpx"})
    record_activity_edge_visits("test_export_act_1", {TEST_HEAT_EDGE: 1}, uid, "mtb")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        exp_res = await client.get("/api/privacy/export", headers={"X-Test-User": uid})
        assert exp_res.status_code == 200
        data = exp_res.json()
        act = next(a for a in data["activities"] if a["id"] == "test_export_act_1")
        assert "visited_edges" in act
        # GPS coordinates in the export are the visited edges' real geometry.
        assert act["gps_coordinates"]
        assert [-71.36, 43.13] in [[round(c[0], 2), round(c[1], 2)] for c in act["gps_coordinates"]]
        assert "heat_trail_contributions" in data
