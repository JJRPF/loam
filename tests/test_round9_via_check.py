"""GH-41 phase 0: unit tests of the midpoint-loop checker (loam_eval/via_check.py), synthetic
coordinates only, no stack. Each rule C1-C8 has a test that goes red when the rule is broken."""
import math

from loam_eval.via_check import check_via_route

LAT0, LON0 = 43.13, -71.50
DLAT, DLON = 0.001, 0.001 / math.cos(math.radians(LAT0))


def _line(a, b, n=20):
    return [[a[0] + (b[0] - a[0]) * i / n, a[1] + (b[1] - a[1]) * i / n] for i in range(n)]


def _poly(pts):
    out = []
    for a, b in zip(pts, pts[1:]):
        out += _line(a, b)
    return out + [list(pts[-1])]


def _pt(north, east):  # (lon, lat) offset in units of ~111 m
    return [LON0 + east * DLON, LAT0 + north * DLAT]


def fake_eval(offset=3.0, road=0.0):
    def ev(coords, target):
        from loam_eval.real import _hav
        miles = sum(_hav(coords[i], coords[i + 1]) for i in range(len(coords) - 1)) / 1609.344
        return {"miles": round(miles, 2), "offset_m": offset, "road_pct": road,
                "dist_err": round(abs(miles - target) / target, 3) if target else None}
    return ev


START = (LAT0, LON0)
# a ~0.5 mi square-ish loop: S -> A (north) -> B (north-east) -> C (east) -> S
A, B, C = _pt(5, 0), _pt(5, 5), _pt(0, 5)
LOOP = _poly([_pt(0, 0), A, B, C, _pt(0, 0)])
VIA_A, VIA_B, VIA_C = (A[1], A[0]), (B[1], B[0]), (C[1], C[0])


def check(coords=LOOP, vias=(VIA_A, VIA_B), **kw):
    kw.setdefault("evaluate", fake_eval())
    return check_via_route(coords, START, list(vias), **kw)


def test_clean_loop_passes_everything():
    r = check(vias=(VIA_A, VIA_B, VIA_C))
    assert r["ok"], r
    assert r["failed"] == []


def test_c1_unclosed_loop_fails():
    r = check(coords=LOOP[:-30])
    assert "C1" in r["failed"]


def test_c1_start_snap_widens_limit_but_loop_must_close():
    off = (LAT0 + 0.0008, LON0)  # start coordinate ~89 m north of where the route starts and ends
    r = check_via_route(LOOP, off, [VIA_A], evaluate=fake_eval())
    assert "C1" in r["failed"]
    assert check_via_route(LOOP, off, [VIA_A], evaluate=fake_eval(), start_snap_m=89.0)["C1"]["ok"]
    assert "C1" in check_via_route(LOOP[:-30], off, [VIA_A], evaluate=fake_eval(), start_snap_m=89.0)["failed"]


def test_c1_point_to_point_ends_at_end():
    r = check(coords=_poly([_pt(0, 0), A, B]), vias=(VIA_A,), end=(B[1], B[0]))
    assert r["C1"]["ok"], r
    assert not check(coords=_poly([_pt(0, 0), A, B]), vias=(VIA_A,))["C1"]["ok"]


def test_c2_missed_via_fails_and_snap_widens_tolerance():
    far = (LAT0 + 3 * DLAT, LON0 + 3 * DLON * 3)  # ~330 m from any vertex of the loop
    assert "C2" in check(vias=(VIA_A, far))["failed"]
    near = (A[1] + 0.0004, A[0])  # ~44 m north of the corner, off the route
    assert "C2" in check(vias=(near,))["failed"]
    assert check(vias=(near,), snap_m=[30.0])["C2"]["ok"]       # snap 30 m + 25 m slack
    assert not check(vias=(far,), snap_m=[500.0])["C2"]["ok"]   # never beyond VIA_TOLERANCE_M


def test_c3_wrong_order_fails():
    r = check(vias=(VIA_B, VIA_A))
    assert r["C2"]["ok"] and "C3" in r["failed"]


def test_c3_a_pass_on_the_way_does_not_break_the_order():
    # S -> B is on the way to A: the route passes B early, reaches A, comes back through B, closes at S
    coords = _poly([_pt(0, 0), B, A, B, _pt(0, 0)])
    r = check(coords=coords, vias=(VIA_A, VIA_B))
    assert r["C3"]["ok"], r                       # A at the middle, B again after it
    assert "C3" in check(coords=_poly([_pt(0, 0), B, A, _pt(0, 0)]), vias=(VIA_A, VIA_B))["failed"]  # B only before A


def test_c4_straight_line_fabrication_fails():
    r = check(evaluate=fake_eval(offset=240.0))
    assert "C4" in r["failed"]
    assert "C4" in check(evaluate=lambda c, t: {"offset_m": None, "road_pct": 0.0})["failed"]


def test_c4_way_ids_use_geometry_offset():
    r = check(way_ids=[1], offset=lambda c, w: 40.0)
    assert "C4" in r["failed"]
    assert check(way_ids=[1], offset=lambda c, w: 4.0)["C4"]["ok"]


def test_c5_out_and_back_fails():
    out = _poly([_pt(0, 0), A, B])
    r = check(coords=out + out[::-1][1:], vias=(VIA_B,))
    assert r["C1"]["ok"] and r["C2"]["ok"]
    assert "C5" in r["failed"]
    assert r["C5"]["retrace"] > 0.28


def test_c5_dead_end_waived_only_with_notice():
    out = _poly([_pt(0, 0), A, B])
    coords = out + out[::-1][1:]
    r = check(coords=coords, vias=(VIA_B,), dead_end_vias=[0])
    assert r["C5"]["waived"] and "C8" in r["failed"]
    r = check(coords=coords, vias=(VIA_B,), dead_end_vias=[0], notice="Midpoint 1 is at the end of a dead-end trail")
    assert r["ok"], r


def test_c6_reported_miles_must_match_geometry():
    assert "C6" in check(reported_miles=9.9)["failed"]
    assert check(reported_miles=check()["C6"]["geometry_miles"])["C6"]["ok"]


def test_c6_target_distance_tolerance():
    miles = check()["C6"]["geometry_miles"]
    assert check(target_miles=miles)["C6"]["ok"]
    assert "C6" in check(target_miles=miles * 3)["failed"]


def test_c7_road_share_over_cap_fails():
    assert "C7" in check(evaluate=fake_eval(road=40.0))["failed"]
    assert check(evaluate=fake_eval(road=40.0), road_cap_pct=50.0)["C7"]["ok"]
