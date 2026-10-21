"""Midpoint (via) benchmark scenarios, GH-41 phase 1. Reproducible: same PostGIS import, same file.

    python -m loam_eval via-scenarios        # writes benchmark/via_scenarios.json

Starts are public trailheads only (frontend/src/data/trailheads.json, built from OSM by
scripts/build_trailheads.py); nothing here reads data/garmin-stripped or any GPS start. Midpoints
are picked programmatically from trail_segments: the trail point nearest to a spot at a given
bearing and straight-line distance from the trailhead. Selection is deterministic (distance, then
segment_id).

Each scenario: id, kind, start [lat, lon], start_osm, name, profile, mode, miles, waypoints
[[lat, lon], ...], optional end, `expect` (the outcome the plan asks for) and `via_meta` (what the
picker found: way id, trail name, class, snap distance to the network, dead-end flag).
"""
from __future__ import annotations

import json
import math
import os
from typing import Any, Dict, List, Optional, Tuple

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
TRAILHEADS = os.path.join(ROOT, "frontend", "src", "data", "trailheads.json")
OUT = os.path.join(ROOT, "benchmark", "via_scenarios.json")
R = 6371008.8
PROFILE = "mtb_hardtail"
OFF_ROAD = ("singletrack", "doubletrack", "gravel")


def destination(lat: float, lon: float, bearing: float, dist_m: float) -> Tuple[float, float]:
    b, d = math.radians(bearing), dist_m / R
    p1, l1 = math.radians(lat), math.radians(lon)
    p2 = math.asin(math.sin(p1) * math.cos(d) + math.cos(p1) * math.sin(d) * math.cos(b))
    l2 = l1 + math.atan2(math.sin(b) * math.sin(d) * math.cos(p1), math.cos(d) - math.sin(p1) * math.sin(p2))
    return math.degrees(p2), (math.degrees(l2) + 540) % 360 - 180


def _q(sql: str, args: tuple):
    from app.db import get_connection
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(sql, args)
        return cur.fetchall()


def trail_point(lat: float, lon: float, *, cats=OFF_ROAD, radius_m: float = 900.0) -> Optional[Dict[str, Any]]:
    """The trail point (segment midpoint) nearest the spot; None if none within radius_m."""
    rows = _q(
        """WITH p AS (SELECT ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography g),
                c AS (SELECT segment_id, osm_way_id, name, highway, category,
                             ST_LineInterpolatePoint(geom, 0.5) pt, geom FROM trail_segments, p
                      WHERE category = ANY(%s) AND geom && ST_Expand(p.g::geometry, %s)
                        AND ST_DWithin(geom::geography, p.g, %s))
           SELECT ST_Y(pt), ST_X(pt), segment_id, osm_way_id, name, highway, category,
                  ST_Distance(geom::geography, (SELECT g FROM p)) snap
           FROM c ORDER BY ST_Distance(pt::geography, (SELECT g FROM p)), segment_id LIMIT 1""",
        (lon, lat, list(cats), radius_m / 111000.0 * 1.5, radius_m))
    if not rows:
        return None
    y, x, seg, way, name, hw, cat, snap = rows[0]
    return {"point": [round(y, 6), round(x, 6)], "segment_id": seg, "osm_way_id": way, "name": name,
            "highway": hw, "category": cat, "spot_to_point_m": round(snap, 1)}


def dead_end_point(lat: float, lon: float, bearing: float, dist_m: float) -> Optional[Dict[str, Any]]:
    """A trail-end node (degree 1, off-road) nearest the spot."""
    slat, slon = destination(lat, lon, bearing, dist_m)
    rows = _q(
        """WITH ends AS (
             SELECT n, (array_agg(segment_id ORDER BY segment_id))[1] seg FROM (
               SELECT from_node n, segment_id FROM trail_segments WHERE geom && ST_Expand(ST_SetSRID(ST_MakePoint(%s, %s), 4326), 0.05) UNION ALL
               SELECT to_node, segment_id FROM trail_segments WHERE geom && ST_Expand(ST_SetSRID(ST_MakePoint(%s, %s), 4326), 0.05)) x
             GROUP BY n HAVING count(*) = 1)
           SELECT ST_Y(e.pt), ST_X(e.pt), t.segment_id, t.osm_way_id, t.name, t.highway, t.category
           FROM (SELECT ends.n, ends.seg,
                        CASE WHEN ts.from_node = ends.n THEN ST_StartPoint(ts.geom) ELSE ST_EndPoint(ts.geom) END pt
                 FROM ends JOIN trail_segments ts ON ts.segment_id = ends.seg
                 WHERE ts.category = ANY(%s)
                   AND ST_DWithin(ts.geom::geography, ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography, 1500)) e
           JOIN trail_segments t ON t.segment_id = e.seg
           ORDER BY ST_Distance(e.pt::geography, ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography), t.segment_id
           LIMIT 1""", (slon, slat, slon, slat, list(OFF_ROAD), slon, slat, slon, slat))
    if not rows:
        return None
    y, x, seg, way, name, hw, cat = rows[0]
    return {"point": [round(y, 6), round(x, 6)], "segment_id": seg, "osm_way_id": way, "name": name,
            "highway": hw, "category": cat, "dead_end": True}


def off_network_point(lat: float, lon: float) -> Optional[Dict[str, Any]]:
    """A spot 1-4 km from the trailhead that is >= 500 m from every segment (water or wilderness)."""
    for radius in (1500, 2000, 2500, 3000, 3500, 4000):
        for bearing in range(0, 360, 15):
            plat, plon = destination(lat, lon, bearing, radius)
            near = _q("SELECT min(ST_Distance(geom::geography, ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography)) "
                      "FROM trail_segments WHERE geom && ST_Expand(ST_SetSRID(ST_MakePoint(%s, %s), 4326), 0.01) "
                      "AND ST_DWithin(geom::geography, ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography, 500)",
                      (plon, plat, plon, plat, plon, plat))
            if near[0][0] is None:
                return {"point": [round(plat, 6), round(plon, 6)], "bearing": bearing, "radius_m": radius}
    return None


def snap_m(lat: float, lon: float, cats=None) -> float:
    rows = _q("SELECT min(ST_Distance(geom::geography, ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography)) "
              "FROM trail_segments WHERE geom && ST_Expand(ST_SetSRID(ST_MakePoint(%s, %s), 4326), 0.06) "
              "AND ST_DWithin(geom::geography, ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography, 5000)"
              + (" AND category = ANY(%s)" if cats else ""),
              (lon, lat, lon, lat, lon, lat) + ((list(cats),) if cats else ()))
    return round(rows[0][0], 1) if rows and rows[0][0] is not None else float("inf")


def endpoint_snap(lat: float, lon: float) -> float:
    """Allowance for where a route may start/end relative to a trailhead's coordinate: the engine's loops
    start on the nearest off-road trail, which can be farther than the nearest road (Bow: 16 m vs 78 m).
    Capped at 150 m (VIA_TOLERANCE_M)."""
    return min(150.0, max(snap_m(lat, lon), snap_m(lat, lon, OFF_ROAD)))


def _meta(tp: Dict[str, Any]) -> Dict[str, Any]:
    out = {k: tp[k] for k in ("osm_way_id", "name", "highway", "category", "dead_end") if k in tp}
    out["snap_m"] = snap_m(*tp["point"])
    return out


SCALES = (1.0, 0.8, 0.65, 0.5, 0.4, 0.3)


def plain_route(sc: Dict[str, Any]):
    """(miles, coordinates) of start -> midpoints -> end (the start again for a loop) routed with the
    engine's own GraphHopper profile and custom model, or None. This is the engine's plain 'Via Loop'."""
    import asyncio
    import httpx
    from app.routing import _query_gh, build_custom_model, decode_points, get_gh_profile
    from loam_eval.via_run import _request
    req = _request(sc)
    end = tuple(sc["end"]) if sc.get("end") else tuple(sc["start"])
    pts = [tuple(sc["start"])] + [tuple(w) for w in sc["waypoints"]] + [end]

    async def go():
        async with httpx.AsyncClient(timeout=20.0) as c:
            return await _query_gh(c, pts, get_gh_profile(req.profile), build_custom_model(req))
    r = asyncio.run(go())
    try:
        if r is None or r.status_code != 200:
            return None
        path = r.json()["paths"][0]
        return round(path["distance"] / 1609.344, 2), decode_points(path.get("points", {}))
    except Exception:
        return None


ROAD_CAP = 15.0   # the engine's road cap (percent), what C7 checks


def _road_pct(coords, miles: float) -> float:
    from loam_eval.real import evaluate_option
    r = evaluate_option([list(c) for c in coords], miles).get("road_pct")
    return 100.0 if r is None else r


def profile_snaps(sc: Dict[str, Any], coords) -> List[float]:
    """How close the plain route passes each midpoint: the snap distance on the network the profile can
    actually ride (a trail the profile refuses is not reachable, whatever the OSM table says)."""
    from app.route_builder import haversine_m
    return [round(min(haversine_m(c, [lon, lat]) for c in coords), 1) for lat, lon in sc["waypoints"]]


def build() -> Dict[str, Any]:
    ths = {t["parking_osm"]: t for t in json.load(open(TRAILHEADS))["trailheads"]}
    key = {"bear_brook": "way/414782002", "bow": "way/1412556913", "knox": "way/856160607",
           "oak_hill": "way/848156793", "white_park": "way/856490731", "franklin": "way/1126358623",
           "stratham": "way/320044045"}
    scs: List[Dict[str, Any]] = []

    def base(sid: str, kind: str, th: str, mode: str, miles: float, vias: List[Dict[str, Any]], *,
             expect: Dict[str, Any], end: Optional[str] = None) -> None:
        t = ths[key[th]]
        sc: Dict[str, Any] = {
            "id": sid, "kind": kind, "start": [t["lat"], t["lon"]], "start_osm": t["parking_osm"], "name": t["name"],
            "profile": PROFILE, "mode": mode, "miles": miles, "waypoints": [v["point"] for v in vias],
            "start_snap_m": endpoint_snap(t["lat"], t["lon"]),
            "via_meta": [_meta(v) for v in vias], "expect": expect}
        if end:
            e = ths[key[end]]
            sc["end"] = [e["lat"], e["lon"]]
            sc["end_osm"] = e["parking_osm"]
            sc["end_snap_m"] = endpoint_snap(e["lat"], e["lon"])
        res = plain_route(sc) if vias else None
        if res:  # snap on the network the profile can ride, not the OSM table's
            for m, d in zip(sc["via_meta"], profile_snaps(sc, res[1])):
                m["db_snap_m"], m["snap_m"] = m.get("snap_m"), d
        scs.append(sc)

    def feasible(th: str, miles: float, make) -> Optional[Tuple[List[Dict[str, Any]], float, float]]:
        """Largest scale at which make(scale) midpoints give a plain loop of 0.6-1.1x the target, within the
        road cap, passing every midpoint on the network the profile can ride: a scenario the engine can satisfy by construction. (vias, scale, plain loop miles)."""
        t = ths[key[th]]
        for sc_ in SCALES:
            vs = make(sc_)
            if not vs or not all(vs):
                continue
            probe = {"start": [t["lat"], t["lon"]], "name": t["name"], "profile": PROFILE, "mode": "loop", "miles": miles,
                     "waypoints": [v["point"] for v in vs]}
            res = plain_route(probe)
            if res is None:
                continue
            L, coords = res
            if 0.6 * miles <= L <= 1.1 * miles and max(profile_snaps(probe, coords)) <= 150.0 \
                    and _road_pct(coords, miles) <= ROAD_CAP:
                return vs, sc_, L
        return None

    def pick(th: str, bearing: float, dist_m: float, **kw) -> Optional[Dict[str, Any]]:
        t = ths[key[th]]
        la, lo = destination(t["lat"], t["lon"], bearing, dist_m)
        return trail_point(la, lo, **kw)

    ok = {"outcome": "ok"}
    # 1 midpoint at about 1/4 of the target (straight line from the trailhead), 4 bearings
    for th, targets in (("bear_brook", (5, 10, 15)), ("bow", (10,)), ("knox", (10,)), ("oak_hill", (10,)),
                        ("white_park", (10,))):
        for miles in targets:
            for b in (45, 135, 225, 315):
                f = feasible(th, float(miles), lambda k, b=b: [pick(th, b, miles * 1609.344 / 4 * k)])
                if f:
                    base(f"v1_{th}_{miles}mi_b{b}", "one_via", th, "loop", float(miles), f[0],
                         expect={**ok, "via_scale": f[1], "plain_via_miles": f[2]})
    # 2 midpoints ~120 degrees apart, and the same two reversed
    for th in ("bear_brook", "bow", "knox", "oak_hill"):
        for b in (30, 150):
            r = 10 * 1609.344 / 4.5
            f = feasible(th, 10.0, lambda k, b=b: [pick(th, b, r * k), pick(th, b + 120, r * k)])
            if f and f[0][0]["point"] != f[0][1]["point"]:
                v1, v2 = f[0]
                e = {**ok, "via_scale": f[1], "plain_via_miles": f[2]}
                base(f"v2_{th}_10mi_b{b}", "two_vias", th, "loop", 10.0, [v1, v2], expect=e)
                base(f"v2r_{th}_10mi_b{b}", "two_vias_reversed", th, "loop", 10.0, [v2, v1], expect=e)
    # 3 midpoints (a triangle)
    for th in ("bear_brook", "bow", "knox"):
        r = 10 * 1609.344 / 5.5
        f = feasible(th, 10.0, lambda k: [pick(th, b, r * k) for b in (20, 140, 260)])
        if f:
            base(f"v3_{th}_10mi", "three_vias", th, "loop", 10.0, f[0], expect={**ok, "via_scale": f[1], "plain_via_miles": f[2]})

    # adversarial, each with its expected outcome
    bb = ths[key["bear_brook"]]
    de = dead_end_point(bb["lat"], bb["lon"], 90, 10 * 1609.344 / 4)
    if de:
        base("adv_dead_end_bear_brook", "adversarial", "bear_brook", "loop", 10.0, [de],
             expect={"outcome": "notice", "dead_end_vias": [0],
                     "note": "only way to the midpoint is a spur; the route may ride it twice but the notice must say so"})
    road = next((r for b in (200, 250, 300, 0, 60, 120, 160) if (r := pick("bear_brook", b, 10 * 1609.344 / 4, cats=("paved",)))), None)
    if road:
        base("adv_paved_via_bear_brook", "adversarial", "bear_brook", "loop", 10.0, [road],
             expect={"outcome": "ok_or_notice", "note": "a midpoint on a road: route passes it, within the road cap, or says why not"})
    far = pick("bear_brook", 300, 5 * 1609.344 * 0.8)
    if far:
        base("adv_far_via_bear_brook", "adversarial", "bear_brook", "loop", 5.0, [far],
             expect={"outcome": "notice_or_error",
                     "note": "midpoint ~4 mi straight-line from the start with a 5 mi target: a round trip cannot fit. "
                             "Decision: return the route with a notice that the distance is longer than the target, "
                             "or a clear error; never a route that skips the midpoint"})
    lake = off_network_point(ths[key["franklin"]]["lat"], ths[key["franklin"]]["lon"])
    if lake:
        scs_before = len(scs)
        base("adv_off_network_franklin", "adversarial", "franklin", "loop", 5.0,
             [{"point": lake["point"], "dead_end": False}],
             expect={"outcome": "error", "note": "no routable way within 500 m: a clear error, no fabricated line"})
        scs[scs_before]["via_meta"] = [{"snap_m": snap_m(*lake["point"]), "off_network": True}]
    for b in (90, 45, 135, 180, 270, 315, 0, 225):
        v = pick("bow", b, 10 * 1609.344 / 4)
        if v and _q("SELECT length_m >= 150 FROM trail_segments WHERE segment_id = %s", (v["segment_id"],))[0][0]:
            break
    else:
        v = None
    if v:
        # the second midpoint 50 m further along the same segment (needs a segment of 150 m or more)
        rows = _q("""SELECT ST_Y(ST_LineInterpolatePoint(geom, 0.5 + 50.0 / length_m)),
                            ST_X(ST_LineInterpolatePoint(geom, 0.5 + 50.0 / length_m))
                     FROM trail_segments WHERE segment_id = %s AND length_m >= 150""", (v["segment_id"],))
        if rows:
            v2 = {"point": [round(rows[0][0], 6), round(rows[0][1], 6)]}
            base("adv_two_vias_50m_bow", "adversarial", "bow", "loop", 10.0, [v, v2],
                 expect={"outcome": "ok", "note": "two midpoints ~50 m apart: both visited in order"})
    base("adv_via_at_start_bow", "adversarial", "bow", "loop", 10.0,
         [{"point": [ths[key["bow"]]["lat"], ths[key["bow"]]["lon"]]}],
         expect={"outcome": "ok_or_error", "note": "a midpoint at the start itself: a normal loop, or a clear message"})

    # point to point with 1-2 midpoints between two trailheads (regression)
    for a, z in (("bow", "knox"), ("knox", "white_park")):
        ta, tz = ths[key[a]], ths[key[z]]
        brg = math.degrees(math.atan2((tz["lon"] - ta["lon"]) * math.cos(math.radians(ta["lat"])), tz["lat"] - ta["lat"]))
        d = math.hypot((tz["lat"] - ta["lat"]) * 111320, (tz["lon"] - ta["lon"]) * 111320 * math.cos(math.radians(ta["lat"])))
        mids = [trail_point(*destination(ta["lat"], ta["lon"], brg, d * f)) for f in (0.5,)]
        if all(mids):
            base(f"p2p1_{a}_{z}", "p2p_one_via", a, "point_to_point", round(d / 1609.344 * 1.4, 1), mids, expect=ok, end=z)
        mids2 = [trail_point(*destination(ta["lat"], ta["lon"], brg, d * f)) for f in (0.33, 0.66)]
        if all(mids2):
            base(f"p2p2_{a}_{z}", "p2p_two_vias", a, "point_to_point", round(d / 1609.344 * 1.4, 1), mids2, expect=ok, end=z)

    # plain loops with no midpoints (regression: these must not change)
    for th in ("bear_brook", "bow", "knox", "oak_hill", "white_park"):
        base(f"plain_{th}_10mi", "plain_loop", th, "loop", 10.0, [], expect=ok)
    base("plain_bear_brook_5mi", "plain_loop", "bear_brook", "loop", 5.0, [], expect=ok)
    base("plain_bear_brook_15mi", "plain_loop", "bear_brook", "loop", 15.0, [], expect=ok)
    return {"source": "public OSM trailheads (frontend/src/data/trailheads.json) and trail_segments; "
                      "generated by loam_eval/via_scenarios.py", "scenarios": scs}


def write(path: str = OUT) -> int:
    doc = build()
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=1)
        fh.write("\n")
    by_kind: Dict[str, int] = {}
    for s in doc["scenarios"]:
        by_kind[s["kind"]] = by_kind.get(s["kind"], 0) + 1
    print(f"{len(doc['scenarios'])} via scenarios -> {path}  {by_kind}")
    return 0
