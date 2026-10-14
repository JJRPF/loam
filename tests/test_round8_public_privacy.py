"""Round 8 (GH-38) phase 6: what the privacy policy says about public data and deletion is true."""
import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.db import delete_user_account, ensure_user_exists, get_connection
from app.main import app
from tests.conftest import as_user


def _edge():
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT osm_id FROM edges WHERE highway = 'path' AND geom IS NOT NULL ORDER BY osm_id LIMIT 1")
        row = cur.fetchone()
    if not row:
        pytest.skip("OSM graph not imported in the dev database")
    return row[0]


async def _client():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_public_endpoints_never_show_who_contributed():
    uid = f"r8_pub_{uuid.uuid4().hex[:8]}"
    edge = _edge()
    h = as_user(uid)
    try:
        async with await _client() as c:
            f = await c.post("/api/flags", json={"edge_osm_id": edge, "flag_type": "blocked", "details": "tree down"}, headers=h)
            assert f.status_code == 200, f.text
            ck = await c.post(f"/api/trails/{edge}/checkin", json={"status": "open"}, headers=h)
            assert ck.status_code == 200, ck.text
            sub = await c.post("/api/submissions", headers=h, json={
                "name": "r8 test trail", "sport": "mtb", "difficulty": "blue",
                "coordinates": [[-71.0, 43.0], [-71.001, 43.001]]})
            # public reads, signed out
            flags = (await c.get("/api/flags", params={"edge_osm_id": edge})).json()
            checkins = (await c.get(f"/api/trails/{edge}/checkins")).json()
            status = (await c.get(f"/api/trails/{edge}/status")).json()
            subs = (await c.get("/api/submissions")).json()
        body = str(flags) + str(checkins) + str(status) + str(subs)
        assert uid not in body
        assert any(x["edge_osm_id"] == edge for x in flags) and checkins
        if sub.status_code == 200:
            async with await _client() as c:
                assert uid not in (await c.get(f"/api/submissions/{sub.json()['id']}")).text
    finally:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM trail_submissions WHERE user_id = %s", (uid,))
            conn.commit()
        delete_user_account(uid)


@pytest.mark.asyncio
async def test_account_deletion_removes_reports_and_unlinks_submissions():
    uid = f"r8_del_{uuid.uuid4().hex[:8]}"
    ensure_user_exists(uid)
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO trail_submissions (user_id, name, sport, status) VALUES (%s, 'r8 pending', 'mtb', 'pending')", (uid,))
        cur.execute("INSERT INTO trail_submissions (user_id, name, sport, status) VALUES (%s, 'r8 verified', 'mtb', 'verified') RETURNING id", (uid,))
        verified_id = cur.fetchone()[0]
        cur.execute("INSERT INTO route_reports (id, user_id, comment, request_json, route_json) "
                    "VALUES (gen_random_uuid(), %s, 'bad', '{}', '{}')", (uid,))
        conn.commit()
    try:
        async with await _client() as c:
            export = (await c.get("/api/privacy/export", headers=as_user(uid))).json()
            assert len(export["route_reports"]) == 1 and len(export["trail_submissions"]) == 2
            r = await c.delete("/api/privacy/account", headers=as_user(uid))
            assert r.status_code == 200, r.text
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM route_reports WHERE user_id = %s", (uid,))
            assert cur.fetchone()[0] == 0
            cur.execute("SELECT count(*) FROM users WHERE id = %s", (uid,))
            assert cur.fetchone()[0] == 0
            cur.execute("SELECT count(*) FROM trail_submissions WHERE name = 'r8 pending'")
            assert cur.fetchone()[0] == 0
            cur.execute("SELECT user_id FROM trail_submissions WHERE id = %s", (verified_id,))
            assert cur.fetchone() == (None,)  # the verified trail stays, without its author
    finally:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM trail_submissions WHERE name IN ('r8 pending', 'r8 verified') AND (user_id IS NULL OR user_id = %s)", (uid,))
            conn.commit()
