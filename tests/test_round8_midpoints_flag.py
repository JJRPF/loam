"""Round 8 (GH-38) phase 2: midpoints behind ENABLE_MIDPOINTS (off in production)."""
import json

import pytest
from httpx import ASGITransport, AsyncClient

import app.main as main
from app.config import settings
from app.main import MIDPOINTS_OFF_NOTICE, app
from app.models import RouteResponse
from app.routing import OptionsResult

START = {"lat": 43.1, "lon": -71.5}
MID = [{"lat": 43.11, "lon": -71.51}]


def _route():
    return RouteResponse(distance_miles=1.0, duration_minutes=10.0, surface_breakdown={}, surface_strip=[],
                         coordinates=[[-71.5, 43.1], [-71.51, 43.11]], bbox=[-71.51, 43.1, -71.5, 43.11])


@pytest.fixture
def stubbed(monkeypatch):
    seen = []

    async def fake_options(req, count=10, user_id=None):
        seen.append(list(req.waypoints or []))
        return OptionsResult([_route()], None, None, 1, {})

    async def fake_route(req, user_id=None):
        seen.append(list(req.waypoints or []))
        return _route()

    monkeypatch.setattr(main, "plan_route_options", fake_options)
    monkeypatch.setattr(main, "fetch_route", fake_route)
    return seen


async def _post(path, body):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        return await c.post(path, json=body)


def test_flag_defaults_to_off():
    from app.config import Settings
    import os
    assert Settings().enable_midpoints is False or "ENABLE_MIDPOINTS" in os.environ


@pytest.mark.asyncio
async def test_flag_off_ignores_waypoints_with_a_notice_on_all_endpoints(monkeypatch, stubbed):
    monkeypatch.setattr(settings, "enable_midpoints", False)
    body = {"start": START, "waypoints": MID, "route_mode": "loop", "target_distance_miles": 5}

    r = await _post("/api/route", body)
    assert r.status_code == 200 and r.json()["notice"] == MIDPOINTS_OFF_NOTICE

    r = await _post("/api/route/options", body)
    assert r.status_code == 200 and MIDPOINTS_OFF_NOTICE in r.json()["notice"]

    r = await _post("/api/route/options/stream", body)
    assert r.status_code == 200
    complete = [line for line in r.text.splitlines() if line.startswith("data: ") and '"status"' in line][-1]
    assert MIDPOINTS_OFF_NOTICE in json.loads(complete[6:])["notice"]

    assert stubbed == [[], [], []]  # the route builder never saw the waypoints


@pytest.mark.asyncio
async def test_flag_off_without_waypoints_has_no_notice(monkeypatch, stubbed):
    monkeypatch.setattr(settings, "enable_midpoints", False)
    r = await _post("/api/route/options", {"start": START, "route_mode": "loop", "target_distance_miles": 5})
    assert r.status_code == 200 and r.json()["notice"] is None


@pytest.mark.asyncio
async def test_get_stream_has_no_waypoints_to_ignore(monkeypatch, stubbed):
    """The GET stream (EventSource) takes no waypoints at all, so the flag has nothing to drop."""
    monkeypatch.setattr(settings, "enable_midpoints", False)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/route/options/stream", params={"lat": 43.1, "lon": -71.5, "target_miles": 5})
    assert r.status_code == 200 and stubbed == [[]]


@pytest.mark.asyncio
async def test_flag_on_passes_waypoints_through(monkeypatch, stubbed):
    monkeypatch.setattr(settings, "enable_midpoints", True)
    body = {"start": START, "waypoints": MID, "route_mode": "loop", "target_distance_miles": 5}
    r = await _post("/api/route/options", body)
    assert r.status_code == 200 and r.json()["notice"] is None
    assert len(stubbed[0]) == 1 and stubbed[0][0].lat == 43.11


@pytest.mark.asyncio
async def test_public_config(monkeypatch):
    monkeypatch.setattr(settings, "enable_midpoints", False)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        data = (await c.get("/api/config")).json()
    assert data["midpoints_enabled"] is False
    assert data["min_unique_riders"] == settings.heat_min_unique_riders
    assert data["seed_heat_public"] == settings.seed_heat_public
    assert set(data["connectors"]) == {"strava", "garmin", "trailforks", "cubetrek"}
    assert all(isinstance(v, bool) for v in data["connectors"].values())
    assert data["source_url"] == "https://github.com/JJRPF/loam"
    meta = (await AsyncClient(transport=ASGITransport(app=app), base_url="http://test").get("/api/heat/meta")).json()
    assert meta["min_unique_riders"] == data["min_unique_riders"]
