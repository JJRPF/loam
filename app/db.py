import psycopg2
from psycopg2.extras import RealDictCursor
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
                    (psycopg2.extras.Json(geojson_linestring),)
                )
                return [dict(r) for r in cur.fetchall()]
    except Exception:
        return []
