#!/usr/bin/env python3
"""Import designated Wilderness Areas from USGS PAD-US as bike-only hard blocks.

Federal Wilderness bans bicycles (not feet), so these polygons become `restrictions` rows with
is_hard=true, applies_to='bike', restriction_type='wilderness'. Source: the USGS PAD-US feature
service (PADUS_Protected_Areas_States), Des_Tp = 'WA', clipped to New Hampshire's bounding box;
areas managed from the neighbouring state (e.g. Maine's Caribou-Speckled Mountain) are kept only
if they intersect the box, which the routing never reaches anyway. Re-running replaces the rows
whose source starts with "PAD-US".

PAD-US "closed to public" (Pub_Access = XA) polygons are NOT imported: most are private farm and
conservation easements, and a soft restriction would silently remove routes over public rights of way.

    python -m scripts.import_padus [--dry-run]
"""
import argparse
import json
import sys

import httpx
import psycopg2

from app.config import settings

SERVICE = ("https://services.arcgis.com/v01gqwM5QqNysAAi/ArcGIS/rest/services/"
           "PADUS_Protected_Areas_States/FeatureServer/0/query")
NH_BBOX = "-72.6,42.69,-70.6,45.31"  # min lon, min lat, max lon, max lat
SOURCE = "PAD-US (USGS), Des_Tp=WA"


def fetch_wilderness() -> list:
    params = {
        "where": "Des_Tp='WA'", "geometry": NH_BBOX, "geometryType": "esriGeometryEnvelope", "inSR": "4326",
        "spatialRel": "esriSpatialRelIntersects", "outSR": "4326", "outFields": "Unit_Nm,Mang_Name,ST_Name,Pub_Access",
        "returnGeometry": "true", "f": "geojson",
    }
    r = httpx.get(SERVICE, params=params, timeout=120.0)
    r.raise_for_status()
    data = r.json()
    if "error" in data:
        raise RuntimeError(f"PAD-US service error: {data['error'].get('message')}")
    return data.get("features", [])


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    features = fetch_wilderness()
    if not features:
        sys.exit("PAD-US returned no wilderness areas; nothing changed")
    for f in features:
        p = f["properties"]
        print(f"  {p['Unit_Nm']} ({p['ST_Name']}, {p['Mang_Name']})", file=sys.stderr)
    if args.dry_run:
        print(f"{len(features)} wilderness polygons (dry run)")
        return
    with psycopg2.connect(settings.database_url) as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM restrictions WHERE source LIKE 'PAD-US%'")
        for f in features:
            p = f["properties"]
            cur.execute(
                """INSERT INTO restrictions (name, restriction_type, source, is_hard, applies_to, description, geom)
                   VALUES (%s, 'wilderness', %s, TRUE, 'bike', %s,
                           ST_Multi(ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326)))""",
                (p["Unit_Nm"], SOURCE, "Designated Wilderness: bicycles are not allowed (Wilderness Act).",
                 json.dumps(f["geometry"])),
            )
        conn.commit()
    print(f"imported {len(features)} wilderness polygons")


if __name__ == "__main__":
    main()
