import math
from typing import Dict, Any, List, Tuple, Optional
from app.models import TerrainPreference, SurfaceSegment, SportProfile

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
            dist_score = max(0.0, 100.0 * (1.0 - 1.5 * err))
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
    edge_heat_dict: Optional[Dict[int, Dict[str, Any]]] = None
) -> float:
    """
    Computes Heat score (0 - 100) based on recency-weighted activity on traversed edges.
    Where no activity is recorded, applies neutral score (70.0) per coverage-aware plan rules.
    """
    if not edge_osm_ids:
        return 70.0

    heat_data = edge_heat_dict or {}
    total_edges = len(edge_osm_ids)
    scored_vals = []

    for wid in edge_osm_ids:
        record = heat_data.get(wid)
        if record:
            w_score = float(record.get("weighted_score", 1.0))
            score_val = min(100.0, 70.0 + w_score * 3.0)
            scored_vals.append(score_val)
        else:
            scored_vals.append(70.0)

    avg_score = sum(scored_vals) / max(total_edges, 1)
    return round(min(100.0, max(0.0, avg_score)), 1)

def score_mode_value(
    surface_breakdown: Dict[str, float],
    sport: SportProfile
) -> float:
    """
    Computes Mode Value score (0 - 100) based on trail quality and sport alignment.
    Rewards singletrack for MTB; rewards footpaths/trails for Trail Run.
    """
    st_pct = surface_breakdown.get("singletrack", 0.0)
    dt_pct = surface_breakdown.get("doubletrack", 0.0)
    gr_pct = surface_breakdown.get("gravel", 0.0)
    pv_pct = surface_breakdown.get("paved", 0.0)

    if sport in (SportProfile.TRAIL_RUN, SportProfile.FOOT):
        score = (st_pct * 1.0) + (dt_pct * 0.85) + (gr_pct * 0.75) + (pv_pct * 0.35)
    elif sport == SportProfile.MTB_GRAVEL:
        score = (gr_pct * 1.0) + (dt_pct * 0.85) + (st_pct * 0.70) + (pv_pct * 0.40)
    else:
        score = (st_pct * 1.0) + (dt_pct * 0.80) + (gr_pct * 0.65) + (pv_pct * 0.20)

    return round(min(100.0, max(0.0, score)), 1)

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
    warnings: List[str]
) -> float:
    """
    Computes Penalties score (0 - 100).
    Rule: Out-and-back repetition penalty applies when repetition >= 0.25.
    Soft warnings (closures, DNR) deduct 15 points each.
    """
    # Out-and-back repetition penalty threshold < 0.25
    if repetition_ratio <= 0.10:
        rep_score = 100.0
    elif repetition_ratio < 0.25:
        # Mild linear ramp between 0.10 and 0.25
        rep_score = 100.0 - (repetition_ratio - 0.10) * 200.0
    else:
        # Heavy penalty for repetition >= 0.25
        rep_score = max(0.0, 70.0 - (repetition_ratio - 0.25) * 250.0)

    # Warnings penalty
    warn_deduction = len(warnings) * 15.0
    total = max(0.0, rep_score - warn_deduction)
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
    edge_heat_dict: Optional[Dict[int, Dict[str, Any]]] = None
) -> Tuple[int, Dict[str, float], str]:
    """
    Calculates the 5-component composite score:
    - 60% input match
    - 15% heat
    - 10% mode value
    - 10% quality
    - 5% penalties (out-and-back repetition penalty < 0.25)
    Returns: (composite_score_int, score_breakdown_dict, verbal_explanation)
    """
    s_input = score_input_match(distance_miles, target_distance_miles, surface_breakdown, preference)
    s_heat = score_heat(edge_osm_ids, sport.value, edge_heat_dict)
    s_mode = score_mode_value(surface_breakdown, sport)
    s_qual = score_quality(surface_strip, distance_miles)
    s_pen = score_penalties(repetition_ratio, warnings)

    # Weighted composite sum: 60% + 15% + 10% + 10% + 5% = 100%
    composite = (
        0.60 * s_input +
        0.15 * s_heat +
        0.10 * s_mode +
        0.10 * s_qual +
        0.05 * s_pen
    )

    composite_int = int(round(min(100.0, max(1.0, composite))))

    breakdown = {
        "composite": float(composite_int),
        "input_match": s_input,
        "heat": s_heat,
        "mode_value": s_mode,
        "quality": s_qual,
        "penalties": s_pen,
        "repetition_ratio": round(repetition_ratio, 3),
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
    if rep_pct < 25:
        parts.append(f"{rep_pct}% repetition (clean loop)")
    else:
        parts.append(f"{rep_pct}% repetition (out-and-back penalty applied)")

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
