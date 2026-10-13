"""Round 8 (GH-38) phase 1: one publication rule for heat, through every reader.

Uses real OSM edges and trail segments from the dev database (no invented geometry): each test
picks edges nobody has ridden, adds visits for throwaway users, and removes everything again.
"""
import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import settings
from app.db import (
    delete_user_account, get_connection, get_edge_heat, get_edges_heat, get_heat_trail_geojson,
    get_unridden_high_heat_trails, record_activity, record_activity_edge_visits, recalculate_all_edge_heat,
    refresh_edge_heat,
)
from app.decay import heat_is_public
from app.garmin_seeds import seed_catalog
from app.main import app

TRAIL = ("path", "track", "bridleway", "cycleway")
NOT_TRAIL = ("residential", "footway", "service", "unclassified")


def _free_edge(highway: str, n: int = 1):
    """Real, geometry-bearing edges of this highway class with no visits from anyone."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT e.osm_id FROM edges e
               WHERE e.highway = %s AND e.geom IS NOT NULL AND e.length_m > 150
                 AND NOT EXISTS (SELECT 1 FROM activity_edge_visits v WHERE v.edge_osm_id = e.osm_id)
                 AND NOT EXISTS (SELECT 1 FROM edge_heat h WHERE h.edge_osm_id = e.osm_id AND h.weighted_score > 0)
               ORDER BY e.osm_id LIMIT %s""", (highway, n))
        rows = [r[0] for r in cur.fetchall()]
    if len(rows) < n:
        pytest.skip(f"no free {highway} edge in the dev database (run scripts/import_osm_graph.py)")
    return rows if n > 1 else rows[0]


def _ride(uid, edge, seed=False, sport="mtb"):
    act = f"r8_{uuid.uuid4().hex[:10]}"
    record_activity({"id": act, "user_id": uid, "sport": sport, "distance_miles": 1.0})
    if seed:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("UPDATE activities SET source = 'garmin_export' WHERE id = %s", (act,))
            conn.commit()
    record_activity_edge_visits(act, {edge: 1}, uid, sport)
    return act


def _cleanup(uids, edges):
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM seed_loops WHERE user_id = ANY(%s)", (uids,))
        cur.execute("DELETE FROM users WHERE id = ANY(%s)", (uids,))  # cascades to activities and visits
        conn.commit()
    refresh_edge_heat(edges)


@pytest.fixture
def riders():
    uids = [f"r8_{uuid.uuid4().hex[:8]}" for _ in range(4)]
    edges = []
    yield uids, edges
    _cleanup(uids, edges)


def _is_public(edge, sport="mtb"):
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT is_public FROM edge_heat WHERE edge_osm_id = %s AND sport = %s", (edge, sport))
        row = cur.fetchone()
    return bool(row and row[0])


def _in_geojson(edge):
    return any(f["properties"]["osm_id"] == edge for f in get_heat_trail_geojson(sport="mtb", limit=100000)["features"])


def _edge_point(edge):
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT ST_Y(ST_PointOnSurface(geom)), ST_X(ST_PointOnSurface(geom)) FROM edges WHERE osm_id = %s", (edge,))
        return cur.fetchone()


def test_rule_unit(monkeypatch):
    monkeypatch.setattr(settings, "heat_min_unique_riders", 3)
    monkeypatch.setattr(settings, "seed_heat_public", True)
    assert not heat_is_public(2, False, "path")
    assert heat_is_public(3, False, "residential")
    for hw in TRAIL:
        assert heat_is_public(1, True, hw)
    for hw in NOT_TRAIL + (None,):
        assert not heat_is_public(1, True, hw)
    assert not heat_is_public(1, False, "path")
    monkeypatch.setattr(settings, "seed_heat_public", False)
    assert not heat_is_public(1, True, "path")


def test_threshold_defaults_to_three():
    from app.config import Settings
    import os
    assert Settings().heat_min_unique_riders == 3 or "HEAT_MIN_UNIQUE_RIDERS" in os.environ
    assert Settings().seed_heat_public is True or "SEED_HEAT_PUBLIC" in os.environ


@pytest.mark.asyncio
async def test_one_rider_is_private_through_every_reader_even_before_recalculation(riders, monkeypatch):
    monkeypatch.setattr(settings, "heat_min_unique_riders", 3)
    uids, edges = riders
    edge = _free_edge("path")
    edges.append(edge)
    _ride(uids[0], edge)  # an ordinary upload: no recalculation has run
    assert not _is_public(edge)
    assert not _in_geojson(edge)
    lat, lon = _edge_point(edge)
    assert all(t["edge_osm_id"] != edge for t in get_unridden_high_heat_trails(uids[1], lat, lon, 1.0, "mtb"))
    assert edge not in get_edges_heat([edge], "mtb", user_id=uids[1])  # routing lookup for another user
    other = get_edge_heat(edge, "mtb", user_id=uids[1])
    assert other["weighted_score"] == 0.0 and other["unique_riders_12mo"] == 0 and not other["is_accessible"]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/api/heat/trails", params={"sport": "mtb"})
        assert all(f["properties"]["osm_id"] != edge for f in r.json()["features"])
    # the rider still sees their own heat
    assert edge in get_edges_heat([edge], "mtb", user_id=uids[0])
    recalculate_all_edge_heat()
    assert not _is_public(edge) and not _in_geojson(edge)


def test_a_contributor_sees_only_their_own_contribution_on_a_private_edge(riders, monkeypatch):
    monkeypatch.setattr(settings, "heat_min_unique_riders", 3)
    uids, edges = riders
    edge = _free_edge("residential")
    edges.append(edge)
    _ride(uids[0], edge)
    _ride(uids[1], edge)
    mine = get_edges_heat([edge], "mtb", user_id=uids[0])[edge]
    assert mine["unique_riders_12mo"] == 1 and mine["total_passes_12mo"] == 1
    assert 0.9 < mine["weighted_score"] <= 1.0  # one pass, not two riders' sum
    assert mine["contributor_ids"] == [uids[0]]


def test_three_riders_are_public(riders, monkeypatch):
    monkeypatch.setattr(settings, "heat_min_unique_riders", 3)
    uids, edges = riders
    edge = _free_edge("residential")  # public by riders on any road class
    edges.append(edge)
    for u in uids[:2]:
        _ride(u, edge)
    assert not _is_public(edge)
    _ride(uids[2], edge)
    assert _is_public(edge) and _in_geojson(edge)
    assert edge in get_edges_heat([edge], "mtb", user_id=uids[3])
    recalculate_all_edge_heat()
    assert _is_public(edge)


@pytest.mark.parametrize("highway", TRAIL)
def test_seed_visit_on_trail_class_is_public(riders, monkeypatch, highway):
    monkeypatch.setattr(settings, "heat_min_unique_riders", 3)
    monkeypatch.setattr(settings, "seed_heat_public", True)
    uids, edges = riders
    edge = _free_edge(highway)
    edges.append(edge)
    _ride(uids[0], edge, seed=True)
    assert _is_public(edge) and _in_geojson(edge)
    recalculate_all_edge_heat()
    assert _is_public(edge)


@pytest.mark.parametrize("highway", NOT_TRAIL)
def test_seed_visit_off_trail_is_not_public(riders, monkeypatch, highway):
    monkeypatch.setattr(settings, "heat_min_unique_riders", 3)
    monkeypatch.setattr(settings, "seed_heat_public", True)
    uids, edges = riders
    edge = _free_edge(highway)
    edges.append(edge)
    _ride(uids[0], edge, seed=True)
    assert not _is_public(edge) and not _in_geojson(edge)
    recalculate_all_edge_heat()
    assert not _is_public(edge)


def test_seed_heat_public_false_hides_seed_on_trails(riders, monkeypatch):
    monkeypatch.setattr(settings, "heat_min_unique_riders", 3)
    monkeypatch.setattr(settings, "seed_heat_public", False)
    uids, edges = riders
    edge = _free_edge("path")
    edges.append(edge)
    _ride(uids[0], edge, seed=True)
    assert not _is_public(edge)
    recalculate_all_edge_heat()
    assert not _is_public(edge)


def test_account_deletion_removes_a_contributors_effect(riders, monkeypatch):
    monkeypatch.setattr(settings, "heat_min_unique_riders", 3)
    uids, edges = riders
    edge = _free_edge("path")
    edges.append(edge)
    for u in uids[:3]:
        _ride(u, edge)
    assert _is_public(edge)
    assert delete_user_account(uids[2])
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT is_public, unique_riders_12mo, contributor_ids FROM edge_heat WHERE edge_osm_id = %s", (edge,))
        is_pub, n, contribs = cur.fetchone()
    assert not is_pub and n == 2 and uids[2] not in contribs


def test_migration_007_backfills_seed_visits():
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("""SELECT count(*) FROM activity_edge_visits v JOIN activities a ON a.id = v.activity_id
                       WHERE a.source = 'garmin_export' AND NOT v.is_seed""")
        assert cur.fetchone()[0] == 0


def _loop_row(uid, segments, sport="mtb"):
    ways = [s[1] for s in segments]
    with get_connection() as conn, conn.cursor() as cur:
        act = f"r8_{uuid.uuid4().hex[:10]}"
        record_activity({"id": act, "user_id": uid, "sport": sport, "distance_miles": 1.0})
        cur.execute("UPDATE activities SET source = 'garmin_export' WHERE id = %s", (act,))
        cur.execute(
            "INSERT INTO seed_loops (user_id, activity_id, sport, way_ids, node_path, segment_ids, osm_import_id, "
            "distance_m, retrace, rider_ids) VALUES (%s,%s,%s,%s,%s,%s,NULL,%s,0,%s)",
            (uid, act, sport, ways, [s[2] for s in segments] + [segments[-1][3]], [s[0] for s in segments],
             sum(s[4] for s in segments), [uid]))
        conn.commit()


def _segments_near(lon, lat, classes, total_m=8000.0):
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT segment_id, osm_way_id, from_node, to_node, length_m FROM trail_segments
               WHERE highway = ANY(%s)
                 AND ST_DWithin(geom::geography, ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography, 2000)
               ORDER BY geom <-> ST_SetSRID(ST_MakePoint(%s, %s), 4326)""", (list(classes), lon, lat, lon, lat))
        out, acc = [], 0.0
        for row in cur.fetchall():
            out.append(row)
            acc += row[4]
            if acc >= total_m:
                return out
    return None


def test_seed_loop_gating_by_trail_share(riders, monkeypatch):
    import json, pathlib
    monkeypatch.setattr(settings, "heat_min_unique_riders", 3)
    monkeypatch.setattr(settings, "seed_heat_public", True)
    uids, _ = riders
    th = json.loads((pathlib.Path(__file__).parents[1] / "frontend/src/data/trailheads.json").read_text())["trailheads"]
    bear = next(t for t in th if t["parking_osm"] == "way/414782002")
    concord = next(t for t in th if "Oak Hill" in t["name"])
    trail_segs = _segments_near(bear["lon"], bear["lat"], TRAIL)
    road_segs = _segments_near(concord["lon"], concord["lat"], ("residential", "unclassified", "tertiary", "service"))
    if not trail_segs or not road_segs:
        pytest.skip("OSM graph not imported in the dev database")
    _loop_row(uids[0], trail_segs)
    stranger = uids[1]
    assert seed_catalog.get_matching_seeds(bear["lat"], bear["lon"], 5.0, sport="mtb", user_id=stranger)
    monkeypatch.setattr(settings, "seed_heat_public", False)
    assert not seed_catalog.get_matching_seeds(bear["lat"], bear["lon"], 5.0, sport="mtb", user_id=stranger)
    monkeypatch.setattr(settings, "seed_heat_public", True)
    _loop_row(uids[0], road_segs)
    got = seed_catalog.get_matching_seeds(concord["lat"], concord["lon"], 5.0, sport="mtb", user_id=stranger)
    assert all(g.way_ids != [s[1] for s in road_segs] for g in got)  # the road-heavy loop is not offered
