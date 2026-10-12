"""
Nearby Start Suggestions for Loam.
Evaluates nearby start locations (trailheads and junctions within ~0.5 miles)
that enable a true closed loop (retrace <= 10%) when the requested start
only yields out-and-backs or high-retrace routes.
"""
import math
from typing import Dict, Any, List, Optional
from app.scoring import haversine_m
from app.db import get_connection, RealDictCursor

METERS_TO_MILES = 0.000621371192


def find_nearby_loop_start(
    start_lat: float,
    start_lon: float,
    current_retrace_ratio: float,
    graph: Optional[Any] = None,
    max_radius_m: float = 850.0  # ~0.53 miles
) -> Optional[Dict[str, Any]]:
    """
    If current retrace > 0.10, searches within ~0.5 miles for alternative trailheads
    or junction nodes that connect directly into true loop circuits.
    Returns suggestion dictionary with friendly message if found.
    """
    # If the current start already produced a true loop, no suggestion needed
    if current_retrace_ratio <= 0.10:
        return None

    start_pt = [start_lon, start_lat]

    # 1. Query contracted graph junctions with degree >= 2
    if graph and hasattr(graph, "junctions"):
        candidates = []
        for j_id, j in graph.junctions.items():
            if j.degree >= 3:  # Major trail junction
                d_m = haversine_m(start_pt, [j.lon, j.lat])
                if 80.0 <= d_m <= max_radius_m:
                    candidates.append((d_m, j))

        if candidates:
            candidates.sort(key=lambda c: c[0])
            best_d_m, best_j = candidates[0]
            dist_mi = round(best_d_m * METERS_TO_MILES, 1)

            # Find name of adjacent trail
            adjacent_edges = graph.adjacency.get(best_j.id, [])
            trail_names = [e.name for _, e in adjacent_edges if e.name and not e.name.startswith("Trail #")]
            j_name = trail_names[0] if trail_names else "an unnamed trail junction"

            return {
                "suggested_lat": best_j.lat,
                "suggested_lon": best_j.lon,
                "distance_miles": dist_mi,
                "junction_name": j_name,
                "message": f"Try starting {dist_mi} mi away at {j_name}"
            }

    # 2. Database query for nearby trail nodes if graph not in memory
    try:
        deg_radius = max_radius_m / 111132.0
        with get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT name, ST_Y(ST_StartPoint(geom)) as lat, ST_X(ST_StartPoint(geom)) as lon,
                           ST_Distance(geom::geography, ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography) as dist_m
                    FROM edges
                    WHERE geom IS NOT NULL
                      AND highway IN ('path', 'track')
                      AND ST_DWithin(geom::geography, ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography, %s)
                    ORDER BY dist_m ASC
                    LIMIT 3;
                    """,
                    (start_lon, start_lat, start_lon, start_lat, max_radius_m)
                )
                rows = cur.fetchall()
                for r in rows:
                    d_m = float(r.get("dist_m") or 0.0)
                    if d_m >= 100.0:
                        dist_mi = round(d_m * METERS_TO_MILES, 1)
                        name = r.get("name") or "an unnamed trail"
                        return {
                            "suggested_lat": float(r["lat"]),
                            "suggested_lon": float(r["lon"]),
                            "distance_miles": dist_mi,
                            "junction_name": name,
                            "message": f"Try starting {dist_mi} mi away at {name}"
                        }
    except Exception:
        pass

    return None
