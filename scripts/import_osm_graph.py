#!/usr/bin/env python3
"""Import the OSM trail and road network into PostGIS (docs/round7-plan.md 5.1).

Reads the same extract GraphHopper uses (so way ids match), keeps trail and road ways plus
snowmobile ways, splits them into segments at every node shared by two or more kept ways
and at way endpoints, and writes:
  - trail_segments: one row per segment, with OSM node ids as junctions and the way's tags;
  - edges: one row per way (heat stays keyed by way id), geometry and tags overwritten from OSM.
Edges rows whose way isn't in the extract keep their row (heat history) but lose geometry.

Re-run whenever the extract changes:
    python -m scripts.import_osm_graph [--pbf $DATA_DIR/osm/new-hampshire-latest.osm.pbf]
"""
import argparse
import datetime
import io
import math
import os
import sys
import time
from array import array

import numpy as np
import osmium

from app.db import get_connection
from app.surface import classify_surface

KEEP_HIGHWAYS = {
    "path", "track", "footway", "bridleway", "cycleway", "unclassified", "residential", "service",
    "tertiary", "secondary", "primary", "living_street", "steps", "pedestrian",
}
TAG_KEYS = ["name", "highway", "surface", "tracktype", "mtb:scale", "mtb:scale:imba", "sac_scale",
            "access", "bicycle", "foot", "motor_vehicle", "snowmobile", "seasonal", "informal",
            "smoothness", "check_date"]
EARTH_R = 6371008.8


def haversine_m(lon1, lat1, lon2, lat2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_R * math.asin(math.sqrt(a))


def line_length(coords):
    return sum(haversine_m(*coords[i], *coords[i + 1]) for i in range(len(coords) - 1))


def is_kept(tags, snowmobile_route_ways, way_id):
    hw = tags.get("highway")
    if hw in KEEP_HIGHWAYS and tags.get("area") != "yes":
        return True
    if way_id in snowmobile_route_ways:
        return True
    return tags.get("snowmobile") not in (None, "no")


def copy_value(v):
    if v is None:
        return r"\N"
    return str(v).replace("\\", "\\\\").replace("\t", " ").replace("\n", " ").replace("\r", " ")


def wkt(coords):
    return "SRID=4326;LINESTRING(" + ",".join(f"{lon:.7f} {lat:.7f}" for lon, lat in coords) + ")"


def split_points(node_ids, junctions):
    """Indices where a way is cut into segments: its endpoints plus every interior node in
    `junctions` (shared by two or more kept ways, or repeated within one way)."""
    cuts = [0]
    for i in range(1, len(node_ids) - 1):
        if node_ids[i] in junctions:
            cuts.append(i)
    cuts.append(len(node_ids) - 1)
    return cuts


def mtb_scale_int(raw):
    try:
        return int(str(raw).strip()[0]) if raw else None
    except (ValueError, IndexError):
        return None


def main():
    default = os.path.join(os.environ.get("DATA_DIR", os.path.expanduser("~/dev/loam/main/data")),
                           "osm", "new-hampshire-latest.osm.pbf")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pbf", default=default)
    args = ap.parse_args()
    t0 = time.time()

    # Pass 1: ways that belong to snowmobile route relations.
    snowmobile_route_ways = set()
    for rel in osmium.FileProcessor(args.pbf, osmium.osm.RELATION):
        if rel.tags.get("route") == "snowmobile":
            snowmobile_route_ways.update(m.ref for m in rel.members if m.type == "w")
    print(f"snowmobile route ways: {len(snowmobile_route_ways)}", file=sys.stderr)

    # Pass 2: node use counts over kept ways, and every way id in the extract.
    refs = array("q")
    all_way_ids = array("q")
    kept = 0
    for w in osmium.FileProcessor(args.pbf, osmium.osm.WAY):
        all_way_ids.append(w.id)
        if not is_kept(w.tags, snowmobile_route_ways, w.id):
            continue
        kept += 1
        refs.extend(n.ref for n in w.nodes)
    node_ids, counts = np.unique(np.frombuffer(refs, dtype=np.int64), return_counts=True)
    junctions = set(node_ids[counts >= 2].tolist())
    del refs, node_ids, counts
    print(f"kept ways: {kept}; junction nodes: {len(junctions)}", file=sys.stderr)

    # Pass 3: split kept ways into segments, with node locations.
    seg_buf, edge_buf = io.StringIO(), io.StringIO()
    n_segments = 0
    for w in osmium.FileProcessor(args.pbf, osmium.osm.NODE | osmium.osm.WAY).with_locations():
        if not isinstance(w, osmium.osm.Way) or not is_kept(w.tags, snowmobile_route_ways, w.id):
            continue
        try:
            nodes = [(n.ref, n.lon, n.lat) for n in w.nodes]
        except osmium.InvalidLocationError:
            continue
        if len(nodes) < 2:
            continue
        tags = {k: w.tags.get(k) for k in TAG_KEYS}
        cls = classify_surface({**tags, "route": "snowmobile" if w.id in snowmobile_route_ways else None})
        ts = w.timestamp.isoformat() if w.timestamp else None

        way_coords = [(lon, lat) for _, lon, lat in nodes]
        edge_buf.write("\t".join(copy_value(v) for v in (
            w.id, tags["name"], tags["highway"], tags["surface"], tags["tracktype"],
            mtb_scale_int(tags["mtb:scale"]), tags["mtb:scale"], tags["mtb:scale:imba"], tags["sac_scale"],
            tags["bicycle"], tags["foot"], cls.snowmobile, tags["access"], tags["motor_vehicle"],
            tags["seasonal"], tags["informal"], tags["smoothness"], ts, cls.category,
            wkt(way_coords), round(line_length(way_coords), 2),
        )) + "\n")

        cuts = split_points([n[0] for n in nodes], junctions)
        seq = 0
        for start, i in zip(cuts, cuts[1:]):
            coords = way_coords[start:i + 1]
            length = line_length(coords)
            if length > 0:
                seg_buf.write("\t".join(copy_value(v) for v in (
                    w.id, seq, nodes[start][0], nodes[i][0], wkt(coords), round(length, 2),
                    tags["name"], tags["highway"], tags["surface"], tags["tracktype"], tags["mtb:scale"],
                    tags["mtb:scale:imba"], tags["sac_scale"], tags["access"], tags["bicycle"],
                    tags["foot"], tags["motor_vehicle"], tags["snowmobile"], tags["seasonal"],
                    tags["informal"], tags["smoothness"], tags["check_date"], ts, cls.category,
                    cls.snowmobile, cls.steps,
                )) + "\n")
                seq += 1
                n_segments += 1
    print(f"segments: {n_segments} ({time.time() - t0:.0f} s)", file=sys.stderr)

    seg_buf.seek(0)
    edge_buf.seek(0)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE trail_segments RESTART IDENTITY")
            cur.copy_expert(
                "COPY trail_segments (osm_way_id, seq, from_node, to_node, geom, length_m, name, highway, surface, "
                "tracktype, mtb_scale, mtb_scale_imba, sac_scale, access, bicycle, foot, motor_vehicle, snowmobile, "
                "seasonal, informal, smoothness, check_date, osm_timestamp, category, is_snowmobile, is_steps) "
                "FROM STDIN", seg_buf)
            cur.execute(
                "CREATE TEMP TABLE edges_import (osm_id BIGINT, name TEXT, highway TEXT, surface TEXT, tracktype TEXT, "
                "mtb_scale INT, mtb_scale_raw TEXT, mtb_scale_imba TEXT, sac_scale TEXT, bicycle TEXT, foot TEXT, "
                "snowmobile BOOLEAN, access TEXT, motor_vehicle TEXT, seasonal TEXT, informal TEXT, smoothness TEXT, "
                "osm_timestamp TIMESTAMPTZ, category TEXT, geom GEOMETRY(LineString, 4326), length_m DOUBLE PRECISION) "
                "ON COMMIT DROP")
            cur.copy_expert("COPY edges_import FROM STDIN", edge_buf)
            cur.execute(
                """
                INSERT INTO edges (osm_id, name, highway, surface, tracktype, mtb_scale, mtb_scale_raw, mtb_scale_imba,
                                   sac_scale, bicycle, foot, snowmobile, access, motor_vehicle, seasonal, informal,
                                   smoothness, osm_timestamp, last_osm_edit, category, geom, length_m, osm_source)
                SELECT osm_id, name, highway, surface, tracktype, mtb_scale, mtb_scale_raw, mtb_scale_imba,
                       sac_scale, bicycle, foot, snowmobile, access, motor_vehicle, seasonal, informal,
                       smoothness, osm_timestamp, osm_timestamp::date, category, geom, length_m, TRUE
                FROM edges_import
                ON CONFLICT (osm_id) DO UPDATE SET
                    name = EXCLUDED.name, highway = EXCLUDED.highway, surface = EXCLUDED.surface,
                    tracktype = EXCLUDED.tracktype, mtb_scale = EXCLUDED.mtb_scale,
                    mtb_scale_raw = EXCLUDED.mtb_scale_raw, mtb_scale_imba = EXCLUDED.mtb_scale_imba,
                    sac_scale = EXCLUDED.sac_scale, bicycle = EXCLUDED.bicycle, foot = EXCLUDED.foot,
                    snowmobile = EXCLUDED.snowmobile, access = EXCLUDED.access,
                    motor_vehicle = EXCLUDED.motor_vehicle, seasonal = EXCLUDED.seasonal,
                    informal = EXCLUDED.informal, smoothness = EXCLUDED.smoothness,
                    osm_timestamp = EXCLUDED.osm_timestamp, last_osm_edit = EXCLUDED.last_osm_edit,
                    category = EXCLUDED.category, geom = EXCLUDED.geom, length_m = EXCLUDED.length_m,
                    osm_source = TRUE
                """
            )
            edges_upserted = cur.rowcount
            # Rows for ways that don't exist in OSM at all (hand-made ids, deleted ways) keep their
            # heat history but lose any geometry that wasn't drawn from OSM.
            cur.execute("CREATE TEMP TABLE osm_way_ids (id BIGINT PRIMARY KEY) ON COMMIT DROP")
            id_buf = io.StringIO("\n".join(str(i) for i in sorted(set(all_way_ids))) + "\n")
            cur.copy_expert("COPY osm_way_ids FROM STDIN", id_buf)
            cur.execute(
                """
                UPDATE edges e SET geom = NULL, length_m = NULL, osm_source = FALSE
                WHERE NOT EXISTS (SELECT 1 FROM osm_way_ids o WHERE o.id = e.osm_id)
                  AND (e.geom IS NOT NULL OR e.osm_source)
                """
            )
            not_in_osm = cur.rowcount
            st = os.stat(args.pbf)
            cur.execute(
                "INSERT INTO osm_imports (pbf_path, pbf_size, pbf_mtime, ways_kept, segments, edges_upserted, edges_not_in_osm) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (os.path.basename(args.pbf), st.st_size,
                 datetime.datetime.fromtimestamp(st.st_mtime, datetime.timezone.utc),
                 kept, n_segments, edges_upserted, not_in_osm),
            )
        conn.commit()
        with conn.cursor() as cur:
            cur.execute("ANALYZE trail_segments; ANALYZE edges;")
        conn.commit()
    print(f"edges upserted from OSM: {edges_upserted}; edges not in the extract (geometry cleared): {not_in_osm}",
          file=sys.stderr)
    print(f"done in {time.time() - t0:.0f} s", file=sys.stderr)


if __name__ == "__main__":
    main()
