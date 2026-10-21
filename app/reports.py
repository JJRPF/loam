"""'Report bad route' (Round 7 plan section 9): a signed-in rider's report becomes a GitHub issue.

The full snapshot (request, route, options shown) is stored in `route_reports` and readable only by
an admin. The issue carries the comment, the inputs without any coordinates, the scores, and the route
line with 0.5 mi removed from both ends. It never carries the rider's email, name or user id.
"""
import hashlib
import json
import logging
import os
import subprocess
import uuid
from typing import Any, Dict, List, Optional

import httpx
from psycopg2.extras import Json, RealDictCursor

from app.activity_parser import TrackPoint
from app.config import settings
from app.db import get_connection
from app.engine_config import CONFIG_VERSION
from app.privacy import trim_ride_endpoints

logger = logging.getLogger("loam.reports")

REPORT_TRIM_M = 805.0  # 0.5 mi from each end
DAILY_LIMIT = 5
MAX_ISSUE_CHARS = 60000
LABEL = "in-app feedback"
GITHUB_API = "https://api.github.com"


def git_sha() -> str:
    sha = os.getenv("LOAM_GIT_SHA")
    if sha:
        return sha
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    try:
        with open(os.path.join(root, "REVISION")) as f:
            return f.read().strip() or "unknown"
    except OSError:
        pass
    try:
        return subprocess.run(["git", "rev-parse", "--short=12", "HEAD"], cwd=root, capture_output=True,
                              text=True, timeout=3).stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def user_hash(user_id: str) -> str:
    return hashlib.sha256(user_id.encode()).hexdigest()[:8]


def neutralize_mentions(text: str) -> str:
    """'@' followed by a zero-width space, so GitHub doesn't notify the named account."""
    return text.replace("@", "@​")


def trimmed_line(coords: List[List[float]], simplify_to: Optional[int] = None) -> List[List[float]]:
    """The route line without its first and last 0.5 mi, rounded to 5 decimals. Empty when the route
    is shorter than 1 mi, because then nothing of it is safely away from the ends."""
    pts = [TrackPoint(lat=c[1], lon=c[0]) for c in coords or [] if len(c) >= 2]
    kept, _, _ = trim_ride_endpoints(pts, trim_distance_m=REPORT_TRIM_M)
    line = [[round(p.lon, 5), round(p.lat, 5)] for p in kept]
    if simplify_to and len(line) > simplify_to:
        step = len(line) / simplify_to
        line = [line[int(i * step)] for i in range(simplify_to)] + [line[-1]]
    return line


def _route_name(route: Dict[str, Any]) -> str:
    return neutralize_mentions((route.get("name") or "Loam Route").replace("\n", " "))[:80]


def issue_title(route: Dict[str, Any], request: Dict[str, Any]) -> str:
    shape = route.get("route_type") or "route"
    miles = route.get("distance_miles")
    dist = f"{miles:.1f}" if isinstance(miles, (int, float)) else "?"
    sport = request.get("profile") or route.get("sport")
    return f"In-app feedback: bad route — {_route_name(route)} ({dist} mi {shape}, {sport})"


def no_search_request(route: Dict[str, Any], source: str, waypoints: Optional[list] = None) -> Dict[str, Any]:
    """Stand-in for the search settings when they are unknown (a saved or shared route)."""
    return {"search_unavailable": True, "report_source": source, "profile": route.get("sport"),
            "waypoints": waypoints or []}


def saved_route_snapshot(saved_id: str, user_id: str):
    """(route, request) built from the rider's own saved_routes row; (None, None) if it is missing or
    someone else's. The client's geometry is never used here."""
    from app.db import get_saved_route_by_id
    row = get_saved_route_by_id(saved_id, user_id=user_id)
    if not row:
        return None, None
    summary = row.get("surface_summary") or {}
    route = {"id": str(row["id"]), "name": row.get("name"), "sport": row.get("sport"),
             "distance_miles": row.get("distance_miles"), "elevation_gain_ft": row.get("elevation_gain_ft"),
             "elevation_loss_ft": row.get("elevation_loss_ft"), "surface_breakdown": row.get("surface_breakdown") or {},
             "surface_strip": row.get("surface_strip") or [], "coordinates": row.get("coordinates") or [],
             "verbal_summary": row.get("verbal_summary"), "source": "saved"}
    wps = row.get("waypoints") or []
    return route, no_search_request(route, "saved", wps if isinstance(wps, list) else [])


SOURCE_LINES = {"saved": "saved route", "shared": "shared link", "other": "route opened outside a search"}


def _inputs(request: Dict[str, Any]) -> List[str]:
    if request.get("search_unavailable"):
        mids = request.get("waypoints") or []
        return [
            f"- Reported from: {SOURCE_LINES.get(request.get('report_source'), 'saved route')} (search settings unavailable)",
            f"- sport: {request.get('profile')}",
            f"- midpoints: {len(mids)}",
            "- start, end and midpoint coordinates are withheld",
        ]
    mids = request.get("waypoints") or []
    terrain = request.get("terrain_preference")
    return [
        f"- sport: {request.get('profile')}",
        f"- mode: {request.get('route_mode')}",
        f"- target distance: {request.get('target_distance_miles')} mi",
        f"- terrain mix: {json.dumps(terrain) if terrain else 'default'}",
        f"- loops only: {request.get('loops_only')}",
        f"- avoid closed: {request.get('avoid_closed')}",
        f"- DNR override: {request.get('override_dnr')}",
        f"- end point set: {'yes' if request.get('end') else 'no'}; midpoints: {len(mids)} (in order)",
        "- start, end and midpoint coordinates are withheld",
    ]


def build_issue_body(report_id: str, user_id: str, comment: str, request: Dict[str, Any],
                     route: Dict[str, Any], options: List[Dict[str, Any]], sha: str) -> str:
    fence = "`" * 5  # longer than anything a rider is likely to type
    head = "\n".join([
        "## Rider comment", f"{fence}text", neutralize_mentions(comment.strip()), fence, "",
        "## Inputs", *_inputs(request), "",
        "## Route",
        f"- id: {route.get('id')}; source: {route.get('source')}; shape: {route.get('route_type')}",
        f"- distance: {route.get('distance_miles')} mi; elevation gain: {route.get('elevation_gain_ft')} ft",
        f"- match score: {route.get('match_score')}; retrace: {route.get('repetition_ratio')}; "
        f"road %: {route.get('road_pct')}; access miles: {route.get('access_miles')}",
        f"- max offset from claimed OSM ways: {route.get('geometry_max_offset_m')} m",
        f"- surface breakdown: {json.dumps(route.get('surface_breakdown') or {})}",
        f"- score breakdown: {json.dumps(route.get('score_breakdown') or {})}",
        f"- warnings: {json.dumps((route.get('warnings') or []) + (route.get('dnr_warnings') or []))}", "",
        f"## Options shown ({len(options)})",
        *[f"- {o.get('id')}: {_route_name(o)}, {o.get('distance_miles')} mi, {o.get('route_type')}, "
          f"score {o.get('match_score')}" for o in options[:25]], "",
        "## Build", f"- engine config version: {CONFIG_VERSION}", f"- git sha: {sha}",
        f"- report id: {report_id}; reporter: {user_hash(user_id)}", "",
    ])
    for simplify in (None, 800, 300, 100):
        line = trimmed_line(route.get("coordinates") or [], simplify)
        geo = json.dumps({"type": "Feature", "properties": {"trimmed_each_end_m": REPORT_TRIM_M},
                          "geometry": {"type": "LineString", "coordinates": line}}, separators=(",", ":"))
        body = (f"{head}\n<details><summary>Route line (first and last 0.5 mi removed)</summary>\n\n"
                f"```json\n{geo}\n```\n\n</details>\n")
        if len(body) <= MAX_ISSUE_CHARS:
            return body
    return head + "\n(route line omitted: too large)\n"


def count_recent(user_id: str) -> int:
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM route_reports WHERE user_id = %s "
                    "AND created_at > NOW() - INTERVAL '24 hours'", (user_id,))
        return cur.fetchone()[0]


def count_recent_global() -> int:
    """Reports from everyone in the last 24 hours (the cap that keeps GitHub issue spam bounded)."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM route_reports WHERE created_at > NOW() - INTERVAL '24 hours'")
        return cur.fetchone()[0]


def store_report(user_id: str, comment: str, request: Dict[str, Any], route: Dict[str, Any],
                 options: List[Dict[str, Any]]) -> str:
    rid = str(uuid.uuid4())
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO route_reports (id, user_id, comment, request_json, route_json, options_json, "
            "engine_config_version, git_sha) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
            (rid, user_id, comment, Json(request), Json(route), Json(options), CONFIG_VERSION, git_sha()))
        conn.commit()
    return rid


def get_report(report_id: str) -> Optional[Dict[str, Any]]:
    with get_connection() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT * FROM route_reports WHERE id = %s", (report_id,))
        row = cur.fetchone()
    if not row:
        return None
    row = dict(row)
    row["id"] = str(row["id"])
    row["created_at"] = row["created_at"].isoformat()
    return row


def _headers() -> Dict[str, str]:
    return {"Authorization": f"Bearer {settings.github_feedback_token}", "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28", "User-Agent": settings.user_agent}


def _post_issue(client: httpx.Client, title: str, body: str) -> httpx.Response:
    url = f"{GITHUB_API}/repos/{settings.github_feedback_repo}/issues"
    return client.post(url, headers=_headers(), json={"title": title, "body": body, "labels": [LABEL]})


def file_issue(report: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Creates the issue for a stored report; returns {number, url}, or None (the report stays pending)."""
    if not settings.github_feedback_token:
        logger.warning("GITHUB_FEEDBACK_TOKEN is not set; report stays pending")
        return None
    request, route = report["request_json"], report["route_json"]
    body = build_issue_body(report["id"], report["user_id"], report["comment"], request, route,
                            report["options_json"], report["git_sha"] or "unknown")
    title = issue_title(route, request)
    try:
        with httpx.Client(timeout=15.0) as client:
            resp = _post_issue(client, title, body)
            if resp.status_code == 422:  # the label doesn't exist yet
                client.post(f"{GITHUB_API}/repos/{settings.github_feedback_repo}/labels", headers=_headers(),
                            json={"name": LABEL, "color": "5E8C61", "description": "Filed from the Loam app"})
                resp = _post_issue(client, title, body)
        if resp.status_code == 201:
            data = resp.json()
            return {"number": data["number"], "url": data["html_url"]}
        logger.warning(f"GitHub issue creation returned status {resp.status_code}")  # never log the body
    except Exception as e:
        logger.warning(f"GitHub issue creation failed: {type(e).__name__}")
    return None


def mark_attempt(report_id: str, filed: Optional[Dict[str, Any]]) -> None:
    with get_connection() as conn, conn.cursor() as cur:
        if filed:
            cur.execute("UPDATE route_reports SET status='filed', github_issue_number=%s, github_issue_url=%s, "
                        "attempts=attempts+1 WHERE id=%s", (filed["number"], filed["url"], report_id))
        else:
            cur.execute("UPDATE route_reports SET attempts=attempts+1 WHERE id=%s", (report_id,))
        conn.commit()


def retry_pending(limit: int = 20) -> Dict[str, int]:
    """Worker entry: files every report still pending (oldest first, at most `limit` per run)."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM route_reports WHERE status='pending' AND attempts < 20 "
                    "ORDER BY created_at LIMIT %s", (limit,))
        ids = [str(r[0]) for r in cur.fetchall()]
    filed = 0
    for rid in ids:
        report = get_report(rid)
        result = file_issue(report) if report else None
        mark_attempt(rid, result)
        filed += bool(result)
    return {"tried": len(ids), "filed": filed}
