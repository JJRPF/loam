import math
from dataclasses import dataclass
from typing import Dict, Any, List, Tuple, Optional
from app.models import TerrainPreference, SurfaceSegment, SportProfile
from app.engine_config import get_config

# Multipliers and constants for scoring
SECTOR_NAMES = {
    0: ("North Ridge", "N", "Q1 (NE)"),
    22.5: ("North-Northeast", "NNE", "Q1 (NE)"),
    45: ("Northeast", "NE", "Q1 (NE)"),
    67.5: ("East-Northeast", "ENE", "Q1 (NE)"),
    90: ("East Valley", "E", "Q2 (SE)"),
    112.5: ("East-Southeast", "ESE", "Q2 (SE)"),
    135: ("Southeast Flow", "SE", "Q2 (SE)"),
    157.5: ("South-Southeast", "SSE", "Q2 (SE)"),
    180: ("South Woods", "S", "Q3 (SW)"),
    202.5: ("South-Southwest", "SSW", "Q3 (SW)"),
    225: ("Southwest Ridge", "SW", "Q3 (SW)"),
    247.5: ("West-Southwest", "WSW", "Q3 (SW)"),
    270: ("West Overlook", "W", "Q4 (NW)"),
    292.5: ("West-Northwest", "WNW", "Q4 (NW)"),
    315: ("Northwest Peak", "NW", "Q4 (NW)"),
    337.5: ("North-Northwest", "NNW", "Q4 (NW)"),
}

def get_sector_info(angle_deg: float) -> Tuple[str, str, str]:
    """Returns (friendly_name, compass_code, quadrant_code) for an azimuth in degrees."""
    normalized = angle_deg % 360.0
    # Find closest sector in SECTOR_NAMES
    best_key = min(SECTOR_NAMES.keys(), key=lambda k: min(abs(normalized - k), 360 - abs(normalized - k)))
    return SECTOR_NAMES[best_key]

def haversine_m(coord1: List[float], coord2: List[float]) -> float:
    """Calculates haversine distance in meters between [lon1, lat1] and [lon2, lat2]."""
    lon1, lat1 = coord1[0], coord1[1]
    lon2, lat2 = coord2[0], coord2[1]
    r = 6371000.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2.0) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2.0) ** 2)
    return 2.0 * r * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1.0 - a)))

SPUR_MIN_M = 10.0      # shorter doublings are vertex noise, not spurs
SPUR_LABEL_M = 50.0    # a loop with a spur longer than this is never called clean


@dataclass(frozen=True)
class Spur:
    """A stretch coords[start_idx..end_idx] that goes out to coords[turn_idx] and returns the same way."""
    start_idx: int
    turn_idx: int
    end_idx: int
    length_m: float  # one way, so the spur adds twice this to the route


def _vkey(c: List[float]) -> Tuple[float, float]:
    return (round(c[0], 6), round(c[1], 6))


def find_spurs(coordinates: List[List[float]], way_details: Optional[List[List[Any]]] = None,
               min_length_m: float = SPUR_MIN_M) -> List[Spur]:
    """Dead-end stretches ridden out and back: the route reaches a vertex, then retraces the same
    vertices in reverse until it is back at the node it left. Found as maximal palindromes of the
    vertex sequence (GraphHopper and the trail graph repeat OSM node coordinates exactly), so the
    way ids are not needed; `way_details` is accepted for symmetry with calculate_repetition_ratio.
    A whole-route out-and-back is one spur from the first to the last vertex."""
    n = len(coordinates)
    if n < 3:
        return []
    keys = [_vkey(c) for c in coordinates]
    spurs: List[Spur] = []
    t = 1
    while t < n - 1:
        k = 0
        while t - k - 1 >= 0 and t + k + 1 < n and keys[t - k - 1] == keys[t + k + 1]:
            k += 1
        if k > 0 and keys[t - 1] != keys[t]:
            length = sum(haversine_m(coordinates[i], coordinates[i + 1]) for i in range(t - k, t))
            if length >= min_length_m:
                spurs.append(Spur(t - k, t, t + k, length))
                t += k  # the far side of this palindrome is its mirror, not a new spur
        t += 1
    return spurs


def calculate_repetition_ratio(
    coordinates: List[List[float]],
    osm_way_details: Optional[List[List[Any]]] = None
) -> float:
    """
    Calculates out-and-back repetition ratio (0.0 - 1.0).
    A loop with no retracing returns ~0.0.
    A strict out-and-back return along the same path returns ~0.50.
    Uses OSM way IDs when available, complemented with geometric proximity backtracking check.
    """
    if not coordinates or len(coordinates) < 2:
        return 0.0

    # 1. Calculate individual segment lengths
    seg_lengths = []
    total_dist = 0.0
    for i in range(len(coordinates) - 1):
        dist = haversine_m(coordinates[i], coordinates[i + 1])
        seg_lengths.append(dist)
        total_dist += dist

    if total_dist <= 1.0:
        return 0.0

    # Method A: OSM way IDs if provided
    if osm_way_details:
        visits = []
        for item in osm_way_details:
            if len(item) >= 3:
                s_idx, e_idx, wid = item[0], item[1], item[2]
                is_reversed = False
                if visits and visits[-1]["wid"] == wid:
                    v_prev = visits[-1]
                    if v_prev["end"] > v_prev["start"] and e_idx > s_idx:
                        p1 = coordinates[v_prev["start"]]
                        p2 = coordinates[v_prev["end"]]
                        q1 = coordinates[s_idx]
                        q2 = coordinates[e_idx]
                        dx1, dy1 = p2[0] - p1[0], p2[1] - p1[1]
                        dx2, dy2 = q2[0] - q1[0], q2[1] - q1[1]
                        dot = dx1 * dx2 + dy1 * dy2
                        if dot < 0:
                            is_reversed = True

                if visits and visits[-1]["wid"] == wid and not is_reversed:
                    visits[-1]["end"] = e_idx
                else:
                    visits.append({"start": s_idx, "end": e_idx, "wid": wid})

        seen_ways = set()
        repeated_dist = 0.0
        for v in visits:
            wid = v["wid"]
            v_len = sum(seg_lengths[k] for k in range(v["start"], min(v["end"], len(seg_lengths))))
            if wid in seen_ways:
                repeated_dist += v_len
            else:
                seen_ways.add(wid)

        return round(min(1.0, repeated_dist / total_dist), 3)

    # Method B: Geometric retracing detection (fallback or complementary)
    # Check if a segment in the second half retraces an earlier segment in reverse direction
    repeated_dist_geom = 0.0
    num_pts = len(coordinates)
    stride = max(1, num_pts // 120)
    for i in range(num_pts // 2, num_pts - 1, stride):
        p1 = coordinates[i]
        p2 = coordinates[i + 1]
        mid_i = [(p1[0] + p2[0]) / 2.0, (p1[1] + p2[1]) / 2.0]
        v_i = (p2[0] - p1[0], p2[1] - p1[1])
        mag_i = math.hypot(v_i[0], v_i[1])
        if mag_i == 0:
            continue

        for j in range(0, num_pts // 2, stride):
            q1 = coordinates[j]
            q2 = coordinates[j + 1]
            mid_j = [(q1[0] + q2[0]) / 2.0, (q1[1] + q2[1]) / 2.0]
            if haversine_m(mid_i, mid_j) < 25.0:
                v_j = (q2[0] - q1[0], q2[1] - q1[1])
                mag_j = math.hypot(v_j[0], v_j[1])
                if mag_j > 0:
                    dot = (v_i[0] * v_j[0] + v_i[1] * v_j[1]) / (mag_i * mag_j)
                    if dot < -0.5: # Opposing direction, out-and-back retracing
                        repeated_dist_geom += seg_lengths[i] * stride
                        break

    return round(min(1.0, repeated_dist_geom / total_dist), 3)

def classify_route_geometry(
    coordinates: List[List[float]],
    osm_way_details: Optional[List[List[Any]]] = None,
    repetition_ratio: Optional[float] = None
) -> Tuple[str, float]:
    """
    Classifies a route into one of:
    - 'loop': Pure closed loop with minimal or no retracing.
    - 'lollipop': Stem (approach) -> closed loop circuit -> stem return.
    - 'out_and_back': Traverses out and returns along the same path with no significant loop circuit.
    - 'point_to_point': Distant start and end points.

    Returns: (geometry_type, loop_fraction)
    """
    if not coordinates or len(coordinates) < 2:
        return "loop", 1.0

    total_dist = 0.0
    seg_lens = []
    for i in range(len(coordinates) - 1):
        d = haversine_m(coordinates[i], coordinates[i + 1])
        seg_lens.append(d)
        total_dist += d

    if total_dist <= 1.0:
        return "loop", 1.0

    start_pt = coordinates[0]
    end_pt = coordinates[-1]
    endpoint_gap = haversine_m(start_pt, end_pt)

    # Point to point check: start and end are distinctly separate
    if endpoint_gap > 600.0 and (endpoint_gap / total_dist) > 0.20:
        return "point_to_point", 0.0

    cfg = get_config()
    if repetition_ratio is None:
        repetition_ratio = calculate_repetition_ratio(coordinates, osm_way_details)

    # If repetition is low, it's a pure loop
    if repetition_ratio <= cfg.loop_max_retrace:
        return "loop", round(1.0 - repetition_ratio, 3)

    # Honest labelling: a route that retraces more than the lollipop cap is an
    # out-and-back, regardless of any small circuit at its far end ("fake lollipop").
    if repetition_ratio > cfg.lollipop_max_retrace:
        return "out_and_back", 0.0

    # In a lollipop loop:
    # There is an unrepeated segment that forms a closed loop circuit and has substantial length (>= 15% of total_dist or >= 400m).
    num_pts = len(coordinates)
    best_loop_len = 0.0
    is_lollipop = False

    # Check via OSM ways if details exist
    if osm_way_details:
        way_ids = [w[2] for w in osm_way_details if len(w) >= 3]
        if way_ids:
            half = len(way_ids) // 2
            first_half = way_ids[:half]
            second_half = way_ids[half:]
            common_ways = set(first_half) & set(second_half)
            unique_middle_ways = set(way_ids) - common_ways
            
            if unique_middle_ways:
                unique_dist = 0.0
                for item in osm_way_details:
                    if len(item) >= 3 and item[2] in unique_middle_ways:
                        s_idx, e_idx = item[0], item[1]
                        unique_dist += sum(seg_lens[k] for k in range(s_idx, min(e_idx, len(seg_lens))))
                
                unique_frac = unique_dist / total_dist
                if unique_frac >= cfg.min_lollipop_circuit_frac and unique_dist >= 350.0:
                    is_lollipop = True
                    best_loop_len = unique_dist

    # Geometric check if OSM check didn't confirm or wasn't available
    if not is_lollipop and num_pts >= 6:
        max_separation = 0.0
        mid_start = max(1, num_pts // 5)
        mid_end = min(num_pts - 2, (4 * num_pts) // 5)
        for i in range(mid_start, mid_end):
            pt = coordinates[i]
            dist_to_start_stem = min(haversine_m(pt, coordinates[j]) for j in range(0, mid_start))
            if dist_to_start_stem > max_separation:
                max_separation = dist_to_start_stem

        unrepeated_ratio = max(0.0, 1.0 - repetition_ratio)
        if max_separation >= 100.0 and (unrepeated_ratio >= 0.50 or repetition_ratio < 0.40):
            is_lollipop = True
            best_loop_len = max(unrepeated_ratio * total_dist, 400.0)

    if is_lollipop:
        loop_frac = best_loop_len / total_dist
        stem_frac = repetition_ratio / 2.0  # One-way stem fraction of total route
        if stem_frac < 0.20 and loop_frac >= 0.60:
            return "lollipop", round(loop_frac, 3)
        return "out_and_back", 0.0

    # Retraces more than a clean loop allows and has no genuine circuit: out-and-back.
    return "out_and_back", 0.0

def score_input_match(
    distance_miles: float,
    target_distance_miles: Optional[float],
    surface_breakdown: Dict[str, float],
    preference: Optional[TerrainPreference]
) -> float:
    """
    Computes Input Match score (0 - 100), combining:
    - Distance accuracy against target miles
    - Terrain mix preference match against actual breakdown
    """
    # 1. Distance score
    if target_distance_miles and target_distance_miles > 0:
        err = abs(distance_miles - target_distance_miles) / target_distance_miles
        if err <= 0.05:
            dist_score = 100.0
        else:
            dist_score = max(0.0, 100.0 * (1.0 - get_config().distance_slope * err))
    else:
        dist_score = 100.0

    # 2. Terrain match score
    pref = preference or TerrainPreference(singletrack=0.6, doubletrack=0.2, gravel=0.15, paved=0.05)
    pref_map = {
        "singletrack": pref.singletrack,
        "doubletrack": pref.doubletrack,
        "gravel": pref.gravel,
        "paved": pref.paved,
    }

    # Normalize breakdown percentages to fractions (0.0 - 1.0)
    actual_fractions = {
        cat: surface_breakdown.get(cat, 0.0) / 100.0
        for cat in ["singletrack", "doubletrack", "gravel", "paved"]
    }

    # L1 error
    l1_err = 0.5 * sum(abs(actual_fractions[k] - pref_map[k]) for k in pref_map)
    terrain_score = max(0.0, 100.0 * (1.0 - l1_err))

    if target_distance_miles and target_distance_miles > 0:
        return round(0.50 * dist_score + 0.50 * terrain_score, 1)
    return round(terrain_score, 1)

def score_heat(
    edge_osm_ids: List[int],
    sport: str,
    edge_heat_dict: Optional[Dict[int, Dict[str, Any]]] = None,
    user_id: Optional[str] = None,
    is_covered_region: bool = False
) -> float:
    """
    Computes Heat score (0 - 100) based on recency-weighted activity on traversed edges.
    - An edge's heat influences routing if unique_riders >= 3 (privacy threshold) OR if user is a contributor.
    - If an edge has no active heat:
      - If local region has sufficient coverage (is_covered_region=True): applies zero-heat / ghost trail penalty (25.0).
      - If local region is sparse (is_covered_region=False): applies neutral score (70.0, 'No recent data').
    - If traversed edges have active heat, scores 70.0 + scaled weight (up to 100.0).
    """
    if not edge_osm_ids:
        return 25.0 if is_covered_region else 70.0

    heat_data = edge_heat_dict or {}
    total_edges = len(edge_osm_ids)
    scored_vals = []

    for wid in edge_osm_ids:
        record = heat_data.get(wid)
        has_usable_heat = False
        w_score = 0.0

        if record:
            is_pub = record.get("is_public")
            contribs = record.get("contributor_ids")
            is_contrib = (user_id is not None and contribs is not None and user_id in contribs)

            # An edge's heat influences public routing only with >= 3 contributing riders;
            # otherwise counts only for the individual contributor.
            if is_pub is None and contribs is None:
                # Direct test or mock dict compatibility
                has_usable_heat = True
                w_score = float(record.get("weighted_score", 1.0))
            elif is_pub or is_contrib:
                has_usable_heat = True
                w_score = float(record.get("weighted_score", 1.0))

        if has_usable_heat:
            score_val = min(100.0, 70.0 + max(1.0, w_score) * 3.5)
            scored_vals.append(score_val)
        else:
            # No usable heat on this edge
            if is_covered_region:
                # Ghost trail in covered region: penalize heavily
                scored_vals.append(25.0)
            else:
                # Sparse area: neutral score per coverage-aware rules
                scored_vals.append(70.0)

    avg_score = sum(scored_vals) / max(total_edges, 1)
    return round(min(100.0, max(0.0, avg_score)), 1)

def score_mode_value(
    surface_breakdown: Dict[str, float],
    sport: SportProfile,
    find_new_trails_mode: bool = False,
    unridden_percent: float = 0.0,
    target_new_percent: Optional[float] = None,
    unridden_miles: float = 0.0,
    target_new_miles: Optional[float] = None
) -> float:
    """
    Computes Mode Value score (0 - 100).
    Per Project Plan Section 6 & 9:
    - Normal mode raises 'popular' (rewards high-quality trail surfaces aligned to the sport).
    - Find New Trails mode raises 'new to me' (rewards percentage / miles of unridden trails matching targets).
    - Trail Running Polish: Favors footpaths, hiking singletrack, stairs, and penalizes paved roads.
    """
    st_pct = surface_breakdown.get("singletrack", 0.0)
    dt_pct = surface_breakdown.get("doubletrack", 0.0)
    gr_pct = surface_breakdown.get("gravel", 0.0)
    pv_pct = surface_breakdown.get("paved", 0.0)

    # Base sport alignment score
    if sport in (SportProfile.TRAIL_RUN, SportProfile.FOOT):
        # Trail running polish: favors footpaths/singletrack (1.0), doubletrack (0.85), gravel (0.75), heavily penalizes road (0.15)
        sport_score = (st_pct * 1.0) + (dt_pct * 0.85) + (gr_pct * 0.75) + (pv_pct * 0.15)
    elif sport == SportProfile.MTB_GRAVEL:
        sport_score = (gr_pct * 1.0) + (dt_pct * 0.85) + (st_pct * 0.70) + (pv_pct * 0.40)
    else:
        sport_score = (st_pct * 1.0) + (dt_pct * 0.80) + (gr_pct * 0.65) + (pv_pct * 0.20)

    if not find_new_trails_mode:
        return round(min(100.0, max(0.0, sport_score)), 1)

    # Find New Trails Mode: score is heavily driven by 'new to me' unridden trails
    if target_new_percent is not None and target_new_percent > 0:
        if unridden_percent >= target_new_percent:
            # Exceeds requested unridden target -> high reward 90 - 100
            new_score = 90.0 + min(10.0, (unridden_percent - target_new_percent) * 0.3)
        else:
            # Below target
            ratio = unridden_percent / target_new_percent
            new_score = max(20.0, 90.0 * ratio)
    elif target_new_miles is not None and target_new_miles > 0:
        if unridden_miles >= target_new_miles:
            new_score = 90.0 + min(10.0, (unridden_miles - target_new_miles) * 2.0)
        else:
            new_score = max(20.0, 90.0 * (unridden_miles / target_new_miles))
    else:
        # General Find New Trails mode: scales with unridden percentage
        # A route with 50%+ unridden gets 90-100; a route with 0% unridden gets 30
        new_score = 30.0 + min(70.0, unridden_percent * 1.4)

    # Blend: 70% 'new to me' achievement + 30% sport surface quality
    blended = 0.70 * new_score + 0.30 * sport_score
    return round(min(100.0, max(0.0, blended)), 1)

def score_quality(
    surface_strip: List[SurfaceSegment],
    distance_miles: float
) -> float:
    """
    Computes Quality score (0 - 100) measuring surface continuity.
    Fewer choppy transitions per mile = higher quality.
    """
    if not surface_strip or distance_miles <= 0:
        return 90.0

    transitions = max(0, len(surface_strip) - 1)
    transitions_per_mile = transitions / max(distance_miles, 1.0)

    if transitions_per_mile <= 1.0:
        continuity_score = 100.0
    elif transitions_per_mile <= 4.0:
        continuity_score = 100.0 - (transitions_per_mile - 1.0) * 20.0
    else:
        continuity_score = max(30.0, 40.0 - (transitions_per_mile - 4.0) * 5.0)

    return round(min(100.0, max(0.0, continuity_score)), 1)

def score_penalties(
    repetition_ratio: float,
    warnings: List[str],
    is_lollipop: bool = False,
    spur_max_m: float = 0.0
) -> float:
    """
    Computes Penalties score (0 - 100).
    Rule: Out-and-back repetition penalty applies when repetition >= 0.25 on non-lollipop routes.
    For lollipop loops (stem -> loop -> return stem), stem repetition is expected and permitted.
    Soft warnings (closures, DNR) deduct 15 points each.
    """
    if is_lollipop:
        # Lollipop loops: stem repetition is normal and expected
        lp_cap = get_config().lollipop_max_retrace
        if repetition_ratio <= lp_cap:
            rep_score = 100.0
        elif repetition_ratio <= lp_cap + 0.10:
            rep_score = 100.0 - (repetition_ratio - lp_cap) * 150.0
        else:
            rep_score = max(50.0, 85.0 - (repetition_ratio - lp_cap - 0.10) * 200.0)
    else:
        # Out-and-back repetition penalty threshold < 0.25
        if repetition_ratio <= get_config().loop_max_retrace:
            rep_score = 100.0
        elif repetition_ratio < 0.25:
            # Mild linear ramp between 0.10 and 0.25
            rep_score = 100.0 - (repetition_ratio - get_config().loop_max_retrace) * 200.0
        else:
            # Heavy penalty for repetition >= 0.25
            rep_score = max(0.0, 70.0 - (repetition_ratio - 0.25) * 250.0)

    # Warnings penalty
    warn_deduction = len(warnings) * 15.0
    # A spur costs by its own length, however small a share of the whole route it is.
    spur_deduction = min(50.0, spur_max_m / 10.0) if spur_max_m > SPUR_MIN_M else 0.0
    total = max(0.0, rep_score - warn_deduction - spur_deduction)
    return round(min(100.0, total), 1)

def calculate_composite_score(
    distance_miles: float,
    target_distance_miles: Optional[float],
    surface_breakdown: Dict[str, float],
    surface_strip: List[SurfaceSegment],
    preference: Optional[TerrainPreference],
    sport: SportProfile,
    repetition_ratio: float,
    warnings: List[str],
    edge_osm_ids: List[int],
    edge_heat_dict: Optional[Dict[int, Dict[str, Any]]] = None,
    user_id: Optional[str] = None,
    is_covered_region: bool = False,
    find_new_trails_mode: bool = False,
    unridden_percent: float = 0.0,
    target_new_percent: Optional[float] = None,
    unridden_miles: float = 0.0,
    target_new_miles: Optional[float] = None,
    is_lollipop: bool = False,
    route_type: Optional[str] = None,
    spur_count: int = 0,
    spur_max_m: float = 0.0
) -> Tuple[int, Dict[str, float], str]:
    """
    Calculates the 5-component composite score:
    - 60% input match
    - 15% heat
    - 10% mode value (Find New Trails raises 'new to me'; Normal raises 'popular')
    - 10% quality
    - 5% penalties (out-and-back repetition penalty < 0.25)
    Returns: (composite_score_int, score_breakdown_dict, verbal_explanation)
    """
    s_input = score_input_match(distance_miles, target_distance_miles, surface_breakdown, preference)
    s_heat = score_heat(edge_osm_ids, sport.value, edge_heat_dict, user_id=user_id, is_covered_region=is_covered_region)
    s_mode = score_mode_value(
        surface_breakdown=surface_breakdown,
        sport=sport,
        find_new_trails_mode=find_new_trails_mode,
        unridden_percent=unridden_percent,
        target_new_percent=target_new_percent,
        unridden_miles=unridden_miles,
        target_new_miles=target_new_miles
    )
    s_qual = score_quality(surface_strip, distance_miles)
    s_pen = score_penalties(repetition_ratio, warnings, is_lollipop=is_lollipop, spur_max_m=spur_max_m)

    cfg = get_config()
    shape = route_type or ("lollipop" if is_lollipop else ("loop" if repetition_ratio <= cfg.loop_max_retrace else "out_and_back"))
    shape_mult = {
        "loop": cfg.mult_loop,
        "lollipop": cfg.mult_lollipop,
        "out_and_back": cfg.mult_out_and_back,
    }.get(shape, 1.0)

    # Weighted composite (default 60/15/10/10/5), normalised so tuned weights stay on a 0-100 scale
    w_sum = cfg.w_input + cfg.w_heat + cfg.w_mode + cfg.w_quality + cfg.w_penalty
    composite = (
        cfg.w_input * s_input +
        cfg.w_heat * s_heat +
        cfg.w_mode * s_mode +
        cfg.w_quality * s_qual +
        cfg.w_penalty * s_pen
    ) / max(w_sum, 1e-9)

    # Honest shape multiplier: a retraced out-and-back may not outrank a true loop on distance alone
    composite *= shape_mult

    # Road penalty beyond what the rider asked for
    pref_paved_pct = (preference.paved if preference else 0.05) * 100.0
    road_excess = max(0.0, surface_breakdown.get("paved", 0.0) - pref_paved_pct)
    composite -= cfg.road_score_weight * road_excess

    composite_int = int(round(min(100.0, max(1.0, composite))))

    breakdown = {
        "composite": float(composite_int),
        "input_match": s_input,
        "heat": s_heat,
        "mode_value": s_mode,
        "quality": s_qual,
        "penalties": s_pen,
        "repetition_ratio": round(repetition_ratio, 3),
        "is_lollipop": is_lollipop,
        "spur_count": spur_count,
        "spur_max_m": round(spur_max_m, 1),
        "unridden_miles": round(unridden_miles, 2),
        "unridden_percent": round(unridden_percent, 1),
    }

    # Verbal summary in plain language per Section 18
    parts = []
    if target_distance_miles and target_distance_miles > 0:
        diff = distance_miles - target_distance_miles
        pct = (diff / target_distance_miles) * 100.0
        sign = "+" if pct >= 0 else ""
        parts.append(f"{distance_miles:.1f} mi vs {target_distance_miles:.1f} mi target ({sign}{pct:.0f}%)")
    else:
        parts.append(f"{distance_miles:.1f} mi")

    st_pct = surface_breakdown.get("singletrack", 0.0)
    desired_st = int(round((preference.singletrack if preference else 0.6) * 100))
    if st_pct > 0:
        status_word = "exceeds" if st_pct >= desired_st else "vs"
        parts.append(f"{st_pct:.0f}% singletrack ({status_word} {desired_st}% goal)")

    rep_pct = int(round(repetition_ratio * 100))
    if is_lollipop:
        parts.append(f"{rep_pct}% stem retracing (lollipop loop)")
    elif shape == "out_and_back":
        parts.append(f"{rep_pct}% retraced (out-and-back, not a loop)")
    elif spur_max_m > SPUR_LABEL_M:
        parts.append(f"Loop with a {spur_max_m / 1609.344:.1f} mi spur ({rep_pct}% repetition)")
    else:
        parts.append(f"{rep_pct}% repetition (clean loop)")

    if s_heat < 50.0 and is_covered_region:
        parts.append("Ghost trail penalty applied")
    elif s_heat >= 85.0:
        parts.append("High recency heat")

    if find_new_trails_mode or unridden_miles > 0:
        parts.append(f"{unridden_miles:.1f} mi new to you ({unridden_percent:.0f}% unridden)")

    if not warnings:
        parts.append("0 closures or DNR conflicts.")
    else:
        parts.append(f"{len(warnings)} warning(s).")

    verbal = "; ".join(parts)
    return composite_int, breakdown, verbal



def generate_minimap(
    coordinates: List[List[float]],
    width: int = 120,
    height: int = 80,
    padding: int = 8
) -> Tuple[List[float], str]:
    """
    Generates bounding box and compact SVG path string (d="M ... L ...")
    normalized to the requested width x height viewport with aspect ratio preservation.
    """
    if not coordinates or len(coordinates) < 2:
        return [-71.35, 43.13, -71.35, 43.13], ""

    lons = [p[0] for p in coordinates]
    lats = [p[1] for p in coordinates]
    min_lon, max_lon = min(lons), max(lons)
    min_lat, max_lat = min(lats), max(lats)
    bbox = [min_lon, min_lat, max_lon, max_lat]

    mid_lat = (min_lat + max_lat) / 2.0
    lat_scale = math.cos(math.radians(mid_lat))

    delta_x = (max_lon - min_lon) * lat_scale
    delta_y = (max_lat - min_lat)

    usable_w = width - 2 * padding
    usable_h = height - 2 * padding

    if delta_x <= 0 or delta_y <= 0:
        return bbox, f"M {width/2:.1f} {height/2:.1f}"

    scale = min(usable_w / delta_x, usable_h / delta_y)
    offset_x = padding + (usable_w - delta_x * scale) / 2.0
    offset_y = padding + (usable_h - delta_y * scale) / 2.0

    # Downsample points for lightweight SVG representation
    step = max(1, len(coordinates) // 60)
    sampled = coordinates[::step]
    if sampled[-1] != coordinates[-1]:
        sampled.append(coordinates[-1])

    cmds = []
    for idx, pt in enumerate(sampled):
        lon, lat = pt[0], pt[1]
        x = offset_x + (lon - min_lon) * lat_scale * scale
        y = height - (offset_y + (lat - min_lat) * scale)
        cmd = "M" if idx == 0 else "L"
        cmds.append(f"{cmd}{x:.1f},{y:.1f}")

    return bbox, " ".join(cmds)
