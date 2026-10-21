"""Before/after maps of midpoint loops (GH-41 phase 4), for the owner to eyeball "is this a sensible loop".

    python -m loam_eval via-maps --before <tree with main's app> --out docs/screenshots/round9-midpoints

For each scenario id below: the top option of main's engine (--before tree) and of this branch, drawn over the
OSM trail network (PostGIS trail_segments) as an SVG, rendered to PNG with headless Chromium. Public trailheads
and OSM data only; nothing from data/garmin-stripped.
"""
from __future__ import annotations

import html
import json
import math
import os
import subprocess
import sys
import tempfile
from typing import Any, Dict, List

from loam_eval import real
from loam_eval.via_scenarios import OUT as SCENARIOS

PICKS = ["v1_bear_brook_10mi_b135", "v2_bear_brook_10mi_b30", "v3_knox_10mi", "adv_dead_end_bear_brook"]
W, H = 760, 760


def _network(bbox):
    from app.db import get_connection
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT ST_AsGeoJSON(geom), category FROM trail_segments WHERE geom && ST_MakeEnvelope(%s, %s, %s, %s, 4326)", bbox)
        return [(json.loads(g)["coordinates"], c) for g, c in cur.fetchall()]


def _panel(title: str, sc: Dict[str, Any], coords: List[List[float]], net, proj, colour: str) -> str:
    out = [f'<g><text x="12" y="24" font-size="17" font-weight="700">{html.escape(title)}</text>']
    for line, cat in net:
        pts = " ".join(f"{proj(c[0], c[1])[0]:.1f},{proj(c[0], c[1])[1]:.1f}" for c in line)
        out.append(f'<polyline points="{pts}" fill="none" stroke="{"#c9ced1" if cat == "paved" else "#8d9a8f"}" stroke-width="{0.8 if cat == "paved" else 1.4}"/>')
    if coords:
        pts = " ".join(f"{proj(c[0], c[1])[0]:.1f},{proj(c[0], c[1])[1]:.1f}" for c in coords)
        out.append(f'<polyline points="{pts}" fill="none" stroke="{colour}" stroke-width="3" stroke-opacity="0.85" stroke-linejoin="round"/>')
    x, y = proj(sc["start"][1], sc["start"][0])
    out.append(f'<rect x="{x - 7:.1f}" y="{y - 7:.1f}" width="14" height="14" fill="#111"/>')
    for i, (la, lo) in enumerate(sc["waypoints"], start=1):
        x, y = proj(lo, la)
        out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="11" fill="#fff" stroke="#111" stroke-width="2"/>'
                   f'<text x="{x:.1f}" y="{y + 5:.1f}" font-size="13" font-weight="700" text-anchor="middle">{i}</text>')
    if not coords:
        out.append('<text x="12" y="48" font-size="14" fill="#a00">no route returned</text>')
    return "".join(out) + "</g>"


def render(sc, before, after, png: str) -> None:
    allc = [c for r in (before, after) for c in r] + [[sc["start"][1], sc["start"][0]]] + [[lo, la] for la, lo in sc["waypoints"]]
    pad = 0.004
    lon0, lon1 = min(c[0] for c in allc) - pad, max(c[0] for c in allc) + pad
    lat0, lat1 = min(c[1] for c in allc) - pad, max(c[1] for c in allc) + pad
    k = math.cos(math.radians((lat0 + lat1) / 2))
    scale = min((W - 24) / ((lon1 - lon0) * k), (H - 70) / (lat1 - lat0))

    def proj(lon, lat):
        return 12 + (lon - lon0) * k * scale, 50 + (lat1 - lat) * scale
    net = _network((lon0, lat0, lon1, lat1))
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{2 * W + 12}" height="{H + 40}" font-family="sans-serif">'
           f'<rect width="100%" height="100%" fill="#f4f1ea"/>'
           f'<text x="12" y="20" font-size="14" fill="#333">{html.escape(sc["id"])}: {html.escape(sc["name"])}, {sc["miles"]} mi target. '
           f'Square = trailhead, numbered circles = midpoints in order. Grey = OSM trails, light grey = roads.</text>'
           f'<g transform="translate(0,16)">{_panel("Before (main)", sc, before, net, proj, "#d1491f")}</g>'
           f'<g transform="translate({W + 12},16)">{_panel("After (this branch)", sc, after, net, proj, "#1565c0")}</g></svg>')
    page = os.path.splitext(png)[0] + ".html"
    with open(page, "w", encoding="utf-8") as fh:
        fh.write(f'<!doctype html><meta charset="utf-8"><body style="margin:0">{svg}</body>')
    subprocess.run(["chromium", "--headless", "--no-sandbox", "--disable-gpu", "--hide-scrollbars",
                    f"--window-size={2 * W + 12},{H + 40}", f"--screenshot={png}", f"file://{page}"], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    os.remove(page)


def main(before_tree: str, out: str) -> int:
    scs = [s for s in json.load(open(SCENARIOS))["scenarios"] if s["id"] in PICKS]
    os.makedirs(out, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "picks.json")
        json.dump({"scenarios": scs}, open(path, "w"))
        runs = {"before": real.run_engine(os.path.abspath(before_tree), path, os.path.join(tmp, "before.json")),
                "after": real.run_engine(real.ROOT, path, os.path.join(tmp, "after.json"))}
    for sc in scs:
        top = {k: next((r for r in v if r["id"] == sc["id"]), {"options": []})["options"] for k, v in runs.items()}
        coords = {k: ([list(c) for c in o[0]["coordinates"]] if o else []) for k, o in top.items()}
        png = os.path.join(out, f"{sc['id']}.png")
        render(sc, coords["before"], coords["after"], png)
        print(png, {k: (o[0]["distance_miles"] if o else None) for k, o in top.items()})
    return 0
