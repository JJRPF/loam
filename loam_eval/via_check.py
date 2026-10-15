"""Executable definition of a *correct* loop through midpoints (GH-41, docs/round9-midpoints-worklog.md).

    check_via_route(coords, start, vias, end=None, target_miles=None, way_ids=None) -> dict

Checks (all must hold for `ok`; a failed rule never hides the others):

  C1 closes at the start (loop) / ends at `end`            first/last point <= 60 m
  C2 passes every midpoint                                  closest approach <= snap distance + 25 m
                                                            (and never beyond VIA_TOLERANCE_M)
  C3 passes midpoints in the requested order                indices of closest approach increase
  C4 real ways only                                         offset to the OSM network <= 15 m
  C5 not an out-and-back                                    retrace and repetition ratio <= 0.28
                                                            (waived for a dead-end midpoint, C8)
  C6 distance                                               reported miles == geometry length (1%);
                                                            with a target, dist_err <= 0.15 (the
                                                            engine's distance_tolerance)
  C7 surface / road share                                   road_pct <= the profile cap
  C8 honest output                                          a waived C5 needs the response notice

`vias` are (lat, lon) as in app.routing.passes_vias; coordinates are [lon, lat(, ele)].
The network lookups (`evaluate`, `offset`) are injectable so the checker's own unit tests run
without PostGIS; by default they are loam_eval.real.evaluate_option and
app.route_builder.geometry_offset_m.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from loam_eval.real import _hav, evaluate_option

CLOSE_M = 60.0
VIA_SLACK_M = 25.0
VIA_TOLERANCE_M = 150.0
OFFSET_MAX_M = 15.0
RETRACE_MAX = 0.28
MILES_REL_TOL = 0.01
DIST_ERR_MAX = 0.15
ROAD_CAP_PCT = 15.0
M_PER_MILE = 1609.344


def _closest(coords: Sequence[Sequence[float]], lat: float, lon: float) -> Tuple[float, int]:
    """(distance m, index) of the route vertex nearest the point. Routes are densely noded."""
    best, bi = float("inf"), -1
    for i, c in enumerate(coords):
        d = _hav(c, (lon, lat))
        if d < best:
            best, bi = d, i
    return best, bi


def _geometry_miles(coords: Sequence[Sequence[float]]) -> float:
    return sum(_hav(coords[i], coords[i + 1]) for i in range(len(coords) - 1)) / M_PER_MILE


def _local_retrace(coords: Sequence[Sequence[float]]) -> float:
    from app.route_builder import _step_key
    total = repeated = 0.0
    seen = set()
    for i in range(len(coords) - 1):
        d = _hav(coords[i], coords[i + 1])
        total += d
        k = _step_key(coords[i], coords[i + 1])
        if k in seen:
            repeated += d
        seen.add(k)
    return repeated / total if total else 0.0


def _rule(ok: bool, **detail: Any) -> Dict[str, Any]:
    return {"ok": bool(ok), **detail}


def check_via_route(
    coords: List[List[float]],
    start: Tuple[float, float],
    vias: Sequence[Tuple[float, float]],
    end: Optional[Tuple[float, float]] = None,
    target_miles: Optional[float] = None,
    way_ids: Optional[Sequence[int]] = None,
    *,
    snap_m: Optional[Sequence[float]] = None,
    dead_end_vias: Sequence[int] = (),
    notice: Optional[str] = None,
    reported_miles: Optional[float] = None,
    road_cap_pct: float = ROAD_CAP_PCT,
    evaluate: Callable[[List[List[float]], Optional[float]], Dict[str, Any]] = evaluate_option,
    offset: Optional[Callable[[Sequence[Sequence[float]], Sequence[int]], Optional[float]]] = None,
) -> Dict[str, Any]:
    """`start`/`end` are (lat, lon). `snap_m[i]` is midpoint i's distance to the routable network
    (reported separately; it widens C2 only). `dead_end_vias` are the midpoints whose only access
    is a dead-end spur; `notice` is the response notice; `reported_miles` the API's distance."""
    res: Dict[str, Any] = {}
    if len(coords) < 2:
        return {"ok": False, "error": "route has fewer than 2 points"}
    ev = evaluate(coords, target_miles)

    # C1
    goal = end if end is not None else start
    d_first = _hav(coords[0], (start[1], start[0]))
    d_last = _hav(coords[-1], (goal[1], goal[0]))
    res["C1"] = _rule(d_first <= CLOSE_M and d_last <= CLOSE_M,
                      start_m=round(d_first, 1), end_m=round(d_last, 1), limit_m=CLOSE_M)

    # C2 / C3
    snaps = list(snap_m) if snap_m is not None else [0.0] * len(vias)
    hits, approach, idxs = [], [], []
    for i, (lat, lon) in enumerate(vias):
        d, idx = _closest(coords, lat, lon)
        limit = min(snaps[i] + VIA_SLACK_M, VIA_TOLERANCE_M)
        hits.append(d <= limit)
        approach.append(round(d, 1))
        idxs.append(idx)
    res["C2"] = _rule(all(hits), approach_m=approach, snap_m=[round(s, 1) for s in snaps],
                      missed=[i for i, h in enumerate(hits) if not h])
    res["C3"] = _rule(all(a < b for a, b in zip(idxs, idxs[1:])), indices=idxs)

    # C4
    off = ev.get("offset_m")
    if way_ids:
        off = (offset or _default_offset)(coords, way_ids)
    res["C4"] = _rule(off is not None and off <= OFFSET_MAX_M, offset_m=off, limit_m=OFFSET_MAX_M)

    # C5 / C8
    from app.scoring import calculate_repetition_ratio
    retrace = ev.get("retrace")
    if retrace is None:
        retrace = round(_local_retrace(coords), 3)
    rep = round(calculate_repetition_ratio(coords), 3)
    over = retrace > RETRACE_MAX or rep > RETRACE_MAX
    waived = bool(dead_end_vias) and over
    res["C5"] = _rule(not over or waived, retrace=retrace, repetition=rep, limit=RETRACE_MAX, waived=waived)
    res["C8"] = _rule(not waived or bool(notice), waived=waived, notice=notice)

    # C6
    geo = round(_geometry_miles(coords), 3)
    rep_miles = reported_miles if reported_miles is not None else geo
    miles_ok = abs(rep_miles - geo) <= MILES_REL_TOL * max(geo, 1e-9)
    err = ev.get("dist_err")
    if target_miles and err is None:
        err = abs(geo - target_miles) / target_miles
    res["C6"] = _rule(miles_ok and (err is None or err <= DIST_ERR_MAX),
                      miles=rep_miles, geometry_miles=geo, dist_err=err, limit=DIST_ERR_MAX)

    # C7
    road = ev.get("road_pct")
    res["C7"] = _rule(road is not None and road <= road_cap_pct, road_pct=road, cap=road_cap_pct)

    res["ok"] = all(v["ok"] for k, v in res.items() if k.startswith("C"))
    res["failed"] = [k for k, v in res.items() if k.startswith("C") and not v["ok"]]
    return res


def _default_offset(coords, way_ids):
    from app.route_builder import geometry_offset_m
    return geometry_offset_m(coords, way_ids)
