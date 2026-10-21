"""GH-45: deploy info, /api/version, the staging startup guards, noindex."""
import json

import pytest
from httpx import ASGITransport, AsyncClient

from app import deploy_info
from app.config import Settings, check_production_config, check_staging_config, staging_problems
from app.config import settings
from app.main import app
from tests.conftest import as_user

GOOD = dict(
    loam_env="staging",
    database_url="postgresql://loam_staging:pw@localhost:5432/loam_staging",
    github_feedback_token="",
    connector_secret_key="x" * 40,
    cors_origins=["https://loamstaging.thepfisters.com", "http://localhost:5173"],
    public_app_origin="",
    enable_strava_connector=False,
    enable_trailforks_connector=False,
)


def make(**kw):
    return Settings(**{**GOOD, **kw})


def test_a_safe_staging_config_starts():
    assert staging_problems(make()) == []
    check_staging_config(make())
    check_production_config(make())


def test_other_environments_are_not_checked():
    assert staging_problems(make(loam_env="development", database_url="postgresql://x@h/loam")) == []


@pytest.mark.parametrize("url", [
    "postgresql://loam:loam_dev_pw@localhost:5432/loam",
    "postgresql://loam:pw@core-node:5432/loam?sslmode=disable",
])
def test_staging_refuses_the_production_database(url):
    with pytest.raises(RuntimeError, match="production database"):
        check_production_config(make(database_url=url))


def test_staging_refuses_the_real_github_token():
    with pytest.raises(RuntimeError, match="GITHUB_FEEDBACK_TOKEN"):
        check_staging_config(make(github_feedback_token="github_pat_x"))


@pytest.mark.parametrize("flag", ["enable_strava_connector", "enable_trailforks_connector"])
def test_staging_refuses_connectors_with_live_credentials(flag):
    with pytest.raises(RuntimeError, match="connector"):
        check_staging_config(make(**{flag: True}))


@pytest.mark.parametrize("origins", [
    ["https://loam.thepfisters.com"],
    ["https://loamstaging.thepfisters.com", "https://core-node.tailcd5892.ts.net/"],
])
def test_staging_refuses_a_production_cors_origin(origins):
    with pytest.raises(RuntimeError, match="CORS_ORIGINS"):
        check_staging_config(make(cors_origins=origins))


def test_staging_refuses_the_funnel_redirect_to_production():
    with pytest.raises(RuntimeError, match="PUBLIC_APP_ORIGIN"):
        check_staging_config(make(public_app_origin="https://loam.thepfisters.com"))


def test_staging_refuses_the_development_secret_key():
    with pytest.raises(RuntimeError, match="CONNECTOR_SECRET_KEY"):
        check_staging_config(make(connector_secret_key="loam_dev_secret_key_32bytes_min_len!"))


def test_staging_refuses_the_auth_emulator():
    with pytest.raises(RuntimeError, match="APP_ENV=staging"):
        check_production_config(make(auth_emulator_host="127.0.0.1:9099", host="127.0.0.1"))


def test_every_problem_is_reported_at_once():
    p = staging_problems(make(database_url="postgresql://a@h/loam", github_feedback_token="t", cors_origins=["https://loam.thepfisters.com"]))
    assert len(p) == 3


# --- deploy info ---------------------------------------------------------------------------------------------

def test_deploy_info_reads_the_file_and_adds_env(tmp_path, monkeypatch):
    f = tmp_path / "deploy-info.json"
    f.write_text(json.dumps({"sha": "a" * 40, "pr": 7, "pr_title": "T", "commits_ahead": 3}))
    monkeypatch.setenv("DEPLOY_INFO_FILE", str(f))
    info = deploy_info.get_deploy_info()
    assert info["env"] == "test" and info["short_sha"] == "aaaaaaa" and info["pr"] == 7 and info["commits_ahead"] == 3


def test_deploy_info_is_reread_when_the_file_changes(tmp_path, monkeypatch):
    f = tmp_path / "deploy-info.json"
    monkeypatch.setenv("DEPLOY_INFO_FILE", str(f))
    f.write_text(json.dumps({"sha": "a" * 40}))
    assert deploy_info.get_deploy_info()["short_sha"] == "aaaaaaa"
    f.write_text(json.dumps({"sha": "b" * 40, "x": "longer so the size and mtime change"}))
    import os
    os.utime(f, ns=(1, 2_000_000_000_000_000_000))
    assert deploy_info.get_deploy_info()["short_sha"] == "bbbbbbb"


@pytest.mark.parametrize("content", [None, "not json", "[1, 2]"])
def test_deploy_info_falls_back_without_a_usable_file(tmp_path, monkeypatch, content):
    f = tmp_path / "deploy-info.json"
    if content is not None:
        f.write_text(content)
    monkeypatch.setenv("DEPLOY_INFO_FILE", str(f))
    info = deploy_info.get_deploy_info()
    assert info["env"] == "test" and "pr" not in info


def client():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_version_needs_a_signed_in_user():
    async with client() as c:
        assert (await c.get("/api/version")).status_code == 401
        r = await c.get("/api/version", headers=as_user("u1"))
    assert r.status_code == 200 and r.json()["env"] == "test"


@pytest.mark.asyncio
async def test_version_rejects_a_bad_token(real_auth):
    async with client() as c:
        r = await c.get("/api/version", headers={"Authorization": "Bearer nonsense"})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_staging_sends_noindex_and_robots(monkeypatch):
    async with client() as c:
        r = await c.get("/api/config")
        assert "x-robots-tag" not in r.headers
        assert (await c.get("/robots.txt")).status_code == 404
        monkeypatch.setattr(settings, "loam_env", "staging")
        r = await c.get("/api/config")
        assert r.headers["x-robots-tag"] == "noindex, nofollow"
        robots = await c.get("/robots.txt")
    assert robots.status_code == 200 and "Disallow: /" in robots.text


# --- Firebase Hosting: prod and staging sites ----------------------------------------------------------------
from pathlib import Path  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def _hosting():
    cfg = json.loads((ROOT / "firebase.json").read_text())["hosting"]
    return {h["target"]: h for h in cfg}


def _header(h, key):
    return next(x["value"] for b in h["headers"] for x in b["headers"] if x["key"] == key)


def test_hosting_has_a_prod_and_a_staging_target():
    hosting = _hosting()
    assert set(hosting) == {"prod", "staging"}
    targets = json.loads((ROOT / ".firebaserc").read_text())["targets"]["thepfisters"]["hosting"]
    assert targets == {"prod": ["thepfisters"], "staging": ["loamstaging"]}


def test_staging_csp_allows_only_the_staging_api():
    prod, staging = _hosting()["prod"], _hosting()["staging"]
    assert "https://core-node.tailcd5892.ts.net:8443" not in _header(prod, "Content-Security-Policy")
    s_csp = _header(staging, "Content-Security-Policy")
    assert "connect-src 'self' https://core-node.tailcd5892.ts.net:8443 " in s_csp
    assert "https://core-node.tailcd5892.ts.net " not in s_csp
    # the rest of the policy is the same
    assert s_csp.replace(":8443", "") == _header(prod, "Content-Security-Policy")


def test_only_staging_sends_noindex():
    assert _header(_hosting()["staging"], "X-Robots-Tag") == "noindex, nofollow"
    with pytest.raises(StopIteration):
        _header(_hosting()["prod"], "X-Robots-Tag")


def test_deploy_web_is_hosting_only_and_never_both_sites():
    s = (ROOT / "scripts" / "deploy-web.sh").read_text()
    assert "--only hosting:${HOSTING_TARGET}" in s and "--only hosting " not in s
