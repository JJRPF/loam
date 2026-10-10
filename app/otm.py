import logging
import json
import re
import httpx
from typing import Dict, Any, List, Optional, Tuple
from app.db import get_connection, resolve_osm_trail_name
from psycopg2.extras import RealDictCursor

logger = logging.getLogger(__name__)

# Overpass API endpoint for live OpenTrailMap queries
OVERPASS_API_URL = "https://overpass-api.de/api/interpreter"

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

# Curated regional fallback OTM trails for Bear Brook, Bow Town Forest, and NH networks
FALLBACK_OTM_TRAILS = [
    {
        "osm_id": 220551350,
        "name": "Bear Brook Trail",
        "highway": "path",
        "surface": "singletrack",
        "mtb_scale": 1,
        "sac_scale": "hiking",
        "operator": "NH State Parks / NEMBA",
        "length_miles": 1.45,
        "geometry": [[-71.3524, 43.1305], [-71.3550, 43.1320], [-71.3580, 43.1340], [-71.3610, 43.1360]]
    },
    {
        "osm_id": 220551352,
        "name": "Bobcat Trail",
        "highway": "path",
        "surface": "singletrack",
        "mtb_scale": 1,
        "sac_scale": "mountain_hiking",
        "operator": "NH State Parks / NEMBA",
        "length_miles": 0.85,
        "geometry": [[-71.3524, 43.1305], [-71.3558, 43.1296], [-71.3583, 43.1308], [-71.3618, 43.1321]]
    },
    {
        "osm_id": 247358974,
        "name": "Little Bear Trail",
        "highway": "path",
        "surface": "singletrack",
        "mtb_scale": 0,
        "sac_scale": "hiking",
        "operator": "NH State Parks / NEMBA",
        "length_miles": 0.72,
        "geometry": [[-71.3618, 43.1321], [-71.3640, 43.1350], [-71.3658, 43.1380], [-71.3662, 43.1410]]
    },
    {
        "osm_id": 220551345,
        "name": "Salt Lick Trail",
        "highway": "path",
        "surface": "singletrack",
        "mtb_scale": 1,
        "sac_scale": "hiking",
        "operator": "NH State Parks",
        "length_miles": 0.95,
        "geometry": [[-71.3662, 43.1410], [-71.3645, 43.1435], [-71.3610, 43.1450], [-71.3570, 43.1440]]
    },
    {
        "osm_id": 247358962,
        "name": "Pitch Pine Trail",
        "highway": "path",
        "surface": "dirt",
        "mtb_scale": 1,
        "sac_scale": "hiking",
        "operator": "NH State Parks",
        "length_miles": 0.88,
        "geometry": [[-71.3570, 43.1440], [-71.3540, 43.1420], [-71.3510, 43.1390], [-71.3500, 43.1350]]
    },
    {
        "osm_id": 999202,
        "name": "Boulder Trail",
        "highway": "path",
        "surface": "singletrack",
        "mtb_scale": 2,
        "sac_scale": "demanding_mountain_hiking",
        "operator": "NH State Parks / NEMBA",
        "length_miles": 1.10,
        "geometry": [[-71.3500, 43.1350], [-71.3480, 43.1330], [-71.3490, 43.1310], [-71.3524, 43.1305]]
    },
    {
        "osm_id": 999101,
        "name": "Boundary Trail",
        "highway": "path",
        "surface": "doubletrack",
        "mtb_scale": 0,
        "sac_scale": "hiking",
        "operator": "NH State Parks",
        "length_miles": 1.45,
        "geometry": [[-71.3658, 43.1380], [-71.3700, 43.1420], [-71.3720, 43.1470], [-71.3680, 43.1500]]
    },
    {
        "osm_id": 220551370,
        "name": "Cascade Trail",
        "highway": "path",
        "surface": "singletrack",
        "mtb_scale": 1,
        "sac_scale": "mountain_hiking",
        "operator": "NH State Parks",
        "length_miles": 0.65,
        "geometry": [[-71.3540, 43.1420], [-71.3560, 43.1460], [-71.3590, 43.1490], [-71.3620, 43.1510]]
    },
    {
        "osm_id": 741060716,
        "name": "Podunk Road",
        "highway": "track",
        "surface": "gravel",
        "mtb_scale": 0,
        "sac_scale": "hiking",
        "operator": "Town of Allenstown",
        "length_miles": 2.10,
        "geometry": [[-71.3524, 43.1305], [-71.3550, 43.1360], [-71.3570, 43.1440], [-71.3600, 43.1520]]
    },
    # Bow Town Forest Curated Trail Network
    {
        "osm_id": 289829667,
        "name": "Robertson Trail",
        "highway": "path",
        "surface": "singletrack",
        "mtb_scale": 1,
        "sac_scale": "hiking",
        "operator": "Bow Town Forest",
        "length_miles": 1.10,
        "geometry": [[-71.53038, 43.15331], [-71.53043, 43.15315], [-71.53047, 43.15299], [-71.5306, 43.1524], [-71.5308, 43.1518]]
    },
    {
        "osm_id": 289829681,
        "name": "Single Circuit Trail",
        "highway": "path",
        "surface": "singletrack",
        "mtb_scale": 2,
        "sac_scale": "mountain_hiking",
        "operator": "Bow Town Forest",
        "length_miles": 1.40,
        "geometry": [[-71.51359, 43.14735], [-71.5141, 43.14693], [-71.51422, 43.14683], [-71.5148, 43.1462], [-71.5155, 43.1455]]
    },
    {
        "osm_id": 289829857,
        "name": "Boulder Trail",
        "highway": "path",
        "surface": "singletrack",
        "mtb_scale": 1,
        "sac_scale": "hiking",
        "operator": "Bow Town Forest",
        "length_miles": 0.90,
        "geometry": [[-71.51832, 43.13684], [-71.51849, 43.13684], [-71.51851, 43.13684], [-71.5190, 43.1369], [-71.5195, 43.1371]]
    },
    {
        "osm_id": 302693899,
        "name": "Robinson's Crest Trail",
        "highway": "path",
        "surface": "singletrack",
        "mtb_scale": 2,
        "sac_scale": "mountain_hiking",
        "operator": "Bow Town Forest",
        "length_miles": 1.25,
        "geometry": [[-71.51832, 43.13684], [-71.51826, 43.13684], [-71.51817, 43.13687], [-71.5178, 43.1372], [-71.5172, 43.1376]]
    },
    {
        "osm_id": 339654248,
        "name": "Mossy Trail",
        "highway": "path",
        "surface": "singletrack",
        "mtb_scale": 1,
        "sac_scale": "hiking",
        "operator": "Bow Town Forest",
        "length_miles": 1.35,
        "geometry": [[-71.52417, 43.14533], [-71.52407, 43.14533], [-71.52396, 43.14536], [-71.5235, 43.1455], [-71.5230, 43.1458]]
    },
    {
        "osm_id": 18854090,
        "name": "Branch Londonderry Turnpike East",
        "highway": "track",
        "surface": "doubletrack",
        "mtb_scale": 0,
        "sac_scale": "hiking",
        "operator": "Bow Town Forest",
        "length_miles": 1.80,
        "geometry": [[-71.51599, 43.1221], [-71.51611, 43.12208], [-71.51619, 43.12211], [-71.5170, 43.1225], [-71.5180, 43.1230]]
    }
]


async def fetch_otm_trails_by_bbox(
    min_lat: float,
    min_lon: float,
    max_lat: float,
    max_lon: float,
    sport: Optional[str] = "mtb",
    limit: int = 150
) -> Dict[str, Any]:
    """
    Fetches OpenTrailMap / OSM trails within a bounding box.
    Order of precedence:
    1. Local PostGIS database (high speed, offline capable).
    2. Overpass API (live updates if database is sparse in region).
    3. Curated fallback trails.
    """
    features = []

    # 1. Query local PostGIS database edges
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
                      AND (highway IN ('path', 'track', 'footway', 'bridleway', 'cycleway') OR surface IN ('dirt', 'ground', 'gravel', 'compacted'))
                    ORDER BY length_m DESC
                    LIMIT %s;
                    """,
                    (min_lon, min_lat, max_lon, max_lat, limit)
                )
                rows = cur.fetchall()
                for r in rows:
                    gj = r.get("geom_json")
                    if not gj:
                        continue
                    geom = json.loads(gj)
                    trail_name = r["name"] or resolve_osm_trail_name(r["osm_id"])
                    mtb_s = r.get("mtb_scale") if r.get("mtb_scale") is not None else 1
                    difficulty_info = MTB_SCALE_DESCRIPTIONS.get(mtb_s, MTB_SCALE_DESCRIPTIONS[1])
                    length_mi = round((r.get("length_m") or 0.0) / 1609.34, 2)

                    hw = (r.get("highway") or "path").lower()
                    raw_surf = r.get("surface")
                    ROAD_CLASSES = {"primary", "secondary", "tertiary", "residential", "service", "unclassified", "living_street", "motorway", "trunk", "road"}
                    if hw in ROAD_CLASSES:
                        surf = "paved" if not raw_surf or raw_surf in ("asphalt", "paved", "concrete") else "gravel"
                    elif raw_surf:
                        surf = raw_surf
                    elif hw in ("path", "bridleway"):
                        surf = "singletrack"
                    elif hw == "track":
                        surf = "doubletrack"
                    else:
                        surf = "singletrack"

                    features.append({
                        "type": "Feature",
                        "properties": {
                            "osm_id": r["osm_id"],
                            "name": trail_name,
                            "highway": hw,
                            "surface": surf,
                            "mtb_scale": mtb_s,
                            "difficulty": difficulty_info["rating"].lower(),
                            "difficulty_name": difficulty_info["name"],
                            "difficulty_color": difficulty_info["color"],
                            "sac_scale": r.get("sac_scale") or "hiking",
                            "length_miles": length_mi,
                            "source": "OpenTrailMap / PostGIS"
                        },
                        "geometry": geom
                    })
    except Exception as db_err:
        logger.warning(f"Error querying PostGIS edges for OTM trails: {db_err}")

    # 2. If database produced results, return immediately
    if len(features) >= 5:
        return {
            "type": "FeatureCollection",
            "features": features
        }

    # 3. Live Overpass API query if online and local database is sparse
    try:
        overpass_query = f"""
        [out:json][timeout:12];
        (
          way["highway"~"path|track|footway|cycleway"]({min_lat},{min_lon},{max_lat},{max_lon});
        );
        out body geom;
        """
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.post(
                OVERPASS_API_URL,
                data={"data": overpass_query},
                headers={"User-Agent": "LoamTrailApp/1.0"}
            )
            if resp.status_code == 200:
                data = resp.json()
                for el in data.get("elements", []):
                    if el.get("type") == "way" and el.get("geometry"):
                        tags = el.get("tags", {})
                        coords = [[pt["lon"], pt["lat"]] for pt in el["geometry"]]
                        if len(coords) < 2:
                            continue

                        wid = el["id"]
                        name = tags.get("name") or resolve_osm_trail_name(wid)
                        hw = (tags.get("highway") or "path").lower()
                        raw_surf = tags.get("surface")
                        ROAD_CLASSES = {"primary", "secondary", "tertiary", "residential", "service", "unclassified", "living_street", "motorway", "trunk", "road"}
                        if hw in ROAD_CLASSES:
                            surf = "paved" if not raw_surf or raw_surf in ("asphalt", "paved", "concrete") else "gravel"
                        elif raw_surf:
                            surf = raw_surf
                        elif hw in ("path", "bridleway"):
                            surf = "singletrack"
                        elif hw == "track":
                            surf = "doubletrack"
                        else:
                            surf = "singletrack"

                        mtb_s_raw = tags.get("mtb:scale")
                        try:
                            mtb_s = int(mtb_s_raw) if mtb_s_raw else 1
                        except Exception:
                            mtb_s = 1

                        diff_info = MTB_SCALE_DESCRIPTIONS.get(mtb_s, MTB_SCALE_DESCRIPTIONS[1])
                        features.append({
                            "type": "Feature",
                            "properties": {
                                "osm_id": wid,
                                "name": name,
                                "highway": hw,
                                "surface": surf,
                                "mtb_scale": mtb_s,
                                "difficulty": diff_info["rating"].lower(),
                                "difficulty_name": diff_info["name"],
                                "difficulty_color": diff_info["color"],
                                "sac_scale": tags.get("sac_scale", "hiking"),
                                "operator": tags.get("operator", "Local Land Manager"),
                                "source": "OpenTrailMap Live"
                            },
                            "geometry": {
                                "type": "LineString",
                                "coordinates": coords
                            }
                        })
    except Exception as op_err:
        logger.debug(f"Overpass live query skipped: {op_err}")

    # 4. Fallback to curated OTM trail set if neither database nor live Overpass yielded results
    if not features:
        # Prioritize matching bounding box
        matched_curated = []
        for trail in FALLBACK_OTM_TRAILS:
            coords = trail["geometry"]
            in_bbox = any(
                (min_lat - 0.05 <= pt[1] <= max_lat + 0.05) and (min_lon - 0.05 <= pt[0] <= max_lon + 0.05)
                for pt in coords
            )
            if in_bbox:
                matched_curated.append(trail)

        pool = matched_curated if matched_curated else FALLBACK_OTM_TRAILS
        for trail in pool:
            diff_info = MTB_SCALE_DESCRIPTIONS.get(trail["mtb_scale"], MTB_SCALE_DESCRIPTIONS[1])
            features.append({
                "type": "Feature",
                "properties": {
                    "osm_id": trail["osm_id"],
                    "name": trail["name"],
                    "highway": trail["highway"],
                    "surface": trail["surface"],
                    "mtb_scale": trail["mtb_scale"],
                    "difficulty": diff_info["rating"].lower(),
                    "difficulty_name": diff_info["name"],
                    "difficulty_color": diff_info["color"],
                    "sac_scale": trail["sac_scale"],
                    "operator": trail["operator"],
                    "length_miles": trail["length_miles"],
                    "source": "OpenTrailMap Curated"
                },
                "geometry": {
                    "type": "LineString",
                    "coordinates": trail["geometry"]
                }
            })

    return {
        "type": "FeatureCollection",
        "features": features
    }


def get_otm_trail_details(osm_way_id: int) -> Dict[str, Any]:
    """
    Returns detailed OpenTrailMap metadata for a specific OSM way ID.
    """
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
                if row:
                    mtb_s = row.get("mtb_scale") if row.get("mtb_scale") is not None else 1
                    diff_info = MTB_SCALE_DESCRIPTIONS.get(mtb_s, MTB_SCALE_DESCRIPTIONS[1])
                    t_name = row["name"] or resolve_osm_trail_name(row["osm_id"])
                    hw = (row.get("highway") or "path").lower()
                    raw_surf = row.get("surface")
                    ROAD_CLASSES = {"primary", "secondary", "tertiary", "residential", "service", "unclassified", "living_street", "motorway", "trunk", "road"}
                    ROAD_NAME_REGEX = re.compile(r'\b(road|rd|drive|dr|lane|ln|street|st|avenue|ave|boulevard|blvd|highway|hwy|turnpike|pike)\b', re.IGNORECASE)
                    is_road = hw in ROAD_CLASSES or bool(ROAD_NAME_REGEX.search(t_name))
                    if is_road:
                        surf = "paved" if not raw_surf or raw_surf in ("asphalt", "paved", "concrete") else "gravel"
                        hw = "road"
                    elif raw_surf:
                        surf = raw_surf
                    elif hw in ("path", "bridleway"):
                        surf = "singletrack"
                    elif hw == "track":
                        surf = "doubletrack"
                    else:
                        surf = "singletrack"

                    return {
                        "osm_id": row["osm_id"],
                        "name": t_name,
                        "highway": hw,
                        "surface": surf,
                        "mtb_scale": mtb_s,
                        "difficulty": diff_info,
                        "sac_scale": row.get("sac_scale") or "hiking",
                        "bicycle": row.get("bicycle") or "yes",
                        "foot": row.get("foot") or "yes",
                        "length_miles": round((row.get("length_m") or 0.0) / 1609.34, 2),
                        "geometry": json.loads(row["geom_json"]) if row.get("geom_json") else None
                    }
    except Exception as e:
        logger.warning(f"Error querying trail details for {osm_way_id}: {e}")

    # Fallback lookup
    for t in FALLBACK_OTM_TRAILS:
        if t["osm_id"] == osm_way_id:
            diff_info = MTB_SCALE_DESCRIPTIONS.get(t["mtb_scale"], MTB_SCALE_DESCRIPTIONS[1])
            return {
                "osm_id": t["osm_id"],
                "name": t["name"],
                "highway": t["highway"],
                "surface": t["surface"],
                "mtb_scale": t["mtb_scale"],
                "difficulty": diff_info,
                "sac_scale": t["sac_scale"],
                "operator": t["operator"],
                "length_miles": t["length_miles"],
                "geometry": {
                    "type": "LineString",
                    "coordinates": t["geometry"]
                }
            }

    name = resolve_osm_trail_name(osm_way_id)
    ROAD_NAME_REGEX = re.compile(r'\b(road|rd|drive|dr|lane|ln|street|st|avenue|ave|boulevard|blvd|highway|hwy|turnpike|pike)\b', re.IGNORECASE)
    is_road = bool(ROAD_NAME_REGEX.search(name))
    diff_info = MTB_SCALE_DESCRIPTIONS[0 if is_road else 1]
    return {
        "osm_id": osm_way_id,
        "name": name,
        "highway": "road" if is_road else "path",
        "surface": "paved" if is_road else "singletrack",
        "mtb_scale": 0 if is_road else 1,
        "difficulty": diff_info,
        "sac_scale": "hiking",
        "length_miles": 0.75,
        "geometry": None
    }
