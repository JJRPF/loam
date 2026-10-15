"""Shared route links and friends (GH-42, Round 9).

Rules (docs/round9-sharing-worklog.md): only planned routes are ever shared, never rides. A share is a
snapshot of one saved route, made when the owner shares it; editing or deleting the route later never
changes or leaks through it. Every response below is built from an explicit allowlist of fields, and the
user's id, email, photo, privacy zones, activities, heat and other routes never appear in one.

Tokens (route links, friend invites) are 32 random bytes; only their sha256 is stored, and they are
redacted from access logs (`redact_tokens`).
"""
import hashlib
import json
import logging
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Response
from psycopg2.extras import Json, RealDictCursor
from pydantic import BaseModel, Field

from app.auth import AuthUser, get_current_user
from app.config import settings
from app.db import ensure_user_exists, get_connection, get_privacy_zones, save_route_to_db
from app.fit_export import build_fit_course
from app.gpx_export import build_gpx_track
from app.privacy import haversine_m
from app.ratelimit import rate_limited

logger = logging.getLogger("loam.sharing")

router = APIRouter()

DEFAULT_SHARE_NAME = "A Loam rider"
MAX_SHARE_NAME = 40
INVITE_DAYS = 7
MAX_PENDING_INVITES = 20
METERS_PER_MILE = 1609.344
TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{43}$")  # secrets.token_urlsafe(32)

# Unknown, revoked and deleted shares all answer exactly like this.
NOT_FOUND = "This link no longer works."
PUBLIC_HEADERS = {"X-Robots-Tag": "noindex, nofollow", "Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}


def link_gone() -> HTTPException:
    return HTTPException(status_code=404, detail=NOT_FOUND, headers=PUBLIC_HEADERS)

share_view_limit = rate_limited("share_view", "opening shared routes")
share_create_limit = rate_limited("share_create", "sharing")


# --- tokens -------------------------------------------------------------------------------------

def new_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def valid_token_shape(token: str) -> bool:
    return bool(TOKEN_RE.match(token or ""))


_TOKEN_PATHS = re.compile(r"(/api/shared/|/api/friends/invites/|/r/|/friends/invite/)[A-Za-z0-9_-]{20,}")


def redact_tokens(text: str) -> str:
    return _TOKEN_PATHS.sub(r"\1<token>", text)


class _RedactAccessLog(logging.Filter):
    """uvicorn's access log prints the request path, which for a shared route holds the token."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple):
            record.args = tuple(redact_tokens(a) if isinstance(a, str) else a for a in record.args)
        if isinstance(record.msg, str):
            record.msg = redact_tokens(record.msg)
        return True


def install_log_redaction() -> None:
    for name in ("uvicorn.access", "uvicorn.error", "uvicorn"):
        lg = logging.getLogger(name)
        if not any(isinstance(f, _RedactAccessLog) for f in lg.filters):
            lg.addFilter(_RedactAccessLog())


def app_url(path: str) -> str:
    return (settings.public_app_origin + path) if settings.public_app_origin else path


# --- privacy-zone trimming ----------------------------------------------------------------------

def _in_zone(pt: List[float], zones: List[Dict[str, Any]]) -> bool:
    for z in zones:
        if haversine_m(pt[0], pt[1], float(z["lon"]), float(z["lat"])) <= float(z.get("radius_m") or 320.0):
            return True
    return False


def endpoints_in_zones(coords: List[List[float]], zones: List[Dict[str, Any]]) -> bool:
    """True when the route's first or last point is inside one of the owner's privacy zones."""
    if not coords or not zones:
        return False
    return _in_zone(coords[0], zones) or _in_zone(coords[-1], zones)


def trim_to_zones(coords: List[List[float]], zones: List[Dict[str, Any]]) -> Tuple[int, int]:
    """(lo, hi): the slice coords[lo:hi+1] left after dropping the leading and trailing points that lie
    inside a privacy zone. (0, -1) when nothing remains."""
    lo, hi = 0, len(coords) - 1
    while lo <= hi and _in_zone(coords[lo], zones):
        lo += 1
    while hi >= lo and _in_zone(coords[hi], zones):
        hi -= 1
    return (lo, hi) if hi - lo >= 1 else (0, -1)


def length_miles(coords: List[List[float]]) -> float:
    m = sum(haversine_m(a[0], a[1], b[0], b[1]) for a, b in zip(coords, coords[1:]))
    return round(m / METERS_PER_MILE, 2)


SAFE_STRIP_KEYS = ("start_index", "end_index", "surface_type", "raw_surface", "raw_road_class")


def build_snapshot(route: Dict[str, Any], zones: List[Dict[str, Any]], trim: bool) -> Dict[str, Any]:
    """What a share stores of a saved route. `is_unridden` (the owner's riding history), the verbal summary
    and the owner's via-points are left out on purpose."""
    coords = [[float(p[0]), float(p[1])] for p in (route.get("coordinates") or [])]
    strip = [{k: s.get(k) for k in SAFE_STRIP_KEYS} for s in (route.get("surface_strip") or [])]
    breakdown = dict(route.get("surface_breakdown") or {})
    gain, loss = route.get("elevation_gain_ft"), route.get("elevation_loss_ft")
    distance = route.get("distance_miles")
    trimmed = False

    if trim and endpoints_in_zones(coords, zones):
        lo, hi = trim_to_zones(coords, zones)
        if hi < lo:
            raise HTTPException(
                status_code=422,
                detail="This route lies inside your privacy zones, so there is nothing left to share.")
        if lo > 0 or hi < len(coords) - 1:
            trimmed = True
            n = hi - lo
            coords = coords[lo:hi + 1]
            new_strip = []
            for s in strip:
                a, b = max(int(s["start_index"]) - lo, 0), min(int(s["end_index"]) - lo, n)
                if b > a:
                    new_strip.append({**s, "start_index": a, "end_index": b})
            strip = new_strip
            seg_len: Dict[str, float] = {}
            for s in strip:
                seg_len[s["surface_type"]] = seg_len.get(s["surface_type"], 0.0) + sum(
                    haversine_m(coords[i][0], coords[i][1], coords[i + 1][0], coords[i + 1][1])
                    for i in range(s["start_index"], s["end_index"]))
            total = sum(seg_len.values())
            breakdown = {k: round(v / total * 100.0, 1) for k, v in seg_len.items() if total > 0 and v > 0}
            distance = length_miles(coords)
            gain = loss = None  # not known for the trimmed line; never scaled or guessed
    return {
        "name": str(route.get("name") or "Loam Route")[:120],
        "sport": route.get("sport") or "mtb",
        "distance_miles": distance,
        "elevation_gain_ft": gain,
        "elevation_loss_ft": loss,
        "coordinates": coords,
        "surface_summary": {"breakdown": breakdown, "strip": strip},
        "trimmed": trimmed,
    }


# --- response builders (explicit allowlists) ----------------------------------------------------

def share_payload(row: Dict[str, Any]) -> Dict[str, Any]:
    """The only shape a share leaves the server in (public link and friends alike)."""
    summary = row.get("surface_summary") or {}
    geo = json.loads(row["geojson"]) if row.get("geojson") else {}
    return {
        "name": row["name"],
        "sport": row["sport"],
        "distance_miles": row["distance_miles"],
        "elevation_gain_ft": row["elevation_gain_ft"],
        "elevation_loss_ft": row["elevation_loss_ft"],
        "coordinates": geo.get("coordinates", []),
        "surface_breakdown": summary.get("breakdown", {}),
        "surface_strip": [{k: s.get(k) for k in SAFE_STRIP_KEYS} for s in summary.get("strip", [])],
        "trimmed": bool(row["trimmed"]),
        "shared_by": row.get("shared_by") or DEFAULT_SHARE_NAME,
        "shared_at": row["created_at"].isoformat() if row.get("created_at") else "",
    }


def friend_route_summary(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "sport": row["sport"],
        "distance_miles": row["distance_miles"],
        "elevation_gain_ft": row["elevation_gain_ft"],
        "elevation_loss_ft": row["elevation_loss_ft"],
        "trimmed": bool(row["trimmed"]),
        "shared_by": row.get("shared_by") or DEFAULT_SHARE_NAME,
        "shared_at": row["created_at"].isoformat() if row.get("created_at") else "",
    }


SHARE_COLUMNS = (
    "s.id, s.route_id, s.mode, s.name, s.sport, s.distance_miles, s.elevation_gain_ft, s.elevation_loss_ft, "
    "s.surface_summary, s.trimmed, s.created_at, ST_AsGeoJSON(s.geom) AS geojson, "
    "u.share_display_name AS shared_by"
)


def _display_name(cur, uid: str) -> str:
    """`cur` is a RealDictCursor."""
    cur.execute("SELECT share_display_name FROM users WHERE id = %s", (uid,))
    row = cur.fetchone()
    return (row["share_display_name"] if row and row["share_display_name"] else DEFAULT_SHARE_NAME)


# --- owner: sharing a saved route ---------------------------------------------------------------

class ShareRequest(BaseModel):
    mode: str = Field(pattern="^(link|friends)$")
    trim: bool = True


class ProfileUpdate(BaseModel):
    share_display_name: Optional[str] = None


def _owned_route(cur, route_id: str, uid: str) -> Optional[Dict[str, Any]]:
    cur.execute(
        """
        SELECT id, name, sport, distance_miles, elevation_gain_ft, elevation_loss_ft,
               surface_summary, ST_AsGeoJSON(geom) AS geojson
        FROM saved_routes WHERE id = %s AND user_id = %s
        """,
        (route_id, uid),
    )
    row = cur.fetchone()
    if not row:
        return None
    item = dict(row)
    summary = item.get("surface_summary") or {}
    item["surface_breakdown"] = summary.get("breakdown", {})
    item["surface_strip"] = summary.get("strip", [])
    item["coordinates"] = json.loads(item["geojson"])["coordinates"] if item.get("geojson") else []
    return item


def _revoke(cur, route_id: str) -> None:
    cur.execute("DELETE FROM route_shares WHERE route_id = %s", (route_id,))
    cur.execute("UPDATE saved_routes SET visibility = 'private' WHERE id = %s", (route_id,))


@router.get("/api/saved-routes/{route_id}/share/preview")
async def preview_share(route_id: str, user: AuthUser = Depends(get_current_user)):
    """Tells the share dialog whether the route starts or ends inside the owner's privacy zones."""
    with get_connection() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        route = _owned_route(cur, route_id, user.uid)
    if not route:
        raise HTTPException(status_code=404, detail="Saved route not found")
    return {"zone_overlap": endpoints_in_zones(route["coordinates"], get_privacy_zones(user.uid))}


@router.post("/api/saved-routes/{route_id}/share")
async def share_route(route_id: str, req: ShareRequest, user: AuthUser = Depends(get_current_user),
                      _limit: None = Depends(share_create_limit)):
    zones = get_privacy_zones(user.uid)
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            route = _owned_route(cur, route_id, user.uid)
            if not route:
                raise HTTPException(status_code=404, detail="Saved route not found")
            if len(route["coordinates"]) < 2:
                raise HTTPException(status_code=422, detail="This route has no line to share.")
            snap = build_snapshot(route, zones, req.trim)
            _revoke(cur, route_id)  # sharing again replaces the old share (and kills an old link)
            token = new_token() if req.mode == "link" else None
            cur.execute(
                """
                INSERT INTO route_shares (route_id, user_id, mode, token_hash, name, sport, distance_miles,
                    elevation_gain_ft, elevation_loss_ft, geom, surface_summary, trimmed)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s,
                    ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326), %s, %s)
                """,
                (route_id, user.uid, req.mode, hash_token(token) if token else None, snap["name"], snap["sport"],
                 snap["distance_miles"], snap["elevation_gain_ft"], snap["elevation_loss_ft"],
                 json.dumps({"type": "LineString", "coordinates": snap["coordinates"]}),
                 Json(snap["surface_summary"]), snap["trimmed"]),
            )
            cur.execute("UPDATE saved_routes SET visibility = %s WHERE id = %s", (req.mode, route_id))
        conn.commit()
    out: Dict[str, Any] = {"mode": req.mode, "trimmed": snap["trimmed"]}
    if token:
        out["path"] = f"/r/{token}"
        out["url"] = app_url(out["path"])
    return out


@router.delete("/api/saved-routes/{route_id}/share")
async def revoke_share(route_id: str, user: AuthUser = Depends(get_current_user)):
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            if not _owned_route(cur, route_id, user.uid):
                raise HTTPException(status_code=404, detail="Saved route not found")
            _revoke(cur, route_id)
        conn.commit()
    return {"status": "private", "id": route_id}


@router.get("/api/me/shares")
async def my_shares(user: AuthUser = Depends(get_current_user)):
    with get_connection() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT route_id, mode, name, trimmed, created_at, last_viewed_at, view_count
            FROM route_shares WHERE user_id = %s ORDER BY created_at DESC
            """,
            (user.uid,),
        )
        rows = cur.fetchall()
    return {"shares": [{
        "route_id": r["route_id"], "mode": r["mode"], "name": r["name"], "trimmed": r["trimmed"],
        "shared_at": r["created_at"].isoformat(),
        "last_viewed_at": r["last_viewed_at"].isoformat() if r["last_viewed_at"] else None,
        "view_count": r["view_count"],
    } for r in rows]}


def clean_display_name(raw: Optional[str]) -> Optional[str]:
    name = " ".join("".join(ch for ch in (raw or "") if ch.isprintable()).split())
    if len(name) > MAX_SHARE_NAME:
        raise HTTPException(status_code=422, detail=f"Keep your sharing name to {MAX_SHARE_NAME} characters or fewer.")
    return name or None


@router.get("/api/me/profile")
async def get_profile(user: AuthUser = Depends(get_current_user)):
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT share_display_name FROM users WHERE id = %s", (user.uid,))
        row = cur.fetchone()
    return {"share_display_name": row[0] if row else None, "default_share_display_name": DEFAULT_SHARE_NAME}


@router.put("/api/me/profile")
async def put_profile(req: ProfileUpdate, user: AuthUser = Depends(get_current_user)):
    name = clean_display_name(req.share_display_name)
    ensure_user_exists(user.uid, email=user.email)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET share_display_name = %s WHERE id = %s", (name, user.uid))
        conn.commit()
    return {"share_display_name": name, "default_share_display_name": DEFAULT_SHARE_NAME}


# --- public: a shared link ----------------------------------------------------------------------

def _public_headers(response: Response) -> None:
    response.headers.update(PUBLIC_HEADERS)


def _link_share(token: str, count_view: bool) -> Dict[str, Any]:
    """The live link share behind a token, or a 404 that is the same for unknown, revoked and deleted."""
    if not valid_token_shape(token):
        raise link_gone()
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"""
                SELECT {SHARE_COLUMNS} FROM route_shares s JOIN users u ON u.id = s.user_id
                WHERE s.token_hash = %s AND s.mode = 'link'
                """,
                (hash_token(token),),
            )
            row = cur.fetchone()
            if not row:
                raise link_gone()
            if count_view:
                cur.execute("UPDATE route_shares SET view_count = view_count + 1, last_viewed_at = NOW() "
                            "WHERE id = %s", (row["id"],))
        conn.commit()
    return dict(row)


@router.get("/api/shared/{token}")
async def get_shared(token: str, response: Response, _limit: None = Depends(share_view_limit)):
    _public_headers(response)
    return share_payload(_link_share(token, count_view=True))


def _export(payload: Dict[str, Any], fmt: str) -> Response:
    from app.main import attachment_headers  # the one filename slugger

    coords = payload["coordinates"]
    miles = payload["distance_miles"] or 0.0
    if fmt == "gpx":
        body = build_gpx_track(
            name=payload["name"], sport=payload["sport"], coordinates=coords, distance_miles=miles,
            duration_minutes=max(miles * 6.0, 10.0), elevation_gain_ft=payload["elevation_gain_ft"],
            elevation_loss_ft=payload["elevation_loss_ft"])
        media = "application/gpx+xml"
    else:
        body = build_fit_course(
            name=payload["name"], sport=payload["sport"], coordinates=coords, distance_miles=miles,
            duration_minutes=max(miles * 6.0, 10.0), elevation_gain_ft=payload["elevation_gain_ft"] or 0.0,
            elevation_loss_ft=payload["elevation_loss_ft"] or 0.0)
        media = "application/vnd.ant.fit"
    headers = attachment_headers(payload["name"], fmt)
    headers["X-Robots-Tag"] = "noindex, nofollow"
    headers["Cache-Control"] = "no-store"
    return Response(content=body, media_type=media, headers=headers)


@router.get("/api/shared/{token}/export/gpx")
async def shared_gpx(token: str, _limit: None = Depends(share_view_limit)):
    return _export(share_payload(_link_share(token, count_view=False)), "gpx")


@router.get("/api/shared/{token}/export/fit")
async def shared_fit(token: str, _limit: None = Depends(share_view_limit)):
    return _export(share_payload(_link_share(token, count_view=False)), "fit")


def _copy_to_viewer(payload: Dict[str, Any], uid: str) -> Dict[str, Any]:
    route_id = save_route_to_db(uid, {
        "name": payload["name"], "sport": payload["sport"], "distance_miles": payload["distance_miles"] or 0.0,
        "elevation_gain_ft": payload["elevation_gain_ft"], "elevation_loss_ft": payload["elevation_loss_ft"],
        "coordinates": payload["coordinates"], "surface_breakdown": payload["surface_breakdown"],
        "surface_strip": payload["surface_strip"],
    })
    if not route_id:
        raise HTTPException(status_code=500, detail="Failed to save route to database")
    return {"status": "saved", "id": route_id}


@router.post("/api/shared/{token}/copy")
async def copy_shared(token: str, user: AuthUser = Depends(get_current_user),
                      _limit: None = Depends(share_create_limit)):
    return _copy_to_viewer(share_payload(_link_share(token, count_view=False)), user.uid)


# --- friends ------------------------------------------------------------------------------------

def _pair(a: str, b: str) -> Tuple[str, str]:
    """Byte order, like the friendships CHECK (`COLLATE "C"`); Firebase uids are mixed case."""
    return (a, b) if a.encode() < b.encode() else (b, a)


def _blocked_either_way(cur, a: str, b: str) -> bool:
    cur.execute("SELECT 1 FROM blocks WHERE (blocker = %s AND blocked = %s) OR (blocker = %s AND blocked = %s)",
                (a, b, b, a))
    return cur.fetchone() is not None


class FriendsSql:
    """The friend set of a user: accepted friendships with no block either way."""
    IDS = """
        SELECT CASE WHEN f.user_a = %(u)s THEN f.user_b ELSE f.user_a END
        FROM friendships f
        WHERE (f.user_a = %(u)s OR f.user_b = %(u)s)
          AND NOT EXISTS (SELECT 1 FROM blocks b
                          WHERE (b.blocker = f.user_a AND b.blocked = f.user_b)
                             OR (b.blocker = f.user_b AND b.blocked = f.user_a))
    """


@router.post("/api/friends/invites")
async def create_invite(user: AuthUser = Depends(get_current_user), _limit: None = Depends(share_create_limit)):
    ensure_user_exists(user.uid, email=user.email)
    token = new_token()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM friend_invites WHERE inviter_id = %s AND used_at IS NULL "
                        "AND expires_at > NOW()", (user.uid,))
            if cur.fetchone()[0] >= MAX_PENDING_INVITES:
                raise HTTPException(status_code=429, detail="You have a lot of open invites. Cancel some first.",
                                    headers={"Retry-After": "3600"})
            expires = datetime.now(timezone.utc) + timedelta(days=INVITE_DAYS)
            cur.execute("INSERT INTO friend_invites (token_hash, inviter_id, expires_at) VALUES (%s, %s, %s) "
                        "RETURNING id", (hash_token(token), user.uid, expires))
            invite_id = cur.fetchone()[0]
        conn.commit()
    path = f"/friends/invite/{token}"
    return {"id": invite_id, "path": path, "url": app_url(path), "expires_at": expires.isoformat()}


@router.get("/api/friends/invites")
async def list_invites(user: AuthUser = Depends(get_current_user)):
    with get_connection() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT id, created_at, expires_at FROM friend_invites WHERE inviter_id = %s "
                    "AND used_at IS NULL AND expires_at > NOW() ORDER BY created_at DESC", (user.uid,))
        rows = cur.fetchall()
    return {"invites": [{"id": r["id"], "created_at": r["created_at"].isoformat(),
                         "expires_at": r["expires_at"].isoformat()} for r in rows]}


@router.delete("/api/friends/invites/{invite_id}")
async def cancel_invite(invite_id: int, user: AuthUser = Depends(get_current_user)):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM friend_invites WHERE id = %s AND inviter_id = %s AND used_at IS NULL",
                        (invite_id, user.uid))
            gone = cur.rowcount > 0
        conn.commit()
    if not gone:
        raise HTTPException(status_code=404, detail="Invite not found")
    return {"status": "cancelled", "id": invite_id}


def _usable_invite(cur, token: str, uid: str, lock: bool) -> Dict[str, Any]:
    """The invite behind `token` for `uid`. Unknown tokens and invites from or to a blocked user are 404;
    your own invite is 400; a used or expired one is 410."""
    if not valid_token_shape(token):
        raise HTTPException(status_code=404, detail="This invite doesn't work.")
    cur.execute(
        "SELECT id, inviter_id, expires_at, used_at FROM friend_invites WHERE token_hash = %s"
        + (" FOR UPDATE" if lock else ""),
        (hash_token(token),),
    )
    row = cur.fetchone()
    if not row or _blocked_either_way(cur, row["inviter_id"], uid):
        raise HTTPException(status_code=404, detail="This invite doesn't work.")
    if row["inviter_id"] == uid:
        raise HTTPException(status_code=400, detail="That's your own invite. Send it to a friend instead.")
    if row["used_at"] is not None or row["expires_at"] <= datetime.now(timezone.utc):
        raise HTTPException(status_code=410, detail="This invite was already used or has expired.")
    return dict(row)


@router.get("/api/friends/invites/{token}")
async def look_at_invite(token: str, user: AuthUser = Depends(get_current_user),
                         _limit: None = Depends(share_view_limit)):
    with get_connection() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        inv = _usable_invite(cur, token, user.uid, lock=False)
        return {"inviter_name": _display_name(cur, inv["inviter_id"])}


@router.post("/api/friends/invites/{token}/accept")
async def accept_invite(token: str, user: AuthUser = Depends(get_current_user),
                        _limit: None = Depends(share_create_limit)):
    ensure_user_exists(user.uid, email=user.email)
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            inv = _usable_invite(cur, token, user.uid, lock=True)
            a, b = _pair(inv["inviter_id"], user.uid)
            cur.execute("INSERT INTO friendships (user_a, user_b) VALUES (%s, %s) ON CONFLICT DO NOTHING "
                        "RETURNING id", (a, b))
            cur.execute("UPDATE friend_invites SET used_by = %s, used_at = NOW() WHERE id = %s",
                        (user.uid, inv["id"]))
            name = _display_name(cur, inv["inviter_id"])
        conn.commit()
    return {"status": "friends", "friend_name": name}


@router.get("/api/friends")
async def list_friends(user: AuthUser = Depends(get_current_user)):
    with get_connection() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            f"""
            SELECT f.id, f.created_at, u.share_display_name
            FROM friendships f
            JOIN users u ON u.id = CASE WHEN f.user_a = %(u)s THEN f.user_b ELSE f.user_a END
            WHERE (f.user_a = %(u)s OR f.user_b = %(u)s)
              AND (CASE WHEN f.user_a = %(u)s THEN f.user_b ELSE f.user_a END) IN ({FriendsSql.IDS})
            ORDER BY f.created_at DESC
            """,
            {"u": user.uid},
        )
        friends = cur.fetchall()
        cur.execute("SELECT b.id, b.created_at, u.share_display_name FROM blocks b JOIN users u ON u.id = b.blocked "
                    "WHERE b.blocker = %s ORDER BY b.created_at DESC", (user.uid,))
        blocked = cur.fetchall()
    return {
        "friends": [{"id": r["id"], "name": r["share_display_name"] or DEFAULT_SHARE_NAME,
                     "since": r["created_at"].isoformat()} for r in friends],
        "blocked": [{"id": r["id"], "name": r["share_display_name"] or DEFAULT_SHARE_NAME,
                     "since": r["created_at"].isoformat()} for r in blocked],
    }


def _friendship_other(cur, friendship_id: int, uid: str) -> Optional[str]:
    cur.execute("SELECT user_a, user_b FROM friendships WHERE id = %s AND (user_a = %s OR user_b = %s)",
                (friendship_id, uid, uid))
    row = cur.fetchone()
    if not row:
        return None
    return row["user_b"] if row["user_a"] == uid else row["user_a"]


@router.delete("/api/friends/{friendship_id}")
async def remove_friend(friendship_id: int, user: AuthUser = Depends(get_current_user)):
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            if _friendship_other(cur, friendship_id, user.uid) is None:
                raise HTTPException(status_code=404, detail="Friend not found")
            cur.execute("DELETE FROM friendships WHERE id = %s", (friendship_id,))
        conn.commit()
    return {"status": "removed", "id": friendship_id}


@router.post("/api/friends/{friendship_id}/block")
async def block_friend(friendship_id: int, user: AuthUser = Depends(get_current_user)):
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            other = _friendship_other(cur, friendship_id, user.uid)
            if other is None:
                raise HTTPException(status_code=404, detail="Friend not found")
            cur.execute("INSERT INTO blocks (blocker, blocked) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                        (user.uid, other))
            cur.execute("DELETE FROM friendships WHERE id = %s", (friendship_id,))
        conn.commit()
    return {"status": "blocked"}


@router.delete("/api/friends/blocks/{block_id}")
async def unblock(block_id: int, user: AuthUser = Depends(get_current_user)):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM blocks WHERE id = %s AND blocker = %s", (block_id, user.uid))
            gone = cur.rowcount > 0
        conn.commit()
    if not gone:
        raise HTTPException(status_code=404, detail="Not found")
    return {"status": "unblocked", "id": block_id}


@router.get("/api/friends/routes")
async def friends_routes(user: AuthUser = Depends(get_current_user)):
    with get_connection() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            f"""
            SELECT {SHARE_COLUMNS} FROM route_shares s JOIN users u ON u.id = s.user_id
            WHERE s.mode = 'friends' AND s.user_id IN ({FriendsSql.IDS})
            ORDER BY s.created_at DESC
            """,
            {"u": user.uid},
        )
        rows = cur.fetchall()
    return {"routes": [friend_route_summary(r) for r in rows]}


def _friend_share(share_id: int, uid: str) -> Dict[str, Any]:
    with get_connection() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            f"""
            SELECT {SHARE_COLUMNS} FROM route_shares s JOIN users u ON u.id = s.user_id
            WHERE s.id = %(id)s AND s.mode = 'friends'
              AND s.user_id IN ({FriendsSql.IDS})
            """,
            {"id": share_id, "u": uid},
        )
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Route not found")
    return dict(row)


@router.get("/api/friends/routes/{share_id}")
async def friend_route(share_id: int, user: AuthUser = Depends(get_current_user)):
    return {**share_payload(_friend_share(share_id, user.uid)), "id": share_id}


@router.get("/api/friends/routes/{share_id}/export/gpx")
async def friend_route_gpx(share_id: int, user: AuthUser = Depends(get_current_user)):
    return _export(share_payload(_friend_share(share_id, user.uid)), "gpx")


@router.get("/api/friends/routes/{share_id}/export/fit")
async def friend_route_fit(share_id: int, user: AuthUser = Depends(get_current_user)):
    return _export(share_payload(_friend_share(share_id, user.uid)), "fit")


@router.post("/api/friends/routes/{share_id}/copy")
async def copy_friend_route(share_id: int, user: AuthUser = Depends(get_current_user),
                            _limit: None = Depends(share_create_limit)):
    return _copy_to_viewer(share_payload(_friend_share(share_id, user.uid)), user.uid)
