"""GH-44: a dead-end spur ridden out and back is found, cut when unwanted, kept when required,
and never hidden behind a "clean loop" label."""
import pytest

from app.models import LatLon, RouteRequest, SportProfile
from app.route_builder import Piece, build_route_response, haversine_m, trim_spurs
from app.scoring import calculate_composite_score, find_spurs

PATH = {"highway": "path"}


def _req(**kw):
    base = dict(start=LatLon(lat=43.13, lon=-71.50, name="Test"), profile=SportProfile.MTB,
                route_mode="loop", target_distance_miles=2.0)
    base.update(kw)
    return RouteRequest(**base)


def _build(coords, pieces, req=None, **kw):
    return build_route_response(coords, pieces, req or _req(), "test", None, trust_result={"all_warnings": []},
                                heat_cache={}, covered=False, check_geometry=False, **kw)


@pytest.fixture(autouse=True)
def _no_dem(monkeypatch):
    import app.route_builder as rb
    monkeypatch.setattr(rb, "route_elevation", lambda pts: (None, None, None))


D = 0.01  # ~1.1 km on a side
# Loop with a spur from the SE corner: A=(D,0) -> spur out to S2 and back to A.
SQ = [[-71.50, 43.13], [-71.50 + D, 43.13], [-71.50 + D, 43.13 + D], [-71.50, 43.13 + D]]
SPUR = [[-71.50 + D, 43.13 - 0.001], [-71.50 + D, 43.13 - 0.002]]  # ~220 m out


def _loop_with_spur():
    a = SQ[1]
    coords = [SQ[0], a] + SPUR + [SPUR[0], a] + [SQ[2], SQ[3], SQ[0]]
    pieces = [Piece(0, 1, 1, PATH), Piece(1, 5, 2, PATH), Piece(5, 9, 3, PATH)]
    return coords, pieces


def _spur_len():
    return haversine_m(SQ[1], SPUR[1])


def test_spur_detected_with_right_length():
    coords, _ = _loop_with_spur()
    spurs = find_spurs(coords)
    assert len(spurs) == 1
    assert (spurs[0].start_idx, spurs[0].turn_idx, spurs[0].end_idx) == (1, 3, 5)
    assert spurs[0].length_m == pytest.approx(_spur_len(), abs=1.0)


def test_spur_free_loop_unchanged():
    coords = SQ + [SQ[0]]
    assert find_spurs(coords) == []
    pieces = [Piece(0, 4, 1, PATH)]
    c2, p2, cut = trim_spurs(coords, pieces)
    assert c2 == coords and p2 == pieces and cut == []
    r = _build(coords, pieces).route
    assert r.score_breakdown["spur_count"] == 0 and "clean loop" in r.verbal_summary


def test_cut_spur_leaves_continuous_geometry():
    coords, pieces = _loop_with_spur()
    c2, p2, cut = trim_spurs(coords, pieces)
    assert len(cut) == 1
    assert c2 == [SQ[0], SQ[1], SQ[2], SQ[3], SQ[0]]
    assert [(p.start, p.end, p.way_id) for p in p2] == [(0, 1, 1), (1, 4, 3)]
    assert max(haversine_m(c2[i], c2[i + 1]) for i in range(len(c2) - 1)) < 1300.0
    r = _build(coords, pieces).route
    assert r.repetition_ratio == 0.0 and r.score_breakdown["spur_count"] == 0
    assert r.distance_miles == pytest.approx(_build(SQ + [SQ[0]], [Piece(0, 4, 1, PATH)]).route.distance_miles)


def test_required_point_keeps_its_spur():
    coords, pieces = _loop_with_spur()
    tip = SPUR[1]
    c2, p2, cut = trim_spurs(coords, pieces, [tip])
    assert c2 == coords and cut == []
    r = _build(coords, pieces, required_points=[tip]).route
    assert r.repetition_ratio > 0
    assert r.score_breakdown["spur_count"] == 0 and "spur" not in r.verbal_summary


def test_req_waypoints_are_required_by_default():
    coords, pieces = _loop_with_spur()
    req = _req(waypoints=[LatLon(lat=SPUR[1][1], lon=SPUR[1][0])])
    assert _build(coords, pieces, req).route.repetition_ratio > 0


def test_spur_at_route_start_is_cut_but_whole_out_and_back_is_not():
    coords = [SQ[0]] + [[-71.50, 43.13 - 0.002]] + [SQ[0], SQ[1], SQ[2], SQ[3], SQ[0]]
    pieces = [Piece(0, 2, 1, PATH), Piece(2, 6, 2, PATH)]
    c2, _, cut = trim_spurs(coords, pieces)
    assert len(cut) == 1 and c2 == SQ + [SQ[0]]
    oab = [SQ[0], SQ[1], SQ[2], SQ[1], SQ[0]]
    c3, _, cut3 = trim_spurs(oab, [Piece(0, 4, 1, PATH)])
    assert c3 == oab and cut3 == []
    assert _build(oab, [Piece(0, 4, 1, PATH)]).route.route_type == "out_and_back"


def test_label_and_penalty_scale_with_spur_length():
    kw = dict(distance_miles=2.0, target_distance_miles=2.0, surface_breakdown={"singletrack": 100.0},
              surface_strip=[], preference=None, sport=SportProfile.MTB, repetition_ratio=0.03, warnings=[],
              edge_osm_ids=[])
    _, b0, v0 = calculate_composite_score(**kw)
    _, b1, v1 = calculate_composite_score(**kw, spur_count=1, spur_max_m=320.0)
    assert "clean loop" in v0 and "clean loop" not in v1 and "0.2 mi spur" in v1
    assert b1["penalties"] < b0["penalties"]
    _, _, v2 = calculate_composite_score(**kw, spur_count=1, spur_max_m=40.0)
    assert "clean loop" in v2


def test_nested_and_double_spur_fully_cut():
    # A spur with a branch on its way out: out A-B-C-B-A with a fork B-D-B inside is one maximal
    # palindrome only if symmetric; here two separate spurs on one loop are both removed.
    a, b = SQ[1], SQ[2]
    s1 = [[a[0], a[1] - 0.001]]
    s2 = [[b[0] + 0.001, b[1]]]
    coords = [SQ[0], a] + s1 + [a, b] + s2 + [b, SQ[3], SQ[0]]
    pieces = [Piece(0, len(coords) - 1, 7, PATH)]
    c2, _, cut = trim_spurs(coords, pieces)
    assert len(cut) == 2 and c2 == SQ + [SQ[0]]


# ------------------------------------------------------------------------------------------
# Live: public trailheads only (frontend/src/data/trailheads.json), never a rider's position
# ------------------------------------------------------------------------------------------

def _live_ready():
    import json, pathlib
    import httpx
    from app.config import settings
    if not (pathlib.Path(__file__).resolve().parents[1] / "frontend/src/data/trailheads.json").exists():
        return "trailheads.json not built (scripts/build_trailheads.py)"
    try:
        if httpx.get(f"{settings.graphhopper_url}/health", timeout=2).status_code != 200:
            return "GraphHopper is not running"
        from app.db import get_connection
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM trail_segments")
            if cur.fetchone()[0] == 0:
                return "OSM graph not imported"
    except Exception:
        return "GraphHopper or PostGIS is not reachable"
    return None


@pytest.mark.skipif(_live_ready() is not None, reason=str(_live_ready()))
@pytest.mark.parametrize("name", ["Bow Town Forest parking", "Bear Brook State Park parking"])
def test_live_plain_loops_have_no_spur_over_50m(name, monkeypatch):
    import asyncio, json, pathlib
    from app.models import RouteOptionsRequest
    from app.routing import plan_route_options
    monkeypatch.undo()  # this module's autouse DEM stub must not hide a real elevation failure
    root = pathlib.Path(__file__).resolve().parents[1]
    th = next(t for t in json.loads((root / "frontend/src/data/trailheads.json").read_text())["trailheads"]
              if t["name"] == name)
    req = RouteOptionsRequest(start=LatLon(lat=th["lat"], lon=th["lon"], name=name), profile="mtb_hardtail",
                              route_mode="loop", target_distance_miles=10.0, candidate_count=10)
    res = asyncio.run(plan_route_options(req, count=10))
    assert res.options
    for o in res.options:
        assert max([s.length_m for s in find_spurs([c[:2] for c in o.coordinates])], default=0.0) <= 50.0, o.name
        assert "clean loop" not in o.verbal_summary or o.score_breakdown["spur_count"] == 0
        assert o.geometry_max_offset_m is not None and o.geometry_max_offset_m <= 15.0
