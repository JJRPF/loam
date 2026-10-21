"""GH-41 phase 4: what the API tells the rider when a loop through midpoints is not a clean loop."""
import json

import pytest
from httpx import ASGITransport, AsyncClient

import app.main as main
from app.config import settings
from app.main import app
from app.models import RouteResponse
from app.routing import DEAD_END_NOTICE, MidpointError

START = {"lat": 43.13, "lon": -71.5}
MID = [{"lat": 43.14, "lon": -71.49}]
OUT = [[-71.5 + 0.01 * i / 20, 43.13 + 0.01 * i / 20] for i in range(21)]
LOOP = OUT + [[-71.49 - 0.01 * i / 20, 43.14] for i in range(1, 21)] + [[-71.5, 43.14 - 0.01 * i / 10] for i in range(1, 11)]


def _route(coords):
    return RouteResponse(distance_miles=1.0, duration_minutes=10.0, surface_breakdown={}, surface_strip=[],
                         coordinates=coords, bbox=[-71.51, 43.12, -71.48, 43.15])


async def _post(path, body):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        return await c.post(path, json=body)


BODY = {"start": START, "waypoints": MID, "route_mode": "loop", "target_distance_miles": 5}


@pytest.fixture(autouse=True)
def midpoints_on(monkeypatch):
    monkeypatch.setattr(settings, "enable_midpoints", True)


@pytest.mark.asyncio
async def test_route_says_so_when_the_loop_retraces_itself(monkeypatch):
    async def fake(req, user_id=None):
        return _route(OUT + OUT[::-1][1:])
    monkeypatch.setattr(main, "fetch_route", fake)
    r = await _post("/api/route", BODY)
    assert r.status_code == 200 and DEAD_END_NOTICE in r.json()["notice"]


@pytest.mark.asyncio
async def test_route_has_no_notice_for_a_clean_loop(monkeypatch):
    async def fake(req, user_id=None):
        return _route(LOOP)
    monkeypatch.setattr(main, "fetch_route", fake)
    r = await _post("/api/route", BODY)
    assert r.status_code == 200 and r.json().get("notice") is None


@pytest.mark.asyncio
async def test_options_returns_422_with_the_reason_for_an_unreachable_midpoint(monkeypatch):
    async def fake(req, count=10, user_id=None):
        raise MidpointError("Midpoint 1 is 651 m from the nearest way. Move it onto a trail or road.")
    monkeypatch.setattr(main, "plan_route_options", fake)
    r = await _post("/api/route/options", BODY)
    assert r.status_code == 422 and "Midpoint 1" in r.json()["detail"]


@pytest.mark.asyncio
async def test_stream_reports_the_same_reason_as_an_error_event(monkeypatch):
    async def fake(req, count=10, user_id=None):
        raise MidpointError("Midpoint 1 is 651 m from the nearest way. Move it onto a trail or road.")
    monkeypatch.setattr(main, "plan_route_options", fake)
    r = await _post("/api/route/options/stream", BODY)
    assert "event: error" in r.text and "Midpoint 1 is 651 m" in r.text
