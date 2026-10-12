import re
import json
import uuid
import datetime
import psycopg2
from psycopg2.extras import RealDictCursor, Json
from typing import Optional, Dict, Any, List
from app.config import settings
from app.decay import heat_sport, min_unique_riders

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
    Heat is looked up per heat sport (a routing profile like mtb_hardtail maps to mtb).
    Batch query edge_heat table for a list of OSM way/edge IDs.
    Filters by the privacy threshold: heat counts only if is_public (>= 3 riders)
    OR if the current user is a contributing rider.
    """
    if not edge_osm_ids:
        return {}
    sport = heat_sport(sport)
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
                           surface_summary, waypoints, ST_AsGeoJSON(geom) as geojson
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
                    item["surface_strip"] = summary.get("strip", [])
                    item["verbal_summary"] = summary.get("verbal_summary")
                    if item.get("geojson"):
                        try:
                            geo = json.loads(item["geojson"])
                            item["coordinates"] = geo.get("coordinates", [])
                        except Exception:
                            item["coordinates"] = []
                    else:
                        item["coordinates"] = []
                    results.append(item)
                return results
    except Exception as e:
        print(f"Failed to get saved routes: {e}")
        return []
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
        user_id = activity["user_id"]
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
                    SET matched_edge_count = EXCLUDED.matched_edge_count
                    WHERE activities.user_id = EXCLUDED.user_id;
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
    sport = heat_sport(sport)

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
                cur.execute("DELETE FROM activity_edge_visits WHERE activity_id = %s;", (activity_id,))
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
                        VALUES (%s, %s, 1, %s, %s, %s::date, TRUE, ARRAY[%s])
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
                            is_public = TRUE;
                        """,
                        (
                            edge_id, sport, pass_count, add_score, visited_at, user_id,
                            user_id, user_id,
                            user_id
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
                    is_pub = (u_count >= min_unique_riders())
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

                # 3. Heat is derived from visits only: any row without a visit in the window
                #    (aged out, or its activity was deleted) is reset to 0.
                cur.execute(
                    """
                    UPDATE edge_heat h
                    SET unique_riders_12mo = 0,
                        total_passes_12mo = 0,
                        weighted_score = 0.0,
                        is_public = FALSE,
                        contributor_ids = '{}'
                    WHERE NOT EXISTS (
                        SELECT 1 FROM activity_edge_visits v
                        WHERE v.edge_osm_id = h.edge_osm_id AND v.sport = h.sport AND v.visited_at >= %s
                    );
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

# =========================================================================
# Stage 5: Trust Layer Database Operations
# Flags, Check-ins, DNR, Restrictions, Waivers, and Privacy Compliance
# =========================================================================

def create_community_flag(
    edge_osm_id: int,
    flag_type: str,
    user_id: str,
    details: Optional[str] = None
) -> Dict[str, Any]:
    """
    Submits a community trail flag (gone, blocked, closed, seasonal).
    Initializes confirmed_count=1 and registers the creator's vote.
    """
    ensure_user_exists(user_id)
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("INSERT INTO edges (osm_id) VALUES (%s) ON CONFLICT (osm_id) DO NOTHING;", (edge_osm_id,))
            cur.execute(
                """
                INSERT INTO flags (edge_osm_id, flag_type, user_id, confirmed_count, disputed_count, status, details, created_at)
                VALUES (%s, %s, %s, 1, 0, 'active', %s, NOW())
                RETURNING id, edge_osm_id, flag_type, user_id, confirmed_count, disputed_count, status, details, created_at;
                """,
                (edge_osm_id, flag_type, user_id, details)
            )
            row = cur.fetchone()
            flag_data = dict(row)
            flag_id = flag_data["id"]

            # Record vote from creator
            cur.execute(
                """
                INSERT INTO flag_votes (flag_id, user_id, vote_type, created_at)
                VALUES (%s, %s, 'confirm', NOW())
                ON CONFLICT (flag_id, user_id) DO NOTHING;
                """,
                (flag_id, user_id)
            )

            # If 'gone' flag, reduce edge confidence score
            if flag_type == "gone":
                cur.execute(
                    "UPDATE edges SET confidence_score = GREATEST(0.1, COALESCE(confidence_score, 1.0) - 0.25) WHERE osm_id = %s;",
                    (edge_osm_id,)
                )

            conn.commit()
            flag_data["created_at"] = flag_data["created_at"].isoformat() if flag_data.get("created_at") else ""
            return flag_data

def vote_community_flag(flag_id: int, user_id: str, vote_type: str) -> Dict[str, Any]:
    """
    Abuse-resistant voting on a community flag.
    Enforces 1 vote per user per flag.
    Recalculates confirmed/disputed counts and updates status (active, verified, dismissed).
    """
    ensure_user_exists(user_id)
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT id, edge_osm_id, flag_type, status FROM flags WHERE id = %s;", (flag_id,))
            flag = cur.fetchone()
            if not flag:
                raise ValueError("Flag not found")

            # Check previous vote
            cur.execute("SELECT vote_type FROM flag_votes WHERE flag_id = %s AND user_id = %s;", (flag_id, user_id))
            prev_vote = cur.fetchone()
            if prev_vote and prev_vote["vote_type"] == vote_type:
                raise ValueError("User has already submitted this vote for this flag")

            cur.execute(
                """
                INSERT INTO flag_votes (flag_id, user_id, vote_type, created_at)
                VALUES (%s, %s, %s, NOW())
                ON CONFLICT (flag_id, user_id) DO UPDATE
                SET vote_type = EXCLUDED.vote_type, created_at = NOW();
                """,
                (flag_id, user_id, vote_type)
            )

            # Recount votes
            cur.execute(
                """
                SELECT
                    COUNT(CASE WHEN vote_type = 'confirm' THEN 1 END) AS confirmed_cnt,
                    COUNT(CASE WHEN vote_type = 'dispute' THEN 1 END) AS disputed_cnt
                FROM flag_votes
                WHERE flag_id = %s;
                """,
                (flag_id,)
            )
            counts = cur.fetchone()
            conf_cnt = int(counts["confirmed_cnt"])
            disp_cnt = int(counts["disputed_cnt"])

            # Determine abuse-resistant status
            if disp_cnt >= conf_cnt + 2 and conf_cnt < 3:
                new_status = "dismissed"
            elif conf_cnt >= 2:
                new_status = "verified"
            else:
                new_status = "active"

            cur.execute(
                """
                UPDATE flags
                SET confirmed_count = %s, disputed_count = %s, status = %s
                WHERE id = %s
                RETURNING id, edge_osm_id, flag_type, user_id, confirmed_count, disputed_count, status, details, created_at;
                """,
                (conf_cnt, disp_cnt, new_status, flag_id)
            )
            updated = dict(cur.fetchone())
            conn.commit()
            updated["created_at"] = updated["created_at"].isoformat() if updated.get("created_at") else ""
            return updated

def get_community_flags(
    edge_osm_id: Optional[int] = None,
    status: Optional[str] = "active",
    limit: int = 100
) -> List[Dict[str, Any]]:
    """Fetches community flags with optional edge and status filters."""
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            query = "SELECT id, edge_osm_id, flag_type, user_id, confirmed_count, disputed_count, status, details, created_at FROM flags WHERE 1=1"
            params: List[Any] = []
            if edge_osm_id is not None:
                query += " AND edge_osm_id = %s"
                params.append(edge_osm_id)
            if status is not None and status.lower() != "all":
                query += " AND status = %s"
                params.append(status)
            query += " ORDER BY created_at DESC LIMIT %s;"
            params.append(limit)

            cur.execute(query, tuple(params))
            rows = cur.fetchall()
            results = []
            for r in rows:
                item = dict(r)
                item["created_at"] = item["created_at"].isoformat() if item.get("created_at") else ""
                results.append(item)
            return results

def record_trail_checkin(
    edge_osm_id: int,
    user_id: str,
    status: str = "open",
    note: Optional[str] = None
) -> Dict[str, Any]:
    """
    Records a one-tap rider check-in ("still open").
    Refreshes trail confidence and recency:
    1. Updates edges.check_date = CURRENT_DATE and confidence_score.
    2. Updates edge_heat.last_ridden_date = CURRENT_DATE.
    3. Counters/resolves stale 'gone' flags if check-ins confirm active status.
    """
    ensure_user_exists(user_id)
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("INSERT INTO edges (osm_id) VALUES (%s) ON CONFLICT (osm_id) DO NOTHING;", (edge_osm_id,))

            cur.execute(
                """
                INSERT INTO trail_checkins (edge_osm_id, user_id, status, note, checked_in_at)
                VALUES (%s, %s, %s, %s, NOW())
                RETURNING id, edge_osm_id, user_id, status, note, checked_in_at;
                """,
                (edge_osm_id, user_id, status, note)
            )
            checkin = dict(cur.fetchone())

            # Refresh confidence score and check_date on edge
            cur.execute(
                """
                UPDATE edges
                SET check_date = CURRENT_DATE,
                    confidence_score = LEAST(1.0, COALESCE(confidence_score, 0.7) + 0.2)
                WHERE osm_id = %s
                RETURNING confidence_score;
                """,
                (edge_osm_id,)
            )
            c_row = cur.fetchone()
            conf_score = float(c_row["confidence_score"]) if c_row else 1.0

            # Update edge_heat last_ridden_date
            cur.execute(
                """
                UPDATE edge_heat
                SET last_ridden_date = CURRENT_DATE
                WHERE edge_osm_id = %s;
                """,
                (edge_osm_id,)
            )

            # Auto-resolve stale 'gone' or 'blocked' flags if verified by check-ins
            cur.execute(
                """
                SELECT COUNT(*) as c_count FROM trail_checkins
                WHERE edge_osm_id = %s AND checked_in_at >= NOW() - INTERVAL '14 days';
                """,
                (edge_osm_id,)
            )
            recent_cnt = cur.fetchone()["c_count"]
            if recent_cnt >= 2:
                cur.execute(
                    """
                    UPDATE flags
                    SET status = 'resolved'
                    WHERE edge_osm_id = %s AND flag_type IN ('gone', 'blocked') AND status = 'active';
                    """,
                    (edge_osm_id,)
                )

            conn.commit()
            checkin["checked_in_at"] = checkin["checked_in_at"].isoformat() if checkin.get("checked_in_at") else ""
            checkin["confidence_score"] = conf_score
            return checkin

def get_trail_checkins(edge_osm_id: int, limit: int = 20) -> List[Dict[str, Any]]:
    """Returns recent check-in history for an edge."""
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, edge_osm_id, user_id, status, note, checked_in_at
                FROM trail_checkins
                WHERE edge_osm_id = %s
                ORDER BY checked_in_at DESC LIMIT %s;
                """,
                (edge_osm_id, limit)
            )
            res = []
            for r in cur.fetchall():
                item = dict(r)
                item["checked_in_at"] = item["checked_in_at"].isoformat() if item.get("checked_in_at") else ""
                res.append(item)
            return res

def get_trail_status(edge_osm_id: int) -> Dict[str, Any]:
    """Returns aggregated status for an edge including confidence, flags, and check-ins."""
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT osm_id, name, confidence_score, check_date, snowmobile, access, bicycle
                FROM edges WHERE osm_id = %s;
                """,
                (edge_osm_id,)
            )
            edge = cur.fetchone()
            conf_score = float(edge["confidence_score"]) if edge and edge.get("confidence_score") is not None else 1.0
            check_date = edge["check_date"].isoformat() if edge and edge.get("check_date") else None
            snowmobile = bool(edge.get("snowmobile")) if edge else False
            access = edge.get("access") if edge else None
            bicycle = edge.get("bicycle") if edge else None

            # Get recent checkins count
            cur.execute(
                "SELECT COUNT(*) as cnt FROM trail_checkins WHERE edge_osm_id = %s;",
                (edge_osm_id,)
            )
            checkins_cnt = cur.fetchone()["cnt"]

            # Get active flags
            cur.execute(
                """
                SELECT id, edge_osm_id, flag_type, user_id, confirmed_count, disputed_count, status, details, created_at
                FROM flags
                WHERE edge_osm_id = %s AND status IN ('active', 'verified')
                ORDER BY created_at DESC;
                """,
                (edge_osm_id,)
            )
            flags = []
            for f in cur.fetchall():
                f_item = dict(f)
                f_item["created_at"] = f_item["created_at"].isoformat() if f_item.get("created_at") else ""
                flags.append(f_item)

            overall_status = "open"
            if any(f["flag_type"] == "closed" and f["confirmed_count"] >= 3 for f in flags):
                overall_status = "closed"
            elif any(f["flag_type"] == "gone" for f in flags):
                overall_status = "gone"
            elif any(f["flag_type"] == "blocked" for f in flags):
                overall_status = "blocked"
            elif flags or snowmobile or (access in ("private", "no")):
                overall_status = "caution"

            return {
                "edge_osm_id": edge_osm_id,
                "status": overall_status,
                "confidence_score": conf_score,
                "check_date": check_date,
                "snowmobile": snowmobile,
                "access": access,
                "bicycle": bicycle,
                "recent_checkins_count": checkins_cnt,
                "active_flags": flags
            }

def create_user_dnr(
    user_id: str,
    name: str,
    dnr_type: str,
    edge_osm_id: Optional[int] = None,
    geom: Optional[Dict[str, Any]] = None,
    is_soft: bool = True,
    reason: Optional[str] = None
) -> Dict[str, Any]:
    """Creates a user-settable DNR item by trail (edge_osm_id) or area (geom)."""
    ensure_user_exists(user_id)
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            if geom:
                cur.execute(
                    """
                    INSERT INTO user_dnr (user_id, name, dnr_type, edge_osm_id, geom, is_soft, reason, created_at)
                    VALUES (%s, %s, %s, %s, ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326), %s, %s, NOW())
                    RETURNING id, user_id, name, dnr_type, edge_osm_id, ST_AsGeoJSON(geom) as geom_json, is_soft, reason, created_at;
                    """,
                    (user_id, name, dnr_type, edge_osm_id, Json(geom), is_soft, reason)
                )
            else:
                cur.execute(
                    """
                    INSERT INTO user_dnr (user_id, name, dnr_type, edge_osm_id, is_soft, reason, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, NOW())
                    RETURNING id, user_id, name, dnr_type, edge_osm_id, is_soft, reason, created_at;
                    """,
                    (user_id, name, dnr_type, edge_osm_id, is_soft, reason)
                )
            row = dict(cur.fetchone())
            conn.commit()
            row["created_at"] = row["created_at"].isoformat() if row.get("created_at") else ""
            if row.get("geom_json"):
                row["geom"] = json.loads(row.pop("geom_json"))
            else:
                row["geom"] = None
            return row

def get_user_dnr_list(user_id: str) -> List[Dict[str, Any]]:
    """Returns the user's active DNR list."""
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, user_id, name, dnr_type, edge_osm_id, ST_AsGeoJSON(geom) as geom_json, is_soft, reason, created_at
                FROM user_dnr
                WHERE user_id = %s
                ORDER BY created_at DESC;
                """,
                (user_id,)
            )
            items = []
            for r in cur.fetchall():
                it = dict(r)
                it["created_at"] = it["created_at"].isoformat() if it.get("created_at") else ""
                it["geom"] = json.loads(it.pop("geom_json")) if it.get("geom_json") else None
                items.append(it)
            return items

def delete_user_dnr(dnr_id: int, user_id: str) -> bool:
    """Removes an item from the user's DNR list."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM user_dnr WHERE id = %s AND user_id = %s;", (dnr_id, user_id))
            conn.commit()
            return cur.rowcount > 0

def log_dnr_override(
    user_id: str,
    route_id: Optional[str] = None,
    dnr_id: Optional[int] = None,
    edge_osm_id: Optional[int] = None,
    reason: Optional[str] = None
) -> int:
    """Logs a soft DNR override to the audit trail per Section 8."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO dnr_override_logs (user_id, route_id, dnr_id, edge_osm_id, reason, logged_at)
                VALUES (%s, %s, %s, %s, %s, NOW())
                RETURNING id;
                """,
                (user_id, route_id, dnr_id, edge_osm_id, reason or "User override")
            )
            new_id = cur.fetchone()[0]
            conn.commit()
            return new_id

def get_dnr_override_logs(user_id: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
    """Fetches audit log entries for DNR overrides."""
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            if user_id:
                cur.execute(
                    """
                    SELECT id, user_id, route_id, dnr_id, edge_osm_id, reason, logged_at
                    FROM dnr_override_logs
                    WHERE user_id = %s
                    ORDER BY logged_at DESC LIMIT %s;
                    """,
                    (user_id, limit)
                )
            else:
                cur.execute(
                    """
                    SELECT id, user_id, route_id, dnr_id, edge_osm_id, reason, logged_at
                    FROM dnr_override_logs
                    ORDER BY logged_at DESC LIMIT %s;
                    """,
                    (limit,)
                )
            res = []
            for r in cur.fetchall():
                it = dict(r)
                it["logged_at"] = it["logged_at"].isoformat() if it.get("logged_at") else ""
                res.append(it)
            return res

def user_has_ridden_edge(user_id: str, edge_osm_id: int) -> bool:
    """Verifies whether the user has previously recorded a ride on this edge."""
    if not user_id:
        return False
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT 1 FROM activity_edge_visits
                    WHERE user_id = %s AND edge_osm_id = %s
                    LIMIT 1;
                    """,
                    (user_id, edge_osm_id)
                )
                return cur.fetchone() is not None
    except Exception:
        return False

def user_has_ridden_area(user_id: str, geom_geojson: Dict[str, Any]) -> bool:
    """Verifies whether the user has previously recorded visits intersecting this geometry."""
    if not user_id or not geom_geojson:
        return False
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT 1
                    FROM activity_edge_visits v
                    JOIN edges e ON v.edge_osm_id = e.osm_id
                    WHERE v.user_id = %s
                      AND e.geom IS NOT NULL
                      AND ST_Intersects(e.geom, ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326))
                    LIMIT 1;
                    """,
                    (user_id, Json(geom_geojson))
                )
                return cur.fetchone() is not None
    except Exception:
        return False

def check_route_trust_layer(
    geojson_linestring: Dict[str, Any],
    edge_osm_ids: List[int],
    user_id: Optional[str] = None,
    sport: str = "mtb"
) -> Dict[str, Any]:
    """
    Comprehensive Trust Layer verification for a route candidate:
    1. Hard blocks: OSM access=private/no, bicycle=no, restrictions table, and confirmed closures.
       - Hard blocks CANNOT be overridden UNLESS the user has already ridden that trail/area.
    2. Soft DNR: User's DNR list (trail or area) and soft restriction warnings.
    3. Snowmobile trails: Warnings issued, never presented as unrestricted public access.
    4. Community flags: Active flags on traversed edges.
    """
    hard_blocks: List[Dict[str, Any]] = []
    soft_dnrs: List[Dict[str, Any]] = []
    snowmobile_warnings: List[str] = []
    flag_warnings: List[str] = []
    general_warnings: List[str] = []

    is_bike_sport = sport not in ("trail_run", "foot")

    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # A. Check restrictions table (by spatial intersection OR edge_osm_id)
                has_geom = bool(geojson_linestring and geojson_linestring.get("coordinates") and len(geojson_linestring["coordinates"]) >= 2)
                if has_geom or edge_osm_ids:
                    if has_geom and edge_osm_ids:
                        cur.execute(
                            """
                            SELECT id, name, restriction_type, source, is_hard, edge_osm_id,
                                   seasonal_start_month, seasonal_end_month, seasonal_tag,
                                   ST_AsGeoJSON(geom) as geom_json
                            FROM restrictions
                            WHERE ST_Intersects(geom, ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326))
                               OR edge_osm_id = ANY(%s);
                            """,
                            (Json(geojson_linestring), edge_osm_ids)
                        )
                    elif has_geom:
                        cur.execute(
                            """
                            SELECT id, name, restriction_type, source, is_hard, edge_osm_id,
                                   seasonal_start_month, seasonal_end_month, seasonal_tag,
                                   ST_AsGeoJSON(geom) as geom_json
                            FROM restrictions
                            WHERE ST_Intersects(geom, ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326));
                            """,
                            (Json(geojson_linestring),)
                        )
                    else:
                        cur.execute(
                            """
                            SELECT id, name, restriction_type, source, is_hard, edge_osm_id,
                                   seasonal_start_month, seasonal_end_month, seasonal_tag,
                                   ST_AsGeoJSON(geom) as geom_json
                            FROM restrictions
                            WHERE edge_osm_id = ANY(%s);
                            """,
                            (edge_osm_ids,)
                        )

                    current_month = datetime.date.today().month
                    for r in cur.fetchall():
                        # Check seasonality
                        s_start = r.get("seasonal_start_month")
                        s_end = r.get("seasonal_end_month")
                        if s_start and s_end:
                            if s_start <= s_end:
                                active_seasonal = (s_start <= current_month <= s_end)
                            else:
                                active_seasonal = (current_month >= s_start or current_month <= s_end)
                            if not active_seasonal:
                                continue

                        r_hard = bool(r.get("is_hard"))
                        r_name = r.get("name") or "Restricted Area"
                        r_type = r.get("restriction_type") or "restriction"

                        if r_hard:
                            # Verify waiver: has user ridden this trail or area before?
                            waived = False
                            if user_id:
                                if r.get("edge_osm_id") and user_has_ridden_edge(user_id, r["edge_osm_id"]):
                                    waived = True
                                elif r.get("geom_json") and user_has_ridden_area(user_id, json.loads(r["geom_json"])):
                                    waived = True

                            hard_blocks.append({
                                "id": r["id"],
                                "name": r_name,
                                "type": r_type,
                                "source": r.get("source"),
                                "edge_osm_id": r.get("edge_osm_id"),
                                "waived": waived,
                                "reason": f"Hard block: {r_type} ({r_name})"
                            })
                        else:
                            soft_dnrs.append({
                                "id": r["id"],
                                "name": r_name,
                                "reason": f"Soft restriction: {r_type}",
                                "edge_osm_id": r.get("edge_osm_id")
                            })

                # B. Check OSM Edge Attributes (access, bicycle, snowmobile)
                if edge_osm_ids:
                    cur.execute(
                        """
                        SELECT osm_id, name, access, bicycle, snowmobile
                        FROM edges
                        WHERE osm_id = ANY(%s);
                        """,
                        (edge_osm_ids,)
                    )
                    for e in cur.fetchall():
                        eid = e["osm_id"]
                        ename = e.get("name") or f"Edge {eid}"
                        acc = (e.get("access") or "").lower()
                        bike = (e.get("bicycle") or "").lower()
                        is_snow = bool(e.get("snowmobile"))

                        # 1. access=private or access=no -> Hard block
                        if acc in ("private", "no"):
                            waived = user_has_ridden_edge(user_id, eid) if user_id else False
                            hard_blocks.append({
                                "name": ename,
                                "type": "osm_access_private_no",
                                "edge_osm_id": eid,
                                "waived": waived,
                                "reason": f"OSM access={acc}"
                            })

                        # 2. bicycle=no for biking profiles -> Hard block
                        if is_bike_sport and bike in ("no", "prohibited"):
                            waived = user_has_ridden_edge(user_id, eid) if user_id else False
                            hard_blocks.append({
                                "name": ename,
                                "type": "osm_bicycle_no",
                                "edge_osm_id": eid,
                                "waived": waived,
                                "reason": "Bicycles prohibited on this trail"
                            })

                        # 3. Snowmobile trail warning
                        if is_snow:
                            snowmobile_warnings.append(
                                f"Snowmobile trail: permission-based / seasonal access on '{ename}'; not guaranteed public right-of-way."
                            )

                # C. Check Active Community Flags on Edges
                if edge_osm_ids:
                    cur.execute(
                        """
                        SELECT id, edge_osm_id, flag_type, confirmed_count, status, details
                        FROM flags
                        WHERE edge_osm_id = ANY(%s) AND status IN ('active', 'verified');
                        """,
                        (edge_osm_ids,)
                    )
                    for f in cur.fetchall():
                        ftype = f["flag_type"]
                        feid = f["edge_osm_id"]
                        f_conf = f["confirmed_count"]

                        if ftype == "closed" and f_conf >= 3:
                            # Confirmed closure acts as a hard block
                            waived = user_has_ridden_edge(user_id, feid) if user_id else False
                            hard_blocks.append({
                                "name": f"Trail Closure (Edge {feid})",
                                "type": "community_flag_closure",
                                "edge_osm_id": feid,
                                "waived": waived,
                                "reason": f"Community confirmed closure ({f_conf} reports)"
                            })
                        elif ftype == "gone":
                            flag_warnings.append(f"Community Flag: Trail reported overgrown/lost on edge {feid} ({f_conf} confirmations).")
                        elif ftype == "blocked":
                            flag_warnings.append(f"Community Flag: Trail reported blocked (trees/slide) on edge {feid} ({f_conf} confirmations).")
                        elif ftype == "closed":
                            flag_warnings.append(f"Community Flag: Trail closure reported on edge {feid} ({f_conf} report).")
                        elif ftype == "seasonal":
                            flag_warnings.append(f"Community Flag: Seasonal trail condition alert on edge {feid}.")

                # D. Check User's Personal DNR List
                if user_id:
                    if has_geom and edge_osm_ids:
                        cur.execute(
                            """
                            SELECT id, name, dnr_type, edge_osm_id, is_soft, reason
                            FROM user_dnr
                            WHERE user_id = %s
                              AND (edge_osm_id = ANY(%s) OR (geom IS NOT NULL AND ST_Intersects(geom, ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326))));
                            """,
                            (user_id, edge_osm_ids, Json(geojson_linestring))
                        )
                    elif has_geom:
                        cur.execute(
                            """
                            SELECT id, name, dnr_type, edge_osm_id, is_soft, reason
                            FROM user_dnr
                            WHERE user_id = %s
                              AND geom IS NOT NULL AND ST_Intersects(geom, ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326));
                            """,
                            (user_id, Json(geojson_linestring))
                        )
                    elif edge_osm_ids:
                        cur.execute(
                            """
                            SELECT id, name, dnr_type, edge_osm_id, is_soft, reason
                            FROM user_dnr
                            WHERE user_id = %s AND edge_osm_id = ANY(%s);
                            """,
                            (user_id, edge_osm_ids)
                        )
                    else:
                        cur.execute("SELECT 1 WHERE 1=0;")

                    for d in cur.fetchall():
                        d_name = d["name"]
                        d_reason = d.get("reason") or "User DNR"
                        if d.get("is_soft", True):
                            soft_dnrs.append({
                                "id": d["id"],
                                "name": d_name,
                                "reason": d_reason,
                                "edge_osm_id": d.get("edge_osm_id")
                            })
                        else:
                            # User set hard DNR
                            waived = user_has_ridden_edge(user_id, d["edge_osm_id"]) if d.get("edge_osm_id") else False
                            hard_blocks.append({
                                "name": d_name,
                                "type": "user_hard_dnr",
                                "edge_osm_id": d.get("edge_osm_id"),
                                "waived": waived,
                                "reason": f"User hard DNR: {d_reason}"
                            })

    except Exception as e:
        print(f"Error checking trust layer: {e}")

    # Deduplicate snowmobile warnings
    snowmobile_warnings = list(dict.fromkeys(snowmobile_warnings))

    # Compile consolidated warnings list
    all_warnings = []
    for sd in soft_dnrs:
        all_warnings.append(f"DNR Warning: Traverses '{sd['name']}' ({sd.get('reason', 'User DNR')})")
    all_warnings.extend(snowmobile_warnings)
    all_warnings.extend(flag_warnings)
    for hb in hard_blocks:
        if hb["waived"]:
            all_warnings.append(f"Notice: Hard block for '{hb['name']}' waived because you have previously ridden this trail.")

    has_unwaived = any(not b["waived"] for b in hard_blocks)
    waived_count = sum(1 for b in hard_blocks if b["waived"])

    return {
        "hard_blocks": hard_blocks,
        "has_unwaived_hard_blocks": has_unwaived,
        "waived_hard_blocks_count": waived_count,
        "soft_dnr": soft_dnrs,
        "snowmobile_warnings": snowmobile_warnings,
        "community_flag_warnings": flag_warnings,
        "all_warnings": all_warnings
    }

def get_all_restrictions() -> List[Dict[str, Any]]:
    """Returns all restrictions for admin management."""
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, name, restriction_type, source, is_hard, edge_osm_id,
                       seasonal_start_month, seasonal_end_month, seasonal_tag,
                       description, created_at, ST_AsGeoJSON(geom) as geom_json
                FROM restrictions
                ORDER BY created_at DESC;
                """
            )
            rows = []
            for r in cur.fetchall():
                it = dict(r)
                it["created_at"] = it["created_at"].isoformat() if it.get("created_at") else ""
                it["geom"] = json.loads(it.pop("geom_json")) if it.get("geom_json") else None
                rows.append(it)
            return rows

def create_restriction(
    name: str,
    restriction_type: str,
    source: str = "Admin",
    is_hard: bool = True,
    edge_osm_id: Optional[int] = None,
    geom: Optional[Dict[str, Any]] = None,
    seasonal_start_month: Optional[int] = None,
    seasonal_end_month: Optional[int] = None,
    seasonal_tag: Optional[str] = None,
    description: Optional[str] = None
) -> Dict[str, Any]:
    """Admin function: adds a land restriction or closure."""
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            if geom:
                cur.execute(
                    """
                    INSERT INTO restrictions (
                        name, restriction_type, source, is_hard, edge_osm_id, geom,
                        seasonal_start_month, seasonal_end_month, seasonal_tag, description, created_at
                    )
                    VALUES (%s, %s, %s, %s, %s, ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326), %s, %s, %s, %s, NOW())
                    RETURNING id, name, restriction_type, source, is_hard, edge_osm_id,
                              seasonal_start_month, seasonal_end_month, seasonal_tag, description, created_at,
                              ST_AsGeoJSON(geom) as geom_json;
                    """,
                    (name, restriction_type, source, is_hard, edge_osm_id, Json(geom), seasonal_start_month, seasonal_end_month, seasonal_tag, description)
                )
            else:
                cur.execute(
                    """
                    INSERT INTO restrictions (
                        name, restriction_type, source, is_hard, edge_osm_id,
                        seasonal_start_month, seasonal_end_month, seasonal_tag, description, created_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                    RETURNING id, name, restriction_type, source, is_hard, edge_osm_id,
                              seasonal_start_month, seasonal_end_month, seasonal_tag, description, created_at;
                    """,
                    (name, restriction_type, source, is_hard, edge_osm_id, seasonal_start_month, seasonal_end_month, seasonal_tag, description)
                )
            row = dict(cur.fetchone())
            conn.commit()
            row["created_at"] = row["created_at"].isoformat() if row.get("created_at") else ""
            row["geom"] = json.loads(row.pop("geom_json")) if row.get("geom_json") else None
            return row

def update_restriction(
    restriction_id: int,
    name: Optional[str] = None,
    restriction_type: Optional[str] = None,
    source: Optional[str] = None,
    is_hard: Optional[bool] = None,
    edge_osm_id: Optional[int] = None,
    geom: Optional[Dict[str, Any]] = None,
    seasonal_start_month: Optional[int] = None,
    seasonal_end_month: Optional[int] = None,
    seasonal_tag: Optional[str] = None,
    description: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """Admin function: edits an existing restriction."""
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                UPDATE restrictions
                SET name = COALESCE(%s, name),
                    restriction_type = COALESCE(%s, restriction_type),
                    source = COALESCE(%s, source),
                    is_hard = COALESCE(%s, is_hard),
                    edge_osm_id = COALESCE(%s, edge_osm_id),
                    geom = CASE WHEN %s IS NOT NULL THEN ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326) ELSE geom END,
                    seasonal_start_month = COALESCE(%s, seasonal_start_month),
                    seasonal_end_month = COALESCE(%s, seasonal_end_month),
                    seasonal_tag = COALESCE(%s, seasonal_tag),
                    description = COALESCE(%s, description)
                WHERE id = %s
                RETURNING id, name, restriction_type, source, is_hard, edge_osm_id,
                          seasonal_start_month, seasonal_end_month, seasonal_tag, description, created_at,
                          ST_AsGeoJSON(geom) as geom_json;
                """,
                (
                    name, restriction_type, source, is_hard, edge_osm_id,
                    Json(geom) if geom else None, Json(geom) if geom else None,
                    seasonal_start_month, seasonal_end_month, seasonal_tag, description,
                    restriction_id
                )
            )
            row = cur.fetchone()
            if not row:
                return None
            conn.commit()
            res = dict(row)
            res["created_at"] = res["created_at"].isoformat() if res.get("created_at") else ""
            res["geom"] = json.loads(res.pop("geom_json")) if res.get("geom_json") else None
            return res

def delete_restriction(restriction_id: int) -> bool:
    """Admin function: removes a restriction."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM restrictions WHERE id = %s;", (restriction_id,))
            conn.commit()
            return cur.rowcount > 0

def create_takedown(
    name: str,
    edge_osm_id: Optional[int] = None,
    geom: Optional[Dict[str, Any]] = None,
    reason: str = "Land manager takedown request",
    requested_by: str = "Land Manager"
) -> Dict[str, Any]:
    """
    Executes a land manager takedown request per Section 8 & 14.
    Immediately creates a hard block with source='Land Manager Takedown'.
    """
    return create_restriction(
        name=name,
        restriction_type="takedown",
        source=f"Land Manager Takedown ({requested_by})",
        is_hard=True,
        edge_osm_id=edge_osm_id,
        geom=geom,
        description=reason
    )

def export_user_data(user_id: str) -> Dict[str, Any]:
    """
    Exports all personal data for a user per Section 7 privacy compliance.
    Includes profile, consent, privacy zones, activities, saved routes, check-ins, flags, and DNR items.
    Strictly isolated: never exposes any other rider's data.
    """
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # 1. User profile
            cur.execute("SELECT id, email, display_name, created_at FROM users WHERE id = %s;", (user_id,))
            u_row = cur.fetchone()
            profile = dict(u_row) if u_row else {"id": user_id}
            if profile.get("created_at"):
                profile["created_at"] = profile["created_at"].isoformat()

            # 2. Consent
            cur.execute("SELECT consent_given, consented_at FROM contribution_consent WHERE user_id = %s;", (user_id,))
            c_row = cur.fetchone()
            consent = {
                "consent_given": bool(c_row["consent_given"]) if c_row else True,
                "consented_at": c_row["consented_at"].isoformat() if c_row and c_row.get("consented_at") else None
            }

            # 3. Privacy zones
            cur.execute("SELECT id, name, lat, lon, radius_m, created_at FROM user_privacy_zones WHERE user_id = %s;", (user_id,))
            zones = [dict(z) for z in cur.fetchall()]
            for z in zones:
                z["created_at"] = z["created_at"].isoformat() if z.get("created_at") else ""

            # 4. User DNR
            cur.execute("SELECT id, name, dnr_type, edge_osm_id, is_soft, reason, created_at FROM user_dnr WHERE user_id = %s;", (user_id,))
            dnr_items = [dict(d) for d in cur.fetchall()]
            for d in dnr_items:
                d["created_at"] = d["created_at"].isoformat() if d.get("created_at") else ""

            # 5. Check-ins
            cur.execute("SELECT id, edge_osm_id, status, note, checked_in_at FROM trail_checkins WHERE user_id = %s;", (user_id,))
            checkins = [dict(ck) for ck in cur.fetchall()]
            for ck in checkins:
                ck["checked_in_at"] = ck["checked_in_at"].isoformat() if ck.get("checked_in_at") else ""

            # 6. Flags
            cur.execute("SELECT id, edge_osm_id, flag_type, confirmed_count, status, details, created_at FROM flags WHERE user_id = %s;", (user_id,))
            flags = [dict(fl) for fl in cur.fetchall()]
            for fl in flags:
                fl["created_at"] = fl["created_at"].isoformat() if fl.get("created_at") else ""

            # 7. Activities with visited edge geometries and GPS coordinates
            cur.execute(
                """
                SELECT id, sport, activity_date, distance_miles, duration_minutes, file_format, created_at
                FROM activities
                WHERE user_id = %s
                ORDER BY activity_date DESC;
                """,
                (user_id,)
            )
            activities = [dict(ac) for ac in cur.fetchall()]

            # Fetch all visited edge coordinates for this user
            cur.execute(
                """
                SELECT v.activity_id, v.edge_osm_id, v.pass_count, v.visited_at,
                       e.name as trail_name,
                       ST_AsGeoJSON(e.geom) as geom_json
                FROM activity_edge_visits v
                JOIN edges e ON v.edge_osm_id = e.osm_id
                WHERE v.user_id = %s;
                """,
                (user_id,)
            )
            visits_rows = cur.fetchall()

            activity_edges_map: Dict[str, List[Dict[str, Any]]] = {}
            user_contributed_edges: Dict[int, Dict[str, Any]] = {}
            for row in visits_rows:
                act_id = row["activity_id"]
                geom = json.loads(row["geom_json"]) if row.get("geom_json") else None
                coords = geom.get("coordinates") if geom else []
                edge_info = {
                    "edge_osm_id": row["edge_osm_id"],
                    "trail_name": row.get("trail_name"),
                    "pass_count": row.get("pass_count", 1),
                    "coordinates": coords
                }
                if act_id not in activity_edges_map:
                    activity_edges_map[act_id] = []
                activity_edges_map[act_id].append(edge_info)

                eid = row["edge_osm_id"]
                if eid not in user_contributed_edges:
                    user_contributed_edges[eid] = {
                        "edge_osm_id": eid,
                        "trail_name": row.get("trail_name") or f"Trail #{eid}",
                        "coordinates": coords
                    }

            for ac in activities:
                ac["activity_date"] = ac["activity_date"].isoformat() if ac.get("activity_date") else ""
                ac["created_at"] = ac["created_at"].isoformat() if ac.get("created_at") else ""
                visited = activity_edges_map.get(ac["id"], [])
                ac["visited_edges"] = visited
                ac["matched_edge_count"] = len(visited)
                all_pts = []
                for v in visited:
                    for pt in v.get("coordinates", []):
                        all_pts.append(pt)
                ac["gps_coordinates"] = all_pts

            heat_contributions = list(user_contributed_edges.values())

            # 8. Saved Routes
            cur.execute("SELECT id, name, sport, distance_miles, elevation_gain_ft, elevation_loss_ft, created_at FROM saved_routes WHERE user_id = %s;", (user_id,))
            saved = [dict(sr) for sr in cur.fetchall()]
            for sr in saved:
                sr["created_at"] = sr["created_at"].isoformat() if sr.get("created_at") else ""

            return {
                "user_id": user_id,
                "email": profile.get("email"),
                "display_name": profile.get("display_name"),
                "consent": consent,
                "privacy_zones": zones,
                "dnr_items": dnr_items,
                "checkins": checkins,
                "flags": flags,
                "activities": activities,
                "saved_routes": saved,
                "heat_trail_contributions": heat_contributions,
                "exported_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
            }

def delete_user_account(user_id: str) -> bool:
    """
    Purges all user account records and personal data across all tables.
    Deletes privacy zones, DNR entries, override logs, check-ins, flag votes, flags,
    saved routes, activity edge visits, activities, consent settings, and user entity.
    Triggers heat recalculation.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            # 1. Delete dependent tables
            cur.execute("DELETE FROM user_privacy_zones WHERE user_id = %s;", (user_id,))
            cur.execute("DELETE FROM user_dnr WHERE user_id = %s;", (user_id,))
            cur.execute("DELETE FROM dnr_override_logs WHERE user_id = %s;", (user_id,))
            cur.execute("DELETE FROM trail_checkins WHERE user_id = %s;", (user_id,))
            cur.execute("DELETE FROM flag_votes WHERE user_id = %s;", (user_id,))
            cur.execute("DELETE FROM flags WHERE user_id = %s;", (user_id,))
            cur.execute("DELETE FROM saved_routes WHERE user_id = %s;", (user_id,))
            cur.execute("DELETE FROM activity_edge_visits WHERE user_id = %s;", (user_id,))
            cur.execute("DELETE FROM activities WHERE user_id = %s;", (user_id,))
            cur.execute("DELETE FROM contribution_consent WHERE user_id = %s;", (user_id,))
            cur.execute("DELETE FROM users WHERE id = %s;", (user_id,))
            conn.commit()

    # Recalculate heat to remove user's visits
    recalculate_all_edge_heat()
    return True


# =========================================================================
# Stage 6: Differentiators (Find New Trails, Submissions, Connectors)
# =========================================================================

def get_user_connected_service(user_id: str, provider: str) -> Optional[Dict[str, Any]]:
    """Fetches user connected service record (encrypted tokens)."""
    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT id, user_id, provider, encrypted_session_token, token_expires_at, last_synced_at, is_active
                    FROM user_connected_services
                    WHERE user_id = %s AND provider = %s;
                    """,
                    (user_id, provider)
                )
                row = cur.fetchone()
                return dict(row) if row else None
    except Exception:
        return None

def save_user_connected_service(
    user_id: str,
    provider: str,
    encrypted_token: str,
    expires_at: Optional[datetime.datetime] = None
) -> bool:
    """Upserts user connected service record with encrypted session token."""
    try:
        ensure_user_exists(user_id)
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO user_connected_services (
                        user_id, provider, encrypted_session_token, token_expires_at, last_synced_at, is_active
                    )
                    VALUES (%s, %s, %s, %s, NOW(), TRUE)
                    ON CONFLICT (user_id, provider) DO UPDATE
                    SET encrypted_session_token = EXCLUDED.encrypted_session_token,
                        token_expires_at = EXCLUDED.token_expires_at,
                        last_synced_at = NOW(),
                        is_active = TRUE;
                    """,
                    (user_id, provider, encrypted_token, expires_at)
                )
                conn.commit()
                return True
    except Exception:
        return False

def delete_user_connected_service(user_id: str, provider: str) -> bool:
    """Disconnects service and purges stored encrypted tokens."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM user_connected_services WHERE user_id = %s AND provider = %s;",
                    (user_id, provider)
                )
                conn.commit()
                return True
    except Exception:
        return False

def list_user_connected_services(user_id: str) -> List[Dict[str, Any]]:
    """Lists all connected services for a user."""
    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "SELECT id, user_id, provider, token_expires_at, last_synced_at, is_active FROM user_connected_services WHERE user_id = %s;",
                    (user_id,)
                )
                return [dict(r) for r in cur.fetchall()]
    except Exception:
        return []

def get_user_ridden_edge_ids(user_id: str, sport: Optional[str] = None) -> set:
    """Returns set of edge OSM IDs that the user has previously ridden/visited."""
    if not user_id:
        return set()
    sport = heat_sport(sport) if sport else None
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                if sport:
                    cur.execute(
                        "SELECT DISTINCT edge_osm_id FROM activity_edge_visits WHERE user_id = %s AND sport = %s;",
                        (user_id, sport)
                    )
                else:
                    cur.execute(
                        "SELECT DISTINCT edge_osm_id FROM activity_edge_visits WHERE user_id = %s;",
                        (user_id,)
                    )
                return {row[0] for row in cur.fetchall()}
    except Exception:
        return set()

# Names checked against the `name` tag of the same way id in data/osm/new-hampshire-latest.osm.pbf
# (Round 7 audit). The OSM import fills edges.name for everything else.
KNOWN_OSM_TRAIL_NAMES: Dict[int, str] = {
    42743791: "Grandview Road",
    220551352: "Bobcat Trail",
    741060716: "Podunk Road",
    247358976: "Little Bear Trail",
    247358974: "Little Bear Trail",
    220551345: "Salt Lick Trail",
    247358962: "Pitch Pine Trail",
    18854090: "Branch Londonderry Turnpike East",
    313179483: "Powerlines Trail",
}


def resolve_osm_trail_name(osm_way_id: int) -> Optional[str]:
    """The OSM `name` of a way: audited registry, then the imported edges table. None if unnamed."""
    if osm_way_id in KNOWN_OSM_TRAIL_NAMES:
        return KNOWN_OSM_TRAIL_NAMES[osm_way_id]
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT name FROM edges WHERE osm_id = %s;", (osm_way_id,))
                row = cur.fetchone()
                if row and row[0]:
                    return row[0]
    except Exception:
        pass
    return None


def get_unridden_high_heat_trails(
    user_id: str,
    lat: float,
    lon: float,
    radius_miles: float = 15.0,
    sport: str = "mtb"
) -> List[Dict[str, Any]]:
    """
    Trails (not roads, by OSM highway class) with recent heat that the user has not ridden,
    within the radius. Empty when there is no heat data there.
    """
    from app.surface import surface_category

    sport = heat_sport(sport)
    radius_m = radius_miles * 1609.344
    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT e.osm_id as edge_osm_id, e.name, e.highway, e.surface, e.tracktype, h.sport,
                           ROUND((e.length_m * 0.000621371)::numeric, 2) as distance_miles,
                           h.weighted_score as heat_score,
                           ST_AsGeoJSON(e.geom) as geom_json
                    FROM edges e
                    JOIN edge_heat h ON e.osm_id = h.edge_osm_id AND h.sport = %s
                    WHERE (h.unique_riders_12mo >= 1 OR h.weighted_score >= 1.0)
                      AND e.geom IS NOT NULL
                      AND e.highway IN ('path', 'track', 'footway', 'bridleway', 'cycleway')
                      AND e.osm_id NOT IN (
                          SELECT edge_osm_id FROM activity_edge_visits WHERE user_id = %s
                      )
                      AND ST_DWithin(
                          e.geom::geography,
                          ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography,
                          %s
                      )
                    ORDER BY h.weighted_score DESC
                    LIMIT 50;
                    """,
                    (sport, user_id, lon, lat, radius_m)
                )
                items = []
                for row in cur.fetchall():
                    item = dict(row)
                    category = surface_category(item)
                    if category == "paved":
                        continue
                    geom_data = json.loads(item.pop("geom_json"))
                    items.append({
                        "edge_osm_id": item["edge_osm_id"],
                        "name": item.get("name") or "Unnamed trail",
                        "sport": item["sport"],
                        "distance_miles": float(item["distance_miles"]) if item.get("distance_miles") is not None else None,
                        "heat_score": item["heat_score"],
                        "surface": category,
                        "coordinates": geom_data.get("coordinates", []),
                    })
                return items
    except Exception as e:
        print(f"Error loading unridden trails: {e}")
        return []

def upsert_edge_geometries(geoms: Dict[int, Dict[str, Any]]) -> int:
    """Store geometry (and name/class/surface if known) for edges that don't have any yet.

    Never overwrites existing geometry or metadata, so curated / OSM-imported edges win.
    Returns the number of edges written.
    """
    if not geoms:
        return 0
    written = 0
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                for wid, g in geoms.items():
                    coords = g.get("coords") or []
                    if len(coords) < 2:
                        continue
                    geom_json = json.dumps({"type": "LineString", "coordinates": coords})
                    cur.execute(
                        """
                        INSERT INTO edges (osm_id, name, highway, surface, geom, length_m)
                        VALUES (%s, %s, %s, %s, ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326),
                                ST_Length(ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326)::geography))
                        ON CONFLICT (osm_id) DO UPDATE SET
                            geom = COALESCE(edges.geom, EXCLUDED.geom),
                            length_m = COALESCE(edges.length_m, EXCLUDED.length_m),
                            name = COALESCE(edges.name, EXCLUDED.name),
                            highway = COALESCE(edges.highway, EXCLUDED.highway),
                            surface = COALESCE(edges.surface, EXCLUDED.surface);
                        """,
                        (int(wid), g.get("name"), g.get("highway"), g.get("surface"), geom_json, geom_json)
                    )
                    written += 1
                conn.commit()
    except Exception as e:
        print(f"Error upserting edge geometries: {e}")
    return written


def get_heat_trail_geojson(sport: Optional[str] = None, limit: int = 5000) -> Dict[str, Any]:
    """
    Returns GeoJSON FeatureCollection of traversed / heat trails for the map heatmap layer.
    """
    sport = heat_sport(sport) if sport else None
    features = []
    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                if sport:
                    cur.execute(
                        """
                        SELECT e.osm_id, e.name, h.sport, h.weighted_score, h.unique_riders_12mo, h.total_passes_12mo,
                               ST_AsGeoJSON(e.geom) as geom_json
                        FROM edges e
                        JOIN edge_heat h ON e.osm_id = h.edge_osm_id
                        WHERE e.geom IS NOT NULL AND h.sport = %s AND h.is_public = TRUE
                        ORDER BY h.weighted_score DESC, e.osm_id
                        LIMIT %s;
                        """,
                        (sport, limit)
                    )
                else:
                    cur.execute(
                        """
                        SELECT e.osm_id, e.name, h.sport, h.weighted_score, h.unique_riders_12mo, h.total_passes_12mo,
                               ST_AsGeoJSON(e.geom) as geom_json
                        FROM edges e
                        JOIN edge_heat h ON e.osm_id = h.edge_osm_id
                        WHERE e.geom IS NOT NULL AND h.is_public = TRUE
                        ORDER BY h.weighted_score DESC, e.osm_id
                        LIMIT %s;
                        """,
                        (limit,)
                    )
                for row in cur.fetchall():
                    g_json = row.get("geom_json")
                    if g_json:
                        geom = json.loads(g_json)
                        trail_name = row["name"]
                        features.append({
                            "type": "Feature",
                            "properties": {
                                "osm_id": row["osm_id"],
                                "name": trail_name,
                                "sport": row["sport"],
                                "heat_score": float(row["weighted_score"] or 0.0),
                                "passes": int(row["total_passes_12mo"] or 0),
                                "ride_count": int(row["total_passes_12mo"] or 0),
                                "riders": int(row["unique_riders_12mo"] or 0)
                            },
                            "geometry": geom
                        })
    except Exception:
        pass

    return {
        "type": "FeatureCollection",
        "features": features
    }

def create_trail_submission(
    user_id: str,
    name: str,
    sport: str,
    difficulty: str,
    coordinates: List[List[float]],
    description: Optional[str] = None
) -> Dict[str, Any]:
    """
    Creates a new user trail submission and executes initial auto-verification check.
    Submissions start in 'pending' (hidden) status until auto-verified or confirmed by distinct riders.
    """
    ensure_user_exists(user_id)
    geojson_str = json.dumps({"type": "LineString", "coordinates": coordinates})

    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                INSERT INTO trail_submissions (
                    user_id, name, sport, difficulty, geom, status, verifier_count, description, created_at
                )
                VALUES (
                    %s, %s, %s, %s, ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326), 'pending', 0, %s, NOW()
                )
                RETURNING id, user_id, name, sport, difficulty, status, verifier_count, description,
                          created_at, verified_at, rejection_reason,
                          ROUND((ST_Length(geom::geography) * 0.000621371)::numeric, 2) as length_miles,
                          ST_AsGeoJSON(geom) as geom_json;
                """,
                (user_id, name, sport, difficulty, geojson_str, description)
            )
            row = cur.fetchone()
            conn.commit()
            sub_dict = dict(row)
            sub_id = sub_dict["id"]

    # Record submitter's own contribution evidence
    record_submission_evidence(sub_id, user_id)

    # Perform initial auto-verification check
    eval_result = evaluate_and_verify_submission(sub_id)
    return get_trail_submission_by_id(sub_id)

def get_trail_submission_by_id(submission_id: int) -> Optional[Dict[str, Any]]:
    """Retrieves a single trail submission by ID."""
    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT id, user_id, name, sport, difficulty, status, verifier_count,
                           description, rejection_reason, created_at, verified_at,
                           ROUND((COALESCE(ST_Length(geom::geography), 0.0) * 0.000621371)::numeric, 2) as length_miles,
                           ST_AsGeoJSON(geom) as geom_json
                    FROM trail_submissions
                    WHERE id = %s;
                    """,
                    (submission_id,)
                )
                row = cur.fetchone()
                if not row:
                    return None
                data = dict(row)
                geom_data = json.loads(data["geom_json"]) if data.get("geom_json") else {"type": "LineString", "coordinates": []}
                data["coordinates"] = geom_data.get("coordinates", [])
                data.pop("geom_json", None)
                data["created_at"] = data["created_at"].isoformat() if data.get("created_at") else ""
                data["verified_at"] = data["verified_at"].isoformat() if data.get("verified_at") else None
                return data
    except Exception:
        return None

def get_trail_submissions(status_filter: Optional[str] = None) -> List[Dict[str, Any]]:
    """Lists trail submissions with optional status filter."""
    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                if status_filter and status_filter != "all":
                    cur.execute(
                        """
                        SELECT id, user_id, name, sport, difficulty, status, verifier_count,
                               description, rejection_reason, created_at, verified_at,
                               ROUND((COALESCE(ST_Length(geom::geography), 0.0) * 0.000621371)::numeric, 2) as length_miles,
                               ST_AsGeoJSON(geom) as geom_json
                        FROM trail_submissions
                        WHERE status = %s
                        ORDER BY created_at DESC;
                        """,
                        (status_filter,)
                    )
                else:
                    cur.execute(
                        """
                        SELECT id, user_id, name, sport, difficulty, status, verifier_count,
                               description, rejection_reason, created_at, verified_at,
                               ROUND((COALESCE(ST_Length(geom::geography), 0.0) * 0.000621371)::numeric, 2) as length_miles,
                               ST_AsGeoJSON(geom) as geom_json
                        FROM trail_submissions
                        ORDER BY created_at DESC;
                        """
                    )
                rows = cur.fetchall()
                results = []
                for row in rows:
                    data = dict(row)
                    geom_data = json.loads(data["geom_json"]) if data.get("geom_json") else {"type": "LineString", "coordinates": []}
                    data["coordinates"] = geom_data.get("coordinates", [])
                    data.pop("geom_json", None)
                    data["created_at"] = data["created_at"].isoformat() if data.get("created_at") else ""
                    data["verified_at"] = data["verified_at"].isoformat() if data.get("verified_at") else None
                    results.append(data)
                return results
    except Exception:
        return []

def record_submission_evidence(
    submission_id: int,
    user_id: str,
    activity_id: Optional[str] = None,
    coordinates: Optional[List[List[float]]] = None
) -> Dict[str, Any]:
    """
    Records GPS ride evidence confirming a trail submission (abuse-resistant, 1 evidence per user).
    Re-evaluates verification threshold.
    """
    ensure_user_exists(user_id)
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                if activity_id:
                    cur.execute(
                        """
                        INSERT INTO activities (id, user_id, sport, file_format)
                        VALUES (%s, %s, 'mtb', 'gpx')
                        ON CONFLICT (id) DO NOTHING;
                        """,
                        (activity_id, user_id)
                    )
                cur.execute(
                    """
                    INSERT INTO trail_submission_evidence (submission_id, user_id, activity_id, verified_at)
                    VALUES (%s, %s, %s, NOW())
                    ON CONFLICT (submission_id, user_id) DO NOTHING;
                    """,
                    (submission_id, user_id, activity_id)
                )
                conn.commit()


        # Re-evaluate auto-verification
        eval_result = evaluate_and_verify_submission(submission_id)
        sub = get_trail_submission_by_id(submission_id)
        return {
            "submission_id": submission_id,
            "user_id": user_id,
            "status": sub.get("status") if sub else "pending",
            "verifier_count": sub.get("verifier_count", 0) if sub else 0
        }
    except Exception as e:
        return {"error": str(e)}

def evaluate_and_verify_submission(submission_id: int) -> Dict[str, Any]:
    """
    Auto-verification logic per Project Plan Section 10 & Brief:
    1. Checks if geometry intersects any restricted areas (hard blocks, private land, wildlife closures).
       If restricted: auto-verification is blocked / rejected.
    2. Checks if >= 3 unique riders' rides overlap the geometry within the last 12 months.
       If unique riders >= 3 and no restricted areas intersected: status is automatically updated to 'verified'.
    3. Otherwise: remains 'pending' and hidden until crowd-confirmed.
    """
    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # 1. Fetch submission geometry
                cur.execute("SELECT id, status, geom, ST_AsGeoJSON(geom) as geom_json FROM trail_submissions WHERE id = %s;", (submission_id,))
                sub = cur.fetchone()
                if not sub:
                    return {"error": "Submission not found"}

                geom_json = json.loads(sub["geom_json"]) if sub.get("geom_json") else None
                if not geom_json:
                    return {"error": "Invalid geometry"}

                # 2. Check restrictions
                restrictions = check_restrictions_along_line(geom_json)
                hard_blocks = [r for r in restrictions if r.get("is_hard")]
                if hard_blocks:
                    # Restricted area conflict
                    block_names = ", ".join(r["name"] for r in hard_blocks)
                    cur.execute(
                        "UPDATE trail_submissions SET status = 'rejected', rejection_reason = %s WHERE id = %s;",
                        (f"Intersects restricted area: {block_names}", submission_id)
                    )
                    conn.commit()
                    return {
                        "is_verified": False,
                        "status": "rejected",
                        "restricted_area_conflict": True,
                        "conflict_details": block_names
                    }

                # 3. Count unique riders with overlapping activities within 12 months (or submission evidence)
                # Combines evidence records + spatial overlapping activities within 35 meters
                cur.execute(
                    """
                    SELECT COUNT(DISTINCT user_id) as unique_riders
                    FROM (
                        SELECT user_id FROM trail_submission_evidence WHERE submission_id = %s
                        UNION
                        SELECT a.user_id
                        FROM activities a
                        JOIN activity_edge_visits v ON a.id = v.activity_id
                        JOIN edges e ON v.edge_osm_id = e.osm_id
                        JOIN trail_submissions ts ON ts.id = %s
                        WHERE a.activity_date >= (CURRENT_DATE - INTERVAL '12 months')
                          AND e.geom IS NOT NULL
                          AND ST_DWithin(e.geom::geography, ts.geom::geography, 35)
                    ) combined_riders;
                    """,
                    (submission_id, submission_id)
                )
                row = cur.fetchone()
                unique_riders = row["unique_riders"] if row else 0

                new_status = sub["status"]
                verified_at_clause = ""
                if unique_riders >= 3:
                    new_status = "verified"
                    cur.execute(
                        "UPDATE trail_submissions SET status = 'verified', verifier_count = %s, verified_at = COALESCE(verified_at, NOW()) WHERE id = %s;",
                        (unique_riders, submission_id)
                    )
                else:
                    if sub["status"] == "pending":
                        cur.execute(
                            "UPDATE trail_submissions SET verifier_count = %s WHERE id = %s;",
                            (unique_riders, submission_id)
                        )
                conn.commit()

                return {
                    "is_verified": (new_status == "verified"),
                    "status": new_status,
                    "unique_riders_count": unique_riders,
                    "restricted_area_conflict": False
                }
    except Exception as e:
        return {"error": str(e)}

def admin_update_submission_status(
    submission_id: int,
    new_status: str,
    reason: Optional[str] = None
) -> bool:
    """
    Admin moderation interface to review, approve, reverse, or take down submissions.
    Supports: 'verified', 'rejected', 'taken_down', 'pending'.
    """
    if new_status not in ("verified", "rejected", "taken_down", "pending"):
        return False
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                if new_status == "verified":
                    cur.execute(
                        "UPDATE trail_submissions SET status = %s, verified_at = NOW(), rejection_reason = NULL WHERE id = %s;",
                        (new_status, submission_id)
                    )
                elif new_status in ("rejected", "taken_down"):
                    cur.execute(
                        "UPDATE trail_submissions SET status = %s, rejection_reason = %s WHERE id = %s;",
                        (new_status, reason or f"Admin {new_status}", submission_id)
                    )
                else: # reverse to pending
                    cur.execute(
                        "UPDATE trail_submissions SET status = 'pending', rejection_reason = NULL WHERE id = %s;",
                        (submission_id,)
                    )
                conn.commit()
                return True
    except Exception:
        return False





# --- Round 7: OSM way geometry for the geometry-fidelity gate --------------------------------

_way_geom_cache: Dict[int, Optional[List[List[float]]]] = {}
_way_geom_import: Optional[int] = None


_import_id_checked: List[float] = [0.0, 0.0]  # [checked_at, value]


def latest_osm_import_id() -> Optional[int]:
    """Id of the latest OSM import (None before the first import); caches key on it.
    Re-read from the database at most every 30 s."""
    import time as _time
    now = _time.monotonic()
    if now - _import_id_checked[0] < 30.0:
        return _import_id_checked[1]
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT max(id) FROM osm_imports")
                value = cur.fetchone()[0]
    except Exception:
        return None
    _import_id_checked[0], _import_id_checked[1] = now, value
    return value


def get_way_geometries(way_ids: List[int]) -> Dict[int, List[List[float]]]:
    """OSM geometry ([[lon, lat], ...]) of each way that came from the OSM import. Ways with no
    OSM geometry are absent from the result. Cached per import."""
    global _way_geom_import
    current = latest_osm_import_id()
    if current != _way_geom_import:
        _way_geom_cache.clear()
        _way_geom_import = current
    missing = [w for w in set(way_ids) if w not in _way_geom_cache]
    if missing:
        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT osm_id, ST_AsGeoJSON(geom) FROM edges "
                        "WHERE osm_id = ANY(%s) AND osm_source AND geom IS NOT NULL",
                        (missing,),
                    )
                    found = {r[0]: json.loads(r[1])["coordinates"] for r in cur.fetchall()}
        except Exception:
            found = {}
        for w in missing:
            _way_geom_cache[w] = found.get(w)
        if len(_way_geom_cache) > 200_000:
            _way_geom_cache.clear()
    return {w: _way_geom_cache[w] for w in set(way_ids) if _way_geom_cache.get(w)}
