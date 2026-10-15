"""Runs benchmark/via_scenarios.json through plan_route_options (ENABLE_MIDPOINTS=true) and checks
EVERY returned option with loam_eval.via_check (GH-41 phase 1/3).

    python -m loam_eval via --out benchmark/reports/via-baseline [--only SUBSTR] [--label "main's code"]

Writes <out>.json (per scenario and option: C1-C8, miles, retrace, road %, latency) and <out>.md.
Needs the local stack (GraphHopper, PostGIS, 3DEP tiles). Public trailheads only.
"""
from __future__ import annotations

import asyncio
import json
import os
import statistics
import time
from typing import Any, Dict, List, Optional

from loam_eval.via_check import check_via_route
from loam_eval.via_scenarios import OUT as SCENARIOS

RULES = ("C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8")


def _request(sc: Dict[str, Any]):
    from app.models import LatLon, RouteOptionsRequest
    kw: Dict[str, Any] = dict(start=LatLon(lat=sc["start"][0], lon=sc["start"][1], name=sc["name"]), profile=sc["profile"],
                              route_mode=sc["mode"], target_distance_miles=sc["miles"], candidate_count=10)
    if sc.get("end"):
        kw["end"] = LatLon(lat=sc["end"][0], lon=sc["end"][1])
    if sc.get("waypoints"):
        kw["waypoints"] = [LatLon(lat=a, lon=b) for a, b in sc["waypoints"]]
    return RouteOptionsRequest(**kw)


def run_scenario(sc: Dict[str, Any]) -> Dict[str, Any]:
    from app.routing import plan_route_options
    os.environ["ENABLE_MIDPOINTS"] = "true"
    out: Dict[str, Any] = {"id": sc["id"], "kind": sc["kind"], "expect": sc.get("expect"), "options": [],
                           "error": None, "notice": None}
    t0 = time.time()
    try:
        res = asyncio.run(plan_route_options(_request(sc), count=10))
    except Exception as e:  # a clear error is a legitimate outcome for some adversarial cases
        out["error"] = f"{type(e).__name__}: {e}"
        out["latency_s"] = round(time.time() - t0, 2)
        return out
    out["latency_s"] = round(time.time() - t0, 2)
    out["notice"] = res.notice
    vias = [tuple(w) for w in sc.get("waypoints", [])]
    snaps = [m.get("snap_m", 0.0) for m in sc.get("via_meta", [])] or None
    dead = (sc.get("expect") or {}).get("dead_end_vias", [])
    for o in res.options:
        coords = [list(c) for c in o.coordinates]
        chk = check_via_route(coords, tuple(sc["start"]), vias, end=tuple(sc["end"]) if sc.get("end") else None,
                              target_miles=sc["miles"], snap_m=snaps, dead_end_vias=dead, notice=res.notice,
                              start_snap_m=sc.get("start_snap_m", 0.0), end_snap_m=sc.get("end_snap_m", 0.0),
                              reported_miles=o.distance_miles,
                              road_cap_pct=15.0)
        out["options"].append({"name": o.name, "miles": o.distance_miles, "ok": chk["ok"], "failed": chk["failed"],
                               "retrace": chk["C5"]["retrace"], "road_pct": chk["C7"]["road_pct"],
                               "offset_m": chk["C4"]["offset_m"], "dist_err": chk["C6"]["dist_err"],
                               "approach_m": chk["C2"]["approach_m"], "checks": {r: chk[r]["ok"] for r in RULES}})
    return out


def summarize(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    def agg(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
        opts = [o for r in rows for o in r["options"]]
        lat = sorted(r["latency_s"] for r in rows)
        s: Dict[str, Any] = {"scenarios": len(rows), "options": len(opts), "no_options": sum(1 for r in rows if not r["options"]),
                             "errors": sum(1 for r in rows if r["error"]),
                             "options_ok": sum(o["ok"] for o in opts)}
        for rule in RULES:
            s[rule] = sum(o["checks"][rule] for o in opts)
        s["p50_s"] = round(statistics.median(lat), 1) if lat else None
        s["p95_s"] = round(lat[min(len(lat) - 1, int(0.95 * len(lat)))], 1) if lat else None
        return s
    kinds = sorted({r["kind"] for r in results})
    return {"all": agg(results), "by_kind": {k: agg([r for r in results if r["kind"] == k]) for k in kinds}}


def write_report(path_base: str, results: List[Dict[str, Any]], label: str) -> None:
    summ = summarize(results)
    with open(path_base + ".json", "w", encoding="utf-8") as fh:
        json.dump({"label": label, "summary": summ, "results": results}, fh, indent=1)
        fh.write("\n")
    L = [f"# Midpoint routing benchmark: {label}", "",
         "Every returned option is checked (C1 closes/ends, C2 passes every midpoint, C3 in order, C4 real ways, "
         "C5 not an out-and-back, C6 distance, C7 road share, C8 honest notice). Public trailheads only.", "",
         "| kind | scenarios | options | ok | " + " | ".join(RULES) + " | no options | errors | p50 s | p95 s |",
         "|---|---|---|---|" + "---|" * len(RULES) + "---|---|---|---|"]
    for k, s in list(summ["by_kind"].items()) + [("**all**", summ["all"])]:
        L.append(f"| {k} | {s['scenarios']} | {s['options']} | {s['options_ok']} | "
                 + " | ".join(str(s[r]) for r in RULES) + f" | {s['no_options']} | {s['errors']} | {s['p50_s']} | {s['p95_s']} |")
    L += ["", "## Per scenario", "", "| scenario | opts | ok | failing rules | worst retrace | miles | latency s | notice / error |",
          "|---|---|---|---|---|---|---|---|"]
    for r in results:
        opts = r["options"]
        fails: Dict[str, int] = {}
        for o in opts:
            for f in o["failed"]:
                fails[f] = fails.get(f, 0) + 1
        miles = f"{min(o['miles'] for o in opts):.1f}-{max(o['miles'] for o in opts):.1f}" if opts else "-"
        rt = max((o["retrace"] for o in opts), default=None)
        note = (r["error"] or r["notice"] or "").replace("|", "/")[:90]
        L.append(f"| {r['id']} | {len(opts)} | {sum(o['ok'] for o in opts)} | "
                 + (", ".join(f"{k}x{v}" for k, v in sorted(fails.items())) or "-")
                 + f" | {rt if rt is not None else '-'} | {miles} | {r['latency_s']} | {note} |")
    with open(path_base + ".md", "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")


def main(out: str, only: Optional[str] = None, label: str = "") -> int:
    scs = json.load(open(SCENARIOS))["scenarios"]
    if only:
        scs = [s for s in scs if only in s["id"]]
    results = []
    for sc in scs:
        r = run_scenario(sc)
        results.append(r)
        print(f"{sc['id']}: {len(r['options'])} opts, {sum(o['ok'] for o in r['options'])} ok, {r['latency_s']}s"
              + (f"  ERR {r['error'][:80]}" if r["error"] else ""), flush=True)
    write_report(out, results, label or "midpoint benchmark")
    print(f"wrote {out}.json/.md")
    return 0
