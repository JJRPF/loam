"""Round 8 (GH-38) phase 5: the UI shows only enabled connectors, driven by /api/config and /api/connectors.

The rendering itself is checked in the browser suite (tests/browser); here the API contract it relies on.
"""
import pytest
from httpx import ASGITransport, AsyncClient

from app.config import settings
from app.main import app
from tests.conftest import as_user

FLAGS = {
    "strava": "enable_strava_connector",
    "garmin": "enable_garmin_connector",
    "trailforks": "enable_trailforks_connector",
    "cubetrek": "enable_cubetrek_connector",
}


async def _get(path, **kw):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        return await c.get(path, **kw)


@pytest.mark.asyncio
async def test_config_connectors_follow_the_flags(monkeypatch):
    for attr in FLAGS.values():
        monkeypatch.setattr(settings, attr, False)
    assert (await _get("/api/config")).json()["connectors"] == {name: False for name in FLAGS}
    for name, attr in FLAGS.items():
        monkeypatch.setattr(settings, attr, True)
        conns = (await _get("/api/config")).json()["connectors"]
        assert conns[name] is True and sum(conns.values()) == 1
        monkeypatch.setattr(settings, attr, False)


@pytest.mark.asyncio
async def test_connector_list_marks_disabled_ones_and_never_enables_by_default(monkeypatch):
    # strava and trailforks default to off (their terms are unconfirmed); the UI hides whatever is not enabled
    from app.config import Settings
    import os
    for name in ("strava", "trailforks"):
        if f"ENABLE_{name.upper()}_CONNECTOR" not in os.environ:
            assert getattr(Settings(), FLAGS[name]) is False
    monkeypatch.setattr(settings, "enable_strava_connector", False)
    monkeypatch.setattr(settings, "enable_trailforks_connector", False)
    r = await _get("/api/connectors", headers=as_user("r8_conn_user"))
    assert r.status_code == 200
    by_name = {c["name"]: c["enabled"] for c in r.json()}
    assert by_name["strava"] is False and by_name["trailforks"] is False
    cfg = (await _get("/api/config")).json()["connectors"]
    assert by_name == cfg  # the signed-in list and the public config agree
