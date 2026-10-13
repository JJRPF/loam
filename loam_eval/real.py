"""Real-world benchmark (docs/round7-plan.md 6.6): public OSM trailheads, the live local engine.

Unlike the synthetic archetypes in synth.py, these scenarios start at real public trailheads
(OSM `highway=trailhead` nodes and the OSM-derived parking in frontend/src/data/trailheads.json)
and run the engine against the local GraphHopper + PostGIS (+ 3DEP) stack. Every engine's routes
are scored by the same evaluator, which measures them against OSM, not against the engine's own
labels: geometry offset to the OSM network, road share from the OSM category under each point,
retrace from repeated steps, distance error and latency.

    python -m loam_eval real-scenarios --pbf $DATA_DIR/osm/new-hampshire-latest.osm.pbf
    python -m loam_eval real --engines round7[,round6=<path to a Round 6 tree>] --out benchmark/reports/round7.md
"""
from __future__ import annotations

import asyncio
import json
import math
import os
import statistics
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
REAL_SCENARIOS = os.path.join(ROOT, "benchmark", "real_scenarios.json")
TRAILHEADS = os.path.join(ROOT, "frontend", "src", "data", "trailheads.json")
EARTH_R = 6371008.8


def _hav(a, b) -> float:
    p1, p2 = math.radians(a[1]), math.radians(b[1])
    dp, dl = p2 - p1, math.radians(b[0] - a[0])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_R * math.asin(math.sqrt(min(1.0, h)))


# ------------------------------------------------------------------------------------------
# Scenarios
# ------------------------------------------------------------------------------------------

def build_scenarios(pbf: str, n_trailheads: int = 20) -> List[Dict[str, Any]]:
    import osmium

    th = {t["parking_osm"]: t for t in json.load(open(TRAILHEADS))["trailheads"]}
    bow, bb, oak = th["way/1412556913"], th["way/414782002"], th["way/848156793"]
    mid = None
    heads = []
    for o in osmium.FileProcessor(pbf, osmium.osm.NODE | osmium.osm.WAY).with_locations():
        if isinstance(o, osmium.osm.Way):
            if o.id == 220551352 and mid is None:
                n0 = o.nodes[len(o.nodes) // 2]
                mid = (round(n0.lat, 6), round(n0.lon, 6), f"node/{n0.ref}")
            continue
        t = o.tags
        if t.get("highway") == "trailhead" and t.get("name") and t.get("access") not in ("private", "no"):
            heads.append((o.location.lat, o.location.lon, t.get("name"), o.id))

    scenarios = [
        {"id": "bow_10_mtb", "kind": "plan_6.5", "start": [bow["lat"], bow["lon"]], "start_osm": bow["parking_osm"],
         "name": "Bow Town Forest parking", "profile": "mtb_hardtail", "mode": "loop", "miles": 10.0},
        {"id": "bear_brook_10_mtb", "kind": "plan_6.5", "start": [bb["lat"], bb["lon"]], "start_osm": bb["parking_osm"],
         "name": "Bear Brook State Park parking", "profile": "mtb_hardtail", "mode": "loop", "miles": 10.0},
        {"id": "bear_brook_14_mtb", "kind": "plan_6.5", "start": [bb["lat"], bb["lon"]], "start_osm": bb["parking_osm"],
         "name": "Bear Brook State Park parking", "profile": "mtb_hardtail", "mode": "loop", "miles": 14.0},
        {"id": "bow_5_run", "kind": "plan_6.5", "start": [bow["lat"], bow["lon"]], "start_osm": bow["parking_osm"],
         "name": "Bow Town Forest parking", "profile": "trail_run", "mode": "loop", "miles": 5.0},
        {"id": "p2p_midpoint", "kind": "plan_6.5", "start": [bb["lat"], bb["lon"]], "start_osm": bb["parking_osm"],
         "end": [oak["lat"], oak["lon"]], "end_osm": oak["parking_osm"], "waypoints": [[mid[0], mid[1]]],
         "waypoint_osm": [mid[2]], "name": "Bear Brook State Park parking", "profile": "mtb_hardtail",
         "mode": "point_to_point", "miles": None},
    ]
    # ~20 named trailheads spread across the state: one per 0.25-degree cell, north to south.
    heads.sort(key=lambda h: (-h[0], h[1]))
    cells, picked = set(), []
    for lat, lon, name, nid in heads:
        cell = (round(lat / 0.25), round(lon / 0.25))
        if cell in cells:
            continue
        cells.add(cell)
        picked.append((lat, lon, name, nid))
        if len(picked) >= n_trailheads:
            break
    for i, (lat, lon, name, nid) in enumerate(picked):
        run = i % 4 == 3
        scenarios.append({
            "id": f"th_{nid}", "kind": "osm_trailhead", "start": [round(lat, 6), round(lon, 6)],
            "start_osm": f"node/{nid}", "name": name, "profile": "trail_run" if run else "mtb_hardtail",
            "mode": "loop", "miles": 6.0 if run else 10.0,
        })
    return scenarios


def write_scenarios(pbf: str) -> List[Dict[str, Any]]:
    scenarios = build_scenarios(pbf)
    with open(REAL_SCENARIOS, "w") as f:
        json.dump({"source": "OpenStreetMap contributors (ODbL); built by loam_eval.real.build_scenarios",
                   "scenarios": scenarios}, f, indent=1)
        f.write("\n")
    return scenarios


# ------------------------------------------------------------------------------------------
# Engines: each returns, per scenario, the options' coordinates and the wall-clock latency
# ------------------------------------------------------------------------------------------

RUNNER = r'''
import asyncio, json, sys, time, inspect
from app.models import RouteOptionsRequest, LatLon
import app.routing as routing
scs = json.load(open(sys.argv[1]))["scenarios"]
out = []
for sc in scs:
    kw = dict(start=LatLon(lat=sc["start"][0], lon=sc["start"][1], name=sc["name"]), profile=sc["profile"],
              route_mode=sc["mode"], target_distance_miles=sc["miles"], candidate_count=10)
    if sc.get("end"):
        kw["end"] = LatLon(lat=sc["end"][0], lon=sc["end"][1])
    if sc.get("waypoints"):
        kw["waypoints"] = [LatLon(lat=a, lon=b) for a, b in sc["waypoints"]]
    req = RouteOptionsRequest(**kw)
    t0 = time.time()
    try:
        opts = asyncio.run(routing.generate_route_options(req, count=10))
        err = None
    except Exception as e:
        opts, err = [], str(e)
    dt = time.time() - t0
    out.append({"id": sc["id"], "latency_s": round(dt, 2), "error": err,
                "options": [{"coordinates": [c[:2] for c in o.coordinates], "label": o.route_type,
                             "distance_miles": o.distance_miles, "name": o.name} for o in opts]})
    print(sc["id"], len(opts), round(dt, 1), file=sys.stderr, flush=True)
json.dump(out, open(sys.argv[2], "w"))
'''


def run_engine(tree: str, scenarios_path: str, out_path: str, env: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
    """Runs one engine (a source tree with an `app` package) over the scenarios in a subprocess."""
    e = dict(os.environ)
    e.update(env or {})
    e["PYTHONPATH"] = tree
    subprocess.run([sys.executable, "-c", RUNNER, scenarios_path, out_path], cwd=tree, env=e, check=True)
    return json.load(open(out_path))


# ------------------------------------------------------------------------------------------
# Evaluation against OSM
# ------------------------------------------------------------------------------------------

def _network(bbox):
    """OSM segments (trail_segments) in a bbox: shapely lines in local meters + categories."""
    import numpy as np
    import shapely
    from app.db import get_connection

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT ST_AsGeoJSON(geom), category FROM trail_segments "
                    "WHERE geom && ST_MakeEnvelope(%s, %s, %s, %s, 4326)", bbox)
        rows = cur.fetchall()
    lat0 = math.radians((bbox[1] + bbox[3]) / 2)
    scale = np.array([EARTH_R * math.cos(lat0) * math.pi / 180.0, EARTH_R * math.pi / 180.0])
    lines = [shapely.linestrings(np.asarray(json.loads(g)["coordinates"]) * scale) for g, _ in rows]
    return lines, [c for _, c in rows], scale


def evaluate_option(coords: List[List[float]], target_miles: Optional[float]) -> Dict[str, Any]:
    import numpy as np
    import shapely
    from shapely.strtree import STRtree
    from app.elevation import densify
    from app.route_builder import _shape, _step_key

    lons, lats = [c[0] for c in coords], [c[1] for c in coords]
    pad = 0.003
    lines, cats, scale = _network((min(lons) - pad, min(lats) - pad, max(lons) + pad, max(lats) + pad))
    dense, _ = densify(coords)
    total = sum(_hav(coords[i], coords[i + 1]) for i in range(len(coords) - 1))
    res: Dict[str, Any] = {"miles": round(total / 1609.344, 2)}
    if not lines:
        res.update(offset_m=None, road_pct=None, retrace=None, shape=None)
        return res
    tree = STRtree(lines)
    pts = shapely.points(np.asarray(dense) * scale)
    idx, dist = tree.query_nearest(pts, return_distance=True, all_matches=False)
    nearest = np.full(len(dense), -1)
    d = np.full(len(dense), np.inf)
    nearest[idx[0]] = idx[1]
    d[idx[0]] = dist
    res["offset_m"] = round(float(d.max()), 1)
    # road share from the OSM category under each densified point, excluding the leading and
    # trailing road run (access to the trail), as the engine reports it
    cat = ["paved" if (n < 0 or d[i] > 20 or cats[n] == "paved") else cats[n] for i, n in enumerate(nearest)]
    lead = next((i for i, c in enumerate(cat) if c != "paved"), len(cat))
    tail = next((i for i, c in enumerate(reversed(cat)) if c != "paved"), len(cat))
    body = cat[lead:len(cat) - tail] if lead < len(cat) else []
    res["road_pct"] = round(100.0 * sum(c == "paved" for c in body) / max(len(body), 1), 1) if body else 100.0
    seen, retraced = set(), 0.0
    for i in range(len(coords) - 1):
        k = _step_key(coords[i], coords[i + 1])
        if k in seen:
            retraced += _hav(coords[i], coords[i + 1])
        seen.add(k)
    res["retrace"] = round(retraced / total, 3) if total else 0.0
    res["shape"] = _shape(total, retraced, _hav(coords[0], coords[-1]))
    res["dist_err"] = round(abs(res["miles"] - target_miles) / target_miles, 3) if target_miles else None
    res["passes"] = (res["offset_m"] <= 15.0 and res["road_pct"] <= 15.0
                     and (res["dist_err"] is None or res["dist_err"] <= 0.5))
    return res


def evaluate(runs: Dict[str, List[Dict[str, Any]]], scenarios: List[Dict[str, Any]]) -> Dict[str, Any]:
    by_id = {s["id"]: s for s in scenarios}
    per: Dict[str, Dict[str, Any]] = {}
    for engine, results in runs.items():
        for r in results:
            sc = by_id[r["id"]]
            evals = [evaluate_option(o["coordinates"], sc.get("miles")) for o in r["options"]]
            per.setdefault(r["id"], {})[engine] = {"latency_s": r["latency_s"], "error": r["error"], "options": evals}
    # loops exist where any engine produced an OSM-verified loop that passes the gates
    loops_exist = {sid: any(o.get("passes") and o.get("shape") in ("loop", "lollipop")
                            for e in v.values() for o in e["options"]) for sid, v in per.items()}
    summary: Dict[str, Dict[str, Any]] = {}
    for engine in runs:
        rows = [per[sid][engine] for sid in per if engine in per[sid]]
        opts = [o for r in rows for o in r["options"]]
        lat = sorted(r["latency_s"] for r in rows)
        loop_rows = [per[sid][engine] for sid in per if engine in per[sid] and loops_exist[sid]
                     and by_id[sid]["mode"] == "loop"]
        loop_shares = [sum(o.get("shape") in ("loop", "lollipop") and o.get("passes") for o in r["options"])
                       / max(len(r["options"]), 1) for r in loop_rows]
        summary[engine] = {
            "scenarios": len(rows),
            "options_mean": round(statistics.mean(len(r["options"]) for r in rows), 1) if rows else 0,
            "pass_gates_pct": round(100.0 * sum(bool(o.get("passes")) for o in opts) / max(len(opts), 1), 1),
            "geometry_fail_pct": round(100.0 * sum((o.get("offset_m") is None or o["offset_m"] > 15.0) for o in opts)
                                       / max(len(opts), 1), 1),
            "true_loop_pct_when_loops_exist": round(100.0 * statistics.mean(loop_shares), 1) if loop_shares else None,
            "road_pct_mean": round(statistics.mean(o["road_pct"] for o in opts if o.get("road_pct") is not None), 1) if opts else None,
            "retrace_pct_mean": round(100.0 * statistics.mean(o["retrace"] for o in opts if o.get("retrace") is not None), 1) if opts else None,
            "latency_p50_s": round(statistics.median(lat), 1) if lat else None,
            "latency_p95_s": round(lat[min(len(lat) - 1, math.ceil(0.95 * len(lat)) - 1)], 1) if lat else None,
            "errors": sum(1 for r in rows if r["error"]),
        }
    return {"summary": summary, "per_scenario": per, "loops_exist": loops_exist}


def write_report(path: str, result: Dict[str, Any], scenarios: List[Dict[str, Any]], notes: List[str]) -> None:
    engines = list(result["summary"])
    keys = [("options_mean", "options returned (mean of 10 asked)"), ("pass_gates_pct", "% options passing gates"),
            ("geometry_fail_pct", "% options off the OSM network (> 15 m)"),
            ("true_loop_pct_when_loops_exist", "% loop/lollipop options where loops exist"),
            ("road_pct_mean", "road % (mean, excl. access)"), ("retrace_pct_mean", "retrace % (mean)"),
            ("latency_p50_s", "latency p50 (s)"), ("latency_p95_s", "latency p95 (s)"), ("errors", "errors")]
    lines = ["# Round 7 benchmark: real scenarios (GH-34)", "",
             "Real set: the plan 6.5 scenarios plus named OSM `highway=trailhead` nodes across NH "
             "(`benchmark/real_scenarios.json`), run against the live local engine (GraphHopper + PostGIS "
             "with the OSM import + 3DEP). Every engine's routes are scored by the same OSM-based evaluator "
             "(`loam_eval/real.py`), not by the engine's own labels. The Round 5 set (`benchmark/scenarios.json`, "
             "`loam_eval/synth.py`) is **synthetic** and is not used here.", "",
             "Gates: every point within 15 m of an OSM segment; road ≤ 15% excluding the access stretch; "
             "distance within 50% of the target.", ""]
    lines += ["| metric | " + " | ".join(engines) + " |", "|---|" + "---|" * len(engines)]
    for k, label in keys:
        lines.append(f"| {label} | " + " | ".join(str(result["summary"][e].get(k)) for e in engines) + " |")
    lines += ["", "## Per scenario", "", "| scenario | " + " | ".join(f"{e}: options / passing / loops / p50 s" for e in engines) + " |",
              "|---|" + "---|" * len(engines)]
    for sc in scenarios:
        row = [f"`{sc['id']}` {sc['name']} ({sc['profile']}, {sc['miles'] or 'p2p'} mi)"]
        for e in engines:
            r = result["per_scenario"].get(sc["id"], {}).get(e)
            if not r:
                row.append("-")
                continue
            o = r["options"]
            row.append(f"{len(o)} / {sum(bool(x.get('passes')) for x in o)} / "
                       f"{sum(x.get('shape') in ('loop', 'lollipop') for x in o)} / {r['latency_s']}")
        lines.append("| " + " | ".join(row) + " |")
    if notes:
        lines += ["", "## Notes", ""] + [f"- {n}" for n in notes]
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
