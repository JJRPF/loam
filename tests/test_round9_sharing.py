"""Round 9 (GH-42): shared route links and friends. Planned routes only; rides are never shared.

The point of this file is to prove it is actually private: an authorization matrix, leak tests, token
handling, rate limits and a route-table check. Routes are synthetic, on a made-up line in open country.
"""
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from app import sharing
from app.auth import get_current_user
from app.config import settings
from app.db import create_privacy_zone, ensure_user_exists, get_connection
from app.main import app
from app.privacy import haversine_m
from tests.conftest import as_user

FORBIDDEN_KEYS = {"user_id", "email", "uid", "privacy", "activity", "heat", "inviter_id", "photo", "picture",
                  "privacy_zones", "waypoints", "is_unridden", "verbal_summary", "token_hash", "route_id"}
START = (-71.0, 43.0)  # lon, lat: a made-up start


def line(n=40, step=0.002):
    return [[START[0] + i * step, START[1] + i * step * 0.3] for i in range(n)]


def route_body(name="Test Loop", coords=None):
    coords = coords or line()
    return {
        "name": name, "sport": "mtb", "distance_miles": 3.1, "elevation_gain_ft": 300.0, "elevation_loss_ft": 290.0,
        "coordinates": coords,
        "surface_breakdown": {"singletrack": 60.0, "gravel": 40.0},
        "surface_strip": [
            {"start_index": 0, "end_index": 20, "surface_type": "singletrack", "is_unridden": True},
            {"start_index": 20, "end_index": len(coords) - 1, "surface_type": "gravel", "raw_surface": "gravel"},
        ],
        "waypoints": [{"lat": START[1], "lon": START[0], "label": "home-ish via point"}],
        "verbal_summary": "You have ridden 80% of this",
    }


def walk_keys(obj, found=None):
    found = set() if found is None else found
    if isinstance(obj, dict):
        for k, v in obj.items():
            found.add(k.lower())
            walk_keys(v, found)
    elif isinstance(obj, list):
        for v in obj:
            walk_keys(v, found)
    return found


def client():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def token_of(url_or_path: str) -> str:
    return url_or_path.rsplit("/", 1)[1]


@pytest.fixture
def people():
    tag = uuid.uuid4().hex[:8]
    ids = {k: f"r9_{k}_{tag}" for k in ("owner", "friend", "stranger", "blocked", "admin", "viewer")}
    for uid in ids.values():
        ensure_user_exists(uid, email=f"{uid}@test.loam")
    yield ids
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM users WHERE id = ANY(%s)", (list(ids.values()),))
        conn.commit()


async def save(c, uid, **kw):
    r = await c.post("/api/saved-routes", json=route_body(**kw), headers=as_user(uid))
    assert r.status_code == 200, r.text
    return r.json()["id"]


async def befriend(c, a, b):
    inv = (await c.post("/api/friends/invites", headers=as_user(a))).json()
    r = await c.post(f"/api/friends/invites/{token_of(inv['path'])}/accept", headers=as_user(b))
    assert r.status_code == 200, r.text


async def friends_view(c, who, me):
    """The friendship id `me` sees for `who`'s display name is not needed; return the list of routes."""
    return (await c.get("/api/friends/routes", headers=as_user(me))).json()["routes"]


# --- migration ------------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_existing_and_new_routes_stay_private(people):
    async with client() as c:
        rid = await save(c, people["owner"])
        mine = (await c.get("/api/saved-routes", headers=as_user(people["owner"]))).json()["routes"]
    assert [r["visibility"] for r in mine if r["id"] == rid] == ["private"]
    with get_connection() as conn, conn.cursor() as cur:
        # a row written the way pre-migration code wrote it (no visibility column in the INSERT)
        cur.execute("INSERT INTO saved_routes (id, user_id, name, sport) VALUES (%s, %s, 'old', 'mtb') "
                    "RETURNING visibility", (f"old_{uuid.uuid4().hex}", people["owner"]))
        assert cur.fetchone()[0] == "private"
        cur.execute("SELECT count(*) FROM saved_routes WHERE visibility <> 'private' AND user_id = %s",
                    (people["owner"],))
        assert cur.fetchone()[0] == 0
        conn.rollback()


# --- the link flow, and what a public response may hold -----------------------------------------

@pytest.mark.asyncio
async def test_link_share_public_view_export_revoke(people):
    owner = people["owner"]
    async with client() as c:
        await c.put("/api/me/profile", json={"share_display_name": "  Trail  Gnome "}, headers=as_user(owner))
        rid = await save(c, owner)
        share = await c.post(f"/api/saved-routes/{rid}/share", json={"mode": "link"}, headers=as_user(owner))
        assert share.status_code == 200, share.text
        token = token_of(share.json()["path"])
        assert len(token) >= 43  # 32 random bytes

        pub = await c.get(f"/api/shared/{token}")  # signed out
        assert pub.status_code == 200
        assert pub.headers["x-robots-tag"].startswith("noindex")
        body = pub.json()
        assert body["shared_by"] == "Trail Gnome"
        assert body["name"] == "Test Loop" and len(body["coordinates"]) == 40
        assert all("is_unridden" not in s for s in body["surface_strip"])
        assert not (walk_keys(body) & FORBIDDEN_KEYS), walk_keys(body) & FORBIDDEN_KEYS
        text = pub.text
        assert owner not in text and f"{owner}@test.loam" not in text and "ridden" not in text

        gpx = await c.get(f"/api/shared/{token}/export/gpx")
        assert gpx.status_code == 200 and "<trk>" in gpx.text and "home-ish" not in gpx.text
        fit = await c.get(f"/api/shared/{token}/export/fit")
        assert fit.status_code == 200 and len(fit.content) > 50

        listed = (await c.get("/api/me/shares", headers=as_user(owner))).json()["shares"]
        assert listed[0]["view_count"] == 1 and "token" not in json.dumps(listed)
        assert (await c.get("/api/saved-routes", headers=as_user(owner))).json()["routes"][0]["visibility"] == "link"

        assert (await c.delete(f"/api/saved-routes/{rid}/share", headers=as_user(owner))).status_code == 200
        dead = await c.get(f"/api/shared/{token}")
        assert dead.status_code == 404
        assert (await c.get("/api/saved-routes", headers=as_user(owner))).json()["routes"][0]["visibility"] == "private"
    with get_connection() as conn, conn.cursor() as cur:  # a revoked share leaves nothing behind
        cur.execute("SELECT count(*) FROM route_shares WHERE route_id = %s", (rid,))
        assert cur.fetchone()[0] == 0


@pytest.mark.asyncio
async def test_unknown_revoked_and_deleted_look_identical(people):
    owner = people["owner"]
    async with client() as c:
        rid = await save(c, owner)
        tok_revoked = token_of((await c.post(f"/api/saved-routes/{rid}/share", json={"mode": "link"},
                                             headers=as_user(owner))).json()["path"])
        await c.delete(f"/api/saved-routes/{rid}/share", headers=as_user(owner))
        rid2 = await save(c, owner)
        tok_deleted = token_of((await c.post(f"/api/saved-routes/{rid2}/share", json={"mode": "link"},
                                             headers=as_user(owner))).json()["path"])
        assert (await c.delete(f"/api/saved-routes/{rid2}", headers=as_user(owner))).status_code == 200
        responses = [await c.get(f"/api/shared/{t}") for t in (tok_revoked, tok_deleted, sharing.new_token(), "short")]
    assert {r.status_code for r in responses} == {404}
    assert len({r.text for r in responses}) == 1
    assert all(r.headers["x-robots-tag"].startswith("noindex") and r.headers["cache-control"] == "no-store"
               for r in responses)


@pytest.mark.asyncio
async def test_sharing_again_replaces_the_old_link(people):
    owner = people["owner"]
    async with client() as c:
        rid = await save(c, owner)
        t1 = token_of((await c.post(f"/api/saved-routes/{rid}/share", json={"mode": "link"},
                                    headers=as_user(owner))).json()["path"])
        t2 = token_of((await c.post(f"/api/saved-routes/{rid}/share", json={"mode": "link"},
                                    headers=as_user(owner))).json()["path"])
        assert t1 != t2
        assert (await c.get(f"/api/shared/{t1}")).status_code == 404
        assert (await c.get(f"/api/shared/{t2}")).status_code == 200
        # switching to friends kills the link
        await c.post(f"/api/saved-routes/{rid}/share", json={"mode": "friends"}, headers=as_user(owner))
        assert (await c.get(f"/api/shared/{t2}")).status_code == 404


@pytest.mark.asyncio
async def test_display_name_rules(people):
    async with client() as c:
        h = as_user(people["owner"])
        assert (await c.put("/api/me/profile", json={"share_display_name": "x" * 41}, headers=h)).status_code == 422
        ok = await c.put("/api/me/profile", json={"share_display_name": "x" * 40}, headers=h)
        assert ok.status_code == 200
        reset = await c.put("/api/me/profile", json={"share_display_name": "   "}, headers=h)
        assert reset.json()["share_display_name"] is None
        rid = await save(c, people["owner"])
        tok = token_of((await c.post(f"/api/saved-routes/{rid}/share", json={"mode": "link"}, headers=h)).json()["path"])
        assert (await c.get(f"/api/shared/{tok}")).json()["shared_by"] == "A Loam rider"


# --- privacy zones ---------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_default_trim_leaves_nothing_inside_the_zone(people):
    owner = people["owner"]
    create_privacy_zone(owner, "Home", START[1], START[0], 320.0)
    async with client() as c:
        h = as_user(owner)
        rid = await save(c, owner)
        assert (await c.get(f"/api/saved-routes/{rid}/share/preview", headers=h)).json() == {"zone_overlap": True}
        share = await c.post(f"/api/saved-routes/{rid}/share", json={"mode": "link"}, headers=h)  # default trim
        assert share.json()["trimmed"] is True
        pub = (await c.get(f"/api/shared/{token_of(share.json()['path'])}")).json()
    coords = pub["coordinates"]
    assert 2 <= len(coords) < 40 and pub["trimmed"] is True
    assert all(haversine_m(p[0], p[1], START[0], START[1]) > 320.0 for p in coords)
    assert pub["elevation_gain_ft"] is None and pub["elevation_loss_ft"] is None  # never guessed
    assert pub["distance_miles"] == sharing.length_miles(coords) < sharing.length_miles(line())
    n = len(coords) - 1
    assert all(0 <= s["start_index"] < s["end_index"] <= n for s in pub["surface_strip"])
    assert abs(sum(pub["surface_breakdown"].values()) - 100.0) < 0.5


@pytest.mark.asyncio
async def test_opt_out_stores_the_full_route(people):
    owner = people["owner"]
    create_privacy_zone(owner, "Home", START[1], START[0], 320.0)
    async with client() as c:
        h = as_user(owner)
        rid = await save(c, owner)
        share = await c.post(f"/api/saved-routes/{rid}/share", json={"mode": "link", "trim": False}, headers=h)
        pub = (await c.get(f"/api/shared/{token_of(share.json()['path'])}")).json()
    assert pub["trimmed"] is False and len(pub["coordinates"]) == 40 and pub["elevation_gain_ft"] == 300.0


@pytest.mark.asyncio
async def test_route_outside_zones_is_untouched_and_all_inside_is_refused(people):
    owner = people["owner"]
    create_privacy_zone(owner, "Elsewhere", 10.0, 10.0, 320.0)
    async with client() as c:
        h = as_user(owner)
        rid = await save(c, owner)
        assert (await c.get(f"/api/saved-routes/{rid}/share/preview", headers=h)).json() == {"zone_overlap": False}
        share = await c.post(f"/api/saved-routes/{rid}/share", json={"mode": "link"}, headers=h)
        assert share.json()["trimmed"] is False
        create_privacy_zone(owner, "Everything", START[1], START[0], 50000.0)
        rid2 = await save(c, owner)
        assert (await c.post(f"/api/saved-routes/{rid2}/share", json={"mode": "link"}, headers=h)).status_code == 422


# --- authorization matrix --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_authorization_matrix(people):
    p = people
    async with client() as c:
        await befriend(c, p["owner"], p["friend"])
        await befriend(c, p["owner"], p["blocked"])
        blocked_fid = (await c.get("/api/friends", headers=as_user(p["owner"]))).json()["friends"][0]["id"]  # newest
        assert (await c.post(f"/api/friends/{blocked_fid}/block", headers=as_user(p["owner"]))).status_code == 200

        rid = await save(c, p["owner"])
        actors = {
            "owner": as_user(p["owner"]), "friend": as_user(p["friend"]), "stranger": as_user(p["stranger"]),
            "blocked": as_user(p["blocked"]), "admin": as_user(p["admin"], admin=True), "signed_out": {},
        }

        async def friend_status(state_headers):
            r = await c.get("/api/friends/routes", headers=state_headers)
            if r.status_code != 200:
                return r.status_code, None
            routes = r.json()["routes"]
            return 200, (routes[0]["id"] if routes else None)

        # owner-only endpoints: only the owner gets through; others 404 (signed out 401)
        for name, h in actors.items():
            for method, path, body in (
                ("GET", f"/api/saved-routes/{rid}/share/preview", None),
                ("POST", f"/api/saved-routes/{rid}/share", {"mode": "friends"}),
                ("DELETE", f"/api/saved-routes/{rid}/share", None),
                ("GET", f"/api/export/gpx/{rid}", None),
                ("GET", f"/api/export/fit/{rid}", None),
                ("GET", f"/api/saved-routes/{rid}", None),
            ):
                r = await c.request(method, path, json=body, headers=h)
                if name == "owner":
                    assert r.status_code == 200, (name, method, path, r.text)
                elif name == "signed_out":
                    assert r.status_code == 401, (name, method, path)
                else:
                    assert r.status_code == 404, (name, method, path, r.status_code)
            # leave it shared with friends for the next actor
            await c.post(f"/api/saved-routes/{rid}/share", json={"mode": "friends"}, headers=actors["owner"])

        # friends-visibility: who can see it
        seen = {}
        for name, h in actors.items():
            seen[name] = await friend_status(h)
        assert seen["friend"][0] == 200 and seen["friend"][1] is not None
        assert seen["signed_out"][0] == 401
        for name in ("owner", "stranger", "blocked", "admin"):
            assert seen[name] == (200, None), (name, seen[name])  # an empty list, never the route
        sid = seen["friend"][1]
        for name, h in actors.items():
            for suffix in ("", "/export/gpx", "/export/fit"):
                r = await c.get(f"/api/friends/routes/{sid}{suffix}", headers=h)
                want = 200 if name == "friend" else (401 if name == "signed_out" else 404)
                assert r.status_code == want, (name, suffix, r.status_code)
            r = await c.post(f"/api/friends/routes/{sid}/copy", headers=h)
            want = 200 if name == "friend" else (401 if name == "signed_out" else 404)
            assert r.status_code == want, (name, "copy", r.status_code)
        detail = (await c.get(f"/api/friends/routes/{sid}", headers=actors["friend"])).json()
        assert not (walk_keys(detail) & (FORBIDDEN_KEYS - {"route_id"}))
        assert p["owner"] not in json.dumps(detail)

        # a friends-visibility route has no public link at all
        assert (await c.get("/api/shared/" + sharing.new_token())).status_code == 404

        # revoked and deleted: nobody sees it any more
        await c.delete(f"/api/saved-routes/{rid}/share", headers=actors["owner"])
        assert (await c.get(f"/api/friends/routes/{sid}", headers=actors["friend"])).status_code == 404
        assert (await friends_view(c, None, p["friend"])) == []
        await c.post(f"/api/saved-routes/{rid}/share", json={"mode": "friends"}, headers=actors["owner"])
        assert len(await friends_view(c, None, p["friend"])) == 1
        await c.delete(f"/api/saved-routes/{rid}", headers=actors["owner"])
        assert (await friends_view(c, None, p["friend"])) == []

        # unfriending removes access, blocking too
        rid = await save(c, p["owner"])
        await c.post(f"/api/saved-routes/{rid}/share", json={"mode": "friends"}, headers=actors["owner"])
        assert len(await friends_view(c, None, p["friend"])) == 1
        fid = (await c.get("/api/friends", headers=actors["friend"])).json()["friends"][0]["id"]
        assert (await c.delete(f"/api/friends/{fid}", headers=actors["friend"])).status_code == 200
        assert (await friends_view(c, None, p["friend"])) == []


@pytest.mark.asyncio
async def test_signed_out_and_other_users_cannot_touch_owner_endpoints(people):
    async with client() as c:
        for method, path in (
            ("PUT", "/api/me/profile"), ("GET", "/api/me/profile"), ("GET", "/api/me/shares"),
            ("POST", "/api/friends/invites"), ("GET", "/api/friends/invites"), ("GET", "/api/friends"),
            ("GET", "/api/friends/routes"), ("POST", "/api/shared/" + sharing.new_token() + "/copy"),
        ):
            r = await c.request(method, path, json={} if method in ("PUT", "POST") else None)
            assert r.status_code == 401, (method, path, r.status_code)


@pytest.mark.asyncio
async def test_idor_ids_and_swapped_tokens(people):
    p = people
    async with client() as c:
        a = await save(c, p["owner"], name="A")
        b = await save(c, p["stranger"], name="B")
        ta = token_of((await c.post(f"/api/saved-routes/{a}/share", json={"mode": "link"},
                                    headers=as_user(p["owner"]))).json()["path"])
        # the stranger cannot share, revoke or preview the owner's route id
        for method, path, body in (("POST", f"/api/saved-routes/{a}/share", {"mode": "link"}),
                                   ("DELETE", f"/api/saved-routes/{a}/share", None),
                                   ("GET", f"/api/saved-routes/{a}/share/preview", None)):
            assert (await c.request(method, path, json=body, headers=as_user(p["stranger"]))).status_code == 404
        # ...and the owner's link is still alive
        assert (await c.get(f"/api/shared/{ta}")).status_code == 200
        # a swapped token (the route id, or the token of another route) never opens anything
        tb = token_of((await c.post(f"/api/saved-routes/{b}/share", json={"mode": "link"},
                                    headers=as_user(p["stranger"]))).json()["path"])
        assert (await c.get(f"/api/shared/{a}")).status_code == 404
        assert (await c.get(f"/api/shared/{ta}")).json()["name"] == "A"
        assert (await c.get(f"/api/shared/{tb}")).json()["name"] == "B"
        # the share row's own id is not a token either
        assert (await c.get("/api/shared/1")).status_code == 404


# --- invites ---------------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_invite_rules(people):
    p = people
    async with client() as c:
        inv = (await c.post("/api/friends/invites", headers=as_user(p["owner"]))).json()
        tok = token_of(inv["path"])
        # own invite
        assert (await c.post(f"/api/friends/invites/{tok}/accept", headers=as_user(p["owner"]))).status_code == 400
        # signed out
        assert (await c.post(f"/api/friends/invites/{tok}/accept")).status_code == 401
        # a stranger-to-all can look, then accept; the invite is one-time
        assert (await c.get(f"/api/friends/invites/{tok}", headers=as_user(p["friend"]))).json() == {
            "inviter_name": "A Loam rider"}
        ok = await c.post(f"/api/friends/invites/{tok}/accept", headers=as_user(p["friend"]))
        assert ok.status_code == 200, ok.text
        assert (await c.post(f"/api/friends/invites/{tok}/accept", headers=as_user(p["stranger"]))).status_code == 410
        assert (await c.post(f"/api/friends/invites/{tok}/accept", headers=as_user(p["friend"]))).status_code == 410
        # unknown / malformed tokens
        assert (await c.post(f"/api/friends/invites/{sharing.new_token()}/accept",
                             headers=as_user(p["stranger"]))).status_code == 404
        assert (await c.post("/api/friends/invites/abc/accept", headers=as_user(p["stranger"]))).status_code == 404

        # expired
        inv2 = (await c.post("/api/friends/invites", headers=as_user(p["owner"]))).json()
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("UPDATE friend_invites SET expires_at = %s WHERE id = %s",
                        (datetime.now(timezone.utc) - timedelta(minutes=1), inv2["id"]))
            conn.commit()
        assert (await c.post(f"/api/friends/invites/{token_of(inv2['path'])}/accept",
                             headers=as_user(p["stranger"]))).status_code == 410

        # a blocked user's invite looks like an unknown one, in both directions
        inv3 = (await c.post("/api/friends/invites", headers=as_user(p["blocked"]))).json()
        await c.post(f"/api/friends/invites/{token_of(inv3['path'])}/accept", headers=as_user(p["stranger"]))
        fid = (await c.get("/api/friends", headers=as_user(p["stranger"]))).json()["friends"][0]["id"]
        await c.post(f"/api/friends/{fid}/block", headers=as_user(p["stranger"]))
        inv4 = (await c.post("/api/friends/invites", headers=as_user(p["blocked"]))).json()
        assert (await c.post(f"/api/friends/invites/{token_of(inv4['path'])}/accept",
                             headers=as_user(p["stranger"]))).status_code == 404
        inv5 = (await c.post("/api/friends/invites", headers=as_user(p["stranger"]))).json()
        assert (await c.post(f"/api/friends/invites/{token_of(inv5['path'])}/accept",
                             headers=as_user(p["blocked"]))).status_code == 404
        # unblock, then it works again
        bid = (await c.get("/api/friends", headers=as_user(p["stranger"]))).json()["blocked"][0]["id"]
        assert (await c.delete(f"/api/friends/blocks/{bid}", headers=as_user(p["stranger"]))).status_code == 200
        assert (await c.post(f"/api/friends/invites/{token_of(inv5['path'])}/accept",
                             headers=as_user(p["blocked"]))).status_code == 200


@pytest.mark.asyncio
async def test_invite_list_cancel_and_cap(people):
    p = people
    async with client() as c:
        h = as_user(p["owner"])
        inv = (await c.post("/api/friends/invites", headers=h)).json()
        listed = (await c.get("/api/friends/invites", headers=h)).json()["invites"]
        assert [i["id"] for i in listed] == [inv["id"]] and "path" not in json.dumps(listed)
        assert (await c.delete(f"/api/friends/invites/{inv['id']}", headers=as_user(p["stranger"]))).status_code == 404
        assert (await c.delete(f"/api/friends/invites/{inv['id']}", headers=h)).status_code == 200
        assert (await c.post(f"/api/friends/invites/{token_of(inv['path'])}/accept",
                             headers=as_user(p["friend"]))).status_code == 404
        sharing.MAX_PENDING_INVITES, old = 2, sharing.MAX_PENDING_INVITES
        try:
            for _ in range(2):
                assert (await c.post("/api/friends/invites", headers=h)).status_code == 200
            assert (await c.post("/api/friends/invites", headers=h)).status_code == 429
        finally:
            sharing.MAX_PENDING_INVITES = old


@pytest.mark.asyncio
async def test_friend_ids_are_never_user_ids(people):
    p = people
    async with client() as c:
        await befriend(c, p["owner"], p["friend"])
        for who in ("owner", "friend"):
            body = (await c.get("/api/friends", headers=as_user(p[who]))).text
            assert not any(uid in body for uid in p.values()), body
        # a friendship id of someone else's friendship is 404 for a third party
        fid = (await c.get("/api/friends", headers=as_user(p["owner"]))).json()["friends"][0]["id"]
        assert (await c.delete(f"/api/friends/{fid}", headers=as_user(p["stranger"]))).status_code == 404
        assert (await c.post(f"/api/friends/{fid}/block", headers=as_user(p["stranger"]))).status_code == 404


@pytest.mark.asyncio
async def test_copy_creates_a_private_route_for_the_viewer(people):
    p = people
    async with client() as c:
        rid = await save(c, p["owner"])
        tok = token_of((await c.post(f"/api/saved-routes/{rid}/share", json={"mode": "link"},
                                     headers=as_user(p["owner"]))).json()["path"])
        r = await c.post(f"/api/shared/{tok}/copy", headers=as_user(p["viewer"]))
        assert r.status_code == 200
        mine = (await c.get("/api/saved-routes", headers=as_user(p["viewer"]))).json()["routes"]
        assert [x["id"] for x in mine] == [r.json()["id"]] and mine[0]["visibility"] == "private"
        assert len(mine[0]["coordinates"]) == 40 and mine[0]["waypoints"] == []
        # the copy is the viewer's: deleting the original does not touch it
        await c.delete(f"/api/saved-routes/{rid}", headers=as_user(p["owner"]))
        assert len((await c.get("/api/saved-routes", headers=as_user(p["viewer"]))).json()["routes"]) == 1


# --- tokens ----------------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_only_hashes_are_stored_and_tokens_are_not_logged(people, caplog):
    p = people
    caplog.set_level(logging.DEBUG)
    async with client() as c:
        rid = await save(c, p["owner"])
        share = (await c.post(f"/api/saved-routes/{rid}/share", json={"mode": "link"}, headers=as_user(p["owner"]))).json()
        tok = token_of(share["path"])
        inv = (await c.post("/api/friends/invites", headers=as_user(p["owner"]))).json()
        itok = token_of(inv["path"])
        await c.get(f"/api/shared/{tok}")
        await c.get(f"/api/shared/{tok}/export/gpx")
        await c.post(f"/api/friends/invites/{itok}/accept", headers=as_user(p["friend"]))
    assert len(tok) == 43 and len(itok) == 43  # 256 bits
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT token_hash FROM route_shares WHERE route_id = %s", (rid,))
        assert cur.fetchone()[0] == sharing.hash_token(tok) != tok
        cur.execute("SELECT token_hash FROM friend_invites WHERE id = %s", (inv["id"],))
        assert cur.fetchone()[0] == sharing.hash_token(itok)
        cur.execute("SELECT count(*) FROM route_shares WHERE token_hash = %s", (tok,))
        assert cur.fetchone()[0] == 0
    app_logs = "\n".join(r.getMessage() for r in caplog.records if not r.name.startswith("httpx"))  # httpx is the test client
    assert tok not in app_logs and itok not in app_logs


def test_access_log_redaction():
    filt = sharing._RedactAccessLog()
    tok = sharing.new_token()
    rec = logging.LogRecord("uvicorn.access", logging.INFO, "", 0, '%s - "%s %s HTTP/%s" %d',
                            ("1.2.3.4:5", "GET", f"/api/shared/{tok}/export/gpx", "1.1", 200), None)
    assert filt.filter(rec)
    assert tok not in rec.getMessage() and "/api/shared/<token>/export/gpx" in rec.getMessage()
    assert tok not in sharing.redact_tokens(f"/friends/invite/{tok}") and tok not in sharing.redact_tokens(f"/r/{tok}")
    assert "/api/saved-routes/abc" == sharing.redact_tokens("/api/saved-routes/abc")
    sharing.install_log_redaction()
    assert any(isinstance(f, sharing._RedactAccessLog) for f in logging.getLogger("uvicorn.access").filters)


# --- rate limits -----------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_rate_limits_return_429_with_retry_after(people, monkeypatch):
    monkeypatch.setitem(settings.rate_limits, "share_view", "3/600")
    monkeypatch.setitem(settings.rate_limits, "share_create", "2/600")
    async with client() as c:
        codes = [(await c.get("/api/shared/" + sharing.new_token())) for _ in range(4)]
        assert [r.status_code for r in codes] == [404, 404, 404, 429]
        assert int(codes[-1].headers["retry-after"]) >= 1
        h = as_user(people["owner"])
        rid = await save(c, people["owner"])
        first = [await c.post(f"/api/saved-routes/{rid}/share", json={"mode": "friends"}, headers=h) for _ in range(3)]
        assert [r.status_code for r in first] == [200, 200, 429]
        assert "retry-after" in first[-1].headers


# --- the route table -------------------------------------------------------------------------------

PUBLIC = {
    ("GET", "/api/shared/{token}"),
    ("GET", "/api/shared/{token}/export/gpx"),
    ("GET", "/api/shared/{token}/export/fit"),
}


def _depends_on(dependant, target) -> bool:
    return dependant.call is target or any(_depends_on(d, target) for d in dependant.dependencies)


def _flat(routes):
    for r in routes:
        inner = getattr(r, "original_router", None)  # an include_router() entry
        if inner is not None:
            yield from _flat(inner.routes)
        else:
            yield r


def test_every_non_public_sharing_endpoint_requires_sign_in():
    seen = set()
    for route in _flat(app.routes):  # through the app, so the router really is mounted
        if getattr(getattr(route, "endpoint", None), "__module__", None) != "app.sharing":
            continue
        for method in route.methods:
            key = (method, route.path)
            seen.add(key)
            if key in PUBLIC:
                assert not _depends_on(route.dependant, get_current_user), key
            else:
                assert _depends_on(route.dependant, get_current_user), f"{key} is reachable signed out"
    assert PUBLIC <= seen and len(seen) == 24
    # the existing saved-route exports are owner-only now too
    exports = [r for r in _flat(app.routes) if getattr(r, "path", "") in ("/api/export/gpx/{route_id}", "/api/export/fit/{route_id}")]
    assert len(exports) == 2 and all(_depends_on(r.dependant, get_current_user) for r in exports)
    # nothing else is publicly readable under /api/shared
    shared = {(m, r.path) for r in _flat(app.routes) if getattr(r, "path", "").startswith("/api/shared") for m in r.methods}
    assert {k for k in shared if k[0] == "GET"} <= PUBLIC


# --- deleting or moving an account ---------------------------------------------------------------------

@pytest.mark.asyncio
async def test_account_deletion_removes_everything_shared(people):
    from app.db import delete_user_account
    p = people
    async with client() as c:
        await befriend(c, p["owner"], p["friend"])
        rid = await save(c, p["owner"])
        tok = token_of((await c.post(f"/api/saved-routes/{rid}/share", json={"mode": "link"},
                                     headers=as_user(p["owner"]))).json()["path"])
        await c.post(f"/api/saved-routes/{rid}/share", json={"mode": "friends"}, headers=as_user(p["owner"]))
        rid2 = await save(c, p["owner"], name="Two")
        tok2 = token_of((await c.post(f"/api/saved-routes/{rid2}/share", json={"mode": "link"},
                                      headers=as_user(p["owner"]))).json()["path"])
        await c.post("/api/friends/invites", headers=as_user(p["owner"]))
        assert (await c.get(f"/api/shared/{tok2}")).status_code == 200
        delete_user_account(p["owner"])
        assert (await c.get(f"/api/shared/{tok2}")).status_code == 404
        assert (await c.get(f"/api/shared/{tok}")).status_code == 404
        assert (await c.get("/api/friends", headers=as_user(p["friend"]))).json()["friends"] == []
        assert (await friends_view(c, None, p["friend"])) == []
    with get_connection() as conn, conn.cursor() as cur:
        for sql in ("SELECT count(*) FROM route_shares WHERE user_id = %s",
                    "SELECT count(*) FROM friend_invites WHERE inviter_id = %s",
                    "SELECT count(*) FROM friendships WHERE user_a = %s OR user_b = %s",
                    "SELECT count(*) FROM blocks WHERE blocker = %s OR blocked = %s"):
            cur.execute(sql, (p["owner"],) * sql.count("%s"))
            assert cur.fetchone()[0] == 0, sql


@pytest.mark.asyncio
async def test_legacy_account_rekey_moves_shares(people):
    from app.account_migration import rekey_users
    p = people
    legacy = f"google_{uuid.uuid4().hex[:8]}"
    ensure_user_exists(legacy, email="legacy@test.loam")
    try:
        async with client() as c:
            rid = await save(c, legacy)
            tok = token_of((await c.post(f"/api/saved-routes/{rid}/share", json={"mode": "link"},
                                         headers=as_user(legacy))).json()["path"])
        with get_connection() as conn, conn.cursor() as cur:
            rekey_users(cur, [legacy], p["owner"], None, dry_run=False)
            conn.commit()
        async with client() as c:
            assert (await c.get(f"/api/shared/{tok}")).status_code == 200
            assert [s["route_id"] for s in (await c.get("/api/me/shares", headers=as_user(p["owner"]))).json()["shares"]] == [rid]
    finally:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM users WHERE id = %s", (legacy,))
            conn.commit()


@pytest.mark.asyncio
async def test_mixed_case_user_ids_can_befriend_each_other():
    """Firebase uids are mixed case; the pair order must not depend on the database's locale collation."""
    tag = uuid.uuid4().hex[:6]
    a, b = f"Zz{tag}A", f"aa{tag}b"  # 'Z' < 'a' in byte order, the reverse in en_US
    for uid in (a, b):
        ensure_user_exists(uid, email=f"{uid}@test.loam")
    try:
        async with client() as c:
            for inviter, joiner in ((a, b), (b, a)):
                with get_connection() as conn, conn.cursor() as cur:
                    cur.execute("DELETE FROM friendships WHERE user_a = ANY(%s) OR user_b = ANY(%s)", ([a, b], [a, b]))
                    conn.commit()
                inv = (await c.post("/api/friends/invites", headers=as_user(inviter))).json()
                r = await c.post(f"/api/friends/invites/{token_of(inv['path'])}/accept", headers=as_user(joiner))
                assert r.status_code == 200, r.text
                assert len((await c.get("/api/friends", headers=as_user(inviter))).json()["friends"]) == 1
    finally:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM users WHERE id = ANY(%s)", ([a, b],))
            conn.commit()


@pytest.mark.asyncio
async def test_data_export_includes_sharing_without_other_people_or_tokens(people):
    p = people
    async with client() as c:
        await c.put("/api/me/profile", json={"share_display_name": "Gnome"}, headers=as_user(p["owner"]))
        await befriend(c, p["owner"], p["friend"])
        rid = await save(c, p["owner"])
        share = (await c.post(f"/api/saved-routes/{rid}/share", json={"mode": "link"}, headers=as_user(p["owner"]))).json()
        await c.post("/api/friends/invites", headers=as_user(p["owner"]))
        out = await c.get("/api/privacy/export", headers=as_user(p["owner"]))
    assert out.status_code == 200
    data = out.json()["sharing"]
    assert data["share_display_name"] == "Gnome"
    assert [s["mode"] for s in data["shared_routes"]] == ["link"] and len(data["friendships"]) == 1
    assert len(data["friend_invites"]) == 2
    text = out.text
    assert p["friend"] not in text and token_of(share["path"]) not in text and "token_hash" not in text


def test_privacy_policy_and_terms_describe_sharing():
    import pathlib
    legal = pathlib.Path(__file__).resolve().parents[1] / "frontend" / "public" / "legal"
    priv = (legal / "privacy" / "index.html").read_text()
    terms = (legal / "terms" / "index.html").read_text()
    for needle in ('id="sharing"', "Your rides are never shared", "sharing name", "Anyone with the link",
                   "privacy zones", "7 days", "block", "Stopping", "Counts", "Effective October 14, 2026"):
        assert needle in priv, needle
    assert "Sharing routes" in terms and "Effective October 14, 2026" in terms
