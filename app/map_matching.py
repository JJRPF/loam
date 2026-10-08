import logging
from typing import List, Dict, Any, Optional
import httpx
from app.config import settings
from app.activity_parser import TrackPoint
from app.gpx_export import build_gpx_track
from app.db import get_connection

logger = logging.getLogger("loam.map_matching")

def get_gh_matching_profile(sport: str) -> str:
    s = (sport or "mtb").lower()
    if "run" in s or "foot" in s or "hike" in s:
        return "foot"
    elif "gravel" in s or "bike" in s:
        return "bike"
    return "mtb"

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
        "details": "osm_way_id"
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
