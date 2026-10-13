#!/usr/bin/env python3
"""Import water, bike shop, bike repair and toilet points from the OSM extract into `pois`.

    python -m scripts.import_osm_pois [--pbf $DATA_DIR/osm/new-hampshire-latest.osm.pbf]

Nodes and building ways (shops are often mapped as buildings; their centroid is used) are kept.
Re-running replaces the table. Only OSM data goes in; nothing is invented.
"""
import argparse
import os
import sys

import osmium
import psycopg2
from psycopg2.extras import execute_values

from app.config import settings

KINDS = (
    ("amenity", "drinking_water", "water"),
    ("natural", "spring", "water"),
    ("shop", "bicycle", "bike_shop"),
    ("amenity", "bicycle_repair_station", "bike_repair"),
    ("amenity", "toilets", "toilets"),
)


def kind_of(tags):
    for key, value, kind in KINDS:
        if tags.get(key) == value:
            if kind == "water" and tags.get("drinking_water") == "no":
                return None
            return kind
    return None


def main() -> None:
    default = os.path.join(os.getenv("DATA_DIR", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")),
                           "osm", "new-hampshire-latest.osm.pbf")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pbf", default=default)
    args = ap.parse_args()
    rows = []
    for o in osmium.FileProcessor(args.pbf, osmium.osm.NODE | osmium.osm.WAY).with_locations().with_filter(
            osmium.filter.KeyFilter("amenity", "natural", "shop")):
        kind = kind_of(o.tags)
        if not kind:
            continue
        try:
            if isinstance(o, osmium.osm.Node):
                lon, lat, typ = o.lon, o.lat, "node"
            else:
                pts = [(n.lon, n.lat) for n in o.nodes]
                lon, lat, typ = sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts), "way"
        except (osmium.InvalidLocationError, ZeroDivisionError):
            continue
        rows.append((typ, o.id, kind, o.tags.get("name"), lon, lat))
    if not rows:
        sys.exit("no points found; table left unchanged")
    with psycopg2.connect(settings.database_url) as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM pois")
        execute_values(cur, "INSERT INTO pois (osm_type, osm_id, kind, name, geom) VALUES %s ON CONFLICT DO NOTHING", rows,
                       template="(%s, %s, %s, %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326))")
        conn.commit()
    counts = {}
    for r in rows:
        counts[r[2]] = counts.get(r[2], 0) + 1
    print(f"imported {len(rows)} points: {counts}")


if __name__ == "__main__":
    main()
