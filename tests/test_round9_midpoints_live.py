"""GH-41 phase 3: loops through midpoints on the real local stack (GraphHopper, PostGIS, 3DEP).

Every returned option, not just the top one, goes through loam_eval.via_check. The scenarios are in
benchmark/via_scenarios.json (public trailheads, midpoints picked from trail_segments). Skipped with a
reason when the stack is missing. C1-C5 and C8 are asserted for every option. C6 (distance): an option the
checker finds out of tolerance must also fail the engine's own distance gate (the engine never believes it
is on target). C7 (road share) is measured against OSM and differs from the engine's own road count, so it
is reported by the benchmark (benchmark/reports/via-after.md), not asserted here.
"""
import asyncio
import json
import pathlib

import pytest

from app.engine_config import get_config
from app.routing import DEAD_END_NOTICE, MidpointError, effective_road_cap, passes_hard_gates, plan_route_options
from loam_eval.via_check import check_via_route
from loam_eval.via_run import _request
from tests.test_round7_routing import _stack_ready

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCENARIOS = {s["id"]: s for s in json.loads((ROOT / "benchmark/via_scenarios.json").read_text())["scenarios"]}
live = pytest.mark.skipif(_stack_ready() is not None, reason=str(_stack_ready()))
STRICT = ("C1", "C2", "C3", "C4", "C5", "C8")


def _run(sid):
    sc = SCENARIOS[sid]
    req = _request(sc)
    res = asyncio.run(plan_route_options(req, count=10))
    snaps = [m.get("snap_m", 0.0) for m in sc.get("via_meta", [])] or None
    out = []
    for o in res.options:
        chk = check_via_route(
            [list(c) for c in o.coordinates], tuple(sc["start"]), [tuple(w) for w in sc["waypoints"]],
            end=tuple(sc["end"]) if sc.get("end") else None, target_miles=sc["miles"], snap_m=snaps,
            start_snap_m=sc.get("start_snap_m", 0.0), end_snap_m=sc.get("end_snap_m", 0.0),
            dead_end_vias=(sc.get("expect") or {}).get("dead_end_vias", []), notice=res.notice,
            reported_miles=o.distance_miles, road_cap_pct=effective_road_cap(req, get_config()))
        out.append((o, chk))
    return res, out


def _assert_correct(sid, *, need_ok=True):
    res, checked = _run(sid)
    assert checked, f"{sid}: no options ({res.notice})"
    for o, chk in checked:
        bad = [r for r in STRICT if not chk[r]["ok"]]
        assert not bad, f"{sid} / {o.name}: {bad} {json.dumps({r: chk[r] for r in bad}, default=str)}"
        if not chk["C6"]["ok"]:
            assert "distance" in passes_hard_gates(o, _request(SCENARIOS[sid])), f"{sid} / {o.name}: engine thinks it is on target"
    if need_ok:
        assert any(chk["ok"] for _, chk in checked), f"{sid}: no option passes every rule"
    return res, checked


@live
@pytest.mark.parametrize("sid, need_ok", [("v1_bear_brook_10mi_b135", True), ("v1_bear_brook_10mi_b315", False)])
def test_bear_brook_one_midpoint_10mi(sid, need_ok):
    # b315 only has an 8.2 mi loop on this network (target 10): the strict rules hold, no option hits the distance
    _assert_correct(sid, need_ok=need_ok)


@live
def test_bear_brook_two_midpoints_and_the_same_two_reversed():
    _assert_correct("v2_bear_brook_10mi_b30", need_ok=False)
    _, rev = _assert_correct("v2r_bear_brook_10mi_b30", need_ok=False)
    for _, chk in rev:   # reversed order is honoured: C3 holds against the reversed list
        assert chk["C3"]["ok"]


@live
def test_three_midpoints():
    _assert_correct("v3_knox_10mi", need_ok=False)


@live
def test_dead_end_midpoint_is_honest():
    res, checked = _run("adv_dead_end_bear_brook")
    assert checked
    for _, chk in checked:
        assert chk["C8"]["ok"]
        if chk["C5"]["waived"]:
            assert DEAD_END_NOTICE in (res.notice or "")


@live
def test_off_network_midpoint_is_a_clear_error_not_a_line():
    with pytest.raises(MidpointError, match="nearest way"):
        _run("adv_off_network_franklin")


@live
def test_point_to_point_with_a_midpoint():
    _assert_correct("p2p1_bow_knox", need_ok=False)


@live
def test_plain_loop_is_unchanged():
    res, checked = _run("plain_bear_brook_10mi")
    assert len(checked) >= 5
    for _, chk in checked:
        assert chk["C4"]["ok"] and chk["C5"]["ok"] and chk["C1"]["ok"]
