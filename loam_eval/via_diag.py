"""Stage-by-stage view of one via scenario: what GraphHopper returns for each candidate spec and why the
engine would keep or drop it (GH-41). Not a benchmark; a debugging aid.

    python -m loam_eval via-diag <scenario id>
"""
from __future__ import annotations

import asyncio
import json

import httpx

from loam_eval.via_check import check_via_route
from loam_eval.via_run import _request
from loam_eval.via_scenarios import OUT as SCENARIOS


def main(sid: str) -> int:
    from app.routing import (via_candidate_specs, _query_gh, build_custom_model, get_gh_profile, graphhopper_candidate,
                             passes_vias, repetition)
    sc = next(s for s in json.load(open(SCENARIOS))["scenarios"] if s["id"] == sid)
    start, vias = tuple(sc["start"]), [tuple(v) for v in sc["waypoints"]]
    req = _request(sc)
    cm, prof = build_custom_model(req), get_gh_profile(req.profile)
    print(f"{sid}: target {sc['miles']} mi")
    try:
        specs, _tols = asyncio.run(via_candidate_specs(vias, start, sc["miles"] * 1609.344, prof, cm))
    except Exception as e:
        print(f"  {type(e).__name__}: {e}")
        return 0

    async def go():
        async with httpx.AsyncClient(timeout=20) as c:
            return await asyncio.gather(*[_query_gh(c, p, prof, cm) for _, p, _ in specs])
    for (_, pts, label), r in zip(specs, asyncio.run(go())):
        if r is None or r.status_code != 200:
            print(f"  {label:26s} GraphHopper {getattr(r, 'status_code', None)}")
            continue
        coords, _ = graphhopper_candidate(r.json()["paths"][0])
        chk = check_via_route(coords, start, vias, target_miles=sc["miles"], start_snap_m=sc.get("start_snap_m", 0.0))
        print(f"  {label:26s} {chk['C6']['geometry_miles']:5.1f} mi  vias={passes_vias(coords, vias)}  "
              f"rep={repetition(coords):.2f}  road={chk['C7']['road_pct']}  failed={chk['failed']}")
    return 0
