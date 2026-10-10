"""
Network Gap Audit for Loam.
Audits trail networks to identify:
1. Near-miss trail ends: endpoints that terminate within a small snap distance (< 35m)
   of each other without connecting in OSM, breaking potential loop circuits.
2. Blocking access tags: access=no, access=private, bicycle=no tags that block trail connections.
"""
import math
from typing import Dict, Any, List, Tuple
from app.db import get_connection, RealDictCursor
from app.scoring import haversine_m


def audit_network_gaps(
    center_lat: float,
    center_lon: float,
    radius_miles: float = 5.0,
    snap_distance_m: float = 35.0
) -> Dict[str, Any]:
    """
    Audits the trail network within radius_miles of (center_lat, center_lon)
    to detect near-miss disconnects and access barrier tags.
    """
    deg_lat = radius_miles / 69.0
    deg_lon = radius_miles / (69.0 * math.cos(math.radians(center_lat)))
    min_lon = center_lon - deg_lon
    max_lon = center_lon + deg_lon
    min_lat = center_lat - deg_lat
    max_lat = center_lat + deg_lat

    endpoints: List[Dict[str, Any]] = []
    blocking_ways: List[Dict[str, Any]] = []

    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # 1. Fetch trail lines
                cur.execute(
                    """
                    SELECT osm_id, name, highway, surface, access, bicycle,
                           ST_AsGeoJSON(geom)::json as geom_json
                    FROM edges
                    WHERE geom IS NOT NULL
                      AND ST_Intersects(geom, ST_MakeEnvelope(%s, %s, %s, %s, 4326));
                    """,
                    (min_lon, min_lat, max_lon, max_lat)
                )
                rows = cur.fetchall()

                for r in rows:
                    wid = int(r["osm_id"])
                    name = r.get("name") or f"Trail #{wid}"
                    acc = str(r.get("access") or "").lower()
                    bike = str(r.get("bicycle") or "").lower()

                    # Check blocking tags
                    if acc in ("no", "private") or bike == "no":
                        blocking_ways.append({
                            "osm_id": wid,
                            "name": name,
                            "barrier_tag": f"access={acc}" if acc in ("no", "private") else f"bicycle={bike}",
                            "highway": r.get("highway")
                        })

                    gj = r.get("geom_json")
                    if gj and gj.get("coordinates") and len(gj["coordinates"]) >= 2:
                        coords = gj["coordinates"]
                        endpoints.append({"osm_id": wid, "name": name, "coord": coords[0], "is_start": True})
                        endpoints.append({"osm_id": wid, "name": name, "coord": coords[-1], "is_start": False})

    except Exception as e:
        return {"error": str(e), "near_miss_count": 0, "blocking_count": 0}

    # 2. Find near-miss endpoints from different ways that terminate close by
    near_misses: List[Dict[str, Any]] = []
    seen_pairs = set()

    for i in range(len(endpoints)):
        for j in range(i + 1, len(endpoints)):
            ep1 = endpoints[i]
            ep2 = endpoints[j]
            if ep1["osm_id"] == ep2["osm_id"]:
                continue

            d = haversine_m(ep1["coord"], ep2["coord"])
            # Snap distance between 3m and snap_distance_m indicates disconnected near-miss
            if 3.0 < d <= snap_distance_m:
                pair_key = tuple(sorted([ep1["osm_id"], ep2["osm_id"]]))
                if pair_key not in seen_pairs:
                    seen_pairs.add(pair_key)
                    near_misses.append({
                        "trail_1": ep1["name"],
                        "trail_2": ep2["name"],
                        "osm_id_1": ep1["osm_id"],
                        "osm_id_2": ep2["osm_id"],
                        "gap_meters": round(d, 1),
                        "coords": [ep1["coord"], ep2["coord"]]
                    })

    return {
        "center": {"lat": center_lat, "lon": center_lon},
        "radius_miles": radius_miles,
        "near_miss_count": len(near_misses),
        "near_misses": near_misses[:15],
        "blocking_count": len(blocking_ways),
        "blocking_ways": blocking_ways[:15]
    }
