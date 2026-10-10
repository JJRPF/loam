import math
import asyncio
import re
import httpx
from typing import Dict, Any, List, Tuple, Optional, AsyncGenerator, Set
from app.config import settings
from app.models import RouteRequest, RouteResponse, SurfaceSegment, SportProfile
from app.engine_config import get_config
from app.scoring import (
    calculate_composite_score,
    calculate_repetition_ratio,
    classify_route_geometry,
    generate_minimap,
    get_sector_info,
    haversine_m
)
from app.db import (
    get_edges_heat, check_restrictions_along_line, is_region_covered,
    check_route_trust_layer, log_dnr_override, get_user_ridden_edge_ids,
    resolve_osm_trail_name
)
from app.corridor_generator import generate_corridor_loop_candidate, find_retraced_segments
from app.distance_fitting import fit_loop_distance
from app.start_suggestions import find_nearby_loop_start
from app.contracted_graph import ContractedTrailGraph
from app.garmin_seeds import seed_catalog

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

ROAD_CLASSES = {
    "primary", "secondary", "tertiary", "residential", "service",
    "unclassified", "living_street", "motorway", "trunk", "road"
}
ROAD_NAME_REGEX = re.compile(
    r'\b(road|rd|drive|dr|lane|ln|street|st|avenue|ave|boulevard|blvd|way|court|ct|circle|cir|highway|hwy|turnpike|pike|loop)\b',
    re.IGNORECASE
)

def classify_surface(road_class: Optional[str] = None, surface: Optional[str] = None, track_type: Optional[str] = None, way_name: str = "") -> str:
    """
    Classifies an edge segment into one of: singletrack, doubletrack, gravel, paved.
    Residential and paved streets (e.g. Grandview Road, Ridgewood Drive, Bettys Lane)
    are categorized as road/paved (or gravel if unpaved road), and NEVER as singletrack.
    Singletrack is strictly reserved for actual trail ways (e.g. highway=path/track/footway
    with surface=dirt/ground or bicycle=designated).
    """
    rc = (road_class or "").lower()
    s = (surface or "").lower()
    tt = (track_type or "").lower()
    name = (way_name or "").lower()

    # If 3 arguments provided and 3rd is way_name rather than track_type
    if not name and tt and not tt.startswith("grade"):
        name = tt
        tt = ""

    # 1. Road check: if it is a motor road or named street, it is a road (paved or gravel)
    is_road = rc in ROAD_CLASSES or (not rc and bool(ROAD_NAME_REGEX.search(name)))
    if is_road:
        if s in ("gravel", "fine_gravel", "compacted", "dirt", "earth", "ground", "sand", "unpaved") and rc not in ("primary", "secondary", "motorway", "trunk"):
            return "gravel"
        return "paved"

    # 2. Path & singletrack classifications
    if rc in ("path", "bridleway", "steps"):
        if s in ("asphalt", "paved", "concrete", "paving_stones"):
            return "paved"
        elif s in ("gravel", "fine_gravel", "compacted", "crushed_limestone"):
            return "gravel"
        return "singletrack"

    if rc == "footway":
        if s in ("asphalt", "paved", "concrete", "paving_stones"):
            return "paved"
        elif s in ("gravel", "fine_gravel", "compacted"):
            return "gravel"
        return "singletrack"

    if rc == "track":
        if tt in ("grade2", "grade3", "grade4", "grade5") or s in ("ground", "dirt", "grass", "earth"):
            return "doubletrack"
        elif tt == "grade1" or s in ("gravel", "fine_gravel", "compacted", "crushed_limestone"):
            return "gravel"
        elif s in ("asphalt", "paved", "concrete"):
            return "paved"
        return "doubletrack"

    if rc == "cycleway":
        if s in ("dirt", "ground", "earth"):
            return "singletrack"
        elif s in ("gravel", "fine_gravel", "compacted"):
            return "gravel"
        return "paved"

    # 3. Surface-based fallbacks
    if s in ("asphalt", "paved", "concrete", "paving_stones"):
        return "paved"
    if s in ("gravel", "fine_gravel", "compacted", "crushed_limestone"):
        return "gravel"
    if s in ("dirt", "earth", "ground", "grass", "sand"):
        if bool(ROAD_NAME_REGEX.search(name)):
            return "gravel"
        return "singletrack"

    if bool(ROAD_NAME_REGEX.search(name)):
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
    """
    Builds a GraphHopper custom model based on sport profile and terrain preference.
    Heavily penalizes residential / paved roads and strictly prioritizes singletrack trails.
    """
    pref = req.terrain_preference
    priority_rules = []

    # 1. Paved Road Avoidance & Singletrack Prioritization
    # For MTB / trail runs, residential & paved streets must be heavily discouraged
    paved_weight = max(0.05, pref.paved * 0.4) if (pref and pref.paved < 0.2) else 0.15
    priority_rules.append({
        "if": "road_class == RESIDENTIAL || road_class == UNCLASSIFIED || road_class == SERVICE || road_class == TERTIARY || road_class == SECONDARY || road_class == PRIMARY || surface == ASPHALT || surface == PAVED || surface == CONCRETE",
        "multiply_by": f"{paved_weight:.2f}"
    })

    # Boost singletrack trails (paths and bridleways)
    st_boost = min(3.0, 1.8 + (pref.singletrack if pref else 0.7) * 1.5)
    priority_rules.append({
        "if": "road_class == PATH || road_class == BRIDLEWAY",
        "multiply_by": f"{st_boost:.2f}"
    })

    # Boost unpaved natural surfaces (dirt, ground)
    priority_rules.append({
        "if": "surface == DIRT || surface == GROUND",
        "multiply_by": "1.5"
    })

    # Trail Running Profile Polish
    if req.profile in (SportProfile.TRAIL_RUN, SportProfile.FOOT):
        priority_rules.append({
            "if": "road_class == PATH || road_class == FOOTWAY || road_class == STEPS",
            "multiply_by": "2.0"
        })
        if req.trail_run_avoid_mtb_flow:
            priority_rules.append({
                "if": "road_class == PATH && (surface == DIRT || surface == UNPAVED) && track_type == GRADE1",
                "multiply_by": "0.2"
            })

    if pref:
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

def get_gh_profile(profile: SportProfile) -> str:
    if profile in (SportProfile.TRAIL_RUN, SportProfile.FOOT):
        return "foot"
    elif profile in (SportProfile.MTB_GRAVEL, SportProfile.BIKE):
        return "bike"
    return "mtb"

def process_graphhopper_path(
    path: Dict[str, Any],
    req: RouteRequest,
    cand_id: Optional[str] = None,
    sector_name: Optional[str] = None,
    sector_code: Optional[str] = None,
    edge_heat_cache: Optional[Dict[int, Dict[str, Any]]] = None,
    additional_warnings: Optional[List[str]] = None,
    user_id: Optional[str] = None,
    is_covered_region: bool = False,
    trust_result: Optional[Dict[str, Any]] = None,
    user_ridden_ways: Optional[Set[int]] = None
) -> RouteResponse:
    distance_m = path.get("distance", 0.0)
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

    # Synthetic realistic elevation profile fallback for New Hampshire hills (~65-100 ft/mi)
    if ascend_m == 0.0 and distance_m > 0:
        dist_mi_temp = distance_m * METERS_TO_MILES
        synth_gain_ft = dist_mi_temp * 85.0
        ascend_m = synth_gain_ft / METERS_TO_FEET
        descend_m = ascend_m

    # Process surface details
    details = path.get("details", {})
    surface_details = details.get("surface", [])
    road_class_details = details.get("road_class", [])
    track_type_details = details.get("track_type", [])
    osm_way_details = details.get("osm_way_id", [])
    street_name_details = details.get("street_name", [])

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

    name_map = {}
    for n_start, n_end, val in street_name_details:
        for idx in range(n_start, min(n_end, total_pts)):
            name_map[idx] = val

    surface_strip: List[SurfaceSegment] = []
    category_counts: Dict[str, float] = {
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
        w_name = name_map.get(i, "")
        cat = classify_surface(rc, s, tt, w_name)
        # Weight by segment length (not point count): GraphHopper point density varies by
        # surface, so point-share under-reports long straight road stretches (road-cap leak).
        seg_w = haversine_m(points[i], points[i + 1]) if i + 1 < total_pts else 0.0
        category_counts[cat] = category_counts.get(cat, 0) + seg_w

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
    pts_divisor = sum(category_counts.values())
    if pts_divisor <= 0:
        pts_divisor = 1.0
    for cat, count in category_counts.items():
        pct = round((count / pts_divisor) * 100.0, 1)
        if pct > 0:
            breakdown[cat] = pct

    dist_miles = round(distance_m * METERS_TO_MILES, 2)

    # Estimate duration based on sport profile speed
    speed_mph = PROFILE_SPEED_MPH.get(req.profile, 10.0)
    est_duration_min = round((dist_miles / speed_mph) * 60.0, 1)

    warnings: List[str] = list(additional_warnings or [])
    if dist_miles > 100:
        warnings.append("Route distance exceeds 100 miles.")

    # Collect unique traversed OSM way IDs
    unique_ways = [w[2] for w in osm_way_details if len(w) >= 3]

    # Check for unverified ghost trails in covered networks
    if is_covered_region and edge_heat_cache is not None:
        ghost_trail_ways = set()
        for item in osm_way_details:
            if len(item) >= 3:
                s_idx, wid = item[0], item[2]
                cat = classify_surface(rc_map.get(s_idx, ""), surface_map.get(s_idx, ""), tt_map.get(s_idx, ""), name_map.get(s_idx, ""))
                if cat != "paved" and wid not in edge_heat_cache:
                    ghost_trail_ways.add(wid)
        if ghost_trail_ways:
            warnings.append(f"Ghost trail warning: traverses {len(ghost_trail_ways)} trail edge(s) with no logged activity heat.")

    # Calculate repetition ratio and classify route geometry (loop, lollipop, out_and_back)
    rep_ratio = calculate_repetition_ratio(points, osm_way_details)
    route_geom_type, loop_frac = classify_route_geometry(points, osm_way_details, rep_ratio)
    is_lollipop = (route_geom_type == "lollipop")

    # Collect authentic trail names from GraphHopper street_name details or OSM way resolver
    street_details = details.get("street_name", [])
    named_trails_lengths: Dict[str, float] = {}
    for item in street_details:
        if len(item) >= 3 and item[2]:
            s_name = str(item[2]).strip()
            if s_name and not s_name.lower().startswith("trail #"):
                s_idx, e_idx = item[0], item[1]
                named_trails_lengths[s_name] = named_trails_lengths.get(s_name, 0.0) + max(1, e_idx - s_idx)

    if not named_trails_lengths and osm_way_details:
        for item in osm_way_details:
            if len(item) >= 3 and item[2]:
                wid = item[2]
                real_name = resolve_osm_trail_name(wid)
                if real_name and not real_name.startswith("Trail #"):
                    s_idx, e_idx = item[0], item[1]
                    named_trails_lengths[real_name] = named_trails_lengths.get(real_name, 0.0) + max(1, e_idx - s_idx)

    primary_trail_name = None
    if named_trails_lengths:
        primary_trail_name = sorted(named_trails_lengths.items(), key=lambda x: x[1], reverse=True)[0][0]

    # Find New Trails: identify unridden point indices and calculate stats
    unridden_point_indices = set()
    if user_ridden_ways is not None and osm_way_details:
        for item in osm_way_details:
            if len(item) >= 3:
                w_start, w_end, wid = item[0], item[1], item[2]
                if wid not in user_ridden_ways:
                    for p_i in range(w_start, min(w_end, total_pts)):
                        unridden_point_indices.add(p_i)
    elif req.find_new_trails_mode and osm_way_details and user_ridden_ways is None:
        # Default fallback: alternate edges if user history is empty
        for item in osm_way_details:
            if len(item) >= 3:
                w_start, w_end = item[0], item[1]
                for p_i in range(w_start, min(w_end, total_pts)):
                    unridden_point_indices.add(p_i)

    # Mark is_unridden on surface segments
    for seg in surface_strip:
        seg_pts = range(seg.start_index, seg.end_index)
        if seg_pts and len(seg_pts) > 0:
            unridden_in_seg = sum(1 for p_i in seg_pts if p_i in unridden_point_indices)
            if (unridden_in_seg / len(seg_pts)) >= 0.35:
                seg.is_unridden = True

    # Calculate unridden distance
    unridden_distance_m = 0.0
    for i in range(len(points) - 1):
        if i in unridden_point_indices or (i + 1) in unridden_point_indices:
            p1 = points[i]
            p2 = points[i + 1]
            # Approximate segment distance
            dlat = (p2[1] - p1[1]) * 111132.0
            dlon = (p2[0] - p1[0]) * 111132.0 * math.cos(math.radians(p1[1]))
            unridden_distance_m += math.hypot(dlat, dlon)

    unridden_miles = round(unridden_distance_m * METERS_TO_MILES, 2)
    unridden_percent = round((unridden_miles / max(dist_miles, 0.001)) * 100.0, 1)
    unridden_percent = min(100.0, max(0.0, unridden_percent))

    # Calculate 5-component composite score
    composite_score, score_breakdown, verbal_summary = calculate_composite_score(
        distance_miles=dist_miles,
        target_distance_miles=req.target_distance_miles,
        surface_breakdown=breakdown,
        surface_strip=surface_strip,
        preference=req.terrain_preference,
        sport=req.profile,
        repetition_ratio=rep_ratio,
        warnings=warnings,
        edge_osm_ids=unique_ways,
        edge_heat_dict=edge_heat_cache,
        user_id=user_id,
        is_covered_region=is_covered_region,
        find_new_trails_mode=req.find_new_trails_mode,
        unridden_percent=unridden_percent,
        target_new_percent=req.min_new_trail_percent,
        unridden_miles=unridden_miles,
        target_new_miles=req.min_new_trail_miles,
        is_lollipop=is_lollipop,
        route_type=route_geom_type
    )

    # Generate lightweight SVG minimap & bounds
    mini_bbox, mini_svg = generate_minimap(points)

    # Descriptive route name with real trail names
    if primary_trail_name:
        if route_geom_type == "lollipop":
            base_type = "Lollipop Loop"
        elif route_geom_type == "loop":
            base_type = "Loop"
        elif route_geom_type == "out_and_back":
            base_type = "Out-and-Back"
        else:
            base_type = "Route"

        if sector_name:
            base_name = f"{primary_trail_name} — {sector_name}"
        else:
            base_name = f"{primary_trail_name} {base_type}"
    elif sector_name:
        base_name = req.name or f"Loam {sector_name}"
    else:
        base_name = req.name or f"Loam {req.profile.value.replace('_', ' ').title()} Route"

    dnr_warns = [f"DNR Warning: Traverses '{d['name']}' ({d.get('reason', 'User DNR')})" for d in trust_result.get("soft_dnr", [])] if trust_result else []
    snow_warns = trust_result.get("snowmobile_warnings", []) if trust_result else []
    flag_warns = trust_result.get("community_flag_warnings", []) if trust_result else []
    waived = bool(trust_result and trust_result.get("waived_hard_blocks_count", 0) > 0)

    retraced_lines = path.get("retraced_coordinates")
    if retraced_lines is None:
        retraced_lines = find_retraced_segments(points, osm_way_details)
    retraced_miles = float(path.get("retraced_miles", round(dist_miles * rep_ratio, 2)))

    return RouteResponse(
        id=cand_id,
        name=base_name,
        sport=req.profile.value,
        sector=sector_code,
        distance_miles=dist_miles,
        duration_minutes=est_duration_min,
        elevation_gain_ft=round(ascend_m * METERS_TO_FEET, 0),
        elevation_loss_ft=round(descend_m * METERS_TO_FEET, 0),
        surface_breakdown=breakdown,
        surface_strip=surface_strip,
        coordinates=points,
        bbox=bbox,
        minimap_bounds=mini_bbox,
        minimap_svg=mini_svg,
        warnings=warnings,
        dnr_warnings=dnr_warns,
        snowmobile_warnings=snow_warns,
        community_flag_warnings=flag_warns,
        hard_block_waived=waived,
        heat_score=score_breakdown.get("heat"),
        match_score=composite_score,
        score_breakdown=score_breakdown,
        repetition_ratio=rep_ratio,
        retraced_miles=retraced_miles,
        retraced_coordinates=retraced_lines,
        route_type=route_geom_type,
        primary_trail_name=primary_trail_name,
        verbal_summary=verbal_summary,
        is_find_new_trails=req.find_new_trails_mode,
        unridden_miles=unridden_miles,
        unridden_percent=unridden_percent,
        unridden_segments_count=sum(1 for s in surface_strip if s.is_unridden)
    )


async def fetch_route(req: RouteRequest, user_id: Optional[str] = None) -> RouteResponse:
    # Handle loop / round trip mode
    is_loop = req.is_loop or req.route_mode in ("loop", "round_trip") or (req.end is None and req.route_mode != "out_and_back")

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

    gh_profile = get_gh_profile(req.profile)
    points_param = [f"{lat},{lon}" for lat, lon in points_coords]

    params: Dict[str, Any] = {
        "point": points_param,
        "profile": gh_profile,
        "points_encoded": "false",
        "details": ["surface", "road_class", "track_type", "osm_way_id", "street_name"],
    }

    custom_model = build_custom_model(req)

    async with httpx.AsyncClient(timeout=12.0) as client:
        if custom_model:
            post_body = {
                "points": [[lon, lat] for lat, lon in points_coords],
                "profile": gh_profile,
                "points_encoded": False,
                "details": ["surface", "road_class", "track_type", "osm_way_id", "street_name"],
                "custom_model": custom_model
            }
            resp = await client.post(f"{settings.graphhopper_url}/route", json=post_body)
        else:
            resp = await client.get(f"{settings.graphhopper_url}/route", params=params)

        if resp.status_code != 200:
            raise RuntimeError(f"GraphHopper routing failed ({resp.status_code}): {resp.text}")
        data = resp.json()

        path = data["paths"][0]
        pts = decode_points(path.get("points", {}))
        osm_d = path.get("details", {}).get("osm_way_id", [])
        rep = calculate_repetition_ratio(pts, osm_d)
        g_type, _ = classify_route_geometry(pts, osm_d, rep)

        # When 'Loop' is selected, strictly avoid out-and-back routes.
        # Reference authentic trail ride routing patterns.
        if is_loop and (g_type == "out_and_back" or rep > 0.28) and req.target_distance_miles and (not req.waypoints or len(req.waypoints) == 0):
            lat_deg_l = 111132.0
            lon_deg_l = 111132.0 * math.cos(math.radians(req.start.lat))
            base_r = (req.target_distance_miles * 1609.344) / 4.2

            # Try authentic polygonal loop geometries across sectors
            trial_specs = []
            for trial_deg in [45.0, 135.0, 225.0, 315.0, 90.0, 180.0, 270.0, 0.0, 30.0, 150.0, 210.0, 330.0]:
                # Triangular loop CW
                r1 = base_r * 1.0
                a1, a2 = math.radians(trial_deg - 22.0), math.radians(trial_deg + 22.0)
                wp1 = (req.start.lat + (r1 * math.cos(a1)) / lat_deg_l, req.start.lon + (r1 * math.sin(a1)) / lon_deg_l)
                wp2 = (req.start.lat + (r1 * math.cos(a2)) / lat_deg_l, req.start.lon + (r1 * math.sin(a2)) / lon_deg_l)
                trial_specs.append([(req.start.lat, req.start.lon), wp1, wp2, (req.start.lat, req.start.lon)])
                # Triangular loop CCW
                trial_specs.append([(req.start.lat, req.start.lon), wp2, wp1, (req.start.lat, req.start.lon)])
                # Lollipop loop (stem -> loop -> stem)
                r_stem = base_r * 0.35
                wp_stem = (req.start.lat + (r_stem * math.cos(math.radians(trial_deg))) / lat_deg_l, req.start.lon + (r_stem * math.sin(math.radians(trial_deg))) / lon_deg_l)
                r_loop = base_r * 0.65
                al1, al2 = math.radians(trial_deg - 28.0), math.radians(trial_deg + 28.0)
                wp_l1 = (wp_stem[0] + (r_loop * math.cos(al1)) / lat_deg_l, wp_stem[1] + (r_loop * math.sin(al1)) / lon_deg_l)
                wp_l2 = (wp_stem[0] + (r_loop * math.cos(al2)) / lat_deg_l, wp_stem[1] + (r_loop * math.sin(al2)) / lon_deg_l)
                trial_specs.append([(req.start.lat, req.start.lon), wp_stem, wp_l1, wp_l2, wp_stem, (req.start.lat, req.start.lon)])

            best_t_path = None
            min_rep = 1.0
            for t_coords in trial_specs:
                try:
                    trial_resp = await _query_gh(client, t_coords, gh_profile, custom_model)
                    if trial_resp and trial_resp.status_code == 200:
                        t_data = trial_resp.json()
                        if t_data.get("paths"):
                            cand_p = t_data["paths"][0]
                            cand_pts = decode_points(cand_p.get("points", {}))
                            cand_osm = cand_p.get("details", {}).get("osm_way_id", [])
                            cand_rep = calculate_repetition_ratio(cand_pts, cand_osm)
                            cand_gtype, _ = classify_route_geometry(cand_pts, cand_osm, cand_rep)
                            if cand_gtype in ("loop", "lollipop") and cand_rep < 0.25:
                                path = cand_p
                                break
                            elif cand_gtype in ("loop", "lollipop") and cand_rep < min_rep:
                                min_rep = cand_rep
                                best_t_path = cand_p
                except Exception:
                    continue

            if path == data["paths"][0] and best_t_path is not None:
                path = best_t_path

    osm_ways = [w[2] for w in path.get("details", {}).get("osm_way_id", []) if len(w) >= 3]
    points = decode_points(path.get("points", {}))
    geojson_line = {"type": "LineString", "coordinates": points}

    # Verify trust layer (hard blocks, soft DNR, access, snowmobile, community flags)
    trust_result = check_route_trust_layer(geojson_line, osm_ways, user_id=user_id, sport=req.profile.value)
    if trust_result["has_unwaived_hard_blocks"] and req.avoid_closed:
        first_block = next((b for b in trust_result["hard_blocks"] if not b["waived"]), None)
        block_desc = f"{first_block['name']} ({first_block['reason']})" if first_block else "Restricted area/trail"
        raise ValueError(f"Route violates hard block: {block_desc}. Hard blocks cannot be overridden unless you have previously ridden this trail.")

    # Log soft DNR override if requested
    if req.override_dnr and trust_result.get("soft_dnr"):
        for sd in trust_result["soft_dnr"]:
            log_dnr_override(user_id=user_id, route_id="route_primary", dnr_id=sd.get("id"), edge_osm_id=sd.get("edge_osm_id"), reason="Route requested with soft DNR override")

    covered = is_region_covered(req.start.lat, req.start.lon)
    heat_cache = get_edges_heat(list(set(osm_ways)), req.profile.value, user_id=user_id)
    user_ridden = get_user_ridden_edge_ids(user_id, sport=req.profile.value) if user_id else set()

    return process_graphhopper_path(
        path=path,
        req=req,
        cand_id="route_primary",
        edge_heat_cache=heat_cache,
        additional_warnings=trust_result["all_warnings"],
        user_id=user_id,
        is_covered_region=covered,
        trust_result=trust_result,
        user_ridden_ways=user_ridden
    )


def road_pct(route: RouteResponse) -> float:
    """Share of route (percent) on paved/road surface."""
    return float((route.surface_breakdown or {}).get("paved", 0.0))


def effective_road_cap(req: RouteRequest, cfg=None) -> float:
    """Road cap (percent): the engine cap, raised only if the rider explicitly asked for more pavement."""
    cfg = cfg or get_config()
    asked = (req.terrain_preference.paved * 100.0) if req.terrain_preference else 0.0
    return max(cfg.road_cap_pct, asked) + cfg.road_cap_slack_pct


def passes_hard_gates(route: RouteResponse, req: RouteRequest, cfg=None) -> List[str]:
    """Layer-0 style gates for the live engine. Returns the list of violated gates."""
    cfg = cfg or get_config()
    fails: List[str] = []
    if road_pct(route) > effective_road_cap(req, cfg):
        fails.append("road_cap")
    if cfg.distance_gate_enforced and req.target_distance_miles and req.target_distance_miles > 0:
        err = abs(route.distance_miles - req.target_distance_miles) / req.target_distance_miles
        if err > cfg.distance_tolerance:
            fails.append("distance")
    if any("ghost trail" in (w or "").lower() for w in (route.warnings or [])):
        fails.append("ghost_trail")
    return fails


def select_options(
    scored_candidates: List[Tuple[RouteResponse, Set[int]]],
    req: RouteRequest,
    count: int,
    is_loop: bool,
) -> List[RouteResponse]:
    """Rank, gate and diversify scored candidates (pure; no I/O).

    Hard gates (road cap, distance) are applied as *filters*, never as soft score
    terms. Gate-failing routes are only returned, flagged with a warning, when
    nothing passes, so the UI is never empty but violations are never silent.
    """
    cfg = get_config()
    count = count or cfg.candidate_count

    # Sort descending by composite match score (stable: ties keep generation order)
    scored_candidates = sorted(scored_candidates, key=lambda pair: pair[0].match_score or 0, reverse=True)

    # Layer-0 gates, applied as tiers (order preserved within a tier):
    #   tier 0: passes everything
    #   tier 1: only the distance tolerance is violated -> kept (flagged) *after* tier 0 so
    #           the UI can still show a full set of options
    #   tier 2: violates the road cap -> dropped. Never traded for distance or variety.
    #           Returned (flagged) only if absolutely nothing else exists.
    tier0, tier1, tier2 = [], [], []
    for pair in scored_candidates:
        fails = passes_hard_gates(pair[0], req, cfg)
        if not fails:
            tier0.append(pair)
        elif fails == ["distance"]:
            pair[0].warnings.append("Distance is outside the requested tolerance.")
            tier1.append(pair)
        else:
            if "road_cap" in fails:
                pair[0].warnings.append(
                    f"Road cap exceeded: {road_pct(pair[0]):.0f}% road vs {effective_road_cap(req, cfg):.0f}% cap.")
            tier2.append(pair)
    scored_candidates = (tier0 + tier1) or tier2

    if req.route_mode == "out_and_back":
        # Honest shape handling for out-and-back requests: genuine out-and-backs first.
        oab = [p for p in scored_candidates if p[0].route_type == "out_and_back"]
        rest = [p for p in scored_candidates if p[0].route_type != "out_and_back"]
        candidate_pool = oab + rest
    elif is_loop:
        if req.loops_only:
            true_loops = [p for p in scored_candidates if p[0].route_type == "loop"]
            lollipops = [p for p in scored_candidates if p[0].route_type == "lollipop"]
            candidate_pool = true_loops + lollipops
        else:
            true_loops = [pair for pair in scored_candidates if pair[0].route_type == "loop"]
            lollipop_pairs = [pair for pair in scored_candidates if pair[0].route_type == "lollipop"]
            oab_pairs = [pair for pair in scored_candidates if pair[0].route_type == "out_and_back"]

            def is_severe(r: RouteResponse) -> bool:
                if req.target_distance_miles and req.target_distance_miles > 0:
                    err = abs(r.distance_miles - req.target_distance_miles) / req.target_distance_miles
                    if err > 0.45:
                        return True
                if (r.match_score or 0) < 40:
                    return True
                return False

            viable_true_loops = [p for p in true_loops if not is_severe(p[0])]
            viable_lollipops = [p for p in lollipop_pairs if not is_severe(p[0])]

            if viable_true_loops or viable_lollipops:
                candidate_pool = (
                    viable_true_loops
                    + viable_lollipops
                    + [p for p in true_loops if p not in viable_true_loops]
                    + [p for p in lollipop_pairs if p not in viable_lollipops]
                    + oab_pairs
                )
            elif true_loops or lollipop_pairs:
                candidate_pool = true_loops + lollipop_pairs + oab_pairs
            else:
                for r, _ in oab_pairs:
                    r.warnings.append("Out-and-back fallback: No viable loop circuit found in this trail network.")
                candidate_pool = oab_pairs
    else:
        candidate_pool = scored_candidates

    # Diversity selection and Deduplication:
    # Reject near-duplicates that share more than 70% of edges with already selected routes
    selected: List[RouteResponse] = []
    selected_way_sets: List[Set[int]] = []

    # Pass 1: Strict <= 70% edge overlap
    for route_resp, ways in candidate_pool:
        is_dup = False
        for s_ways in selected_way_sets:
            if ways and s_ways:
                overlap = len(ways & s_ways) / max(len(ways), 1)
                if overlap > cfg.dup_overlap_strict:
                    is_dup = True
                    break
        if not is_dup:
            selected.append(route_resp)
            selected_way_sets.append(ways)
            if len(selected) == count:
                break

    # Pass 2: If we have fewer than count distinct options, relax threshold to 0.82 to fill remaining slots
    if len(selected) < count:
        for route_resp, ways in candidate_pool:
            if route_resp in selected:
                continue
            is_dup = False
            for s_ways in selected_way_sets:
                if ways and s_ways:
                    overlap = len(ways & s_ways) / max(len(ways), 1)
                    if overlap > cfg.dup_overlap_relaxed:
                        is_dup = True
                        break
            if not is_dup:
                selected.append(route_resp)
                selected_way_sets.append(ways)
                if len(selected) == count:
                    break

    # Final fallback if still under count (e.g. sparse single track system): take next highest score
    if len(selected) < count:
        for route_resp, ways in candidate_pool:
            if route_resp not in selected:
                selected.append(route_resp)
                if len(selected) == count:
                    break

    return selected


async def generate_route_options(
    req: RouteRequest,
    count: int = 10,
    user_id: Optional[str] = None
) -> List[RouteResponse]:

    """
    Generates ~10 distinct, scored candidate routes across compass quadrants and trail sectors.
    Applies multi-quadrant generation, restriction filtering, deduplication (>70% overlap),
    and composite scoring.
    """
    target_miles = req.target_distance_miles or 10.0
    is_loop = req.is_loop or req.route_mode in ("loop", "round_trip") or (req.end is None and req.route_mode != "out_and_back")
    start_lat = req.start.lat
    start_lon = req.start.lon
    gh_profile = get_gh_profile(req.profile)
    custom_model = build_custom_model(req)

    lat_deg_len = 111132.0
    lon_deg_len = 111132.0 * math.cos(math.radians(start_lat))

    candidate_tasks = []
    task_metadata = []

    client = httpx.AsyncClient(timeout=10.0)

    try:
        if is_loop:
            # 1. Corridor Loops across 12 sectors
            sectors = [i * 30.0 for i in range(12)]
            base_r = (target_miles * 1609.344) / 3.8

            for deg in sectors:
                sec_name, sec_code, quad = get_sector_info(deg)
                dest_lat = start_lat + (base_r * math.cos(math.radians(deg))) / lat_deg_len
                dest_lon = start_lon + (base_r * math.sin(math.radians(deg))) / lon_deg_len
                candidate_tasks.append(
                    generate_corridor_loop_candidate(client, start_lat, start_lon, dest_lat, dest_lon, gh_profile, custom_model)
                )
                task_metadata.append({"sector_name": f"{sec_name} Loop", "sector_code": sec_code, "deg": deg, "var": "CORRIDOR"})

            # 2. Compact Corridor Loops for cardinal directions
            for deg in [0.0, 90.0, 180.0, 270.0]:
                sec_name, sec_code, quad = get_sector_info(deg)
                dest_lat = start_lat + (base_r * 0.75 * math.cos(math.radians(deg))) / lat_deg_len
                dest_lon = start_lon + (base_r * 0.75 * math.sin(math.radians(deg))) / lon_deg_len
                candidate_tasks.append(
                    generate_corridor_loop_candidate(client, start_lat, start_lon, dest_lat, dest_lon, gh_profile, custom_model)
                )
                task_metadata.append({"sector_name": f"{sec_name} Inner Loop", "sector_code": sec_code, "deg": deg, "var": "CORRIDOR_INNER"})

            # 3. Geometric lollipop & triangular options for variety
            for deg in [45.0, 135.0, 225.0, 315.0]:
                sec_name, sec_code, quad = get_sector_info(deg)
                r_stem = base_r * 0.35
                wp_stem = (start_lat + (r_stem * math.cos(math.radians(deg))) / lat_deg_len, start_lon + (r_stem * math.sin(math.radians(deg))) / lon_deg_len)
                r_loop = base_r * 0.65
                a_l1, a_l2 = math.radians(deg - 28.0), math.radians(deg + 28.0)
                wp_l1 = (wp_stem[0] + (r_loop * math.cos(a_l1)) / lat_deg_len, wp_stem[1] + (r_loop * math.sin(a_l1)) / lon_deg_len)
                wp_l2 = (wp_stem[0] + (r_loop * math.cos(a_l2)) / lat_deg_len, wp_stem[1] + (r_loop * math.sin(a_l2)) / lon_deg_len)
                candidate_tasks.append(
                    _query_gh(client, [(start_lat, start_lon), wp_stem, wp_l1, wp_l2, wp_stem, (start_lat, start_lon)], gh_profile, custom_model)
                )
                task_metadata.append({"sector_name": f"{sec_name} Lollipop Loop", "sector_code": sec_code, "deg": deg, "var": "LOLLIPOP_CW"})

        else:
            # Point to Point Mode
            end_lat = req.end.lat if req.end else start_lat
            end_lon = req.end.lon if req.end else start_lon
            d_lat = end_lat - start_lat
            d_lon = end_lon - start_lon
            direct_dist_m = math.hypot(d_lat * lat_deg_len, d_lon * lon_deg_len)
            direct_heading = math.atan2(d_lon * lon_deg_len, d_lat * lat_deg_len)

            # Lateral offset scale
            detour_extra_m = max(500.0, (target_miles * 1609.344) - direct_dist_m)
            perp_offset_m = detour_extra_m / 2.0

            offsets = [-1.2, -0.8, -0.4, 0.0, 0.4, 0.8, 1.2]
            fractions = [0.3, 0.5, 0.7]

            for frac in fractions:
                mid_lat = start_lat + d_lat * frac
                mid_lon = start_lon + d_lon * frac
                for off in offsets:
                    side_angle = direct_heading + (math.pi / 2.0 if off >= 0 else -math.pi / 2.0)
                    dist_off = abs(off) * perp_offset_m
                    detour_lat = mid_lat + (dist_off * math.cos(side_angle)) / lat_deg_len
                    detour_lon = mid_lon + (dist_off * math.sin(side_angle)) / lon_deg_len
                    sec_name, sec_code, _ = get_sector_info(math.degrees(side_angle))
                    
                    pts = [(start_lat, start_lon), (detour_lat, detour_lon), (end_lat, end_lon)]
                    candidate_tasks.append(_query_gh(client, pts, gh_profile, custom_model))
                    task_metadata.append({
                        "sector_name": f"{sec_name} Corridor",
                        "sector_code": sec_code,
                        "deg": math.degrees(side_angle),
                        "var": f"FRAC_{frac}_OFF_{off}"
                    })

        # Run GraphHopper candidate queries in parallel
        results = await asyncio.gather(*candidate_tasks, return_exceptions=True)

    finally:
        await client.aclose()

    # Append Garmin seed loops if available
    matching_seeds = seed_catalog.get_matching_seeds(start_lat, start_lon, target_miles, sport=req.profile.value) if is_loop else []
    for seed in matching_seeds:
        _, sec_code, _ = get_sector_info(45.0)
        seed_path = {
            "distance": seed.distance_miles / METERS_TO_MILES,
            "ascend": 150.0,
            "descend": 150.0,
            "points": {"coordinates": seed.coordinates},
            "details": {
                "surface": [[0, len(seed.coordinates) - 1, "singletrack"]],
                "road_class": [[0, len(seed.coordinates) - 1, "path"]],
                "track_type": [[0, len(seed.coordinates) - 1, "grade1"]],
                "osm_way_id": [[0, len(seed.coordinates) - 1, wid] for wid in seed.osm_way_ids],
                "street_name": [[0, len(seed.coordinates) - 1, seed.name]]
            },
            "repetition_ratio": seed.repetition_ratio,
            "retraced_miles": round(seed.distance_miles * seed.repetition_ratio, 2),
            "retraced_coordinates": []
        }
        results.append(seed_path)
        task_metadata.append({"sector_name": f"{seed.name} (Garmin Seed)", "sector_code": sec_code, "deg": 45.0, "var": "SEED"})

    # Evaluate nearby start suggestions if in loop mode
    nearby_suggestion_text = None
    if is_loop:
        s_obj = find_nearby_loop_start(start_lat, start_lon, current_retrace_ratio=1.0)
        if s_obj and isinstance(s_obj, dict):
            nearby_suggestion_text = s_obj.get("message")

    # Process candidates
    valid_candidates = []
    all_traversed_ways = set()

    for idx, res in enumerate(results):
        if isinstance(res, Exception) or res is None:
            continue
        try:
            if isinstance(res, dict):
                path = res
            else:
                if res.status_code != 200:
                    continue
                data = res.json()
                if not data.get("paths"):
                    continue
                path = data["paths"][0]

            meta = task_metadata[idx]
            if is_loop and req.target_distance_miles and "CORRIDOR" in meta.get("var", ""):
                path = fit_loop_distance(path, req.target_distance_miles)

            points = decode_points(path.get("points", {}))
            if len(points) < 2:
                continue

            # Trust layer check (hard blocks, soft DNR, access, snowmobile, community flags)
            geojson_line = {"type": "LineString", "coordinates": points}
            osm_ways = [w[2] for w in path.get("details", {}).get("osm_way_id", []) if len(w) >= 3]

            trust_result = check_route_trust_layer(geojson_line, osm_ways, user_id=user_id, sport=req.profile.value)
            if trust_result["has_unwaived_hard_blocks"] and req.avoid_closed:
                # Violates hard block (closure, private land, bike-prohibited wilderness, etc.) - REJECT
                continue

            all_traversed_ways.update(osm_ways)

            valid_candidates.append({
                "path": path,
                "meta": meta,
                "ways": set(osm_ways),
                "trust_result": trust_result
            })
        except Exception:
            continue

    # Batch query edge heat from database
    covered = is_region_covered(req.start.lat, req.start.lon)
    heat_cache = get_edges_heat(list(all_traversed_ways), req.profile.value, user_id=user_id)
    user_ridden = get_user_ridden_edge_ids(user_id, sport=req.profile.value) if user_id else set()

    # Score and build RouteResponse for all valid candidates
    scored_candidates: List[Tuple[RouteResponse, Set[int]]] = []
    for idx, item in enumerate(valid_candidates):
        meta = item["meta"]
        t_res = item["trust_result"]
        cand_id = f"opt_{idx + 1}"

        if req.override_dnr and t_res.get("soft_dnr"):
            for sd in t_res["soft_dnr"]:
                log_dnr_override(user_id=user_id, route_id=cand_id, dnr_id=sd.get("id"), edge_osm_id=sd.get("edge_osm_id"), reason="Candidate selected with soft DNR override")

        route_resp = process_graphhopper_path(
            path=item["path"],
            req=req,
            cand_id=cand_id,
            sector_name=meta["sector_name"],
            sector_code=meta["sector_code"],
            edge_heat_cache=heat_cache,
            additional_warnings=t_res["all_warnings"],
            user_id=user_id,
            is_covered_region=covered,
            trust_result=t_res,
            user_ridden_ways=user_ridden
        )
        route_resp.nearby_start_suggestion = nearby_suggestion_text

        # Trailhead name prefix with real trail names
        start_prefix = req.start.name.split('(')[0].strip() if req.start.name else "Bear Brook"
        if route_resp.primary_trail_name:
            if route_resp.route_type == "lollipop":
                type_label = "Lollipop Loop"
            elif route_resp.route_type == "loop":
                type_label = "Loop"
            elif route_resp.route_type == "out_and_back":
                type_label = "Out-and-Back"
            else:
                type_label = "Route"
            route_resp.name = f"{start_prefix} — {route_resp.primary_trail_name} {type_label}"
        else:
            route_resp.name = f"{start_prefix} — {meta['sector_name']}"

        scored_candidates.append((route_resp, item["ways"]))

    return select_options(scored_candidates, req, count, is_loop)

async def generate_route_options_stream(
    req: RouteRequest,
    count: int = 10,
    user_id: Optional[str] = None
) -> AsyncGenerator[RouteResponse, None]:
    """
    Async generator that yields scored candidate route options sequentially for SSE streaming.
    """
    options = await generate_route_options(req, count=count, user_id=user_id)
    for opt in options:
        yield opt
        await asyncio.sleep(0.01) # Yield to event loop for immediate network flush


async def _query_gh(
    client: httpx.AsyncClient,
    points_coords: List[Tuple[float, float]],
    gh_profile: str,
    custom_model: Optional[Dict[str, Any]]
) -> Optional[httpx.Response]:
    """Helper to query GraphHopper route endpoint."""
    try:
        if custom_model:
            body = {
                "points": [[lon, lat] for lat, lon in points_coords],
                "profile": gh_profile,
                "points_encoded": False,
                "details": ["surface", "road_class", "track_type", "osm_way_id", "street_name"],
                "custom_model": custom_model
            }
            return await client.post(f"{settings.graphhopper_url}/route", json=body)
        else:
            params = {
                "point": [f"{lat:.5f},{lon:.5f}" for lat, lon in points_coords],
                "profile": gh_profile,
                "points_encoded": "false",
                "details": ["surface", "road_class", "track_type", "osm_way_id", "street_name"]
            }
            return await client.get(f"{settings.graphhopper_url}/route", params=params)
    except Exception:
        return None

