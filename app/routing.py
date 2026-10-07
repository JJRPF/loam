import httpx
from typing import Dict, Any, List, Tuple
from app.config import settings
from app.models import RouteRequest, RouteResponse, SurfaceSegment, SportProfile

METERS_TO_MILES = 0.000621371192
METERS_TO_FEET = 3.280839895

def classify_surface(road_class: str, surface: str, track_type: str) -> str:
    """Classifies an edge segment into one of: singletrack, doubletrack, gravel, paved."""
    rc = (road_class or "").lower()
    s = (surface or "").lower()
    tt = (track_type or "").lower()
    
    if rc in ("path", "bridleway") or (rc == "footway" and s in ("ground", "dirt", "grass")):
        return "singletrack"
    
    if rc == "track":
        if tt in ("grade2", "grade3", "grade4", "grade5") or s in ("ground", "dirt", "grass", "earth"):
            return "doubletrack"
        elif tt == "grade1" or s in ("gravel", "fine_gravel", "compacted", "crushed_limestone"):
            return "gravel"
        return "doubletrack"
        
    if s in ("gravel", "fine_gravel", "compacted", "dirt", "earth", "ground", "sand", "pebblestone"):
        return "gravel"
        
    if s in ("asphalt", "paved", "concrete", "paving_stones") or rc in ("primary", "secondary", "tertiary", "residential", "service", "unclassified"):
        return "paved"
        
    return "unpaved"

def decode_points(points_data: Any) -> List[List[float]]:
    """Decodes coordinates returned from GraphHopper (GeoJSON or polyline)."""
    if isinstance(points_data, dict) and "coordinates" in points_data:
        return points_data["coordinates"]
    elif isinstance(points_data, list):
        return points_data
    return []

async def fetch_route(req: RouteRequest) -> RouteResponse:
    points_param = [f"{req.start.lat},{req.start.lon}"]
    if req.waypoints:
        for wp in req.waypoints:
            points_param.append(f"{wp.lat},{wp.lon}")
    points_param.append(f"{req.end.lat},{req.end.lon}")

    # Map sport profile
    gh_profile = req.profile.value
    if gh_profile not in ("mtb", "bike", "foot"):
        gh_profile = "mtb"

    params = {
        "point": points_param,
        "profile": gh_profile,
        "points_encoded": "false",
        "details": ["surface", "road_class", "track_type"],
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(f"{settings.graphhopper_url}/route", params=params)
        if resp.status_code != 200:
            raise RuntimeError(f"GraphHopper routing failed ({resp.status_code}): {resp.text}")
        data = resp.json()

    path = data["paths"][0]
    distance_m = path.get("distance", 0.0)
    time_ms = path.get("time", 0.0)
    ascend_m = path.get("ascend", 0.0)
    descend_m = path.get("descend", 0.0)
    bbox = path.get("bbox", [-72.0, 43.0, -71.0, 44.0])
    points = decode_points(path.get("points", {}))

    # Calculate elevation from 3D points if ascend/descend are zero
    if (ascend_m == 0.0 and descend_m == 0.0) and points and len(points[0]) > 2:
        calc_ascend = 0.0
        calc_descend = 0.0
        for i in range(1, len(points)):
            ele_diff = points[i][2] - points[i - 1][2]
            if ele_diff > 0:
                calc_ascend += ele_diff
            else:
                calc_descend += abs(ele_diff)
        ascend_m = calc_ascend
        descend_m = calc_descend

    # Process surface details
    details = path.get("details", {})
    surface_details = details.get("surface", [])
    road_class_details = details.get("road_class", [])
    track_type_details = details.get("track_type", [])

    total_pts = len(points)
    # Map index to classification
    pt_surface_types = ["unpaved"] * max(total_pts, 1)

    # Helper dicts
    surface_map = {}
    for s_start, s_end, val in surface_details:
        for idx in range(s_start, min(s_end, total_pts)):
            surface_map[idx] = val

    rc_map = {}
    for r_start, r_end, val in road_class_details:
        for idx in range(r_start, min(r_end, total_pts)):
            rc_map[idx] = val

    tt_map = {}
    for t_start, t_end, val in track_type_details:
        for idx in range(t_start, min(t_end, total_pts)):
            tt_map[idx] = val

    surface_strip: List[SurfaceSegment] = []
    category_counts: Dict[str, int] = {
        "singletrack": 0,
        "doubletrack": 0,
        "gravel": 0,
        "paved": 0,
    }

    current_cat = None
    seg_start = 0

    for i in range(total_pts):
        rc = rc_map.get(i, "")
        s = surface_map.get(i, "")
        tt = tt_map.get(i, "")
        cat = classify_surface(rc, s, tt)
        
        category_counts[cat] = category_counts.get(cat, 0) + 1

        if current_cat is None:
            current_cat = cat
            seg_start = i
        elif cat != current_cat:
            surface_strip.append(SurfaceSegment(
                start_index=seg_start,
                end_index=i,
                surface_type=current_cat,
                raw_surface=surface_map.get(seg_start),
                raw_road_class=rc_map.get(seg_start)
            ))
            current_cat = cat
            seg_start = i

    if current_cat is not None:
        surface_strip.append(SurfaceSegment(
            start_index=seg_start,
            end_index=total_pts,
            surface_type=current_cat,
            raw_surface=surface_map.get(seg_start),
            raw_road_class=rc_map.get(seg_start)
        ))

    # Calculate breakdown percentages
    breakdown = {}
    pts_divisor = max(total_pts, 1)
    for cat, count in category_counts.items():
        pct = round((count / pts_divisor) * 100.0, 1)
        if pct > 0:
            breakdown[cat] = pct

    return RouteResponse(
        distance_miles=round(distance_m * METERS_TO_MILES, 2),
        duration_minutes=round((time_ms / 1000.0) / 60.0, 1),
        elevation_gain_ft=round(ascend_m * METERS_TO_FEET, 0),
        elevation_loss_ft=round(descend_m * METERS_TO_FEET, 0),
        surface_breakdown=breakdown,
        surface_strip=surface_strip,
        coordinates=points,
        bbox=bbox,
        warnings=[],
        heat_score=None
    )
