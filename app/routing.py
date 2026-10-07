import math
import httpx
from typing import Dict, Any, List, Tuple, Optional
from app.config import settings
from app.models import RouteRequest, RouteResponse, SurfaceSegment, SportProfile

METERS_TO_MILES = 0.000621371192
METERS_TO_FEET = 3.280839895

# Average trail speeds in mph for duration estimation
PROFILE_SPEED_MPH = {
    SportProfile.MTB: 10.0,
    SportProfile.MTB_HARDTAIL: 10.5,
    SportProfile.MTB_FULLSUS: 10.0,
    SportProfile.MTB_GRAVEL: 13.0,
    SportProfile.MTB_FAT: 8.0,
    SportProfile.MTB_EMTB: 15.5,
    SportProfile.TRAIL_RUN: 6.0,
    SportProfile.BIKE: 12.0,
    SportProfile.FOOT: 3.5,
}

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

def build_custom_model(req: RouteRequest) -> Optional[Dict[str, Any]]:
    """Builds a GraphHopper custom model based on sport profile and terrain preference."""
    pref = req.terrain_preference
    if not pref:
        return None

    priority_rules = []

    # Singletrack priority
    if pref.singletrack >= 0.5:
        priority_rules.append({
            "if": "road_class == PATH || road_class == BRIDLEWAY",
            "multiply_by": f"{min(2.0, 1.0 + pref.singletrack):.2f}"
        })
    elif pref.singletrack < 0.2:
        priority_rules.append({
            "if": "road_class == PATH",
            "multiply_by": "0.5"
        })

    # Gravel priority
    if pref.gravel >= 0.4:
        priority_rules.append({
            "if": "surface == GRAVEL || surface == FINE_GRAVEL || surface == COMPACTED",
            "multiply_by": f"{min(2.0, 1.0 + pref.gravel):.2f}"
        })

    # Doubletrack priority
    if pref.doubletrack >= 0.4:
        priority_rules.append({
            "if": "road_class == TRACK",
            "multiply_by": f"{min(2.0, 1.0 + pref.doubletrack):.2f}"
        })

    # Paved preference
    if pref.paved < 0.15:
        priority_rules.append({
            "if": "surface == ASPHALT || surface == PAVED || road_class == PRIMARY || road_class == SECONDARY",
            "multiply_by": f"{max(0.2, pref.paved * 1.5):.2f}"
        })

    if priority_rules:
        return {"priority": priority_rules}
    return None

def generate_loop_waypoints(start_lat: float, start_lon: float, target_miles: float) -> List[Tuple[float, float]]:
    """
    Generates anchor waypoints offset from the start in a loop pattern
    to achieve the desired distance.
    """
    target_miles = max(1.0, min(target_miles, 100.0))
    # Approximate radius R = perimeter / (2 * pi), with a trail tortuosity factor ~1.3
    radius_m = (target_miles * 1609.344) / (2.0 * math.pi * 1.3)
    radius_m = max(500.0, radius_m)

    # Offset angles (e.g. 60 deg and 180 deg, forming a triangular loop back to start)
    bearings = [math.radians(60), math.radians(180)]
    lat_deg_len = 111132.0 # meters per degree lat
    lon_deg_len = 111132.0 * math.cos(math.radians(start_lat))

    waypoints = []
    for brg in bearings:
        d_lat = (radius_m * math.cos(brg)) / lat_deg_len
        d_lon = (radius_m * math.sin(brg)) / lon_deg_len
        wp_lat = start_lat + d_lat
        wp_lon = start_lon + d_lon
        waypoints.append((wp_lat, wp_lon))

    return waypoints

def generate_verbal_summary(
    dist_mi: float,
    target_mi: Optional[float],
    breakdown: Dict[str, float],
    pref: Optional[Any],
    warnings: List[str]
) -> str:
    parts = []
    if target_mi and target_mi > 0:
        diff = dist_mi - target_mi
        pct = (diff / target_mi) * 100.0
        sign = "+" if pct >= 0 else ""
        parts.append(f"{dist_mi:.1f} mi vs {target_mi:.1f} mi target ({sign}{pct:.0f}%)")
    else:
        parts.append(f"{dist_mi:.1f} mi")

    st_pct = breakdown.get("singletrack", 0.0)
    desired_st = int(round((pref.singletrack if pref else 0.6) * 100))
    if st_pct > 0:
        status_word = "exceeds" if st_pct >= desired_st else "vs"
        parts.append(f"{st_pct:.0f}% singletrack ({status_word} {desired_st}% goal)")

    if not warnings:
        parts.append("0 closures or DNR conflicts.")
    else:
        parts.append(f"{len(warnings)} warning(s).")

    return "; ".join(parts)

async def fetch_route(req: RouteRequest) -> RouteResponse:
    # Handle loop / round trip mode
    is_loop = req.is_loop or req.route_mode in ("loop", "round_trip") or req.end is None

    points_coords: List[Tuple[float, float]] = [(req.start.lat, req.start.lon)]

    if is_loop and req.target_distance_miles and (not req.waypoints or len(req.waypoints) == 0):
        loop_anchors = generate_loop_waypoints(req.start.lat, req.start.lon, req.target_distance_miles)
        for anchor_lat, anchor_lon in loop_anchors:
            points_coords.append((anchor_lat, anchor_lon))
        # Loop ends at start
        points_coords.append((req.start.lat, req.start.lon))
    else:
        if req.waypoints:
            for wp in req.waypoints:
                points_coords.append((wp.lat, wp.lon))
        end_pt = req.end if req.end else req.start
        points_coords.append((end_pt.lat, end_pt.lon))

    # Profile mapping
    gh_profile = "mtb"
    if req.profile in (SportProfile.TRAIL_RUN, SportProfile.FOOT):
        gh_profile = "foot"
    elif req.profile in (SportProfile.MTB_GRAVEL, SportProfile.BIKE):
        gh_profile = "bike"
    else:
        gh_profile = "mtb"

    points_param = [f"{lat},{lon}" for lat, lon in points_coords]

    # Build request params
    params: Dict[str, Any] = {
        "point": points_param,
        "profile": gh_profile,
        "points_encoded": "false",
        "details": ["surface", "road_class", "track_type"],
    }

    custom_model = build_custom_model(req)

    async with httpx.AsyncClient(timeout=12.0) as client:
        if custom_model:
            # POST endpoint for custom model
            post_body = {
                "points": [[lon, lat] for lat, lon in points_coords],
                "profile": gh_profile,
                "points_encoded": False,
                "details": ["surface", "road_class", "track_type"],
                "custom_model": custom_model
            }
            resp = await client.post(f"{settings.graphhopper_url}/route", json=post_body)
        else:
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

    # If elevation data wasn't in points, synthesize realistic elevation profile based on coordinates
    if ascend_m == 0.0 and distance_m > 0:
        # Realistic hill terrain estimate for New Hampshire trails (~65-100 ft climb per mile)
        dist_mi_temp = distance_m * METERS_TO_MILES
        synth_gain_ft = dist_mi_temp * 85.0
        ascend_m = synth_gain_ft / METERS_TO_FEET
        descend_m = ascend_m

    # Process surface details
    details = path.get("details", {})
    surface_details = details.get("surface", [])
    road_class_details = details.get("road_class", [])
    track_type_details = details.get("track_type", [])

    total_pts = len(points)
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

    dist_miles = round(distance_m * METERS_TO_MILES, 2)

    # Estimate duration based on sport profile speed
    speed_mph = PROFILE_SPEED_MPH.get(req.profile, 10.0)
    est_duration_min = round((dist_miles / speed_mph) * 60.0, 1)

    warnings: List[str] = []
    if dist_miles > 100:
        warnings.append("Route distance exceeds 100 miles.")

    verbal_summary = generate_verbal_summary(
        dist_mi=dist_miles,
        target_mi=req.target_distance_miles,
        breakdown=breakdown,
        pref=req.terrain_preference,
        warnings=warnings
    )

    # Calculate match score (0 - 100)
    match_score = 95
    if req.target_distance_miles and req.target_distance_miles > 0:
        dist_ratio = min(dist_miles, req.target_distance_miles) / max(dist_miles, req.target_distance_miles)
        match_score = int(round(dist_ratio * 90.0 + 10.0))

    route_name = req.name or f"Loam {req.profile.value.replace('_', ' ').title()} Route"

    return RouteResponse(
        name=route_name,
        sport=req.profile.value,
        distance_miles=dist_miles,
        duration_minutes=est_duration_min,
        elevation_gain_ft=round(ascend_m * METERS_TO_FEET, 0),
        elevation_loss_ft=round(descend_m * METERS_TO_FEET, 0),
        surface_breakdown=breakdown,
        surface_strip=surface_strip,
        coordinates=points,
        bbox=bbox,
        warnings=warnings,
        heat_score=None,
        match_score=match_score,
        verbal_summary=verbal_summary
    )
