"""
Corridor-Penalized Loop Generator & Retrace Analysis for Loam.
Enforces true loop candidate generation by routing outbound to an anchor waypoint,
buffering the outbound corridor, and penalizing that corridor for the return leg
via GraphHopper custom models. Also measures and isolates retraced segments for UI highlighting.
"""
import math
from typing import Dict, Any, List, Tuple, Optional
import httpx
from shapely.geometry import LineString, mapping

from app.config import settings
from app.scoring import haversine_m, calculate_repetition_ratio

METERS_TO_MILES = 0.000621371192


def find_retraced_segments(
    coordinates: List[List[float]],
    osm_way_details: Optional[List[List[Any]]] = None,
    proximity_m: float = 25.0
) -> List[List[List[float]]]:
    """
    Identifies coordinate segments where the route traverses in reverse over an earlier section.
    Returns a list of LineString segments [[lon1, lat1], [lon2, lat2]] for red highlighting on MapView.
    """
    if not coordinates or len(coordinates) < 4:
        return []

    retraced_lines: List[List[List[float]]] = []
    num_pts = len(coordinates)

    # 1. Via OSM way IDs if present
    if osm_way_details:
        way_visits: Dict[int, List[Tuple[int, int]]] = {}
        for item in osm_way_details:
            if len(item) >= 3:
                s_idx, e_idx, wid = int(item[0]), int(item[1]), int(item[2])
                way_visits.setdefault(wid, []).append((s_idx, e_idx))

        for wid, intervals in way_visits.items():
            if len(intervals) >= 2:
                # This way was traversed multiple times (retrace)
                for s_idx, e_idx in intervals[1:]:
                    for k in range(s_idx, min(e_idx, num_pts - 1)):
                        retraced_lines.append([coordinates[k], coordinates[k + 1]])

        if retraced_lines:
            return retraced_lines

    # 2. Geometric backtrack detection
    half = num_pts // 2
    for i in range(half, num_pts - 1):
        p1 = coordinates[i]
        p2 = coordinates[i + 1]
        mid_i = [(p1[0] + p2[0]) / 2.0, (p1[1] + p2[1]) / 2.0]
        v_i = (p2[0] - p1[0], p2[1] - p1[1])
        mag_i = math.hypot(v_i[0], v_i[1])
        if mag_i == 0:
            continue

        for j in range(0, half):
            q1 = coordinates[j]
            q2 = coordinates[j + 1]
            mid_j = [(q1[0] + q2[0]) / 2.0, (q1[1] + q2[1]) / 2.0]
            if haversine_m(mid_i, mid_j) <= proximity_m:
                v_j = (q2[0] - q1[0], q2[1] - q1[1])
                mag_j = math.hypot(v_j[0], v_j[1])
                if mag_j > 0:
                    dot = (v_i[0] * v_j[0] + v_i[1] * v_j[1]) / (mag_i * mag_j)
                    if dot < -0.5:  # Opposing direction = retraced out-and-back section
                        retraced_lines.append([p1, p2])
                        break

    return retraced_lines


def build_corridor_custom_model(
    outbound_coords: List[List[float]],
    base_custom_model: Optional[Dict[str, Any]] = None,
    buffer_deg: float = 0.00085  # ~75-95 meters buffer
) -> Optional[Dict[str, Any]]:
    """
    Builds a GraphHopper custom model with an area polygon enclosing the outbound corridor.
    Excludes the first and last 60m so start and turnaround points can connect to alternatives.
    """
    if len(outbound_coords) < 4:
        return base_custom_model

    # Exclude immediate start and end connection zones
    skip = max(1, min(len(outbound_coords) // 6, 6))
    sub_line = outbound_coords[skip:-skip] if len(outbound_coords) > 2 * skip else outbound_coords

    try:
        line_geom = LineString(sub_line)
        buffered_poly = line_geom.buffer(buffer_deg, cap_style=2)
        poly_geojson = mapping(buffered_poly)
        poly_coords = poly_geojson.get("coordinates", [])
    except Exception:
        return base_custom_model

    if not poly_coords:
        return base_custom_model

    cm: Dict[str, Any] = {
        "areas": {
            "type": "FeatureCollection",
            "features": [{
                "id": "outbound_corridor",
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": poly_coords
                }
            }]
        },
        "priority": [
            {
                "if": "in_outbound_corridor",
                "multiply_by": "0.01"  # Heavy 99% penalty forces non-retracing return paths
            }
        ]
    }

    # Merge base rules if provided (e.g. paved road avoidance, singletrack boost)
    if base_custom_model and "priority" in base_custom_model:
        for rule in base_custom_model["priority"]:
            cm["priority"].append(rule)

    return cm


async def generate_corridor_loop_candidate(
    client: httpx.AsyncClient,
    start_lat: float,
    start_lon: float,
    dest_lat: float,
    dest_lon: float,
    gh_profile: str,
    base_custom_model: Optional[Dict[str, Any]] = None
) -> Optional[Dict[str, Any]]:
    """
    Queries GraphHopper for an outbound leg to (dest_lat, dest_lon), then routes back
    with the outbound corridor penalized. Stitches the two legs into a single candidate path.
    """
    start_pt = [start_lon, start_lat]
    dest_pt = [dest_lon, dest_lat]

    # 1. Leg 1: Outbound
    try:
        body1 = {
            "points": [start_pt, dest_pt],
            "profile": gh_profile,
            "points_encoded": False,
            "details": ["surface", "road_class", "track_type", "osm_way_id", "street_name"]
        }
        if base_custom_model:
            body1["custom_model"] = base_custom_model

        resp1 = await client.post(f"{settings.graphhopper_url}/route", json=body1)
        if resp1.status_code != 200:
            return None
        data1 = resp1.json()
        if not data1.get("paths"):
            return None
        p1 = data1["paths"][0]
        coords1 = p1.get("points", {}).get("coordinates", [])
        if len(coords1) < 2:
            return None
    except Exception:
        return None

    # 2. Leg 2: Inbound with outbound corridor penalized
    corridor_model = build_corridor_custom_model(coords1, base_custom_model)

    try:
        body2 = {
            "points": [dest_pt, start_pt],
            "profile": gh_profile,
            "points_encoded": False,
            "details": ["surface", "road_class", "track_type", "osm_way_id", "street_name"],
            "custom_model": corridor_model
        }
        resp2 = await client.post(f"{settings.graphhopper_url}/route", json=body2)
        if resp2.status_code != 200:
            return None
        data2 = resp2.json()
        if not data2.get("paths"):
            return None
        p2 = data2["paths"][0]
        coords2 = p2.get("points", {}).get("coordinates", [])
        if len(coords2) < 2:
            return None
    except Exception:
        return None

    # 3. Stitch together Leg 1 + Leg 2
    full_coords = coords1 + coords2[1:]
    total_dist_m = float(p1.get("distance", 0.0)) + float(p2.get("distance", 0.0))
    total_ascend_m = float(p1.get("ascend", 0.0)) + float(p2.get("ascend", 0.0))
    total_descend_m = float(p1.get("descend", 0.0)) + float(p2.get("descend", 0.0))

    # Stitch details with index offsets
    offset = len(coords1) - 1
    details1 = p1.get("details", {})
    details2 = p2.get("details", {})
    stitched_details: Dict[str, List[Any]] = {}

    for k in ["surface", "road_class", "track_type", "osm_way_id", "street_name"]:
        list1 = details1.get(k, []) or []
        list2 = details2.get(k, []) or []
        shifted2 = [[it[0] + offset, it[1] + offset, it[2]] for it in list2 if len(it) >= 3]
        stitched_details[k] = list1 + shifted2

    rep_ratio = calculate_repetition_ratio(full_coords, stitched_details.get("osm_way_id"))
    retraced_miles = round((total_dist_m * METERS_TO_MILES) * rep_ratio, 2)
    retraced_lines = find_retraced_segments(full_coords, stitched_details.get("osm_way_id"))

    stitched_path = {
        "distance": total_dist_m,
        "ascend": total_ascend_m,
        "descend": total_descend_m,
        "points": {"type": "LineString", "coordinates": full_coords},
        "bbox": [
            min(p[0] for p in full_coords),
            min(p[1] for p in full_coords),
            max(p[0] for p in full_coords),
            max(p[1] for p in full_coords)
        ],
        "details": stitched_details,
        "repetition_ratio": rep_ratio,
        "retraced_miles": retraced_miles,
        "retraced_coordinates": retraced_lines
    }

    return stitched_path
