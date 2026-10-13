"""Round 8 (GH-38) phase 7: rate limits, the route-generation cap, client IP handling, outbound etiquette,
and admin route protection."""
import asyncio
import time

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

import app.main as main
from app import ratelimit
from app.auth import get_admin_user
from app.config import settings
from app.main import app
from app.models import RouteResponse
from app.routing import OptionsResult
from tests.conftest import as_user


def _route():
    return RouteResponse(distance_miles=1.0, duration_minutes=10.0, surface_breakdown={}, surface_strip=[],
                         coordinates=[[-71.5, 43.1], [-71.51, 43.11]], bbox=[-71.51, 43.1, -71.5, 43.11])


@pytest.fixture
def fast_routes(monkeypatch):
    async def fake_options(req, count=10, user_id=None):
        return OptionsResult([_route()], None, None, 1, {})

    async def fake_route(req, user_id=None):
        return _route()

    monkeypatch.setattr(main, "plan_route_options", fake_options)
    monkeypatch.setattr(main, "fetch_route", fake_route)


def _client(**kw):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test", **kw)


BODY = {"start": {"lat": 43.1, "lon": -71.5}, "route_mode": "loop", "target_distance_miles": 5}


def test_token_bucket_math():
    lim = ratelimit.RateLimiter()
    assert all(lim.check("k", 3, 60) is None for _ in range(3))
    wait = lim.check("k", 3, 60)
    assert wait is not None and 1 <= wait <= 20  # one token per 20 s
    assert lim.check("other", 3, 60) is None  # keys are independent


@pytest.mark.asyncio
async def test_route_limit_is_per_key_with_retry_after_and_friendly_detail(monkeypatch, fast_routes):
    monkeypatch.setitem(settings.rate_limits, "route", "3/600")
    async with _client() as c:
        for _ in range(3):
            assert (await c.post("/api/route/options", json=BODY)).status_code == 200
        r = await c.post("/api/route/options", json=BODY)
        assert r.status_code == 429
        assert int(r.headers["retry-after"]) > 0
        assert "building routes faster than Loam allows" in r.json()["detail"] and "minutes" in r.json()["detail"]
        # another signed-in user has their own bucket; the same user hits the same one
        assert (await c.post("/api/route/options", json=BODY, headers=as_user("r8_rl_a"))).status_code == 200
        for _ in range(2):
            assert (await c.post("/api/route/options", json=BODY, headers=as_user("r8_rl_a"))).status_code == 200
        assert (await c.post("/api/route/options", json=BODY, headers=as_user("r8_rl_a"))).status_code == 429
        assert (await c.post("/api/route/options", json=BODY, headers=as_user("r8_rl_b"))).status_code == 200
        # every route endpoint shares the budget (single route and the stream too)
        assert (await c.post("/api/route", json=BODY)).status_code == 429
        assert (await c.post("/api/route/options/stream", json=BODY)).status_code == 429
        assert (await c.get("/api/route/options/stream", params={"lat": 43.1, "lon": -71.5})).status_code == 429


@pytest.mark.asyncio
async def test_geocode_limit(monkeypatch):
    monkeypatch.setitem(settings.rate_limits, "geocode", "2/60")

    async def no_photon(q):
        return []
    monkeypatch.setattr(main, "photon_search", no_photon)
    async with _client() as c:
        assert (await c.get("/api/geocode", params={"q": "bear brook"})).status_code == 200
        assert (await c.get("/api/geocode", params={"q": "bear brook"})).status_code == 200
        r = await c.get("/api/geocode", params={"q": "bear brook"})
        assert r.status_code == 429 and "searching faster" in r.json()["detail"]


@pytest.mark.asyncio
async def test_upload_and_flag_limits(monkeypatch):
    monkeypatch.setitem(settings.rate_limits, "upload", "1/3600")
    monkeypatch.setitem(settings.rate_limits, "flag", "1/3600")
    h = as_user("r8_rl_up")
    async with _client() as c:
        first = await c.post("/api/activities/upload", headers=h, files={"file": ("x.gpx", b"<gpx/>")})
        assert first.status_code != 429  # parsed (and rejected as an empty track), but within the limit
        assert (await c.post("/api/activities/upload", headers=h, files={"file": ("x.gpx", b"<gpx/>")})).status_code == 429
        body = {"edge_osm_id": 1, "flag_type": "blocked"}
        assert (await c.post("/api/flags", json=body, headers=h)).status_code != 429
        assert (await c.post("/api/flags", json=body, headers=h)).status_code == 429
        assert (await c.post("/api/trails/1/checkin", json={"status": "open"}, headers=h)).status_code == 429  # shared flag budget


@pytest.mark.asyncio
async def test_reports_have_a_global_daily_cap(monkeypatch):
    from app import reports
    monkeypatch.setattr(reports, "count_recent", lambda uid: 0)
    monkeypatch.setattr(reports, "count_recent_global", lambda: settings.report_daily_limit_global)
    payload = {"comment": "this route is wrong", "route": _route().model_dump(mode="json"),
               "request": {"start": {"lat": 43.1, "lon": -71.5}}, "options": []}
    async with _client() as c:
        r = await c.post("/api/reports/bad-route", json=payload, headers=as_user("r8_rl_rep"))
    assert r.status_code == 429 and "daily limit" in r.json()["detail"] and r.headers["retry-after"]


@pytest.mark.asyncio
async def test_route_generation_cap_waits_then_429(monkeypatch):
    monkeypatch.setattr(settings, "route_concurrency", 2)
    monkeypatch.setattr(settings, "route_wait_s", 0.3)
    ratelimit._slots = None
    running, peak = 0, 0

    async def slow_options(req, count=10, user_id=None):
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0.6)
        running -= 1
        return OptionsResult([_route()], None, None, 1, {})

    monkeypatch.setattr(main, "plan_route_options", slow_options)
    monkeypatch.setitem(settings.rate_limits, "route", "100/60")
    async with _client() as c:
        results = await asyncio.gather(*[c.post("/api/route/options", json=BODY) for _ in range(3)])
    codes = sorted(r.status_code for r in results)
    assert codes == [200, 200, 429] and peak == 2
    assert "Retry-After" in results[codes.index(429)].headers or any("retry-after" in r.headers for r in results)
    # and the stream reports it as an error event with the status
    ratelimit._slots = None
    async with _client() as c:
        a = asyncio.create_task(c.post("/api/route/options", json=BODY))
        b = asyncio.create_task(c.post("/api/route/options", json=BODY))
        await asyncio.sleep(0.1)
        s = await c.post("/api/route/options/stream", json=BODY)
        await asyncio.gather(a, b)
    assert "event: error" in s.text and '"status": 429' in s.text


def _request(peer, forwarded=None):
    from starlette.requests import Request
    headers = [(b"x-forwarded-for", forwarded.encode())] if forwarded else []
    return Request({"type": "http", "headers": headers, "client": (peer, 1234), "method": "GET", "path": "/"})


def test_client_ip_trusts_forwarded_for_only_from_loopback():
    assert ratelimit.client_ip(_request("127.0.0.1", "203.0.113.9")) == "203.0.113.9"
    assert ratelimit.client_ip(_request("::1", "198.51.100.1, 203.0.113.9")) == "203.0.113.9"  # last = appended by the local proxy
    assert ratelimit.client_ip(_request("192.168.1.20", "203.0.113.9")) == "192.168.1.20"  # LAN peers can't pick their key
    assert ratelimit.client_ip(_request("127.0.0.1")) == "127.0.0.1"


def test_one_user_agent_everywhere():
    from app import otm, reports, weather
    ua = settings.user_agent
    assert ua == "Loam/1.0 (+https://loam.thepfisters.com; jjrpfister@gmail.com)"
    assert weather.HEADERS["User-Agent"] == ua
    assert reports._headers()["User-Agent"] == ua
    import inspect
    assert "settings.user_agent" in inspect.getsource(otm._overpass_elements)
    assert "settings.user_agent" in inspect.getsource(main._photon_fetch)


@pytest.mark.asyncio
async def test_photon_is_cached_for_an_hour(monkeypatch):
    calls = []

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, params=None):
            calls.append(params["q"])
            return httpx.Response(200, json={"features": [{"properties": {"name": "Bow"}, "geometry": {"coordinates": [-71.5, 43.1]}}]})

    monkeypatch.setattr(main.httpx, "AsyncClient", FakeClient)
    main._photon_cache.clear()
    a = await main.photon_search("Bow  NH")
    b = await main.photon_search("bow nh")
    assert a == b and len(calls) == 1
    key = "bow nh"
    main._photon_cache[key] = (time.time() - main.PHOTON_TTL_S - 1, a)
    await main.photon_search("bow nh")
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_overpass_tiles_are_cached_for_a_day(monkeypatch):
    from app import otm
    calls = []

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, data=None, headers=None):
            calls.append(headers["User-Agent"])
            return httpx.Response(200, json={"elements": []})

    monkeypatch.setattr(otm.httpx, "AsyncClient", FakeClient)
    otm._overpass_cache.clear()
    env = otm._tile_envelope(10.001, 10.002, 10.012, 10.013)  # nowhere near any local import
    assert env == otm._tile_envelope(10.04, 10.03, 10.049, 10.041)  # same 0.05 degree tile
    await otm._overpass_elements(env)
    await otm._overpass_elements(env)
    assert calls == [settings.user_agent]
    t, ttl, els = otm._overpass_cache[env]
    assert ttl == otm.OVERPASS_TTL_S >= 24 * 3600


@pytest.mark.asyncio
async def test_nws_cache_follows_cache_control(monkeypatch):
    from app import weather
    resp = httpx.Response(200, headers={"cache-control": "public, max-age=5400"})
    assert weather._ttl(resp) == weather.MAX_TTL_S
    assert weather._ttl(httpx.Response(200, headers={"cache-control": "max-age=60"})) == weather.TTL_S
    assert weather._ttl(httpx.Response(200)) == weather.TTL_S


def _walk(dependant):
    for d in dependant.dependencies:
        yield d.call
        yield from _walk(d)


def test_every_dev_and_admin_route_requires_the_admin_dependency():
    checked = 0
    for route in app.routes:
        path = getattr(route, "path", "")
        if path.startswith("/api/dev") or path.startswith("/api/admin"):
            checked += 1
            assert get_admin_user in set(_walk(route.dependant)), f"{route.methods} {path} has no get_admin_user"
    assert checked >= 5
