"""GH-41 phase 4: the GPX and FIT of a loop through midpoints carry the same track as the API route.

Live: the route comes from the real engine (public Bear Brook scenario), the files from the real export
endpoints. Same point count; start and end within 1 m; the GPX passes every midpoint in order (the checker's
C2 and C3 run on the GPX track itself).
"""
import asyncio
import re
import struct

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.route_builder import haversine_m
from loam_eval.via_check import check_via_route
from tests.test_round9_midpoints_live import SCENARIOS, _run, live

SEMICIRCLE = 180.0 / 2 ** 31
FIT_RECORD_DEF = bytes([0x43, 0, 0, 20, 0, 5, 253, 4, 134, 0, 4, 133, 1, 4, 133, 5, 4, 134, 2, 2, 132])


def fit_points(data: bytes):
    """(lon, lat) of every record message of a Loam FIT course (definition: local 3, global message 20)."""
    i = data.index(FIT_RECORD_DEF) + len(FIT_RECORD_DEF)
    out = []
    while data[i] == 3:
        _, lat, lon, _, _ = struct.unpack_from("<IiiIH", data, i + 1)
        out.append((lon * SEMICIRCLE, lat * SEMICIRCLE))
        i += 19
    return out


def gpx_points(xml: bytes):
    return [(float(lo), float(la)) for la, lo in re.findall(rb'<trkpt lat="(-?[\d.]+)" lon="(-?[\d.]+)"', xml)]


async def _export(kind, option):
    body = {"name": option.name, "sport": "mtb", "distance_miles": option.distance_miles,
            "duration_minutes": option.duration_minutes, "elevation_gain_ft": option.elevation_gain_ft,
            "elevation_loss_ft": option.elevation_loss_ft, "coordinates": option.coordinates}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post(f"/api/export/{kind}", json=body)
    assert r.status_code == 200, r.text
    return r.content


@live
@pytest.mark.parametrize("sid", ["v2_bear_brook_10mi_b30", "v1_bear_brook_10mi_b135"])
def test_exports_carry_the_api_track_and_pass_every_midpoint(sid):
    sc = SCENARIOS[sid]
    res, checked = _run(sid)
    assert checked, f"{sid}: no options"
    option = checked[0][0]
    api = [(c[0], c[1]) for c in option.coordinates]
    gpx = gpx_points(asyncio.run(_export("gpx", option)))
    fit = fit_points(asyncio.run(_export("fit", option)))
    for name, pts in (("GPX", gpx), ("FIT", fit)):
        assert len(pts) == len(api), f"{name} has {len(pts)} points, the API route {len(api)}"
        assert haversine_m(pts[0], api[0]) <= 1.0, f"{name} start"
        assert haversine_m(pts[-1], api[-1]) <= 1.0, f"{name} end"
    snaps = [m.get("snap_m", 0.0) for m in sc["via_meta"]]
    chk = check_via_route([list(p) for p in gpx], tuple(sc["start"]), [tuple(w) for w in sc["waypoints"]], snap_m=snaps,
                          start_snap_m=sc.get("start_snap_m", 0.0))
    assert chk["C2"]["ok"] and chk["C3"]["ok"], (chk["C2"], chk["C3"])


def test_fit_decoder_reads_what_the_exporter_writes():
    from app.fit_export import build_fit_course
    coords = [[-71.36592, 43.134855, 100.0], [-71.3660, 43.1352, 101.0], [-71.3665, 43.1356, 102.0]]
    pts = fit_points(build_fit_course("t", "mtb", coords, 1.0, 10.0, 5.0, 5.0))
    assert len(pts) == 3 and all(haversine_m(p, (c[0], c[1])) < 0.1 for p, c in zip(pts, coords))
