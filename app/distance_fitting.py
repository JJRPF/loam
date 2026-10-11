"""
Distance Fitting for Loam Loop Routes.
Applies local edits to fit generated loops toward the user's requested target distance:
1. Shortcut Connector Joins: trims long loops (e.g. trims a 14.1 mi loop toward 10 mi target)
   when a shorter connector trail joins two junctions on the loop circuit.
2. Detour Side Loops: extends loops when the generated candidate is shorter than requested.
"""
import math
from typing import Dict, Any, List, Tuple, Optional
from app.scoring import haversine_m, calculate_repetition_ratio

METERS_TO_MILES = 0.000621371192


def fit_loop_distance(
    path_dict: Dict[str, Any],
    target_miles: float,
    tolerance: float = 0.15,
    graph: Optional[Any] = None
) -> Dict[str, Any]:
    """
    Trims or extends a loop candidate toward target_miles using shortcut connector joins
    or detour extensions.
    """
    coords = path_dict.get("points", {}).get("coordinates", [])
    if len(coords) < 10 or not target_miles or target_miles <= 0:
        return path_dict

    total_dist_m = float(path_dict.get("distance", 0.0))
    current_miles = total_dist_m * METERS_TO_MILES
    err = (current_miles - target_miles) / target_miles

    # If already within tolerance, keep as is
    if abs(err) <= tolerance:
        return path_dict

    num_pts = len(coords)
    seg_dists: List[float] = [
        haversine_m(coords[k], coords[k + 1]) for k in range(num_pts - 1)
    ]
    cum_dists: List[float] = [0.0]
    for d in seg_dists:
        cum_dists.append(cum_dists[-1] + d)

    # 1. Trimming Long Loops via Shortcut Connector Joins (e.g. 14.1 mi -> 10.0 mi)
    if err > tolerance:
        target_trim_m = (current_miles - target_miles) / METERS_TO_MILES
        best_shortcut = None
        best_score_diff = float("inf")

        # Scan for pairs of non-adjacent route points (i, j) that are close in space
        step = max(1, num_pts // 80)
        for i in range(1, num_pts - 10, step):
            for j in range(i + 15, num_pts - 1, step):
                route_dist_between = cum_dists[j] - cum_dists[i]
                direct_dist = haversine_m(coords[i], coords[j])

                # A valid shortcut joins two points that are geographically close (< 300m)
                # while bypassing a substantial route loop (saving between 1km and 6km)
                if direct_dist <= 250.0 and route_dist_between > (direct_dist + 800.0):
                    savings_m = route_dist_between - direct_dist
                    diff_from_ideal = abs(savings_m - target_trim_m)

                    if diff_from_ideal < best_score_diff:
                        best_score_diff = diff_from_ideal
                        best_shortcut = (i, j, direct_dist, savings_m)

        if best_shortcut and best_score_diff < target_trim_m * 0.70:
            i, j, direct_dist, savings = best_shortcut
            # Splice route: coords[0..i] + intermediate connector + coords[j..end]
            new_coords = coords[:i + 1] + coords[j:]
            new_dist_m = total_dist_m - savings

            # Adjust details
            new_details = {}
            for k, items in path_dict.get("details", {}).items():
                adjusted = []
                for it in items:
                    if len(it) >= 3:
                        s_idx, e_idx, val = it[0], it[1], it[2]
                        if e_idx <= i:
                            adjusted.append([s_idx, e_idx, val])
                        elif s_idx >= j:
                            shift = j - (i + 1)
                            adjusted.append([max(i + 1, s_idx - shift), max(i + 1, e_idx - shift), val])
                new_details[k] = adjusted

            rep_ratio = calculate_repetition_ratio(new_coords, new_details.get("osm_way_id"))
            retraced_miles = round((new_dist_m * METERS_TO_MILES) * rep_ratio, 2)

            trimmed_path = dict(path_dict)
            trimmed_path["distance"] = new_dist_m
            trimmed_path["points"] = {"type": "LineString", "coordinates": new_coords}
            trimmed_path["details"] = new_details
            trimmed_path["repetition_ratio"] = rep_ratio
            trimmed_path["retraced_miles"] = retraced_miles
            trimmed_path["trimmed_via_shortcut"] = True
            return trimmed_path

    # 2. Extending Short Loops via Detour Side Loop
    elif err < -tolerance:
        needed_extra_m = (target_miles - current_miles) / METERS_TO_MILES
        # If area graph available with side loops, splice side loop at closest junction
        if graph and hasattr(graph, "adjacency"):
            best_detour = None
            best_diff = float("inf")

            for k in range(len(coords) // 4, (3 * len(coords)) // 4, max(1, len(coords) // 30)):
                pt = coords[k]
                j_id, d_m = graph.find_nearest_junction(pt[1], pt[0])
                if j_id != -1 and d_m < 80.0:
                    for nxt, edge in graph.adjacency.get(j_id, []):
                        edge_m = edge.length_m
                        if abs(edge_m * 2.0 - needed_extra_m) < best_diff and edge_m >= 400.0:
                            best_diff = abs(edge_m * 2.0 - needed_extra_m)
                            best_detour = (k, edge)

            if best_detour and best_diff < needed_extra_m * 0.75:
                k, edge = best_detour
                detour_coords = edge.coordinates + list(reversed(edge.coordinates))[1:]
                new_coords = coords[:k] + detour_coords + coords[k:]
                new_dist_m = total_dist_m + (edge.length_m * 2.0)

                extended_path = dict(path_dict)
                extended_path["distance"] = new_dist_m
                extended_path["points"] = {"type": "LineString", "coordinates": new_coords}
                extended_path["extended_via_detour"] = True
                return extended_path

    return path_dict
