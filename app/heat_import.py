"""Bulk import of stripped Garmin-export tracks into heat and loop seeds (plan 7.2, 7.4).

Tracks arrive already stripped (lat, lon, time; trimmed; privacy-zone filtered) from
scripts/strip_garmin_export.py. As defence in depth they are trimmed and zone-filtered again
here, then map-matched with GraphHopper. What is stored: an `activities` row (consent given,
source garmin_export), `activity_edge_visits` per matched way, and, for rides that closed a
loop with <= 10% retrace, a `seed_loops` row of OSM node and way ids. Raw points are never stored.
Idempotent by activity id.
"""
import datetime
import math
from typing import Any, Dict, List, Optional, Tuple

from app.activity_parser import TrackPoint
from app.db import (
    get_connection, get_privacy_zones, latest_osm_import_id, record_activity, record_activity_edge_visits,
)
from app.decay import heat_sport
from app.map_matching import edge_counts_from_path, match_path_graphhopper, persist_matched_geometry
from app.privacy import apply_privacy_filters, haversine_m

MAX_BATCH = 25
MAX_POINTS = 50_000
MIN_MILES = 0.5
SEED_MAX_RETRACE = 0.10
SEED_DUP_SHARE = 0.70
SPORTS = {"mtb", "gravel", "trail_run"}
NODE_MATCH_M = 1.0


class TrackError(ValueError):
    pass


def _validate(track: Dict[str, Any]) -> Tuple[str, str, datetime.datetime, List[TrackPoint], bool]:
    try:
        activity_id = str(track["activity_id"]).strip()
        sport = heat_sport(str(track["sport"]))
        start = datetime.datetime.fromisoformat(str(track["start_time"]))
        raw = track["points"]
    except (KeyError, TypeError, ValueError) as e:
        raise TrackError(f"malformed track: {e}")
    if not activity_id.isdigit() or len(activity_id) > 20:
        raise TrackError("activity_id must be Garmin's numeric id")
    if sport not in SPORTS:
        raise TrackError(f"unsupported sport {track.get('sport')!r}")
    if not isinstance(raw, list) or not 2 <= len(raw) <= MAX_POINTS:
        raise TrackError("points must be a list of 2 to 50,000 [lat, lon, epoch_seconds]")
    pts = []
    for p in raw:
        if not isinstance(p, (list, tuple)) or len(p) != 3:
            raise TrackError("each point must be [lat, lon, epoch_seconds]")
        lat, lon, t = float(p[0]), float(p[1]), int(p[2])
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise TrackError("point out of range")
        pts.append(TrackPoint(lat=lat, lon=lon, ele=None,
                              time=datetime.datetime.fromtimestamp(t, datetime.timezone.utc)))
    if start.tzinfo is None:
        start = start.replace(tzinfo=datetime.timezone.utc)
    return activity_id, sport, start, pts, bool(track.get("is_loop", False))


def _downsample(points: List[TrackPoint], min_step_m: float = 10.0) -> List[TrackPoint]:
    out = [points[0]]
    for p in points[1:-1]:
        if haversine_m(out[-1].lon, out[-1].lat, p.lon, p.lat) >= min_step_m:
            out.append(p)
    out.append(points[-1])
    return out


def _miles(points: List[TrackPoint]) -> float:
    return sum(haversine_m(points[i].lon, points[i].lat, points[i + 1].lon, points[i + 1].lat)
               for i in range(len(points) - 1)) / 1609.344


def path_to_segments(path: Dict[str, Any]) -> List[Tuple[int, bool]]:
    """Ordered (segment id, forward) along a matched GraphHopper path, from trail_segments:
    a segment counts when both its end nodes appear, in order, within one run of its way."""
    coords = (path.get("points") or {}).get("coordinates", [])
    runs = [(int(i[0]), int(i[1]), int(i[2])) for i in path.get("details", {}).get("osm_way_id", []) or []
            if len(i) >= 3 and i[2] is not None]
    if not coords or not runs:
        return []
    ways = sorted({w for _, _, w in runs})
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT segment_id, osm_way_id, seq, ST_X(ST_StartPoint(geom)), ST_Y(ST_StartPoint(geom)), "
            "ST_X(ST_EndPoint(geom)), ST_Y(ST_EndPoint(geom)) FROM trail_segments WHERE osm_way_id = ANY(%s)",
            (ways,))
        by_way: Dict[int, List[tuple]] = {}
        for row in cur.fetchall():
            by_way.setdefault(row[1], []).append(row)
    out: List[Tuple[int, bool]] = []
    for s, e, way in runs:
        run = coords[s:e + 1]

        def find(x, y, from_idx=0):
            for k in range(from_idx, len(run)):
                if haversine_m(run[k][0], run[k][1], x, y) <= NODE_MATCH_M:
                    return k
            return None

        hits = []
        for sid, _, seq, x0, y0, x1, y1 in by_way.get(way, []):
            a, b = find(x0, y0), find(x1, y1)
            if a is None or b is None or a == b:
                continue
            hits.append((min(a, b), sid, a < b))
        hits.sort()
        out.extend((sid, fwd) for _, sid, fwd in hits)
    return out


def _segment_rows(segment_ids: List[int]) -> Dict[int, tuple]:
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT segment_id, from_node, to_node, osm_way_id, length_m, "
                    "ST_Y(ST_Centroid(geom)), ST_X(ST_Centroid(geom)) FROM trail_segments WHERE segment_id = ANY(%s)",
                    (segment_ids,))
        return {r[0]: r[1:] for r in cur.fetchall()}


def store_seed_loop(user_id: str, activity_id: str, sport: str, steps: List[Tuple[int, bool]]) -> Optional[str]:
    """Stores a ridden loop as OSM topology, or folds it into a near-duplicate. Returns
    'stored', 'merged' or None (too much retrace / nothing matched)."""
    if len(steps) < 3:
        return None
    rows = _segment_rows([sid for sid, _ in steps])
    if len(rows) != len({sid for sid, _ in steps}):
        return None
    total = sum(rows[sid][3] for sid, _ in steps)
    seen, repeated = set(), 0.0
    for sid, _ in steps:
        if sid in seen:
            repeated += rows[sid][3]
        seen.add(sid)
    retrace = repeated / total if total else 1.0
    if retrace > SEED_MAX_RETRACE or total < MIN_MILES * 1609.344:
        return None
    node_path: List[int] = []
    for sid, fwd in steps:
        u, v = rows[sid][0], rows[sid][1]
        a, b = (u, v) if fwd else (v, u)
        if not node_path or node_path[-1] != a:
            node_path.append(a)
        node_path.append(b)
    way_ids = [rows[sid][2] for sid, _ in steps]
    lat = sum(rows[s][4] * rows[s][3] for s, _ in steps) / total
    lon = sum(rows[s][5] * rows[s][3] for s, _ in steps) / total
    seg_set = {sid for sid, _ in steps}
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT id, segment_ids, rider_ids FROM seed_loops WHERE sport = %s AND osm_import_id = %s",
                    (sport, latest_osm_import_id()))
        for sid_row, other_ids, riders in cur.fetchall():
            other = set(other_ids)
            shared = sum(rows[s][3] for s in seg_set & other if s in rows)
            if shared / max(total, 1.0) >= SEED_DUP_SHARE:
                cur.execute("UPDATE seed_loops SET rides = rides + 1, rider_ids = "
                            "ARRAY(SELECT DISTINCT unnest(rider_ids || %s::text[])) WHERE id = %s",
                            ([user_id], sid_row))
                conn.commit()
                return "merged"
        cur.execute(
            "INSERT INTO seed_loops (user_id, activity_id, sport, way_ids, node_path, segment_ids, osm_import_id, "
            "distance_m, retrace, centroid_rounded, rider_ids) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (user_id, activity_id, sport, way_ids, node_path, [s for s, _ in steps], latest_osm_import_id(),
             total, round(retrace, 3), f"{lat:.2f},{lon:.2f}", [user_id]))
        conn.commit()
    return "stored"


def _exists(activity_id: str) -> bool:
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT 1 FROM activities WHERE id = %s", (activity_id,))
        return cur.fetchone() is not None


async def import_tracks(user_id: str, tracks: List[Dict[str, Any]]) -> Dict[str, Any]:
    if len(tracks) > MAX_BATCH:
        raise TrackError(f"at most {MAX_BATCH} tracks per batch")
    zones = get_privacy_zones(user_id)
    results = []
    for raw in tracks:
        try:
            garmin_id, sport, start, pts, is_loop = _validate(raw)
        except TrackError as e:
            results.append({"activity_id": str(raw.get("activity_id")) if isinstance(raw, dict) else None,
                            "status": "failed", "reason": str(e)})
            continue
        act_id = f"garmin_export_{garmin_id}"
        if _exists(act_id):
            results.append({"activity_id": garmin_id, "status": "skipped", "reason": "already imported"})
            continue
        kept, stats = apply_privacy_filters(pts, zones)  # trims 0.2 mi again, defence in depth
        if stats["is_empty"] or len(kept) < 2 or _miles(kept) < MIN_MILES:
            results.append({"activity_id": garmin_id, "status": "skipped", "reason": "under 0.5 mi after trimming"})
            continue
        path = await match_path_graphhopper(_downsample(kept), sport=sport)
        if not path:
            results.append({"activity_id": garmin_id, "status": "failed", "reason": "map-matching failed"})
            continue
        try:
            persist_matched_geometry(path)
        except Exception:
            pass
        counts = edge_counts_from_path(path)
        duration = (kept[-1].time - kept[0].time).total_seconds() / 60.0 if kept[0].time and kept[-1].time else None
        record_activity({
            "id": act_id, "user_id": user_id, "sport": sport, "activity_date": start,
            "distance_miles": round(_miles(kept), 2), "duration_minutes": round(duration, 1) if duration else None,
            "file_format": "garmin_export", "raw_file_retained": False, "raw_file_path": None,
            "consent_given": True, "matched_edge_count": len(counts),
        })
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("UPDATE activities SET source = 'garmin_export' WHERE id = %s", (act_id,))
            conn.commit()
        record_activity_edge_visits(act_id, counts, user_id, sport, visited_at=start)
        seed = None
        if is_loop:
            try:
                seed = store_seed_loop(user_id, act_id, sport, path_to_segments(path))
            except Exception:
                seed = None
        results.append({"activity_id": garmin_id, "status": "matched", "edges": len(counts), "seed": seed})
    summary = {k: sum(1 for r in results if r["status"] == k) for k in ("matched", "failed", "skipped")}
    return {"results": results, **summary}
