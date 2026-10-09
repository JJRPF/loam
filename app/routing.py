import math
import asyncio
import httpx
from typing import Dict, Any, List, Tuple, Optional, AsyncGenerator, Set
from app.config import settings
from app.models import RouteRequest, RouteResponse, SurfaceSegment, SportProfile
from app.scoring import (
    calculate_composite_score,
    calculate_repetition_ratio,
    classify_route_geometry,
    generate_minimap,
    get_sector_info
)
from app.db import (
    get_edges_heat, check_restrictions_along_line, is_region_covered,
    check_route_trust_layer, log_dnr_override, get_user_ridden_edge_ids,
    resolve_osm_trail_name
)

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
    
    if rc in ("path", "bridleway", "steps") or (rc == "footway" and s in ("ground", "dirt", "grass", "")):
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
    """
    Builds a GraphHopper custom model based on sport profile and terrain preference.
    Includes specialized Trail Running Polish per Project Plan:
    - Favors footpaths, stairs, and hiking trails.
    - Avoids high-speed downhill mountain bike flow trails.
    - Permits steeper grades without bike-specific penalties.
    """
    pref = req.terrain_preference
    priority_rules = []

    # Trail Running Profile Polish
    if req.profile in (SportProfile.TRAIL_RUN, SportProfile.FOOT):
        # Strongly favor footpaths, walking paths, and stairs
        priority_rules.append({
            "if": "road_class == PATH || road_class == FOOTWAY || road_class == STEPS",
            "multiply_by": "2.0"
        })
        # Avoid heavy high-speed downhill mountain bike flow trails
        if req.trail_run_avoid_mtb_flow:
            priority_rules.append({
                "if": "road_class == PATH && (surface == DIRT || surface == UNPAVED) && track_type == GRADE1",
                "multiply_by": "0.2"
            })
        # Heavily penalize paved roadways for trail running
        priority_rules.append({
            "if": "road_class == PRIMARY || road_class == SECONDARY || surface == ASPHALT || surface == PAVED",
            "multiply_by": "0.15"
        })

    if pref:
        # Singletrack priority
        if pref.singletrack >= 0.5 and req.profile not in (SportProfile.TRAIL_RUN, SportProfile.FOOT):
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
        if pref.paved < 0.15 and req.profile not in (SportProfile.TRAIL_RUN, SportProfile.FOOT):
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

    warnings: List[str] = list(additional_warnings or [])
    if dist_miles > 100:
        warnings.append("Route distance exceeds 100 miles.")

    # Collect unique traversed OSM way IDs
    unique_ways = [w[2] for w in osm_way_details if len(w) >= 3]

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
        is_lollipop=is_lollipop
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

        # If user explicitly requested a Loop and initial route produced an out-and-back,
        # attempt lollipop loop geometries to return a true loop
        if is_loop and g_type == "out_and_back" and req.target_distance_miles and (not req.waypoints or len(req.waypoints) == 0):
            lat_deg_l = 111132.0
            lon_deg_l = 111132.0 * math.cos(math.radians(req.start.lat))
            base_r = (req.target_distance_miles * 1609.344) / 4.2
            # Try rotating through sectors with lollipop geometry (stem -> loop -> stem)
            for trial_deg in [45.0, 135.0, 225.0, 315.0, 90.0, 180.0]:
                r_stem = base_r * 0.35
                wp_stem = (req.start.lat + (r_stem * math.cos(math.radians(trial_deg))) / lat_deg_l, req.start.lon + (r_stem * math.sin(math.radians(trial_deg))) / lon_deg_l)
                r_loop = base_r * 0.65
                a1, a2 = math.radians(trial_deg - 28.0), math.radians(trial_deg + 28.0)
                wp_l1 = (wp_stem[0] + (r_loop * math.cos(a1)) / lat_deg_l, wp_stem[1] + (r_loop * math.sin(a1)) / lon_deg_l)
                wp_l2 = (wp_stem[0] + (r_loop * math.cos(a2)) / lat_deg_l, wp_stem[1] + (r_loop * math.sin(a2)) / lon_deg_l)
                trial_coords = [(req.start.lat, req.start.lon), wp_stem, wp_l1, wp_l2, wp_stem, (req.start.lat, req.start.lon)]
                try:
                    trial_resp = await _query_gh(client, trial_coords, gh_profile, custom_model)
                    if trial_resp and trial_resp.status_code == 200:
                        t_data = trial_resp.json()
                        if t_data.get("paths"):
                            t_path = t_data["paths"][0]
                            t_pts = decode_points(t_path.get("points", {}))
                            t_osm = t_path.get("details", {}).get("osm_way_id", [])
                            t_rep = calculate_repetition_ratio(t_pts, t_osm)
                            t_gtype, _ = classify_route_geometry(t_pts, t_osm, t_rep)
                            if t_gtype in ("loop", "lollipop"):
                                path = t_path
                                break
                except Exception:
                    continue

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
    is_loop = req.is_loop or req.route_mode in ("loop", "round_trip") or req.end is None
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
            # 12 sectors across all 4 quadrants (0 deg to 330 deg in 30 deg steps)
            sectors = [i * 30.0 for i in range(12)]
            base_r = (target_miles * 1609.344) / 4.2

            for deg in sectors:
                sec_name, sec_code, quad = get_sector_info(deg)

                # Geometry 1: Triangular Loop CW (radius 1.0)
                r1 = base_r * 1.0
                a1, a2 = math.radians(deg - 22.0), math.radians(deg + 22.0)
                wp1 = (start_lat + (r1 * math.cos(a1)) / lat_deg_len, start_lon + (r1 * math.sin(a1)) / lon_deg_len)
                wp2 = (start_lat + (r1 * math.cos(a2)) / lat_deg_len, start_lon + (r1 * math.sin(a2)) / lon_deg_len)
                candidate_tasks.append(
                    _query_gh(client, [(start_lat, start_lon), wp1, wp2, (start_lat, start_lon)], gh_profile, custom_model)
                )
                task_metadata.append({"sector_name": f"{sec_name} Loop", "sector_code": sec_code, "deg": deg, "var": "CW"})

                # Geometry 2: Triangular Loop CCW (radius 1.0)
                candidate_tasks.append(
                    _query_gh(client, [(start_lat, start_lon), wp2, wp1, (start_lat, start_lon)], gh_profile, custom_model)
                )
                task_metadata.append({"sector_name": f"{sec_name} Reverse Loop", "sector_code": sec_code, "deg": deg, "var": "CCW"})

                # Geometry 3: Sweeping Arc Loop (radius 1.25, 3 waypoints)
                r_arc = base_r * 1.25
                a_arc1, a_arc2, a_arc3 = math.radians(deg - 35.0), math.radians(deg), math.radians(deg + 35.0)
                wp_arc1 = (start_lat + (r_arc * math.cos(a_arc1)) / lat_deg_len, start_lon + (r_arc * math.sin(a_arc1)) / lon_deg_len)
                wp_arc2 = (start_lat + (r_arc * math.cos(a_arc2)) / lat_deg_len, start_lon + (r_arc * math.sin(a_arc2)) / lon_deg_len)
                wp_arc3 = (start_lat + (r_arc * math.cos(a_arc3)) / lat_deg_len, start_lon + (r_arc * math.sin(a_arc3)) / lon_deg_len)
                candidate_tasks.append(
                    _query_gh(client, [(start_lat, start_lon), wp_arc1, wp_arc2, wp_arc3, (start_lat, start_lon)], gh_profile, custom_model)
                )
                task_metadata.append({"sector_name": f"{sec_name} Arc Loop", "sector_code": sec_code, "deg": deg, "var": "ARC"})

                # Geometry 4: Compact Loop (radius 0.78)
                r_comp = base_r * 0.78
                a_c1, a_c2 = math.radians(deg - 18.0), math.radians(deg + 18.0)
                wp_c1 = (start_lat + (r_comp * math.cos(a_c1)) / lat_deg_len, start_lon + (r_comp * math.sin(a_c1)) / lon_deg_len)
                wp_c2 = (start_lat + (r_comp * math.cos(a_c2)) / lat_deg_len, start_lon + (r_comp * math.sin(a_c2)) / lon_deg_len)
                candidate_tasks.append(
                    _query_gh(client, [(start_lat, start_lon), wp_c1, wp_c2, (start_lat, start_lon)], gh_profile, custom_model)
                )
                task_metadata.append({"sector_name": f"{sec_name} Inner Loop", "sector_code": sec_code, "deg": deg, "var": "INNER"})

                # Geometry 5: Lollipop Loop CW (stem -> loop circuit -> stem return)
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

                # Geometry 6: Lollipop Loop CCW
                candidate_tasks.append(
                    _query_gh(client, [(start_lat, start_lon), wp_stem, wp_l2, wp_l1, wp_stem, (start_lat, start_lon)], gh_profile, custom_model)
                )
                task_metadata.append({"sector_name": f"{sec_name} Reverse Lollipop", "sector_code": sec_code, "deg": deg, "var": "LOLLIPOP_CCW"})

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

    # Process candidates
    valid_candidates = []
    all_traversed_ways = set()

    for idx, res in enumerate(results):
        if isinstance(res, Exception) or res is None or res.status_code != 200:
            continue
        try:
            data = res.json()
            if not data.get("paths"):
                continue
            path = data["paths"][0]
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

            meta = task_metadata[idx]
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

        # Trailhead name prefix with real trail names
        if route_resp.primary_trail_name:
            if route_resp.route_type == "lollipop":
                type_label = "Lollipop Loop"
            elif route_resp.route_type == "loop":
                type_label = "Loop"
            elif route_resp.route_type == "out_and_back":
                type_label = "Out-and-Back"
            else:
                type_label = "Route"
            route_resp.name = f"Bear Brook — {route_resp.primary_trail_name} {type_label}"
        elif req.start.name and req.start.name != "Bear Brook Trailhead":
            route_resp.name = f"{req.start.name.split('(')[0].strip()} — {meta['sector_name']}"
        else:
            route_resp.name = f"Bear Brook — {meta['sector_name']}"

        scored_candidates.append((route_resp, item["ways"]))

    # Sort descending by composite match score
    scored_candidates.sort(key=lambda pair: pair[0].match_score or 0, reverse=True)

    # Filter candidate pool when Loop mode is selected:
    # Strictly return loops (including lollipop loops). Do NOT return out-and-back routes
    # unless all other candidate options deviate severely from user inputs.
    if is_loop:
        loop_pairs = [pair for pair in scored_candidates if pair[0].route_type in ("loop", "lollipop")]
        oab_pairs = [pair for pair in scored_candidates if pair[0].route_type == "out_and_back"]

        def is_severe(r: RouteResponse) -> bool:
            if req.target_distance_miles and req.target_distance_miles > 0:
                err = abs(r.distance_miles - req.target_distance_miles) / req.target_distance_miles
                if err > 0.45:
                    return True
            if (r.match_score or 0) < 40:
                return True
            return False

        viable_loops = [p for p in loop_pairs if not is_severe(p[0])]

        if viable_loops:
            candidate_pool = viable_loops + [p for p in loop_pairs if p not in viable_loops]
        elif loop_pairs:
            candidate_pool = loop_pairs
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
                if overlap > 0.70:
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
                    if overlap > 0.82:
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

