import json
import uuid
import datetime
import psycopg2
from psycopg2.extras import RealDictCursor, Json
from typing import Optional, Dict, Any, List
from app.config import settings

def get_connection():
    return psycopg2.connect(settings.database_url)

def check_db_health() -> bool:
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1;")
                return cur.fetchone()[0] == 1
    except Exception:
        return False

def get_edge_heat(edge_osm_id: int, sport: str, user_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT edge_osm_id, sport, unique_riders_12mo, total_passes_12mo,
                           weighted_score, last_ridden_date, is_public, contributor_ids
                    FROM edge_heat
                    WHERE edge_osm_id = %s AND sport = %s;
                    """,
                    (edge_osm_id, sport)
                )
                row = cur.fetchone()
                if not row:
                    return None
                data = dict(row)
                contribs = data.get("contributor_ids") or []
                is_contrib = (user_id is not None and user_id in contribs)
                data["is_contributor"] = is_contrib
                # If neither public (>= 3 riders) nor contributor, public score is 0
                data["is_accessible"] = data.get("is_public", False) or is_contrib
                return data
    except Exception:
        return None

def get_edges_heat(edge_osm_ids: List[int], sport: str, user_id: Optional[str] = None) -> Dict[int, Dict[str, Any]]:
    """
    Batch query edge_heat table for a list of OSM way/edge IDs.
    Filters by the privacy threshold: heat counts only if is_public (>= 3 riders)
    OR if the current user is a contributing rider.
    """
    if not edge_osm_ids:
        return {}
    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT edge_osm_id, sport, unique_riders_12mo, total_passes_12mo,
                           weighted_score, last_ridden_date, is_public, contributor_ids
                    FROM edge_heat
                    WHERE edge_osm_id = ANY(%s) AND sport = %s;
                    """,
                    (edge_osm_ids, sport)
                )
                results: Dict[int, Dict[str, Any]] = {}
                for row in cur.fetchall():
                    item = dict(row)
                    contribs = item.get("contributor_ids") or []
                    is_contrib = (user_id is not None and user_id in contribs)
                    is_pub = item.get("is_public", False)
                    # Privacy rule: influence routes only if >= 3 unique riders OR user is contributor
                    if is_pub or is_contrib:
                        item["is_contributor"] = is_contrib
                        results[item["edge_osm_id"]] = item
                return results
    except Exception:
        return {}

def record_edge_heat(edge_osm_id: int, sport: str, weight: float = 1.0, user_id: Optional[str] = None) -> bool:
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO edges (osm_id) VALUES (%s)
                    ON CONFLICT (osm_id) DO NOTHING;
                    """,
                    (edge_osm_id,)
                )
                contrib_arr = [user_id] if user_id else []
                cur.execute(
                    """
                    INSERT INTO edge_heat (
                        edge_osm_id, sport, unique_riders_12mo, total_passes_12mo,
                        weighted_score, last_ridden_date, is_public, contributor_ids
                    )
                    VALUES (%s, %s, 1, 1, %s, CURRENT_DATE, FALSE, %s)
                    ON CONFLICT (edge_osm_id, sport) DO UPDATE
                    SET total_passes_12mo = edge_heat.total_passes_12mo + 1,
                        weighted_score = edge_heat.weighted_score + EXCLUDED.weighted_score,
                        last_ridden_date = CURRENT_DATE,
                        contributor_ids = CASE
                            WHEN %s IS NOT NULL AND NOT (%s = ANY(edge_heat.contributor_ids))
                            THEN array_append(edge_heat.contributor_ids, %s)
                            ELSE edge_heat.contributor_ids
                        END,
                        unique_riders_12mo = CASE
                            WHEN %s IS NOT NULL AND NOT (%s = ANY(edge_heat.contributor_ids))
                            THEN edge_heat.unique_riders_12mo + 1
                            ELSE edge_heat.unique_riders_12mo
                        END,
                        is_public = (
                            CASE
                                WHEN %s IS NOT NULL AND NOT (%s = ANY(edge_heat.contributor_ids))
                                THEN edge_heat.unique_riders_12mo + 1
                                ELSE edge_heat.unique_riders_12mo
                            END >= 3
                        );
                    """,
                    (
                        edge_osm_id, sport, weight, contrib_arr,
                        user_id, user_id, user_id,
                        user_id, user_id,
                        user_id, user_id
                    )
                )
                conn.commit()
                return True
    except Exception:
        return False


def check_restrictions_along_line(geojson_linestring: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Checks if a route intersects any hard closure or soft DNR."""
    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT id, name, restriction_type, is_hard
                    FROM restrictions
                    WHERE ST_Intersects(geom, ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326));
                    """,
                    (Json(geojson_linestring),)
                )
                return [dict(r) for r in cur.fetchall()]
    except Exception:
        return []

def ensure_user_exists(user_id: str, email: Optional[str] = None, display_name: Optional[str] = None):
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO users (id, email, display_name)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (id) DO UPDATE
                    SET email = COALESCE(EXCLUDED.email, users.email),
                        display_name = COALESCE(EXCLUDED.display_name, users.display_name);
                    """,
                    (user_id, email, display_name)
                )
                conn.commit()
    except Exception as e:
        print(f"Error ensuring user: {e}")

def save_route_to_db(user_id: str, route_data: Dict[str, Any]) -> Optional[str]:
    try:
        ensure_user_exists(user_id, email=route_data.get("user_email"), display_name=route_data.get("user_name"))
        route_id = str(uuid.uuid4())
        
        # Prepare 2D coordinates for LineString
        raw_coords = route_data.get("coordinates", [])
        coords_2d = [[pt[0], pt[1]] for pt in raw_coords] if raw_coords else []
        geojson_geom = {"type": "LineString", "coordinates": coords_2d} if len(coords_2d) >= 2 else None

        surface_summary = {
            "breakdown": route_data.get("surface_breakdown", {}),
            "strip": [s.model_dump() if hasattr(s, "model_dump") else s for s in route_data.get("surface_strip", [])],
            "verbal_summary": route_data.get("verbal_summary")
        }

        with get_connection() as conn:
            with conn.cursor() as cur:
                if geojson_geom:
                    cur.execute(
                        """
                        INSERT INTO saved_routes (
                            id, user_id, name, sport, distance_miles,
                            elevation_gain_ft, elevation_loss_ft,
                            geom, surface_summary, waypoints, created_at
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326), %s, %s, NOW())
                        """,
                        (
                            route_id,
                            user_id,
                            route_data.get("name", "Loam Route"),
                            route_data.get("sport", "mtb"),
                            route_data.get("distance_miles", 0.0),
                            route_data.get("elevation_gain_ft", 0.0),
                            route_data.get("elevation_loss_ft", 0.0),
                            Json(geojson_geom),
                            Json(surface_summary),
                            Json(route_data.get("waypoints") or [])
                        )
                    )
                else:
                    cur.execute(
                        """
                        INSERT INTO saved_routes (
                            id, user_id, name, sport, distance_miles,
                            elevation_gain_ft, elevation_loss_ft,
                            surface_summary, waypoints, created_at
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                        """,
                        (
                            route_id,
                            user_id,
                            route_data.get("name", "Loam Route"),
                            route_data.get("sport", "mtb"),
                            route_data.get("distance_miles", 0.0),
                            route_data.get("elevation_gain_ft", 0.0),
                            route_data.get("elevation_loss_ft", 0.0),
                            Json(surface_summary),
                            Json(route_data.get("waypoints") or [])
                        )
                    )
                conn.commit()
                return route_id
    except Exception as e:
        print(f"Failed to save route: {e}")
        return None

def get_saved_routes_from_db(user_id: str) -> List[Dict[str, Any]]:
    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT id, user_id, name, sport, distance_miles,
                           elevation_gain_ft, elevation_loss_ft, created_at,
                           surface_summary, waypoints
                    FROM saved_routes
                    WHERE user_id = %s
                    ORDER BY created_at DESC;
                    """,
                    (user_id,)
                )
                rows = cur.fetchall()
                results = []
                for row in rows:
                    item = dict(row)
                    item["created_at"] = item["created_at"].isoformat() if item.get("created_at") else ""
                    summary = item.get("surface_summary") or {}
                    item["surface_breakdown"] = summary.get("breakdown", {})
                    item["verbal_summary"] = summary.get("verbal_summary")
                    results.append(item)
                return results
    except Exception as e:
        print(f"Failed to get saved routes: {e}")
        return []

def get_saved_route_by_id(route_id: str, user_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                if user_id:
                    cur.execute(
                        """
                        SELECT id, user_id, name, sport, distance_miles,
                               elevation_gain_ft, elevation_loss_ft, created_at,
                               surface_summary, waypoints, ST_AsGeoJSON(geom) as geojson
                        FROM saved_routes
                        WHERE id = %s AND user_id = %s;
                        """,
                        (route_id, user_id)
                    )
                else:
                    cur.execute(
                        """
                        SELECT id, user_id, name, sport, distance_miles,
                               elevation_gain_ft, elevation_loss_ft, created_at,
                               surface_summary, waypoints, ST_AsGeoJSON(geom) as geojson
                        FROM saved_routes
                        WHERE id = %s;
                        """,
                        (route_id,)
                    )
                row = cur.fetchone()
                if not row:
                    return None
                item = dict(row)
                item["created_at"] = item["created_at"].isoformat() if item.get("created_at") else ""
                summary = item.get("surface_summary") or {}
                item["surface_breakdown"] = summary.get("breakdown", {})
                item["surface_strip"] = summary.get("strip", [])
                item["verbal_summary"] = summary.get("verbal_summary")
                if item.get("geojson"):
                    geo = json.loads(item["geojson"])
                    item["coordinates"] = geo.get("coordinates", [])
                else:
                    item["coordinates"] = []
                return item
    except Exception as e:
        print(f"Failed to get saved route by id: {e}")
        return None

def delete_saved_route_from_db(route_id: str, user_id: Optional[str] = None) -> bool:
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                if user_id:
                    cur.execute(
                        "DELETE FROM saved_routes WHERE id = %s AND user_id = %s;",
                        (route_id, user_id)
                    )
                else:
                    cur.execute("DELETE FROM saved_routes WHERE id = %s;", (route_id,))
                conn.commit()
                return cur.rowcount > 0
    except Exception as e:
        print(f"Failed to delete saved route: {e}")
        return False

# =========================================================================
# Stage 4: Activities, Edge Visits, Privacy Zones, and Regional Coverage
# =========================================================================

def record_activity(activity: Dict[str, Any]) -> bool:
    """Inserts a processed activity into the activities table."""
    try:
        user_id = activity.get("user_id", "justin_default_user")
        ensure_user_exists(user_id)
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO activities (
                        id, user_id, sport, activity_date, created_at,
                        distance_miles, duration_minutes, file_format,
                        raw_file_retained, raw_file_path, consent_given,
                        matched_edge_count
                    )
                    VALUES (%s, %s, %s, %s, NOW(), %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE
                    SET matched_edge_count = EXCLUDED.matched_edge_count;
                    """,
                    (
                        activity["id"],
                        user_id,
                        activity.get("sport", "mtb"),
                        activity.get("activity_date") or datetime.datetime.now(datetime.timezone.utc),
                        activity.get("distance_miles", 0.0),
                        activity.get("duration_minutes", 0.0),
                        activity.get("file_format", "gpx"),
                        activity.get("raw_file_retained", False),
                        activity.get("raw_file_path"),
                        activity.get("consent_given", True),
                        activity.get("matched_edge_count", 0),
                    )
                )
                conn.commit()
                return True
    except Exception as e:
        print(f"Error recording activity: {e}")
        return False

def record_activity_edge_visits(
    activity_id: str,
    edge_counts: Dict[int, int],
    user_id: str,
    sport: str,
    visited_at: Optional[datetime.datetime] = None
) -> int:
    """
    Inserts per-edge visits for an activity and updates edge_heat in PostGIS.
    """
    if not edge_counts:
        return 0

    if visited_at is None:
        visited_at = datetime.datetime.now(datetime.timezone.utc)
    elif visited_at.tzinfo is None:
        visited_at = visited_at.replace(tzinfo=datetime.timezone.utc)

    # Calculate decay weight for today
    now = datetime.datetime.now(datetime.timezone.utc)
    days_ago = max(0.0, (now - visited_at).total_seconds() / 86400.0)
    decay_weight = 2.0 ** (-days_ago / 182.5) if days_ago <= 365.0 else 0.0

    inserted_count = 0
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                ensure_user_exists(user_id)
                for edge_id, pass_count in edge_counts.items():
                    # 1. Ensure edge exists in edges table
                    cur.execute(
                        "INSERT INTO edges (osm_id) VALUES (%s) ON CONFLICT (osm_id) DO NOTHING;",
                        (edge_id,)
                    )
                    # 2. Insert into activity_edge_visits
                    cur.execute(
                        """
                        INSERT INTO activity_edge_visits (
                            activity_id, edge_osm_id, user_id, sport, visited_at, pass_count
                        )
                        VALUES (%s, %s, %s, %s, %s, %s);
                        """,
                        (activity_id, edge_id, user_id, sport, visited_at, pass_count)
                    )
                    # 3. Update edge_heat
                    add_score = decay_weight * pass_count
                    cur.execute(
                        """
                        INSERT INTO edge_heat (
                            edge_osm_id, sport, unique_riders_12mo, total_passes_12mo,
                            weighted_score, last_ridden_date, is_public, contributor_ids
                        )
                        VALUES (%s, %s, 1, %s, %s, %s::date, FALSE, ARRAY[%s])
                        ON CONFLICT (edge_osm_id, sport) DO UPDATE
                        SET total_passes_12mo = edge_heat.total_passes_12mo + EXCLUDED.total_passes_12mo,
                            weighted_score = edge_heat.weighted_score + EXCLUDED.weighted_score,
                            last_ridden_date = GREATEST(edge_heat.last_ridden_date, EXCLUDED.last_ridden_date),
                            contributor_ids = CASE
                                WHEN NOT (%s = ANY(edge_heat.contributor_ids))
                                THEN array_append(edge_heat.contributor_ids, %s)
                                ELSE edge_heat.contributor_ids
                            END,
                            unique_riders_12mo = CASE
                                WHEN NOT (%s = ANY(edge_heat.contributor_ids))
                                THEN edge_heat.unique_riders_12mo + 1
                                ELSE edge_heat.unique_riders_12mo
                            END,
                            is_public = (
                                CASE
                                    WHEN NOT (%s = ANY(edge_heat.contributor_ids))
                                    THEN edge_heat.unique_riders_12mo + 1
                                    ELSE edge_heat.unique_riders_12mo
                                END >= 3
                            );
                        """,
                        (
                            edge_id, sport, pass_count, add_score, visited_at, user_id,
                            user_id, user_id,
                            user_id, user_id,
                            user_id, user_id
                        )
                    )
                    inserted_count += 1
                conn.commit()
    except Exception as e:
        print(f"Error recording activity edge visits: {e}")

    return inserted_count

def get_privacy_zones(user_id: str) -> List[Dict[str, Any]]:
    """Returns active privacy zones for a user."""
    zones = []
    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # 1. From user_privacy_zones table
                cur.execute(
                    """
                    SELECT id, user_id, name, lat, lon, radius_m, created_at
                    FROM user_privacy_zones
                    WHERE user_id = %s
                    ORDER BY id ASC;
                    """,
                    (user_id,)
                )
                for r in cur.fetchall():
                    item = dict(r)
                    item["created_at"] = item["created_at"].isoformat() if item.get("created_at") else ""
                    zones.append(item)

                # 2. From contribution_consent legacy columns if defined and not already in zones
                cur.execute(
                    """
                    SELECT privacy_zone_lat, privacy_zone_lon, privacy_zone_radius_m
                    FROM contribution_consent
                    WHERE user_id = %s AND privacy_zone_lat IS NOT NULL;
                    """,
                    (user_id,)
                )
                r_c = cur.fetchone()
                if r_c and r_c["privacy_zone_lat"] is not None:
                    # check if already added
                    if not any(z["lat"] == r_c["privacy_zone_lat"] and z["lon"] == r_c["privacy_zone_lon"] for z in zones):
                        zones.append({
                            "id": 0,
                            "user_id": user_id,
                            "name": "Consent Zone",
                            "lat": float(r_c["privacy_zone_lat"]),
                            "lon": float(r_c["privacy_zone_lon"]),
                            "radius_m": float(r_c["privacy_zone_radius_m"] or 320.0),
                            "created_at": ""
                        })
    except Exception as e:
        print(f"Error getting privacy zones: {e}")
    return zones

def create_privacy_zone(user_id: str, name: str, lat: float, lon: float, radius_m: float = 320.0) -> Optional[int]:
    """Creates a new privacy zone for a user."""
    try:
        ensure_user_exists(user_id)
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO user_privacy_zones (user_id, name, lat, lon, radius_m, created_at)
                    VALUES (%s, %s, %s, %s, %s, NOW())
                    RETURNING id;
                    """,
                    (user_id, name, lat, lon, radius_m)
                )
                new_id = cur.fetchone()[0]
                conn.commit()
                return new_id
    except Exception as e:
        print(f"Error creating privacy zone: {e}")
        return None

def delete_privacy_zone(zone_id: int, user_id: str) -> bool:
    """Deletes a user's privacy zone."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM user_privacy_zones WHERE id = %s AND user_id = %s;",
                    (zone_id, user_id)
                )
                conn.commit()
                return cur.rowcount > 0
    except Exception as e:
        print(f"Error deleting privacy zone: {e}")
        return False

def get_user_consent(user_id: str) -> bool:
    """Checks whether the user has given consent to contribute heat."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT consent_given FROM contribution_consent WHERE user_id = %s;",
                    (user_id,)
                )
                r = cur.fetchone()
                return bool(r[0]) if r else True  # default True for active contributors
    except Exception:
        return True

def set_user_consent(user_id: str, consent: bool):
    try:
        ensure_user_exists(user_id)
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO contribution_consent (user_id, consent_given, consented_at)
                    VALUES (%s, %s, NOW())
                    ON CONFLICT (user_id) DO UPDATE
                    SET consent_given = EXCLUDED.consent_given,
                        consented_at = NOW();
                    """,
                    (user_id, consent)
                )
                conn.commit()
    except Exception as e:
        print(f"Error setting consent: {e}")

def get_regional_coverage_cell(lat: float, lon: float) -> Optional[Dict[str, Any]]:
    """Fetches regional coverage status for a point's grid cell."""
    import math
    cell_size = 0.05
    min_lat = math.floor(lat / cell_size) * cell_size
    min_lon = math.floor(lon / cell_size) * cell_size
    cell_id = f"{min_lat:.2f}:{min_lon:.2f}"
    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "SELECT cell_id, min_lat, min_lon, max_lat, max_lon, activity_count_12mo, is_sufficient FROM regional_coverage WHERE cell_id = %s;",
                    (cell_id,)
                )
                r = cur.fetchone()
                if r:
                    return dict(r)
                return {
                    "cell_id": cell_id,
                    "min_lat": min_lat,
                    "min_lon": min_lon,
                    "max_lat": min_lat + cell_size,
                    "max_lon": min_lon + cell_size,
                    "activity_count_12mo": 0,
                    "is_sufficient": False
                }
    except Exception:
        return None

def is_region_covered(lat: float, lon: float) -> bool:
    """Returns True if the region around lat/lon has sufficient activity coverage."""
    cell = get_regional_coverage_cell(lat, lon)
    return bool(cell and cell.get("is_sufficient"))

def recalculate_regional_coverage(threshold: int = 3) -> int:
    """
    Recalculates regional coverage grid across all activities in the last 12 months.
    """
    import math
    updated_count = 0
    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Group activities by bounding cell using edges or saved coordinates
                # We can compute cell from visited edges' locations or activities
                cur.execute(
                    """
                    SELECT a.id, e.geom
                    FROM activity_edge_visits v
                    JOIN activities a ON v.activity_id = a.id
                    JOIN edges e ON v.edge_osm_id = e.osm_id
                    WHERE v.visited_at >= NOW() - INTERVAL '365 days'
                      AND e.geom IS NOT NULL;
                    """
                )
                rows = cur.fetchall()
                cell_activity_map: Dict[str, set] = {}
                cell_coords: Dict[str, Tuple[float, float, float, float]] = {}

                for r in rows:
                    act_id = r["activity_id"]
                    # If geom exists, get point
                    cur.execute("SELECT ST_Y(ST_Centroid(%s::geometry)), ST_X(ST_Centroid(%s::geometry));", (r["geom"], r["geom"]))
                    pt = cur.fetchone()
                    if pt and pt[0] is not None:
                        lat, lon = float(pt[0]), float(pt[1])
                        min_lat = math.floor(lat / 0.05) * 0.05
                        min_lon = math.floor(lon / 0.05) * 0.05
                        c_id = f"{min_lat:.2f}:{min_lon:.2f}"
                        if c_id not in cell_activity_map:
                            cell_activity_map[c_id] = set()
                            cell_coords[c_id] = (min_lat, min_lon, min_lat + 0.05, min_lon + 0.05)
                        cell_activity_map[c_id].add(act_id)

                for c_id, act_set in cell_activity_map.items():
                    cnt = len(act_set)
                    is_suff = (cnt >= threshold)
                    b = cell_coords[c_id]
                    cur.execute(
                        """
                        INSERT INTO regional_coverage (cell_id, min_lat, min_lon, max_lat, max_lon, activity_count_12mo, is_sufficient, updated_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
                        ON CONFLICT (cell_id) DO UPDATE
                        SET activity_count_12mo = EXCLUDED.activity_count_12mo,
                            is_sufficient = EXCLUDED.is_sufficient,
                            updated_at = NOW();
                        """,
                        (c_id, b[0], b[1], b[2], b[3], cnt, is_suff)
                    )
                    updated_count += 1
                conn.commit()
    except Exception as e:
        print(f"Error recalculating regional coverage: {e}")
    return updated_count

def recalculate_all_edge_heat(ref_date: Optional[datetime.datetime] = None) -> Dict[str, Any]:
    """
    Nightly background worker recalculation:
    1. Reads all activity_edge_visits in the 12-month window.
    2. Computes exponential decay (6-month half-life).
    3. Aggregates unique riders and applies >= 3 riders privacy threshold.
    4. Upserts edge_heat and zeros out edges with no visits.
    5. Recalculates regional coverage grid.
    """
    if ref_date is None:
        ref_date = datetime.datetime.now(datetime.timezone.utc)
    elif ref_date.tzinfo is None:
        ref_date = ref_date.replace(tzinfo=datetime.timezone.utc)

    start_time = datetime.datetime.now(datetime.timezone.utc)
    window_start = ref_date - datetime.timedelta(days=365)

    stats = {
        "edges_updated": 0,
        "public_edges_count": 0,
        "private_edges_count": 0,
        "coverage_cells_updated": 0,
        "ghost_trails_detected": 0,
        "duration_seconds": 0.0
    }

    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # 1. Fetch all visits within 12 months
                cur.execute(
                    """
                    SELECT edge_osm_id, sport, user_id, visited_at, pass_count
                    FROM activity_edge_visits
                    WHERE visited_at >= %s;
                    """,
                    (window_start,)
                )
                visits = cur.fetchall()

                # Group by (edge_osm_id, sport)
                edge_groups: Dict[Tuple[int, str], List[Dict[str, Any]]] = {}
                for v in visits:
                    key = (v["edge_osm_id"], v["sport"])
                    if key not in edge_groups:
                        edge_groups[key] = []
                    edge_groups[key].append(v)

                # 2. Recalculate each edge's decayed heat
                for (edge_id, sport), v_list in edge_groups.items():
                    contribs = set()
                    total_passes = 0
                    weighted_score = 0.0
                    max_date = None

                    for v in v_list:
                        uid = str(v["user_id"])
                        v_dt = v["visited_at"]
                        if v_dt.tzinfo is None:
                            v_dt = v_dt.replace(tzinfo=datetime.timezone.utc)
                        p_cnt = int(v.get("pass_count", 1))

                        days_ago = max(0.0, (ref_date - v_dt).total_seconds() / 86400.0)
                        if days_ago <= 365.0:
                            w = 2.0 ** (-days_ago / 182.5)
                            contribs.add(uid)
                            total_passes += p_cnt
                            weighted_score += (w * p_cnt)
                            if max_date is None or v_dt > max_date:
                                max_date = v_dt

                    u_count = len(contribs)
                    is_pub = (u_count >= 3)
                    contrib_arr = sorted(list(contribs))

                    cur.execute(
                        """
                        INSERT INTO edge_heat (
                            edge_osm_id, sport, unique_riders_12mo, total_passes_12mo,
                            weighted_score, last_ridden_date, is_public, contributor_ids
                        )
                        VALUES (%s, %s, %s, %s, %s, %s::date, %s, %s)
                        ON CONFLICT (edge_osm_id, sport) DO UPDATE
                        SET unique_riders_12mo = EXCLUDED.unique_riders_12mo,
                            total_passes_12mo = EXCLUDED.total_passes_12mo,
                            weighted_score = EXCLUDED.weighted_score,
                            last_ridden_date = EXCLUDED.last_ridden_date,
                            is_public = EXCLUDED.is_public,
                            contributor_ids = EXCLUDED.contributor_ids;
                        """,
                        (
                            edge_id, sport, u_count, total_passes,
                            round(weighted_score, 3), max_date, is_pub, contrib_arr
                        )
                    )
                    stats["edges_updated"] += 1
                    if is_pub:
                        stats["public_edges_count"] += 1
                    else:
                        stats["private_edges_count"] += 1

                # 3. Edges with no visits in last 365 days -> reset to 0
                cur.execute(
                    """
                    UPDATE edge_heat
                    SET unique_riders_12mo = 0,
                        total_passes_12mo = 0,
                        weighted_score = 0.0,
                        is_public = FALSE
                    WHERE last_ridden_date < %s::date;
                    """,
                    (window_start,)
                )

                conn.commit()

        # 4. Recalculate regional coverage grid
        cells_updated = recalculate_regional_coverage()
        stats["coverage_cells_updated"] = cells_updated

    except Exception as e:
        print(f"Error in recalculate_all_edge_heat: {e}")

    duration = (datetime.datetime.now(datetime.timezone.utc) - start_time).total_seconds()
    stats["duration_seconds"] = round(duration, 3)
    return stats

