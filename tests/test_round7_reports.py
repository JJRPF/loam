"""Round 7 (GH-34) phase 7: 'Report bad route' becomes a GitHub issue (GitHub is mocked)."""
import uuid

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from app import reports
from app.config import settings
from app.db import get_connection
from app.main import app
from tests.conftest import as_user

START = (-71.5400, 43.1000)  # test fixture line, due east: 1e-4 deg lon is about 8 m here


def _line(n=400):
    return [[round(START[0] + i * 1e-4, 6), START[1]] for i in range(n)]  # about 3.2 km


def _body(comment="This loop cuts through a private yard near @someone, fix it please"):
    coords = _line()
    route = {"id": "opt-1", "name": "Test Loop @mention", "sport": "mtb_hardtail", "distance_miles": 2.0,
             "duration_minutes": 30, "surface_breakdown": {"singletrack": 100.0}, "surface_strip": [],
             "coordinates": coords, "bbox": [coords[0][0], START[1], coords[-1][0], START[1]],
             "route_type": "loop", "match_score": 88, "source": "graph_loop"}
    return {"comment": comment,
            "request": {"start": {"lat": START[1], "lon": START[0]}, "end": {"lat": 43.2, "lon": -71.4},
                        "waypoints": [{"lat": 43.11, "lon": -71.52}], "profile": "mtb_hardtail",
                        "route_mode": "loop", "target_distance_miles": 2.0},
            "route": route, "options": [{"id": "opt-1", "name": "Test Loop", "distance_miles": 2.0,
                                         "route_type": "loop", "match_score": 88}]}


@pytest.fixture
def captured(monkeypatch):
    """Mocks the GitHub POST; records the issue title and body. Cleans test reports afterwards."""
    sent = []
    monkeypatch.setattr(settings, "github_feedback_token", "test-token-not-real")

    def fake_post(client, title, body):
        sent.append({"title": title, "body": body})
        return httpx.Response(201, json={"number": 4242, "html_url": "https://github.com/JJRPF/loam/issues/4242"})

    monkeypatch.setattr(reports, "_post_issue", fake_post)
    yield sent
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM route_reports WHERE user_id LIKE 'r7rep_%'")
        conn.commit()


def _uid():
    return f"r7rep_{uuid.uuid4().hex[:8]}"


@pytest.mark.asyncio
async def test_anonymous_is_401_and_short_comment_is_422(real_auth):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        assert (await client.post("/api/reports/bad-route", json=_body())).status_code == 401
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        assert (await client.get("/api/admin/reports/" + str(uuid.uuid4()))).status_code == 401


@pytest.mark.asyncio
async def test_report_files_an_issue_without_endpoints_or_mentions(captured):
    uid = _uid()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        short = _body("too short")
        assert (await client.post("/api/reports/bad-route", json=short, headers=as_user(uid))).status_code == 422
        res = await client.post("/api/reports/bad-route", json=_body(), headers=as_user(uid))
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["status"] == "filed" and data["issue_url"].endswith("/4242")

    issue = captured[0]
    assert issue["title"].startswith("In-app feedback: bad route — Test Loop @​mention (2.0 mi loop, mtb_hardtail)")
    body = issue["body"]
    assert "@someone" not in body and "@​someone" in body
    assert uid not in body and "private yard" in body

    # the line in the issue starts 0.5 mi (805 m, about 100 points here) in and stops 0.5 mi before the end
    coords = _line()
    line = reports.trimmed_line(coords)
    assert line and line[0][0] > coords[95][0] and line[-1][0] < coords[-95][0]
    assert f"[{round(coords[0][0], 5)},{START[1]}]" not in body
    for p in coords[:90] + coords[-90:]:
        assert f"[{round(p[0], 5)},{round(p[1], 5)}]" not in body
    assert f"[{round(coords[200][0], 5)},{START[1]}]" in body  # the middle is there
    inputs = body.split("## Inputs")[1].split("## Route")[0]
    assert "end point set: yes; midpoints: 1" in inputs
    for needle in ("43.2", "-71.4", "43.11", "-71.52", str(START[1])):
        assert needle not in inputs

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT status, github_issue_number, request_json->'start'->>'lat' FROM route_reports WHERE id = %s",
                    (data["id"],))
        assert cur.fetchone() == ("filed", 4242, str(START[1]))  # the server keeps the full snapshot


def test_short_route_has_no_line_in_the_issue():
    assert reports.trimmed_line([[START[0] + i * 1e-4, START[1]] for i in range(150)]) == []  # about 1.2 km


def test_issue_body_stays_under_the_size_limit():
    big = [[START[0] + i * 1e-5, START[1] + (i % 7) * 1e-5] for i in range(60000)]
    body = reports.build_issue_body("rid", "u", "a long enough comment", {"profile": "mtb"},
                                    {"coordinates": big, "distance_miles": 9}, [], "abc123")
    assert len(body) <= reports.MAX_ISSUE_CHARS


@pytest.mark.asyncio
async def test_github_failure_keeps_the_report_pending_and_the_worker_files_it(captured, monkeypatch):
    uid = _uid()
    monkeypatch.setattr(reports, "_post_issue", lambda c, t, b: httpx.Response(503, text="down"))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post("/api/reports/bad-route", json=_body(), headers=as_user(uid))
    data = res.json()
    assert res.status_code == 200 and data["status"] == "pending" and data["message"] == "Saved. It will be filed shortly."

    def ok(client, title, body):
        captured.append({"title": title, "body": body})
        return httpx.Response(201, json={"number": 7, "html_url": "https://github.com/JJRPF/loam/issues/7"})

    monkeypatch.setattr(reports, "_post_issue", ok)
    assert reports.retry_pending(limit=100)["filed"] >= 1
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT status, github_issue_number FROM route_reports WHERE id = %s", (data["id"],))
        assert cur.fetchone() == ("filed", 7)


@pytest.mark.asyncio
async def test_five_a_day_and_admin_reads_the_snapshot(captured):
    uid = _uid()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        ids = []
        for _ in range(5):
            r = await client.post("/api/reports/bad-route", json=_body(), headers=as_user(uid))
            assert r.status_code == 200
            ids.append(r.json()["id"])
        assert (await client.post("/api/reports/bad-route", json=_body(), headers=as_user(uid))).status_code == 429
        assert (await client.post("/api/reports/bad-route", json=_body(), headers=as_user(_uid()))).status_code == 200
        assert (await client.get(f"/api/admin/reports/{ids[0]}", headers=as_user(uid))).status_code == 403
        full = await client.get(f"/api/admin/reports/{ids[0]}", headers=as_user("r7rep_admin", admin=True))
        assert full.status_code == 200 and full.json()["request_json"]["start"]["lat"] == START[1]
        assert (await client.get("/api/admin/reports/not-a-uuid", headers=as_user("r7rep_admin", admin=True))).status_code == 404


def _save(uid, name="Saved Loop"):
    from app.db import save_route_to_db
    coords = _line()
    return save_route_to_db(uid, {"name": name, "sport": "mtb_hardtail", "distance_miles": 2.0,
                                  "elevation_gain_ft": 120, "elevation_loss_ft": 118, "coordinates": coords,
                                  "surface_breakdown": {"singletrack": 100.0}, "surface_strip": [],
                                  "waypoints": [{"lat": 43.11, "lon": -71.52}]})


@pytest.fixture
def saved_cleanup():
    yield
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM saved_routes WHERE user_id LIKE 'r7rep_%'")
        conn.commit()


@pytest.mark.asyncio
async def test_saved_route_report_needs_no_search_and_ignores_client_geometry(captured, saved_cleanup):
    uid = _uid()
    sid = _save(uid)
    assert sid
    body = {"comment": "This saved route crosses a closed gate, please check", "source": "saved",
            "saved_route_id": sid,
            "route": {**_body()["route"], "name": "Client Fake", "coordinates": [[0.0, 0.0], [0.1, 0.1]]}}
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post("/api/reports/bad-route", json=body, headers=as_user(uid))
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "filed"
    issue = captured[0]
    assert "Saved Loop" in issue["title"] and "Client Fake" not in issue["title"]
    text = issue["body"]
    assert "Reported from: saved route (search settings unavailable)" in text
    inputs = text.split("## Inputs")[1].split("## Route")[0]
    for needle in ("43.11", "-71.52", str(START[1])):
        assert needle not in inputs
    coords = _line()
    for p in coords[:90] + coords[-90:]:
        assert f"[{round(p[0], 5)},{round(p[1], 5)}]" not in text
    assert f"[{round(coords[200][0], 5)},{START[1]}]" in text
    assert "[0.1,0.1]" not in text
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT route_json->>'name', request_json->>'search_unavailable' FROM route_reports WHERE id=%s",
                    (res.json()["id"],))
        assert cur.fetchone() == ("Saved Loop", "true")


@pytest.mark.asyncio
async def test_saved_route_report_404_for_other_users_and_missing_ids(captured, saved_cleanup):
    owner, other = _uid(), _uid()
    sid = _save(owner)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        for rid in (sid, str(uuid.uuid4()), "not-a-uuid"):
            res = await client.post("/api/reports/bad-route", headers=as_user(other), json={
                "comment": "This saved route is wrong somehow", "source": "saved", "saved_route_id": rid})
            assert res.status_code == 404, (rid, res.text)
        res = await client.post("/api/reports/bad-route", headers=as_user(other), json={
            "comment": "This saved route is wrong somehow", "source": "saved"})
        assert res.status_code == 422
    assert captured == []


@pytest.mark.asyncio
async def test_shared_route_report_without_request_is_filed(captured):
    body = _body()
    del body["request"]
    body["source"] = "shared"
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post("/api/reports/bad-route", json=body, headers=as_user(_uid()))
    assert res.status_code == 200, res.text
    assert "Reported from: shared link (search settings unavailable)" in captured[0]["body"]
