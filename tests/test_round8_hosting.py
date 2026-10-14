"""Round 8 (GH-38) phase 8: hosting on loam.thepfisters.com (CORS, old-origin redirect, kill-switch SW, configs)."""
import json
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import settings
from app.main import app

ROOT = Path(__file__).resolve().parent.parent
FUNNEL = "core-node.tailcd5892.ts.net"
NEW = "https://loam.thepfisters.com"


def client(host):
    return AsyncClient(transport=ASGITransport(app=app), base_url=f"http://{host}")


@pytest.fixture
def public_origin(monkeypatch):
    monkeypatch.setattr(settings, "public_app_origin", NEW)


@pytest.mark.asyncio
async def test_funnel_navigation_redirects_with_path_and_query(public_origin):
    async with client(FUNNEL) as c:
        r = await c.get("/legal/privacy/?x=1", follow_redirects=False)
    assert r.status_code == 301
    assert r.headers["location"] == f"{NEW}/legal/privacy/?x=1"


@pytest.mark.asyncio
async def test_api_health_and_lan_are_not_redirected(public_origin):
    async with client(FUNNEL) as c:
        assert (await c.get("/health", follow_redirects=False)).status_code == 200
        assert (await c.get("/api/config", follow_redirects=False)).status_code == 200
        # non-GET navigations are never redirected
        assert (await c.post("/nope", follow_redirects=False)).status_code != 301
    async with client("core-node.local:8085") as c:
        assert (await c.get("/api/config", follow_redirects=False)).status_code == 200
        assert (await c.get("/legal/", follow_redirects=False)).status_code != 301


@pytest.mark.asyncio
async def test_unset_origin_never_redirects(monkeypatch):
    monkeypatch.setattr(settings, "public_app_origin", "")
    async with client(FUNNEL) as c:
        assert (await c.get("/legal/", follow_redirects=False)).status_code != 301


@pytest.mark.asyncio
async def test_funnel_sw_is_the_kill_switch(public_origin):
    async with client(FUNNEL) as c:
        r = await c.get("/sw.js", follow_redirects=False)
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-store"
    assert "javascript" in r.headers["content-type"]
    assert "registration.unregister()" in r.text and json.dumps(NEW + "/") in r.text


@pytest.mark.asyncio
async def test_cors_allows_the_hosting_origin_and_authorization():
    assert NEW in settings.cors_origins and "https://" + FUNNEL in settings.cors_origins
    async with client("api.test") as c:
        r = await c.options("/api/route", headers={
            "Origin": NEW, "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type"})
        assert r.status_code == 200
        assert r.headers["access-control-allow-origin"] == NEW
        assert "authorization" in r.headers["access-control-allow-headers"].lower()
        assert "access-control-allow-credentials" not in r.headers
        r = await c.get("/api/config", headers={"Origin": "https://evil.example"})
        assert "access-control-allow-origin" not in r.headers


def test_firebase_json_is_hosting_only():
    cfg = json.loads((ROOT / "firebase.json").read_text())
    assert set(cfg) == {"hosting"}
    h = cfg["hosting"]
    assert h["site"] == "thepfisters" and h["public"] == "frontend/dist"
    assert {"source": "**", "destination": "/index.html"} in h["rewrites"]
    csp = next(x["value"] for b in h["headers"] for x in b["headers"] if x["key"] == "Content-Security-Policy")
    for needle in ("worker-src 'self' blob:", "img-src 'self' data: blob:", "frame-ancestors 'none'"):
        assert needle in csp
    assert json.loads((ROOT / ".firebaserc").read_text())["projects"]["default"] == "thepfisters"


def test_deploy_web_script_is_hosting_only():
    s = (ROOT / "scripts" / "deploy-web.sh").read_text()
    assert "deploy --only hosting --project thepfisters" in s
    for bad in ("firestore", "functions", "storage"):
        assert f"--only {bad}" not in s and f",{bad}" not in s


def test_service_worker_never_answers_firebase_reserved_urls():
    # the sign-in popup opens /__/auth/handler; a service worker serving index.html there shows the app, not Google
    cfg = (ROOT / "frontend" / "vite.config.ts").read_text()
    assert r"/^\/__\//" in cfg
