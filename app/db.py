import json
import uuid
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

def get_edge_heat(edge_osm_id: int, sport: str) -> Optional[Dict[str, Any]]:
    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT edge_osm_id, sport, unique_riders_12mo, weighted_score, last_ridden_date
                    FROM edge_heat
                    WHERE edge_osm_id = %s AND sport = %s;
                    """,
                    (edge_osm_id, sport)
                )
                row = cur.fetchone()
                return dict(row) if row else None
    except Exception:
        return None

def get_edges_heat(edge_osm_ids: List[int], sport: str) -> Dict[int, Dict[str, Any]]:
    """Batch query edge_heat table for a list of OSM way/edge IDs."""
    if not edge_osm_ids:
        return {}
    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT edge_osm_id, sport, unique_riders_12mo, weighted_score, last_ridden_date
                    FROM edge_heat
                    WHERE edge_osm_id = ANY(%s) AND sport = %s;
                    """,
                    (edge_osm_ids, sport)
                )
                results: Dict[int, Dict[str, Any]] = {}
                for row in cur.fetchall():
                    results[row["edge_osm_id"]] = dict(row)
                return results
    except Exception:
        return {}

def record_edge_heat(edge_osm_id: int, sport: str, weight: float = 1.0) -> bool:
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                # Ensure edge row exists for foreign key constraint
                cur.execute(
                    """
                    INSERT INTO edges (osm_id) VALUES (%s)
                    ON CONFLICT (osm_id) DO NOTHING;
                    """,
                    (edge_osm_id,)
                )
                cur.execute(
                    """
                    INSERT INTO edge_heat (edge_osm_id, sport, unique_riders_12mo, weighted_score, last_ridden_date)
                    VALUES (%s, %s, 1, %s, CURRENT_DATE)
                    ON CONFLICT (edge_osm_id, sport) DO UPDATE
                    SET unique_riders_12mo = edge_heat.unique_riders_12mo + 1,
                        weighted_score = edge_heat.weighted_score + EXCLUDED.weighted_score,
                        last_ridden_date = CURRENT_DATE;
                    """,
                    (edge_osm_id, sport, weight)
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
