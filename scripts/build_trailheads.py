#!/usr/bin/env python3
"""Build frontend/src/data/trailheads.json from the OSM extract.

For each public trail area below (an OSM area: park, forest or reserve), find the public
`amenity=parking` closest to it (inside or within 1 km) and record both, with their OSM ids.
Nothing is typed by hand except which areas to look up; every coordinate comes from OSM.

    python -I scripts/build_trailheads.py data/osm/new-hampshire-latest.osm.pbf
"""
import json
import os
import sys

import osmium
from shapely.geometry import Point, Polygon, MultiPolygon
from shapely.ops import nearest_points

# pyosmium area ids: 2 * way_id for closed ways, 2 * relation_id + 1 for relations.
AREAS = [
    (11077099, "Bear Brook State Park", "Allenstown"),
    (95596420, "Bow Town Forest", "Bow"),
    (95596446, "Knox Town Forest", "Bow"),
    (95596360, "Page Road Town Forest", "Bow"),
    (2793433444, "Oak Hill City Forest", "Concord"),
    (101598284, "White Park", "Concord"),
    (38354235, "Franklin Falls Reservoir", "Franklin"),
    (95597358, "Stratham Hill Park", "Stratham"),
]
MAX_PARKING_DISTANCE_M = 1000.0
M_PER_DEG = 111_132.0


def osm_ref(area_id):
    return ("relation", (area_id - 1) // 2) if area_id % 2 else ("way", area_id // 2)


def main(pbf):
    wanted = {a[0] for a in AREAS}
    polygons = {}
    parkings = []
    fp = osmium.FileProcessor(pbf).with_locations().with_areas()
    for o in fp:
        tags = o.tags
        if isinstance(o, osmium.osm.Area) and o.id in wanted:
            polys = []
            for outer in o.outer_rings():
                pts = [(n.lon, n.lat) for n in outer]
                if len(pts) >= 4:
                    polys.append(Polygon(pts))
            if polys:
                polygons[o.id] = MultiPolygon(polys) if len(polys) > 1 else polys[0]
        if tags.get("amenity") != "parking" or tags.get("access") in ("private", "no", "customers"):
            continue
        if isinstance(o, osmium.osm.Node):
            parkings.append(("node", o.id, Point(o.location.lon, o.location.lat), tags.get("name")))
        elif isinstance(o, osmium.osm.Area):
            ring = next(iter(o.outer_rings()), None)
            if ring is not None:
                pts = [(n.lon, n.lat) for n in ring]
                if len(pts) >= 4:
                    kind, ref = osm_ref(o.id)
                    parkings.append((kind, ref, Polygon(pts).centroid, tags.get("name")))

    out = []
    for area_id, name, town in AREAS:
        poly = polygons.get(area_id)
        if poly is None:
            print(f"skip {name}: area {area_id} not in extract", file=sys.stderr)
            continue
        best = None
        for kind, ref, pt, pname in parkings:
            if abs(pt.x - poly.centroid.x) > 0.2 or abs(pt.y - poly.centroid.y) > 0.2:
                continue
            p1, _ = nearest_points(poly, pt)
            d = ((p1.x - pt.x) * M_PER_DEG * 0.73) ** 2 + ((p1.y - pt.y) * M_PER_DEG) ** 2
            d = d ** 0.5 if not poly.contains(pt) else 0.0
            if d > MAX_PARKING_DISTANCE_M:
                continue
            # Nearest to the area first; among parkings inside it, a named trailhead, then the
            # one closest to the area's centroid (deterministic, no hand-picking).
            trailhead_name = bool(pname and ("trail" in pname.lower() or "parking" in pname.lower()))
            rank = (round(d), not trailhead_name, pt.distance(poly.centroid))
            if best is None or rank < best[0]:
                best = (rank, kind, ref, pt, pname)
        if best is None:
            print(f"skip {name}: no public parking within {MAX_PARKING_DISTANCE_M:.0f} m", file=sys.stderr)
            continue
        rank, kind, ref, pt, pname = best
        d = rank[0]
        a_kind, a_ref = osm_ref(area_id)
        out.append({
            "name": f"{name} parking",
            "area": name,
            "town": town,
            "lat": round(pt.y, 6),
            "lon": round(pt.x, 6),
            "parking_osm": f"{kind}/{ref}",
            "parking_name": pname,
            "area_osm": f"{a_kind}/{a_ref}",
            "distance_to_area_m": round(d),
        })
        print(f"{name}: parking {kind}/{ref} ({pname or 'unnamed'}) {d:.0f} m from the area", file=sys.stderr)

    dest = os.path.join(os.path.dirname(__file__), "..", "frontend", "src", "data", "trailheads.json")
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "w") as f:
        json.dump({
            "source": "OpenStreetMap contributors (ODbL), extracted by scripts/build_trailheads.py",
            "trailheads": out,
        }, f, indent=2)
        f.write("\n")
    print(f"wrote {len(out)} trailheads to {os.path.normpath(dest)}", file=sys.stderr)


if __name__ == "__main__":
    main(sys.argv[1])
