"""GH-41 phase 2: loops through midpoints (app/routing.py). Pure/fake tests, no stack needed."""
import math

import httpx
import pytest

from app import routing
from app.routing import (DEAD_END_NOTICE, VIA_REPETITION_MAX, MidpointError, filter_via_repetition,
                         via_loop_specs)

START = (43.13, -71.50)
KX, KY = 111132.0 * math.cos(math.radians(START[0])), 111132.0


def xy(p):
    return ((p[1] - START[1]) * KX, (p[0] - START[0]) * KY)


def ll(x, y):
    return (START[0] + y / KY, START[1] + x / KX)


def side(a, b, p):
    """>0 when p is left of the directed line a->b."""
    return (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])


def test_one_via_detours_sit_on_opposite_sides():
    via = ll(0.0, 2000.0)   # due north
    specs = via_loop_specs(START, [via], 10 * 1609.344)
    assert specs[0][1] == "Via Loop" and specs[0][0] == [START, via, START]
    for pts, label in specs[1:]:
        vi = pts.index(via)
        out = [xy(p) for p in pts[1:vi]]
        back = [xy(p) for p in pts[vi + 1:-1]]
        assert out and back, label
        s, v = xy(START), xy(via)
        sides_out = {math.copysign(1, side(s, v, p)) for p in out}
        sides_back = {math.copysign(1, side(s, v, p)) for p in back}
        assert len(sides_out) == 1 and len(sides_back) == 1, label
        assert sides_out != sides_back, f"{label}: outbound and return detours are on the same side"


def test_one_via_has_a_mirrored_variant():
    via = ll(0.0, 2000.0)
    labels = [l for _, l in via_loop_specs(START, [via], 8 * 1609.344)]
    assert any("mirrored" in l for l in labels)
    first = next(p for p, l in via_loop_specs(START, [via], 8 * 1609.344)[1:] if "mirrored" not in l)
    mirrored = next(p for p, l in via_loop_specs(START, [via], 8 * 1609.344)[1:] if "mirrored" in l)
    assert side(xy(START), xy(via), xy(first[1])) * side(xy(START), xy(via), xy(mirrored[1])) < 0


def test_order_of_midpoints_is_preserved_in_every_spec():
    v = [ll(1500.0, 800.0), ll(-1200.0, 1500.0), ll(-1500.0, -600.0)]
    for pts, label in via_loop_specs(START, v, 12 * 1609.344):
        idx = [pts.index(p) for p in v]
        assert idx == sorted(idx), label
        assert pts[0] == START and pts[-1] == START


def test_several_vias_bulge_away_from_the_centroid():
    v = [ll(1500.0, 800.0), ll(-1200.0, 1500.0)]
    specs = via_loop_specs(START, v, 10 * 1609.344)
    pts = specs[1][0]
    cx = sum(xy(p)[0] for p in [START] + v) / 3
    cy = sum(xy(p)[1] for p in [START] + v) / 3
    stops = [START] + v + [START]
    idx = [pts.index(p) for p in stops[1:-1]]
    # every detour point is farther from the centroid than the midpoint of the chord it belongs to
    bounds = [0] + idx + [len(pts) - 1]
    for k in range(len(bounds) - 1):
        a_, b_ = xy(stops[k]), xy(stops[k + 1])
        mid = ((a_[0] + b_[0]) / 2, (a_[1] + b_[1]) / 2)
        for d in pts[bounds[k] + 1:bounds[k + 1]]:
            assert math.hypot(xy(d)[0] - cx, xy(d)[1] - cy) > math.hypot(mid[0] - cx, mid[1] - cy)


def test_detours_come_in_a_ladder_of_heights():
    via = ll(0.0, 2000.0)
    specs = via_loop_specs(START, [via])
    heights = sorted({round(abs(xy(p[1])[0]), -1) for p, l in specs[1:] if l.startswith("arc") and "mirrored" not in l})
    assert len(heights) == len(routing.VIA_ARC_HEIGHTS)
    assert heights[0] < heights[-1] and heights[-1] <= 0.4 * 2000.0 + 10


def test_via_at_the_start_does_not_blow_up():
    specs = via_loop_specs(START, [START], 10 * 1609.344)
    assert specs and specs[0][0] == [START, START, START]


def _cand(coords):
    return (coords, [], "x", "graphhopper")


def _line(a, b, n=40):
    return [[a[0] + (b[0] - a[0]) * i / n, a[1] + (b[1] - a[1]) * i / n] for i in range(n + 1)]


OUT = _line([-71.50, 43.13], [-71.49, 43.14])
BACK = OUT[::-1]
OUT_AND_BACK = OUT + BACK[1:]
LOOP = OUT + _line([-71.49, 43.14], [-71.50, 43.14])[1:] + _line([-71.50, 43.14], [-71.50, 43.13])[1:]


def test_repetition_filter_drops_out_and_back_when_a_loop_exists():
    kept, repeats = filter_via_repetition([_cand(OUT_AND_BACK), _cand(LOOP)])
    assert [k[0] for k in kept] == [LOOP] and repeats is False


def test_repetition_filter_keeps_best_and_flags_the_dead_end_case():
    kept, repeats = filter_via_repetition([_cand(OUT_AND_BACK)])
    assert len(kept) == 1 and repeats is True
    assert "same trail" in DEAD_END_NOTICE


def test_repetition_filter_limit_is_the_plain_loop_rule():
    assert VIA_REPETITION_MAX == 0.28


@pytest.mark.asyncio
async def test_off_network_midpoint_is_a_clear_error(monkeypatch):
    dists = iter([12.0, 652.3])

    class Resp:
        status_code = 200
        def json(self):
            return {"distance": next(dists)}

    async def fake_get(self, url, params=None):
        assert url.endswith("/nearest")
        return Resp()

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    with pytest.raises(MidpointError, match="Midpoint 2 is 652 m from the nearest way"):
        await routing._check_vias_on_network([START, (43.5, -71.7)])


def test_passes_vias_takes_a_tolerance_per_midpoint():
    route = _line([-71.50, 43.13], [-71.49, 43.13])
    near = (43.13 + 0.0004, -71.495)   # ~44 m off the route
    assert routing.passes_vias(route, [near])                    # default: the 150 m hard bound
    assert routing.passes_vias(route, [near], [60.0])
    assert not routing.passes_vias(route, [near], [30.0])        # snap + slack of a closer midpoint
    assert not routing.passes_vias(route, [near, near], [200.0, 30.0])
