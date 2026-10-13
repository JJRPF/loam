import math
import datetime
from typing import List, Dict, Any, Optional, Tuple

WINDOW_DAYS = 365.0
HALF_LIFE_DAYS = 182.5  # ~6 months
COVERAGE_CELL_SIZE_DEG = 0.05  # ~3.5 miles lat, ~2.5 miles lon
COVERAGE_THRESHOLD_ACTIVITIES = 3  # min 3 activities for sufficient coverage

HEAT_SPORTS = {
    "mtb": "mtb", "mtb_hardtail": "mtb", "mtb_fullsus": "mtb", "mtb_fat": "mtb", "mtb_emtb": "mtb",
    "gravel": "gravel", "mtb_gravel": "gravel", "bike": "gravel",
    "trail_run": "trail_run", "foot": "trail_run", "run": "trail_run", "hike": "trail_run",
}


def heat_sport(sport_or_profile: Optional[str]) -> str:
    """Heat is kept per sport (mtb, gravel, trail_run); every profile maps to one of them."""
    s = (sport_or_profile or "mtb").lower()
    return HEAT_SPORTS.get(s, "trail_run" if "run" in s or "foot" in s else "mtb")


def min_unique_riders() -> int:
    from app.config import settings
    return max(1, int(settings.heat_min_unique_riders))


def compute_recency_weight(visited_at: datetime.datetime, ref_date: Optional[datetime.datetime] = None) -> float:
    """
    Computes exponential decay weight with 6-month half life over a 12-month window.
    weight = 2 ^ (-days_ago / 182.5) if days_ago <= 365 else 0.0.
    """
    if ref_date is None:
        ref_date = datetime.datetime.now(datetime.timezone.utc)
    elif ref_date.tzinfo is None:
        ref_date = ref_date.replace(tzinfo=datetime.timezone.utc)

    if visited_at.tzinfo is None:
        visited_at = visited_at.replace(tzinfo=datetime.timezone.utc)

    delta_seconds = (ref_date - visited_at).total_seconds()
    days_ago = max(0.0, delta_seconds / 86400.0)

    if days_ago > WINDOW_DAYS:
        return 0.0

    return 2.0 ** (-days_ago / HALF_LIFE_DAYS)

def aggregate_edge_visits(
    visits: List[Dict[str, Any]],
    ref_date: Optional[datetime.datetime] = None
) -> Dict[str, Any]:
    """
    Aggregates edge visits for a single edge and sport:
    - Applies exponential decay
    - Counts unique riders
    - Checks the unique-riders privacy threshold (HEAT_MIN_UNIQUE_RIDERS, 3 by default)
    - Tracks contributor IDs
    """
    if not visits:
        return {
            "unique_riders": 0,
            "total_passes": 0,
            "weighted_score": 0.0,
            "is_public": False,
            "contributor_ids": [],
            "last_ridden_date": None
        }

    contributors = set()
    total_passes = 0
    weighted_score = 0.0
    latest_dt = None

    for v in visits:
        uid = str(v.get("user_id", ""))
        v_dt = v.get("visited_at")
        p_cnt = int(v.get("pass_count", 1))

        if not v_dt:
            continue

        w = compute_recency_weight(v_dt, ref_date)
        if w > 0.0:
            contributors.add(uid)
            total_passes += p_cnt
            weighted_score += (w * p_cnt)
            if latest_dt is None or v_dt > latest_dt:
                latest_dt = v_dt

    unique_riders = len(contributors)
    is_public = (unique_riders >= min_unique_riders())

    return {
        "unique_riders": unique_riders,
        "total_passes": total_passes,
        "weighted_score": round(weighted_score, 3),
        "is_public": is_public,
        "contributor_ids": sorted(list(contributors)),
        "last_ridden_date": latest_dt.date().isoformat() if latest_dt else None
    }

def get_grid_cell(lat: float, lon: float, cell_size: float = COVERAGE_CELL_SIZE_DEG) -> Tuple[str, float, float, float, float]:
    """
    Maps a (lat, lon) to a discrete grid cell ID and its bounding box.
    """
    min_lat = math.floor(lat / cell_size) * cell_size
    min_lon = math.floor(lon / cell_size) * cell_size
    max_lat = min_lat + cell_size
    max_lon = min_lon + cell_size
    cell_id = f"{min_lat:.2f}:{min_lon:.2f}"
    return cell_id, min_lat, min_lon, max_lat, max_lon
