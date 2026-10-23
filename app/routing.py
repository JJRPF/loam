import math
import asyncio
import httpx
from typing import Dict, Any, List, Tuple, Optional, AsyncGenerator, Set
from app.config import settings
from app.models import RouteRequest, RouteResponse, SurfaceSegment, SportProfile
from app.surface import surface_category
from app.route_builder import (
    GEOMETRY_MAX_OFFSET_M, METERS_TO_MILES, Piece, build_route_response, haversine_m, pieces_from_graphhopper,
)
from app.engine_config import get_config
from app.scoring import calculate_repetition_ratio, classify_route_geometry, get_sector_info
from app.db import (
    get_edges_heat, is_region_covered, get_user_dnr_list,
    check_route_trust_layer, log_dnr_override, get_user_ridden_edge_ids,
)
from app.corridor_generator import generate_corridor_loop_candidate, find_retraced_segments

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

def classify_surface(road_class: Optional[str] = None, surface: Optional[str] = None,
                     track_type: Optional[str] = None, way_name: str = "") -> str:
    """GraphHopper details -> Loam surface category, via the shared app.surface rules.
    `way_name` is accepted for old callers and ignored: classification uses tags only."""
    return surface_category({"highway": road_class, "surface": surface, "tracktype": track_type})


def _bbox_of(points: List[List[float]]) -> List[float]:
    if not points:
        return []
    lons = [p[0] for p in points]
    lats = [p[1] for p in points]
    return [min(lons), min(lats), max(lons), max(lats)]


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

def graphhopper_candidate(path: Dict[str, Any]) -> Tuple[List[List[float]], List[Piece]]:
    """Coordinates and per-way pieces of a GraphHopper path."""
    points = decode_points(path.get("points", {}))
    return points, pieces_from_graphhopper(path.get("details", {}) or {}, len(points))


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
    """A GraphHopper path through the one route builder."""
    coords, pieces = graphhopper_candidate(path)
    built = build_route_response(
        coords, pieces, req, "graphhopper", user_id, cand_id=cand_id, label=sector_name,
        heat_cache=edge_heat_cache if edge_heat_cache is not None else {}, user_ridden=user_ridden_ways,
        covered=is_covered_region, trust_result=trust_result or {"all_warnings": []},
        extra_warnings=[w for w in (additional_warnings or []) if not trust_result or w not in trust_result.get("all_warnings", [])],
    )
    built.route.sector = sector_code
    return built.route


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

    coords, pieces = graphhopper_candidate(path)
    osm_ways = [pc.way_id for pc in pieces if pc.way_id is not None]

    # Verify trust layer (hard blocks, soft DNR, access, snowmobile, community flags)
    trust_result = check_route_trust_layer({"type": "LineString", "coordinates": coords}, osm_ways,
                                           user_id=user_id, sport=req.profile.value)
    if trust_result["has_unwaived_hard_blocks"] and req.avoid_closed:
        first_block = next((b for b in trust_result["hard_blocks"] if not b["waived"]), None)
        block_desc = f"{first_block['name']} ({first_block['reason']})" if first_block else "Restricted area/trail"
        raise ValueError(f"Route violates hard block: {block_desc}. Hard blocks cannot be overridden unless you have previously ridden this trail.")

    if req.override_dnr and trust_result.get("soft_dnr"):
        for sd in trust_result["soft_dnr"]:
            log_dnr_override(user_id=user_id, route_id="route_primary", dnr_id=sd.get("id"), edge_osm_id=sd.get("edge_osm_id"), reason="Route requested with soft DNR override")

    user_ridden = get_user_ridden_edge_ids(user_id, sport=req.profile.value) if user_id else None
    built = build_route_response(coords, pieces, req, "graphhopper", user_id, cand_id="route_primary",
                                 trust_result=trust_result, user_ridden=user_ridden)
    return built.route


def road_pct(route: RouteResponse) -> float:
    """Road share (percent), excluding the access stretch from the start to the first trail."""
    if route.road_pct is not None:
        return float(route.road_pct)
    return float((route.surface_breakdown or {}).get("paved", 0.0))


def effective_road_cap(req: RouteRequest, cfg=None) -> float:
    """Road cap (percent): the engine cap, raised only if the rider explicitly asked for more pavement."""
    cfg = cfg or get_config()
    asked = (req.terrain_preference.paved * 100.0) if req.terrain_preference else 0.0
    return max(cfg.road_cap_pct, asked) + cfg.road_cap_slack_pct


def distance_out_of_range(route: RouteResponse, req: RouteRequest) -> bool:
    """Plan 6.4: more than 50% off the target, or under 25% of it, is never an option."""
    target = req.target_distance_miles
    if not target or target <= 0:
        return False
    return abs(route.distance_miles - target) / target > 0.50 or route.distance_miles < 0.25 * target


def passes_hard_gates(route: RouteResponse, req: RouteRequest, cfg=None) -> List[str]:
    """Layer-0 style gates for the live engine. Returns the list of violated gates."""
    cfg = cfg or get_config()
    fails: List[str] = []
    # Geometry fidelity (6.3): every point within 15 m of the OSM ways the route claims.
    if route.geometry_max_offset_m is None or route.geometry_max_offset_m > GEOMETRY_MAX_OFFSET_M:
        fails.append("geometry")
    if road_pct(route) > effective_road_cap(req, cfg):
        fails.append("road_cap")
    if cfg.distance_gate_enforced and req.target_distance_miles and req.target_distance_miles > 0:
        err = abs(route.distance_miles - req.target_distance_miles) / req.target_distance_miles
        if err > cfg.distance_tolerance:
            fails.append("distance")
    if any("ghost trail" in (w or "").lower() for w in (route.warnings or [])):
        fails.append("ghost_trail")
    return fails


def _warn(route: RouteResponse, message: str) -> None:
    if message not in route.warnings:
        route.warnings.append(message)


def _overlap(a: Dict[int, float], b: Dict[int, float]) -> float:
    """Shared length of two routes' ways over the shorter route's length."""
    if not a or not b:
        return 0.0
    shared = sum(min(a[w], b[w]) for w in a.keys() & b.keys())
    return shared / max(min(sum(a.values()), sum(b.values())), 1.0)


def select_options(
    scored_candidates: List[Tuple[RouteResponse, Any]],
    req: RouteRequest,
    count: int,
    is_loop: bool,
) -> List[RouteResponse]:
    """Rank, gate and diversify scored candidates (pure; no I/O).

    Never shown, not even as a fallback: geometry failures and routes more than 50% off the
    target distance (or under 25% of it). Road-cap failures are shown, flagged, only when
    nothing else exists. The second element of each pair is the route's way set or, from the
    route builder, a {way id: meters} map; near-duplicates (>= 70% shared length) are dropped.
    """
    cfg = get_config()
    count = count or cfg.candidate_count

    def lengths(ways: Any) -> Dict[int, float]:
        if isinstance(ways, dict):
            return ways
        return {w: 1.0 for w in (ways or ())}

    pairs = [(r, lengths(w)) for r, w in scored_candidates
             if "geometry" not in passes_hard_gates(r, req, cfg) and not distance_out_of_range(r, req)]
    pairs.sort(key=lambda pair: pair[0].match_score or 0, reverse=True)

    tier0, tier1, tier2 = [], [], []
    for pair in pairs:
        fails = passes_hard_gates(pair[0], req, cfg)
        if not fails:
            tier0.append(pair)
        elif fails == ["distance"]:
            _warn(pair[0], "Distance is outside the requested tolerance.")
            tier1.append(pair)
        else:
            if "road_cap" in fails:
                _warn(pair[0], f"Road cap exceeded: {road_pct(pair[0]):.0f}% road vs {effective_road_cap(req, cfg):.0f}% cap.")
            tier2.append(pair)
    pairs = (tier0 + tier1) or tier2

    if req.route_mode == "out_and_back":
        candidate_pool = [p for p in pairs if p[0].route_type == "out_and_back"] + \
                         [p for p in pairs if p[0].route_type != "out_and_back"]
    elif is_loop:
        true_loops = [p for p in pairs if p[0].route_type == "loop"]
        lollipops = [p for p in pairs if p[0].route_type == "lollipop"]
        if req.loops_only:
            candidate_pool = true_loops + lollipops
        elif true_loops or lollipops:
            candidate_pool = true_loops + lollipops + [p for p in pairs if p[0].route_type not in ("loop", "lollipop")]
        else:
            candidate_pool = pairs
            for r, _ in candidate_pool:
                _warn(r, "Out-and-back: no loop found in this trail network.")
    else:
        candidate_pool = pairs

    selected: List[RouteResponse] = []
    selected_ways: List[Dict[int, float]] = []
    for threshold in (cfg.dup_overlap_strict, cfg.dup_overlap_relaxed):
        for route_resp, ways in candidate_pool:
            if len(selected) >= count:
                break
            if any(route_resp is r for r in selected):
                continue
            if all(_overlap(ways, sw) <= threshold for sw in selected_ways):
                selected.append(route_resp)
                selected_ways.append(ways)
    return selected


class OptionsResult:
    def __init__(self, options: List[RouteResponse], notice: Optional[str], nearby_suggestion: Optional[str],
                 pool_size: int, sources: Dict[str, int]):
        self.options = options
        self.notice = notice
        self.nearby_suggestion = nearby_suggestion
        self.pool_size = pool_size
        self.sources = sources


def _ring(start_lat: float, start_lon: float, radius_m: float, deg: float) -> Tuple[float, float]:
    lat_len = 111132.0
    lon_len = 111132.0 * math.cos(math.radians(start_lat))
    return (start_lat + radius_m * math.cos(math.radians(deg)) / lat_len,
            start_lon + radius_m * math.sin(math.radians(deg)) / lon_len)


def _graph_loop_candidates(req: RouteRequest, target_m: float, seed: int, excluded_ways: Set[int],
                           road_budget_m: float) -> Tuple[List[Tuple[List[List[float]], List[Piece], str]], Optional[str]]:
    """Trail-graph loops as (coords, pieces, label), plus a verified nearby-start suggestion."""
    from app.trail_graph import graph_for
    bike = req.profile not in (SportProfile.TRAIL_RUN, SportProfile.FOOT)
    graph = graph_for(req.start.lon, req.start.lat, 0.6 * target_m, bike)
    loops = graph.search_loops(req.start.lon, req.start.lat, target_m, get_config().distance_tolerance,
                               road_budget_m, seed=seed, excluded_ways=excluded_ways)
    out = []
    suggestion = None
    for lp in loops:
        coords = graph.coords_of(lp.steps)
        if coords is None:
            continue  # discontinuous: never shown
        pieces, idx = [], 0
        for sid, fwd in lp.steps:
            seg = graph.segments[sid]
            n = len(seg.coords) - 1
            pieces.append(Piece(start=idx, end=idx + n, way_id=seg.way_id, tags=seg.tags))
            idx += n
        out.append((coords, pieces, "Trail Loop"))
        if suggestion is None and lp.stem_length >= 160.0:
            names = [graph.segments[s].tags.get("name") for s, _ in lp.steps if graph.segments[s].tags.get("name")
                     and graph.segments[s].category != "paved"]
            where = names[0] if names else "the trail junction"
            suggestion = f"Start {lp.stem_length * METERS_TO_MILES:.1f} mi away at {where} for a true loop"
    return out, suggestion


VIA_TOLERANCE_M = 150.0
VIA_REPETITION_MAX = 0.28   # the plain-loop out-and-back rule (plan 6.4), applied to loops through midpoints


class MidpointError(ValueError):
    """A midpoint the engine cannot honour; the message is shown to the rider (HTTP 422)."""


VIA_ARC_HEIGHTS = (0.08, 0.14, 0.2, 0.3, 0.4)   # detour height as a fraction of the leg's chord


def via_loop_specs(start: Tuple[float, float], vias: List[Tuple[float, float]], target_m: Optional[float] = None,
                   base_m: Optional[float] = None) -> List[Tuple[List[Tuple[float, float]], str]]:
    """Point lists for GraphHopper: start -> midpoints in the rider's order -> start, where every leg
    carries a detour bulging to its own side, so the way back cannot retrace the way out.

    One midpoint: the outbound leg bulges left of the start->midpoint bearing and the return leg right
    (and the mirror). Several: every leg bulges outward from the centroid of start and midpoints, the
    shape of a round loop. A detour waypoint snaps to whatever way is nearest, so the length it adds
    cannot be computed from the geometry (a formula gave 15-24 mi for a 10 mi target); instead a ladder
    of heights (VIA_ARC_HEIGHTS, fractions of each chord) is offered and the distance gate keeps the ones
    that land near the target. The plain start->midpoints->start route is kept as one candidate (the
    repetition filter drops it when a real loop exists). The order of the midpoints is never changed.
    """
    lat0 = start[0]
    kx, ky = 111132.0 * math.cos(math.radians(lat0)), 111132.0

    def to_xy(p):
        return ((p[1] - start[1]) * kx, (p[0] - start[0]) * ky)

    def to_ll(xy):
        return (start[0] + xy[1] / ky, start[1] + xy[0] / kx)

    stops = [start] + list(vias) + [start]
    xy = [to_xy(p) for p in stops]
    legs = [(xy[i], xy[i + 1]) for i in range(len(xy) - 1)]
    chords = [math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in legs]
    specs: List[Tuple[List[Tuple[float, float]], str]] = [(list(stops), "Via Loop")]
    if sum(chords) < 1.0:
        return specs

    pts = xy[:-1]
    cx, cy = sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)

    def side_signs(mirror: bool) -> List[float]:
        if len(vias) == 1:  # out left, back right (or the mirror): both normals face away from the chord
            return [1.0, 1.0] if not mirror else [-1.0, -1.0]
        out = []
        for (a, b) in legs:
            mx, my = (a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0
            nx, ny = -(b[1] - a[1]), (b[0] - a[0])  # left normal
            out.append(1.0 if (mx - cx) * nx + (my - cy) * ny >= 0 else -1.0)
        return [-x for x in out] if mirror else out

    for mirror in (False, True) if len(vias) == 1 else (False,):
        signs = side_signs(mirror)
        for hf in VIA_ARC_HEIGHTS:
            for shape, fracs in (("arc", (0.5,)), ("wide", (0.3, 0.7))):
                pts_out: List[Tuple[float, float]] = [start]
                for i, (a, b) in enumerate(legs):
                    c = chords[i]
                    if c >= 1.0:
                        nx, ny = -(b[1] - a[1]) / c, (b[0] - a[0]) / c
                        for f in fracs:
                            pts_out.append(to_ll((a[0] + (b[0] - a[0]) * f + signs[i] * nx * hf * c,
                                                  a[1] + (b[1] - a[1]) * f + signs[i] * ny * hf * c)))
                    if i < len(vias):
                        pts_out.append(vias[i])
                pts_out.append(start)
                specs.append((pts_out, f"{shape} via loop {hf:g}" + (" (mirrored)" if mirror else "")))
    return specs


def repetition(coords: List[List[float]]) -> float:
    """Out-and-back share of a route: the larger of the geometric ratio (scoring) and the share of steps
    ridden twice, the two measures the loop checker applies (loam_eval/via_check.py, C5)."""
    from app.route_builder import _step_key
    seen, again, total = set(), 0.0, 0.0
    for i in range(len(coords) - 1):
        d = haversine_m(coords[i], coords[i + 1])
        total += d
        k = _step_key(coords[i], coords[i + 1])
        if k in seen:
            again += d
        seen.add(k)
    return max(calculate_repetition_ratio(coords), again / total if total else 0.0)


def filter_via_repetition(raw: List[Any]) -> Tuple[List[Any], bool]:
    """Loops through midpoints must not be out-and-backs (C5). Keeps the candidates at or under the
    plain-loop limit when any exist. Otherwise keeps the least repetitive ones and reports True, so the
    caller tells the rider (a dead-end midpoint is the usual reason). Candidates are (coords, ...)."""
    reps = [repetition(r[0]) for r in raw]
    good = [r for r, x in zip(raw, reps) if x <= VIA_REPETITION_MAX]
    if good or not raw:
        return good, False
    best = min(reps)
    return [r for r, x in zip(raw, reps) if x <= best + 0.05], True


# Variants of the "return avoids the way out" probe: (priority factor on the used corridor, corridor width m)
VIA_AVOID_VARIANTS = ((0.05, 35.0), (0.25, 35.0), (0.05, 90.0))
VIA_ANCHOR_SPACING_M = 500.0
VIA_SNAP_SLACK_M = 25.0     # a route may pass a midpoint this much farther than the plain route does
VIA_KEEP_RADIUS_M = 120.0   # no penalty around a leg's own start and end, so the rider can leave a midpoint


def corridor_areas(coords: List[List[float]], keep: List[Tuple[float, float]], width_m: float,
                   max_parts: int = 6) -> List[Dict[str, Any]]:
    """GeoJSON polygons (lon/lat) covering the corridor of a ridden path, minus a disc around each
    `keep` point (lat, lon). Used as GraphHopper custom-model areas to make later legs avoid earlier ones."""
    from shapely.geometry import LineString, Point, mapping
    from shapely.ops import unary_union
    if len(coords) < 2:
        return []
    lon0, lat0 = coords[0][0], coords[0][1]
    kx, ky = 111132.0 * math.cos(math.radians(lat0)), 111132.0

    def fwd(c):
        return ((c[0] - lon0) * kx, (c[1] - lat0) * ky)

    area = LineString([fwd(c) for c in coords]).buffer(width_m)
    for lat, lon in keep:
        area = area.difference(Point(fwd((lon, lat))).buffer(VIA_KEEP_RADIUS_M))
    area = area.simplify(4.0)
    parts = list(area.geoms) if hasattr(area, "geoms") else [area]
    parts = sorted((g for g in parts if g.geom_type == "Polygon" and not g.is_empty), key=lambda g: -g.area)[:max_parts]
    out = []
    for g in parts:
        geo = mapping(g)
        out.append({"type": "Polygon",
                    "coordinates": [[[round(x / kx + lon0, 6), round(y / ky + lat0, 6)] for x, y in ring]
                                    for ring in geo["coordinates"]]})
    return out


def with_corridor_penalty(base: Optional[Dict[str, Any]], geoms: List[Dict[str, Any]], factor: float) -> Dict[str, Any]:
    """The request's custom model plus a priority penalty inside each area."""
    import copy
    cm = copy.deepcopy(base) if base else {}
    prio = cm.setdefault("priority", [])
    feats = []
    for i, g in enumerate(geoms):
        feats.append({"type": "Feature", "id": f"used{i}", "properties": {}, "geometry": g})
        prio.append({"if": f"in_used{i}", "multiply_by": f"{factor:.2f}"})
    cm["areas"] = {"type": "FeatureCollection", "features": feats}
    return cm


def sample_anchors(coords: List[List[float]], spacing_m: float = VIA_ANCHOR_SPACING_M) -> List[Tuple[float, float]]:
    """(lat, lon) points on a path every ~spacing_m, excluding its two ends."""
    out, acc = [], 0.0
    for i in range(1, len(coords) - 1):
        acc += haversine_m(coords[i - 1], coords[i])
        if acc >= spacing_m:
            out.append((coords[i][1], coords[i][0]))
            acc = 0.0
    return out


async def _avoiding_anchors(client, start, vias, gh_profile, base_cm, factor: float, width_m: float
                            ) -> Optional[Tuple[List[Tuple[float, float]], float]]:
    """Route start -> midpoints -> start leg by leg, each leg after the first penalising the corridors of
    the legs before it. Returns (waypoints along that route for one final request, its length m)."""
    stops = [start] + list(vias) + [start]
    used: List[List[float]] = []
    anchors: List[Tuple[float, float]] = [start]
    total = 0.0
    for i in range(len(stops) - 1):
        a, b = stops[i], stops[i + 1]
        cm = base_cm
        if used:
            geoms = corridor_areas(used, [a, b], width_m)
            if geoms:
                cm = with_corridor_penalty(base_cm, geoms, factor)
        leg = await _leg_chain(client, [a, b], gh_profile, cm)
        if leg is None:
            return None
        coords, dist = leg
        total += dist
        if i > 0:
            anchors.extend(sample_anchors(coords))
        if i < len(stops) - 2:
            anchors.append(b)
        used.extend(coords)
    anchors.append(start)
    return anchors, total


async def via_candidate_specs(vias: List[Tuple[float, float]], start: Tuple[float, float], target_m: float,
                              gh_profile: str, custom_model: Optional[Dict[str, Any]]
                              ) -> Tuple[List[Tuple[str, List[Tuple[float, float]], str]], List[float]]:
    """(specs, per-midpoint tolerances in m). Specs are ("route", points, label) for a loop through the rider's midpoints, in the rider's order:
    the plain route, routes whose way back avoids the way out (several corridor strengths), and, when those
    come out short of the target, opposite-side detour loops at a ladder of heights.
    Raises MidpointError for a midpoint the profile cannot reach."""
    async with httpx.AsyncClient(timeout=20.0) as client:
        plain = await _leg_chain(client, [start] + list(vias) + [start], gh_profile, custom_model)
        tols = [VIA_TOLERANCE_M] * len(vias)
        if plain is not None:
            coords, base_m = plain
            for i, (lat, lon) in enumerate(vias, start=1):
                near = min(haversine_m(c, [lon, lat]) for c in coords)
                if near > VIA_TOLERANCE_M:
                    raise MidpointError(f"Midpoint {i} is not on a way this profile can ride (the route passes "
                                        f"{near:.0f} m away). Move it onto a trail or road.")
                tols[i - 1] = min(near + VIA_SNAP_SLACK_M, VIA_TOLERANCE_M)
        else:
            base_m = None
        chains = await asyncio.gather(*[_avoiding_anchors(client, start, vias, gh_profile, custom_model, f, w)
                                        for f, w in VIA_AVOID_VARIANTS])
    specs: List[Tuple[str, List[Tuple[float, float]], str]] = [("route", [start] + list(vias) + [start], "Via Loop")]
    longest = base_m or 0.0
    for (f, w), res in zip(VIA_AVOID_VARIANTS, chains):
        if res is not None:
            specs.append(("route", res[0], f"loop avoiding the way out ({f:g}, {w:.0f} m)"))
            longest = max(longest, res[1])
    if longest < 0.9 * target_m:
        specs.extend(("route", pts, label) for pts, label in via_loop_specs(start, vias)[1:])
    return specs, tols


async def _leg_chain(client, points, gh_profile, cm) -> Optional[Tuple[List[List[float]], float]]:
    resp = await _query_gh(client, points, gh_profile, cm)
    try:
        if resp is None or resp.status_code != 200:
            return None
        path = resp.json()["paths"][0]
        return decode_points(path.get("points", {})), float(path["distance"])
    except Exception:
        return None


DEAD_END_NOTICE = ("A midpoint can only be reached by a spur that you ride out and back, so part of this route "
                   "repeats the same trail. Move the midpoint to a through trail for a true loop.")


def passes_vias(coords: List[List[float]], vias: List[Tuple[float, float]], tol_m: Any = VIA_TOLERANCE_M) -> bool:
    """True when the route passes within tol_m of every midpoint (lat, lon); tol_m is one distance or one per midpoint."""
    tols = list(tol_m) if isinstance(tol_m, (list, tuple)) else [tol_m] * len(vias)
    for (lat, lon), tol in zip(vias, tols):
        if not any(haversine_m(c, [lon, lat]) <= tol for c in coords):
            return False
    return True


def passes_vias_in_order(coords: List[List[float]], vias: List[Tuple[float, float]], tol_m: Any = VIA_TOLERANCE_M) -> bool:
    """True when the route reaches the midpoints in the rider's order: an ordered subsequence, each midpoint
    within its tolerance after the previous one (a route may pass one early, on the way to another, and
    again later)."""
    tols = list(tol_m) if isinstance(tol_m, (list, tuple)) else [tol_m] * len(vias)
    pos = -1
    for (lat, lon), tol in zip(vias, tols):
        nxt = next((j for j in range(pos + 1, len(coords)) if haversine_m(coords[j], [lon, lat]) <= tol), None)
        if nxt is None:
            return False
        pos = nxt
    return True


async def _check_vias_on_network(vias: List[Tuple[float, float]]) -> None:
    """A midpoint with no rideable way near it is a clear error, never a fabricated line (C2, C4)."""
    async with httpx.AsyncClient(timeout=6.0) as client:
        for i, (lat, lon) in enumerate(vias, start=1):
            try:
                r = await client.get(f"{settings.graphhopper_url}/nearest", params={"point": f"{lat},{lon}"})
                dist = float(r.json()["distance"]) if r.status_code == 200 else None
            except Exception:
                dist = None  # GraphHopper unreachable: the routing calls will say so
            if dist is not None and dist > VIA_TOLERANCE_M:
                raise MidpointError(f"Midpoint {i} is {dist:.0f} m from the nearest way. Move it onto a trail or road.")


async def plan_route_options(
    req: RouteRequest,
    count: int = 10,
    user_id: Optional[str] = None
) -> OptionsResult:
    """Every candidate source (GraphHopper corridors and sectors, trail-graph loops, seed loops)
    goes through the one route builder, then the gates and selection (plan 6.1-6.4)."""
    cfg = get_config()
    target_miles = req.target_distance_miles or 10.0
    target_m = target_miles / METERS_TO_MILES
    is_loop = req.is_loop or req.route_mode in ("loop", "round_trip") or (req.end is None and req.route_mode != "out_and_back")
    start_lat, start_lon = req.start.lat, req.start.lon
    gh_profile = get_gh_profile(req.profile)
    custom_model = build_custom_model(req)
    road_budget_m = effective_road_cap(req, cfg) / 100.0 * target_m

    excluded_ways: Set[int] = set()
    if user_id and not req.override_dnr:
        excluded_ways = {d["edge_osm_id"] for d in get_user_dnr_list(user_id) if d.get("edge_osm_id")}

    raw: List[Tuple[List[List[float]], List[Piece], str, str]] = []  # coords, pieces, label, source
    suggestion: Optional[str] = None
    via_repeats = False

    async def gh_round(specs: List[Tuple[str, Any, str]]):
        async with httpx.AsyncClient(timeout=12.0) as client:
            tasks = []
            for kind, arg, _ in specs:
                if kind == "corridor":
                    tasks.append(generate_corridor_loop_candidate(client, start_lat, start_lon, arg[0], arg[1], gh_profile, custom_model))
                else:
                    tasks.append(_query_gh(client, arg, gh_profile, custom_model))
            results = await asyncio.gather(*tasks, return_exceptions=True)
        for (kind, arg, label), res in zip(specs, results):
            path = None
            if isinstance(res, dict):
                path = res
            elif res is not None and not isinstance(res, Exception) and getattr(res, "status_code", 0) == 200:
                data = res.json()
                path = data["paths"][0] if data.get("paths") else None
            if path:
                coords, pieces = graphhopper_candidate(path)
                if len(coords) >= 2:
                    raw.append((coords, pieces, label, "graphhopper"))

    def loop_specs(radius_scale: float, degrees: List[float], inner: bool, lollipop_degs: List[float]):
        specs = []
        base_r = target_m / 3.8 * radius_scale
        for deg in degrees:
            name, _, _ = get_sector_info(deg)
            dest = _ring(start_lat, start_lon, base_r * (0.75 if inner else 1.0), deg)
            specs.append(("corridor", dest, f"{name} Loop"))
        for deg in lollipop_degs:
            name, _, _ = get_sector_info(deg)
            stem = _ring(start_lat, start_lon, base_r * 0.35, deg)
            l1 = _ring(stem[0], stem[1], base_r * 0.65, deg - 28.0)
            l2 = _ring(stem[0], stem[1], base_r * 0.65, deg + 28.0)
            pts = [(start_lat, start_lon), stem, l1, l2, stem, (start_lat, start_lon)]
            specs.append(("route", pts, f"{name} Lollipop"))
        return specs

    vias = [(w.lat, w.lon) for w in (req.waypoints or [])] if is_loop else []

    if is_loop and vias:
        # A loop through the rider's midpoints: start -> midpoints in order -> start, with a detour
        # on the longest leg so the length can reach the target. Graph and seed loops are kept only
        # if they happen to pass every midpoint (checked below with the other candidates).
        widen = None
        await _check_vias_on_network(vias)
        specs, via_tols = await via_candidate_specs(vias, (start_lat, start_lon), target_m, gh_profile, custom_model)
        seed = int(abs(start_lat * 1e5) + abs(start_lon * 1e5) + target_miles * 10) % (2 ** 31)
        graph_task = asyncio.to_thread(_graph_loop_candidates, req, target_m, seed, excluded_ways, road_budget_m)
        (graph_cands, suggestion), _ = await asyncio.gather(graph_task, gh_round(specs))
        raw.extend((c, p, lbl, "graph_loop") for c, p, lbl in graph_cands)
        raw.extend(_seed_candidates(req, target_miles, user_id))
        raw[:] = [r for r in raw if passes_vias_in_order(r[0], vias, via_tols)]
        raw[:], via_repeats = filter_via_repetition(raw)
    elif is_loop:
        seed = int(abs(start_lat * 1e5) + abs(start_lon * 1e5) + target_miles * 10) % (2 ** 31)
        graph_task = asyncio.to_thread(_graph_loop_candidates, req, target_m, seed, excluded_ways, road_budget_m)
        gh_task = gh_round(loop_specs(1.0, [i * 30.0 for i in range(12)], False, [45.0, 135.0, 225.0, 315.0])
                           + loop_specs(1.0, [0.0, 90.0, 180.0, 270.0], True, []))
        (graph_cands, suggestion), _ = await asyncio.gather(graph_task, gh_task)
        raw.extend((c, p, lbl, "graph_loop") for c, p, lbl in graph_cands)
        raw.extend(_seed_candidates(req, target_miles, user_id))

        async def widen():
            """6.4: more sectors at other radii and a second graph-search seed."""
            nonlocal suggestion
            graph_task = asyncio.to_thread(_graph_loop_candidates, req, target_m, seed + 7919, excluded_ways, road_budget_m)
            gh_task = gh_round(loop_specs(1.3, [15.0 + i * 30.0 for i in range(12)], False, [0.0, 90.0, 180.0, 270.0])
                               + loop_specs(0.7, [15.0 + i * 30.0 for i in range(12)], False, []))
            (more_graph, more_suggestion), _ = await asyncio.gather(graph_task, gh_task)
            raw.extend((c, p, lbl, "graph_loop") for c, p, lbl in more_graph)
            suggestion = suggestion or more_suggestion
    else:
        widen = None
        # Point to point: start -> midpoints (in order) -> end; detours vary the longest leg.
        end = req.end or req.start
        stops = [(start_lat, start_lon)] + [(w.lat, w.lon) for w in (req.waypoints or [])] + [(end.lat, end.lon)]
        specs = [("route", list(stops), "Direct")]
        legs = [(i, haversine_m([stops[i][1], stops[i][0]], [stops[i + 1][1], stops[i + 1][0]])) for i in range(len(stops) - 1)]
        li, leg_m = max(legs, key=lambda x: x[1])
        a, b = stops[li], stops[li + 1]
        heading = math.degrees(math.atan2((b[1] - a[1]) * math.cos(math.radians(a[0])), b[0] - a[0]))
        extra = max(500.0, target_m - sum(m for _, m in legs)) / 2.0 if req.target_distance_miles else max(500.0, leg_m * 0.3)
        for frac in (0.3, 0.5, 0.7):
            mid = (a[0] + (b[0] - a[0]) * frac, a[1] + (b[1] - a[1]) * frac)
            for off in (-1.2, -0.8, -0.4, 0.4, 0.8, 1.2):
                side = heading + (90.0 if off > 0 else -90.0)
                det = _ring(mid[0], mid[1], abs(off) * extra, side)
                pts = stops[:li + 1] + [det] + stops[li + 1:]
                name, _, _ = get_sector_info(side)
                specs.append(("route", pts, f"{name} Corridor"))
        await gh_round(specs)

    scored: List[Tuple[RouteResponse, Dict[int, float]]] = []
    sources: Dict[str, int] = {}
    user_ridden = get_user_ridden_edge_ids(user_id, sport=req.profile.value) if user_id else None
    covered = is_region_covered(start_lat, start_lon)

    def score_new(from_index: int) -> None:
        new = raw[from_index:]
        ways_needed = sorted({pc.way_id for _, pieces, _, _ in new for pc in pieces if pc.way_id is not None})
        heat_cache = get_edges_heat(ways_needed, req.profile.value, user_id=user_id)
        for idx, (coords, pieces, label, source) in enumerate(new, start=from_index):
            if req.target_distance_miles:
                miles = sum(haversine_m(coords[i], coords[i + 1]) for i in range(len(coords) - 1)) * METERS_TO_MILES
                if abs(miles - req.target_distance_miles) / req.target_distance_miles > 0.50 \
                        or miles < 0.25 * req.target_distance_miles:
                    continue  # never an option (6.4); skip the expensive build
            ways = [pc.way_id for pc in pieces if pc.way_id is not None]
            trust = check_route_trust_layer({"type": "LineString", "coordinates": coords}, ways,
                                            user_id=user_id, sport=req.profile.value)
            if trust["has_unwaived_hard_blocks"] and req.avoid_closed:
                continue
            cand_id = f"opt_{idx + 1}"
            if req.override_dnr and trust.get("soft_dnr"):
                for sd in trust["soft_dnr"]:
                    log_dnr_override(user_id=user_id, route_id=cand_id, dnr_id=sd.get("id"), edge_osm_id=sd.get("edge_osm_id"),
                                     reason="Candidate selected with soft DNR override")
            built = build_route_response(coords, pieces, req, source, user_id, cand_id=cand_id, label=label,
                                         heat_cache=heat_cache, user_ridden=user_ridden, covered=covered, trust_result=trust)
            scored.append((built.route, built.way_lengths))
            sources[source] = sources.get(source, 0) + 1

    score_new(0)
    options = select_options([(r, w) for r, w in scored], req, count, is_loop)
    if widen is not None and (len(raw) < 40 or len(options) < count):
        before = len(raw)
        await widen()
        score_new(before)
    options = select_options(scored, req, count, is_loop)
    has_true_loop = any(o.route_type == "loop" for o in options)
    if is_loop and has_true_loop:
        suggestion = None
    for o in options:
        o.nearby_start_suggestion = suggestion
    notice = DEAD_END_NOTICE if via_repeats and options else None
    if len(options) < 5:
        notice = " ".join(x for x in (notice, f"Only {len(options)} route{'s' if len(options) != 1 else ''} match; "
                                       "try a different start or distance.") if x)
        if suggestion:
            notice += f" {suggestion}."
    return OptionsResult(options, notice, suggestion, len(scored), sources)


def _seed_candidates(req: RouteRequest, target_miles: float, user_id: Optional[str]):
    """Seed loops from riders' own imported rides (plan 7.4), as (coords, pieces, label, source)."""
    from app.garmin_seeds import seed_catalog
    out = []
    for seed in seed_catalog.get_matching_seeds(req.start.lat, req.start.lon, target_miles, sport=req.profile.value,
                                                user_id=user_id):
        try:
            built = seed_catalog.build_candidate(seed, req)
        except Exception:
            built = None
        if built:
            coords, pieces = built
            out.append((coords, pieces, "Ridden Loop", "seed_loop"))
    return out


async def generate_route_options(
    req: RouteRequest,
    count: int = 10,
    user_id: Optional[str] = None
) -> List[RouteResponse]:
    return (await plan_route_options(req, count=count, user_id=user_id)).options


async def generate_route_options_stream(
    req: RouteRequest,
    count: int = 10,
    user_id: Optional[str] = None
) -> AsyncGenerator[RouteResponse, None]:
    """Yields the selected options one by one for SSE streaming."""
    options = await generate_route_options(req, count=count, user_id=user_id)
    for opt in options:
        yield opt
        await asyncio.sleep(0.01)


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

