import math
from typing import List, Dict, Any, Tuple
from app.activity_parser import TrackPoint

TRIM_METERS = 321.8688  # 0.2 miles in meters

def haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Calculates haversine distance in meters between two lat/lon coordinates."""
    r = 6371000.0  # Earth's radius in meters
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2.0) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2.0) ** 2)
    return 2.0 * r * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1.0 - a)))

def trim_ride_endpoints(
    points: List[TrackPoint],
    trim_distance_m: float = TRIM_METERS
) -> Tuple[List[TrackPoint], int, int]:
    """
    Trims the first 0.2 mi and last 0.2 mi of a ride to protect rider start/finish locations.
    Returns (trimmed_points, start_trimmed_count, end_trimmed_count).
    """
    if not points or len(points) < 2:
        return [], 0, 0

    # Calculate segment distances
    cum_dist = [0.0]
    total_dist = 0.0
    for i in range(len(points) - 1):
        d = haversine_m(points[i].lon, points[i].lat, points[i + 1].lon, points[i + 1].lat)
        total_dist += d
        cum_dist.append(total_dist)

    # If entire activity is shorter than both trims combined, prune all
    if total_dist <= (2.0 * trim_distance_m):
        return [], len(points), 0

    # Find start trim index (first point >= trim_distance_m from start)
    start_idx = 0
    while start_idx < len(points) and cum_dist[start_idx] < trim_distance_m:
        start_idx += 1

    # Find end trim index (last point <= total_dist - trim_distance_m)
    end_idx = len(points) - 1
    while end_idx >= 0 and (total_dist - cum_dist[end_idx]) < trim_distance_m:
        end_idx -= 1

    if start_idx > end_idx:
        return [], len(points), 0

    trimmed_pts = points[start_idx : end_idx + 1]
    start_trimmed_count = start_idx
    end_trimmed_count = len(points) - 1 - end_idx

    return trimmed_pts, start_trimmed_count, end_trimmed_count

def exclude_privacy_zones(
    points: List[TrackPoint],
    privacy_zones: List[Dict[str, Any]]
) -> Tuple[List[TrackPoint], int]:
    """
    Filters out any track points located inside a user's defined privacy zones.
    Returns (filtered_points, points_excluded_count).
    """
    if not points or not privacy_zones:
        return points, 0

    filtered = []
    excluded_count = 0

    for pt in points:
        in_zone = False
        for zone in privacy_zones:
            z_lat = float(zone["lat"])
            z_lon = float(zone["lon"])
            z_radius = float(zone.get("radius_m", 320.0))

            dist = haversine_m(pt.lon, pt.lat, z_lon, z_lat)
            if dist <= z_radius:
                in_zone = True
                break

        if in_zone:
            excluded_count += 1
        else:
            filtered.append(pt)

    return filtered, excluded_count

def apply_privacy_filters(
    points: List[TrackPoint],
    privacy_zones: List[Dict[str, Any]],
    trim_distance_m: float = TRIM_METERS
) -> Tuple[List[TrackPoint], Dict[str, Any]]:
    """
    Applies both ride endpoint trimming and privacy zone exclusions.
    """
    raw_count = len(points)
    trimmed_pts, start_trim_cnt, end_trim_cnt = trim_ride_endpoints(points, trim_distance_m)
    zone_filtered_pts, zone_cnt = exclude_privacy_zones(trimmed_pts, privacy_zones)

    stats = {
        "raw_count": raw_count,
        "start_trimmed_count": start_trim_cnt,
        "end_trimmed_count": end_trim_cnt,
        "privacy_zone_excluded_count": zone_cnt,
        "retained_count": len(zone_filtered_pts),
        "is_empty": len(zone_filtered_pts) == 0
    }

    return zone_filtered_pts, stats
