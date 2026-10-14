"""Round 7 (GH-34) phase 5: Garmin export heat import, the rider threshold, real loop seeds."""
import asyncio
import datetime
import uuid

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from app.config import settings
from app.decay import aggregate_edge_visits, heat_sport, min_unique_riders
from app.main import app
from tests.conftest import as_user


def _visits(n_riders):
    now = datetime.datetime.now(datetime.timezone.utc)
    return [{"user_id": f"r{i}", "visited_at": now, "pass_count": 1} for i in range(n_riders)]


def test_min_unique_riders_defaults_to_three_and_can_be_overridden(monkeypatch):
    from app.config import Settings
    assert Settings().heat_min_unique_riders == 3 or "HEAT_MIN_UNIQUE_RIDERS" in __import__("os").environ
    monkeypatch.setattr(settings, "heat_min_unique_riders", 3)
    assert min_unique_riders() == 3
    assert aggregate_edge_visits(_visits(2))["is_public"] is False
    assert aggregate_edge_visits(_visits(3))["is_public"] is True
    monkeypatch.setattr(settings, "heat_min_unique_riders", 1)
    assert aggregate_edge_visits(_visits(1))["is_public"] is True


@pytest.mark.asyncio
async def test_heat_meta_reports_the_rule(monkeypatch):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        monkeypatch.setattr(settings, "heat_min_unique_riders", 3)
        monkeypatch.setattr(settings, "seed_heat_public", True)
        assert (await client.get("/api/heat/meta")).json() == {"min_unique_riders": 3, "seed_heat_public": True}
        monkeypatch.setattr(settings, "seed_heat_public", False)
        assert (await client.get("/api/heat/meta")).json()["seed_heat_public"] is False


def test_recalculation_uses_the_threshold(monkeypatch):
    from app.db import get_connection, record_activity, record_activity_edge_visits, recalculate_all_edge_heat
    edge = 991951
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO edges (osm_id, name, highway) VALUES (%s, 'TEST threshold edge', 'path') "
                    "ON CONFLICT (osm_id) DO NOTHING", (edge,))
        conn.commit()
    act = f"test_threshold_{uuid.uuid4().hex[:8]}"
    record_activity({"id": act, "user_id": "threshold_rider", "sport": "mtb", "distance_miles": 1.0})
    record_activity_edge_visits(act, {edge: 1}, "threshold_rider", "mtb_hardtail")  # profile -> heat sport
    try:
        for n, expected in ((3, False), (1, True)):
            monkeypatch.setattr(settings, "heat_min_unique_riders", n)
            recalculate_all_edge_heat()
            with get_connection() as conn, conn.cursor() as cur:
                cur.execute("SELECT is_public, sport FROM edge_heat WHERE edge_osm_id = %s", (edge,))
                assert cur.fetchone() == (expected, "mtb")
    finally:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM activities WHERE id = %s", (act,))
            conn.commit()


def test_heat_sport_mapping():
    for p in ("mtb", "mtb_hardtail", "mtb_fullsus", "mtb_fat", "mtb_emtb"):
        assert heat_sport(p) == "mtb"
    for p in ("mtb_gravel", "bike", "gravel"):
        assert heat_sport(p) == "gravel"
    for p in ("trail_run", "foot"):
        assert heat_sport(p) == "trail_run"


@pytest.mark.asyncio
async def test_bulk_import_is_admin_only():
    body = {"tracks": []}
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        assert (await client.post("/api/admin/heat/bulk-import", json=body)).status_code == 401
        assert (await client.post("/api/admin/heat/bulk-import", json=body, headers=as_user("rider"))).status_code == 403
        ok = await client.post("/api/admin/heat/bulk-import", json=body, headers=as_user("r7_admin", admin=True))
        assert ok.status_code == 200 and ok.json()["matched"] == 0
        too_many = {"tracks": [{"activity_id": str(i)} for i in range(26)]}
        assert (await client.post("/api/admin/heat/bulk-import", json=too_many,
                                  headers=as_user("r7_admin", admin=True))).status_code == 400


def _gh_ok():
    try:
        return httpx.get(f"{settings.graphhopper_url}/health", timeout=2).status_code == 200
    except Exception:
        return False


def _loop_track():
    """A test track along a real trail-graph loop in Bear Brook (test fixture, not a user ride)."""
    import json, pathlib
    from app.trail_graph import graph_for
    th = next(t for t in json.loads((pathlib.Path(__file__).parents[1] / "frontend/src/data/trailheads.json").read_text())
              ["trailheads"] if t["parking_osm"] == "way/414782002")
    g = graph_for(th["lon"], th["lat"], 0.6 * 6 * 1609.344, bike=True)
    loops = g.search_loops(th["lon"], th["lat"], 6 * 1609.344, 0.2, 1000.0, seed=3, time_budget_s=1.5)
    coords = g.coords_of(loops[0].steps)
    t0 = int(datetime.datetime(2026, 9, 1, 14, tzinfo=datetime.timezone.utc).timestamp())
    return th, [[c[1], c[0], t0 + 4 * i] for i, c in enumerate(coords)]


@pytest.mark.skipif(not _gh_ok(), reason="GraphHopper is not running")
def test_import_stores_no_points_is_idempotent_and_seeds_a_loop(monkeypatch):
    from app.db import get_connection

    uid = f"r7_seed_{uuid.uuid4().hex[:6]}"
    garmin_id = str(900000000 + uuid.uuid4().int % 99999999)
    th, points = _loop_track()
    track = {"activity_id": garmin_id, "sport": "mtb", "start_time": "2026-09-01T14:00:00+00:00",
             "is_loop": True, "points": points}
    try:
        _seed_checks(uid, garmin_id, th, track, monkeypatch)
    finally:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM seed_loops WHERE %s = ANY(rider_ids)", (uid,))
            cur.execute("DELETE FROM users WHERE id = %s", (uid,))  # cascades to activities and visits
            conn.commit()


def _seed_checks(uid, garmin_id, th, track, monkeypatch):
    from app.db import get_connection
    from app.garmin_seeds import seed_catalog
    from app.heat_import import import_tracks
    from app.models import LatLon, RouteOptionsRequest

    res = asyncio.run(import_tracks(uid, [track]))
    assert res["matched"] == 1, res
    assert res["results"][0]["seed"] in ("stored", "merged")
    again = asyncio.run(import_tracks(uid, [track]))
    assert again["skipped"] == 1 and again["results"][0]["reason"] == "already imported"

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT raw_file_retained, raw_file_path, source, consent_given FROM activities WHERE id = %s",
                    (f"garmin_export_{garmin_id}",))
        assert cur.fetchone() == (False, None, "garmin_export", True)
        # no table this import writes to has any place for coordinates
        cur.execute("""SELECT table_name, column_name FROM information_schema.columns
                       WHERE table_name IN ('activities', 'activity_edge_visits', 'seed_loops')
                         AND (udt_name IN ('geometry', 'json', 'jsonb') OR column_name ~ '(lat|lon|point|coord)')
                         AND column_name <> 'centroid_rounded'""")
        assert cur.fetchall() == []

    # the ridden loop is offered back to its rider as a seed candidate
    monkeypatch.setattr(settings, "heat_min_unique_riders", 3)
    seeds = seed_catalog.get_matching_seeds(th["lat"], th["lon"], 6.0, sport="mtb_hardtail", user_id=uid)
    assert seeds
    monkeypatch.setattr(settings, "seed_heat_public", False)  # the trail-share rule is tested in test_round8_heat_privacy
    assert seed_catalog.get_matching_seeds(th["lat"], th["lon"], 6.0, sport="mtb_hardtail", user_id="someone_else") == []
    req = RouteOptionsRequest(start=LatLon(lat=th["lat"], lon=th["lon"], name=th["name"]), profile="mtb_hardtail",
                              route_mode="loop", target_distance_miles=6.0)
    built = seed_catalog.build_candidate(seeds[0], req)
    assert built is not None
    coords, pieces = built
    assert coords[0] == coords[-1] and pieces
