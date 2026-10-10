import logging
from typing import List, Dict, Any, Optional
import httpx
from app.config import settings
from app.activity_parser import TrackPoint
from app.gpx_export import build_gpx_track
from app.db import get_connection, upsert_edge_geometries

logger = logging.getLogger("loam.map_matching")

def get_gh_matching_profile(sport: str) -> str:
    s = (sport or "mtb").lower()
    if "run" in s or "foot" in s or "hike" in s:
        return "foot"
    elif "gravel" in s or "bike" in s:
        return "bike"
    return "mtb"

def extract_way_geometries(path: Dict[str, Any]) -> Dict[int, Dict[str, Any]]:
    """Longest contiguous matched polyline per OSM way id, with optional name/class/surface."""
    pts = path.get("points") or {}
    coords = pts.get("coordinates", []) if isinstance(pts, dict) else (pts or [])
    details = path.get("details", {}) or {}

    def lookup(key: str, idx: int):
        for it in details.get(key, []) or []:
            if len(it) >= 3 and it[0] <= idx < it[1]:
                return it[2]
        return None

    best: Dict[int, Dict[str, Any]] = {}
    for item in details.get("osm_way_id", []) or []:
        if len(item) < 3:
            continue
        s_idx, e_idx, wid = int(item[0]), int(item[1]), int(item[2])
        seg = [[c[0], c[1]] for c in coords[s_idx:e_idx + 1]]
        if len(seg) < 2 or seg[0] == seg[-1] and len(seg) == 2:
            continue
        cur = best.get(wid)
        if cur is None or len(seg) > len(cur["coords"]):
            best[wid] = {"coords": seg, "name": lookup("street_name", s_idx),
                         "highway": lookup("road_class", s_idx), "surface": lookup("surface", s_idx)}
    return best


def persist_matched_geometry(path: Dict[str, Any]) -> int:
    return upsert_edge_geometries(extract_way_geometries(path))


async def match_trackpoints_graphhopper(
    points: List[TrackPoint],
    sport: str = "mtb",
    timeout: float = 12.0
) -> Dict[int, int]:
    """
    Submits a GPX trace to GraphHopper's /match endpoint and returns traversed osm_way_ids
    with their traversal counts.
    """
    if len(points) < 2:
        return {}

    gh_profile = get_gh_matching_profile(sport)
    coords_3d = [[pt.lon, pt.lat, pt.ele or 0.0] for pt in points]
    gpx_payload = build_gpx_track(
        name="Ingested Ride",
        sport=sport,
        coordinates=coords_3d,
        distance_miles=1.0,
        duration_minutes=30.0,
        start_time=points[0].time
    )

    url = f"{settings.graphhopper_url}/match"
    params = {
        "profile": gh_profile,
        "type": "json",
        "points_encoded": "false",
        "details": ["osm_way_id", "street_name", "road_class", "surface"]
    }
    headers = {"Content-Type": "application/gpx+xml"}

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, params=params, headers=headers, content=gpx_payload.encode("utf-8"))
            if resp.status_code != 200:
                logger.warning(f"GraphHopper map-matching returned status {resp.status_code}: {resp.text}")
                return {}

            data = resp.json()
            paths = data.get("paths", [])
            if not paths:
                return {}

            osm_way_details = paths[0].get("details", {}).get("osm_way_id", [])
            edge_counts: Dict[int, int] = {}
            for item in osm_way_details:
                if len(item) >= 3:
                    wid = int(item[2])
                    edge_counts[wid] = edge_counts.get(wid, 0) + 1

            # Heat can only be drawn for edges that have geometry. Edges first seen via a ride
            # used to be inserted with osm_id only (invisible on the map), which made heat look
            # far sparser than the rides that produced it. Persist the matched geometry.
            try:
                persist_matched_geometry(paths[0])
            except Exception as geo_err:  # never let geometry persistence break ingestion
                logger.warning(f"Persisting matched edge geometry failed: {geo_err}")

            return edge_counts

    except Exception as e:
        logger.warning(f"GraphHopper /match request failed: {e}")
        return {}

def match_trackpoints_spatial_fallback(
    points: List[TrackPoint],
    search_radius_deg: float = 0.0005  # ~50 meters
) -> Dict[int, int]:
    """
    Fallback map-matching using PostGIS spatial proximity ST_DWithin against edges table.
    Used when GraphHopper /match cannot match disconnected/backcountry points or is unavailable.
    """
    if len(points) < 2:
        return {}

    edge_counts: Dict[int, int] = {}
    try:
        # Sample points every 30 meters / 5 points to reduce SQL load
        stride = max(1, len(points) // 40)
        sampled = points[::stride]

        with get_connection() as conn:
            with conn.cursor() as cur:
                for pt in sampled:
                    cur.execute(
                        """
                        SELECT osm_id
                        FROM edges
                        WHERE geom IS NOT NULL AND ST_DWithin(geom, ST_SetSRID(ST_Point(%s, %s), 4326), %s)
                        ORDER BY ST_Distance(geom, ST_SetSRID(ST_Point(%s, %s), 4326)) ASC
                        LIMIT 1;
                        """,
                        (pt.lon, pt.lat, search_radius_deg, pt.lon, pt.lat)
                    )
                    row = cur.fetchone()
                    if row:
                        wid = int(row[0])
                        edge_counts[wid] = edge_counts.get(wid, 0) + 1
    except Exception as e:
        logger.warning(f"Spatial fallback matching failed: {e}")

    return edge_counts

async def map_match_activity(
    points: List[TrackPoint],
    sport: str = "mtb"
) -> Dict[int, int]:
    """
    Primary map-matching function: attempts GraphHopper HMM map-matching first,
    falling back to PostGIS spatial proximity if necessary.
    """
    if len(points) < 2:
        return {}

    # Attempt GraphHopper map matching
    matched = await match_trackpoints_graphhopper(points, sport=sport)
    if matched:
        return matched

    # Fallback to PostGIS nearest-edge matching
    return match_trackpoints_spatial_fallback(points)
