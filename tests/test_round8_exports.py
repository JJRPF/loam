"""Round 8 (GH-38): downloads must work for the default route names (they contain an em dash)."""
import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app, attachment_headers

BODY = {
    "name": "Bear Brook State Park parking — Podunk Road Loop", "sport": "mtb", "distance_miles": 1.2,
    "duration_minutes": 20, "elevation_gain_ft": 30, "elevation_loss_ft": 30,
    "coordinates": [[-71.36592, 43.134855, 100.0], [-71.3660, 43.1352, 101.0], [-71.3665, 43.1356, 102.0]],
}


def test_attachment_headers_are_plain_ascii_and_cannot_break_the_header():
    h = attachment_headers('Evil"\r\nX-Injected: 1 — Loop', "gpx")["Content-Disposition"]
    h.encode("latin-1")  # a header value must encode
    assert "\r" not in h and "\n" not in h
    assert 'filename="evil_x_injected_1_loop.gpx"' in h
    assert "filename*=UTF-8''" in h and "%E2%80%94" in h
    assert 'filename="loam_route.fit"' in attachment_headers(None, "fit")["Content-Disposition"]
    assert 'filename="loam_route.fit"' in attachment_headers("——", "fit")["Content-Disposition"]


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,magic", [("gpx", b"<?xml"), ("fit", b".FIT")])
async def test_export_with_an_em_dash_name(kind, magic):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post(f"/api/export/{kind}", json=BODY)
    assert r.status_code == 200, r.text
    assert magic in r.content[:16]
    assert f'filename="bear_brook_state_park_parking_podunk_road_loop.{kind}"' in r.headers["content-disposition"]
