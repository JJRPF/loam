import logging
import json
import math
import time
import httpx
from typing import Dict, Any, List, Optional, Tuple
from app.config import settings
from app.db import get_connection, resolve_osm_trail_name
from psycopg2.extras import RealDictCursor

logger = logging.getLogger(__name__)

# Overpass API endpoint for live OpenTrailMap queries
OVERPASS_API_URL = "https://overpass-api.de/api/interpreter"

# The Overpass fallback is queried per 0.05 degree grid envelope and cached for 24 hours (failures for
# 5 minutes), so panning around does not repeat requests upstream.
OVERPASS_TILE_DEG = 0.05
OVERPASS_TTL_S = 24 * 3600
OVERPASS_FAIL_TTL_S = 300
_overpass_cache: Dict[tuple, tuple] = {}


def _tile_envelope(min_lat: float, min_lon: float, max_lat: float, max_lon: float) -> tuple:
    t = OVERPASS_TILE_DEG
    return tuple(round(v, 4) for v in (
        math.floor(min_lat / t) * t, math.floor(min_lon / t) * t, math.ceil(max_lat / t) * t, math.ceil(max_lon / t) * t))


async def _overpass_elements(env: tuple) -> list:
    hit = _overpass_cache.get(env)
    if hit and time.time() - hit[0] < hit[1]:
        return hit[2]
    elements, ttl = [], OVERPASS_FAIL_TTL_S
    try:
        overpass_query = f"""
        [out:json][timeout:12];
        (
          way["highway"~"^(path|track|footway|cycleway|bridleway)$"]({env[0]},{env[1]},{env[2]},{env[3]});
        );
        out body geom;
        """
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.post(OVERPASS_API_URL, data={"data": overpass_query},
                                     headers={"User-Agent": settings.user_agent})
        if resp.status_code == 200:
            elements, ttl = resp.json().get("elements", []), OVERPASS_TTL_S
    except Exception as op_err:
        logger.debug(f"Overpass live query skipped: {op_err}")
    if len(_overpass_cache) > 500:
        _overpass_cache.clear()
    _overpass_cache[env] = (time.time(), ttl, elements)
    return elements


# Difficulty mapping for OpenTrailMap mtb:scale (Singletrail Scale 0-6)
MTB_SCALE_DESCRIPTIONS = {
    0: {"name": "Beginner (Green)", "color": "#22C55E", "rating": "Easy"},
    1: {"name": "Intermediate (Blue)", "color": "#3B82F6", "rating": "Moderate"},
    2: {"name": "Advanced (Black)", "color": "#1E293B", "rating": "Difficult"},
    3: {"name": "Expert (Double Black)", "color": "#DC2626", "rating": "Very Difficult"},
    4: {"name": "Pro Only", "color": "#7C3AED", "rating": "Extreme"},
    5: {"name": "Extreme Pro", "color": "#000000", "rating": "Extreme"},
    6: {"name": "Extreme Pro+", "color": "#000000", "rating": "Extreme"}
}


UNKNOWN_DIFFICULTY = {"name": "Not rated", "color": "#94A3B8", "rating": "Unknown"}


def _difficulty(mtb_scale_raw: Any) -> Tuple[Optional[int], Dict[str, str]]:
    """OSM mtb:scale -> (scale, description). Untagged ways are 'Not rated', never guessed."""
    try:
        scale = int(str(mtb_scale_raw).strip()[0]) if mtb_scale_raw not in (None, "") else None
    except (ValueError, IndexError):
        scale = None
    if scale is None:
        return None, UNKNOWN_DIFFICULTY
    return scale, MTB_SCALE_DESCRIPTIONS.get(scale, UNKNOWN_DIFFICULTY)


def _surface_category(highway: Optional[str], surface: Optional[str], tracktype: Optional[str], name: Optional[str]) -> str:
    from app.surface import surface_category
    return surface_category({"highway": highway, "surface": surface, "tracktype": tracktype})


async def fetch_otm_trails_by_bbox(
    min_lat: float,
    min_lon: float,
    max_lat: float,
    max_lon: float,
    sport: Optional[str] = "mtb",
    limit: int = 150
) -> Dict[str, Any]:
    """
    OSM trails within a bounding box, from the local OSM import (`edges`), or live from
    Overpass when the import has nothing there. Every attribute comes from OSM tags; an
    untagged attribute is reported as unknown, never guessed. Empty when neither source has data.
    """
    features = []

    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT osm_id, name, highway, surface, tracktype, mtb_scale, sac_scale,
                           length_m, ST_AsGeoJSON(geom) as geom_json
                    FROM edges
                    WHERE geom IS NOT NULL
                      AND ST_Intersects(geom, ST_MakeEnvelope(%s, %s, %s, %s, 4326))
                      AND highway IN ('path', 'track', 'footway', 'bridleway', 'cycleway')
                    ORDER BY length_m DESC NULLS LAST
                    LIMIT %s;
                    """,
                    (min_lon, min_lat, max_lon, max_lat, limit)
                )
                for r in cur.fetchall():
                    if not r.get("geom_json"):
                        continue
                    scale, diff = _difficulty(r.get("mtb_scale"))
                    features.append({
                        "type": "Feature",
                        "properties": {
                            "osm_id": r["osm_id"],
                            "name": r["name"] or resolve_osm_trail_name(r["osm_id"]),
                            "highway": r.get("highway"),
                            "surface": _surface_category(r.get("highway"), r.get("surface"), r.get("tracktype"), r.get("name")),
                            "mtb_scale": scale,
                            "difficulty": diff["rating"].lower(),
                            "difficulty_name": diff["name"],
                            "difficulty_color": diff["color"],
                            "sac_scale": r.get("sac_scale"),
                            "length_miles": round(r["length_m"] / 1609.34, 2) if r.get("length_m") else None,
                            "source": "OpenStreetMap (local import)"
                        },
                        "geometry": json.loads(r["geom_json"])
                    })
    except Exception as db_err:
        logger.warning(f"Error querying PostGIS edges for OTM trails: {db_err}")

    if features:
        return {"type": "FeatureCollection", "features": features}

    for el in (await _overpass_elements(_tile_envelope(min_lat, min_lon, max_lat, max_lon)))[:limit]:
        if el.get("type") != "way" or not el.get("geometry"):
            continue
        coords = [[pt["lon"], pt["lat"]] for pt in el["geometry"]]
        if len(coords) < 2:
            continue
        tags = el.get("tags", {})
        scale, diff = _difficulty(tags.get("mtb:scale"))
        features.append({
            "type": "Feature",
            "properties": {
                "osm_id": el["id"],
                "name": tags.get("name"),
                "highway": tags.get("highway"),
                "surface": _surface_category(tags.get("highway"), tags.get("surface"), tags.get("tracktype"), tags.get("name")),
                "mtb_scale": scale,
                "difficulty": diff["rating"].lower(),
                "difficulty_name": diff["name"],
                "difficulty_color": diff["color"],
                "sac_scale": tags.get("sac_scale"),
                "operator": tags.get("operator"),
                "source": "OpenStreetMap (Overpass)"
            },
            "geometry": {"type": "LineString", "coordinates": coords}
        })

    return {"type": "FeatureCollection", "features": features}


def get_otm_trail_details(osm_way_id: int) -> Optional[Dict[str, Any]]:
    """OSM metadata for one way from the local import, or None when it isn't there."""
    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT osm_id, name, highway, surface, tracktype, mtb_scale, sac_scale,
                           bicycle, foot, access, length_m, ST_AsGeoJSON(geom) as geom_json
                    FROM edges
                    WHERE osm_id = %s;
                    """,
                    (osm_way_id,)
                )
                row = cur.fetchone()
    except Exception as e:
        logger.warning(f"Error querying trail details for {osm_way_id}: {e}")
        return None
    if not row:
        return None
    scale, diff = _difficulty(row.get("mtb_scale"))
    return {
        "osm_id": row["osm_id"],
        "name": row["name"] or resolve_osm_trail_name(row["osm_id"]),
        "highway": row.get("highway"),
        "surface": _surface_category(row.get("highway"), row.get("surface"), row.get("tracktype"), row.get("name")),
        "mtb_scale": scale,
        "difficulty": diff,
        "sac_scale": row.get("sac_scale"),
        "bicycle": row.get("bicycle"),
        "foot": row.get("foot"),
        "access": row.get("access"),
        "length_miles": round(row["length_m"] / 1609.34, 2) if row.get("length_m") else None,
        "geometry": json.loads(row["geom_json"]) if row.get("geom_json") else None
    }
