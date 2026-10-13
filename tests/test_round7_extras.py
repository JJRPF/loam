"""Round 7 (GH-34): weather and the nightly backup script. (The OSM POI markers were removed in Round 8.)"""
import pathlib
import subprocess

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from app import weather
from app.main import app


def _nws_transport(fail_points=False):
    def handler(request):
        if request.url.path.startswith("/points/"):
            if fail_points:
                return httpx.Response(404)
            return httpx.Response(200, json={"properties": {"forecastHourly": "https://api.weather.gov/gridpoints/GYX/1,1/forecast/hourly"}})
        return httpx.Response(200, json={"properties": {"periods": [
            {"startTime": "2026-10-13T18:00:00-04:00", "temperature": 58, "temperatureUnit": "F",
             "probabilityOfPrecipitation": {"value": 20}, "windSpeed": "5 mph", "shortForecast": "Partly Cloudy"},
            {"startTime": "2026-10-13T19:00:00-04:00", "temperature": 55, "temperatureUnit": "F",
             "probabilityOfPrecipitation": {"value": None}, "windSpeed": "3 mph", "shortForecast": "Clear"}]}})
    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_weather_shapes_the_nws_answer_and_never_invents_one():
    weather._cache.clear()
    async with httpx.AsyncClient(transport=_nws_transport(), headers=weather.HEADERS) as c:
        fc = await weather.hourly_forecast(43.13, -71.37, 12, client=c)
    assert fc["source"] == "National Weather Service"
    assert fc["periods"][0] == {"start": "2026-10-13T18:00:00-04:00", "temp_f": 58, "precip_pct": 20,
                                "wind": "5 mph", "summary": "Partly Cloudy"}
    assert fc["periods"][1]["precip_pct"] is None
    weather._cache.clear()
    async with httpx.AsyncClient(transport=_nws_transport(fail_points=True), headers=weather.HEADERS) as c:
        assert await weather.hourly_forecast(10.0, 10.0, 12, client=c) is None


@pytest.mark.asyncio
async def test_weather_endpoint_is_503_when_unavailable(monkeypatch):
    async def none(*a, **k):
        return None
    monkeypatch.setattr(weather, "hourly_forecast", none)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        assert (await client.get("/api/weather", params=dict(lat=43.1, lon=-71.4))).status_code == 503
        assert (await client.get("/api/weather", params=dict(lat=143.1, lon=-71.4))).status_code == 422


def test_backup_script_is_valid_bash_and_keeps_a_week():
    path = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "backup_db.sh"
    assert subprocess.run(["bash", "-n", str(path)]).returncode == 0
    text = path.read_text()
    assert "pg_dump" in text and "-Fc" in text and "KEEP_DAYS:-7" in text and "pg_restore -l" in text


@pytest.mark.asyncio
async def test_network_percent_counts_only_the_riders_own_visits():
    import uuid
    from app.db import get_connection, record_activity, record_activity_edge_visits
    from tests.conftest import as_user
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT osm_way_id, ST_X(ST_StartPoint(geom)), ST_Y(ST_StartPoint(geom)) FROM trail_segments "
                    "WHERE category <> 'paved' AND geom && ST_MakeEnvelope(-71.40, 43.10, -71.30, 43.17, 4326) LIMIT 1")
        way, lon, lat = cur.fetchone()
        cur.execute("INSERT INTO edges (osm_id, name, highway) VALUES (%s, 'TEST', 'path') ON CONFLICT (osm_id) DO NOTHING", (way,))
        conn.commit()
    uid = f"r7net_{uuid.uuid4().hex[:6]}"
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        before = (await client.get("/api/me/network", params=dict(lat=lat, lon=lon, radius_mi=3), headers=as_user(uid))).json()
        assert before["ridden_miles"] == 0 and before["trail_miles"] > 0
        act = f"net_{uuid.uuid4().hex[:8]}"
        record_activity({"id": act, "user_id": uid, "sport": "mtb", "distance_miles": 1.0})
        record_activity_edge_visits(act, {way: 1}, uid, "mtb_hardtail")
        try:
            after = (await client.get("/api/me/network", params=dict(lat=lat, lon=lon, radius_mi=3), headers=as_user(uid))).json()
            other = (await client.get("/api/me/network", params=dict(lat=lat, lon=lon, radius_mi=3), headers=as_user("someone_else"))).json()
        finally:
            with get_connection() as conn, conn.cursor() as cur:
                cur.execute("DELETE FROM users WHERE id = %s", (uid,))
                cur.execute("DELETE FROM activities WHERE id = %s", (act,))
                conn.commit()
        assert after["ridden_miles"] > 0 and after["ridden_percent"] > 0
        assert other["ridden_miles"] == 0


@pytest.mark.asyncio
async def test_only_verified_submissions_export_as_gpx():
    import json as _json
    from app.db import get_connection
    transport = ASGITransport(app=app)
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO users (id) VALUES ('r7gpx_user') ON CONFLICT DO NOTHING")
        ids = []
        for status in ("pending", "verified"):
            cur.execute("INSERT INTO trail_submissions (user_id, name, sport, difficulty, status, geom) VALUES "
                        "('r7gpx_user', 'TEST export', 'mtb', 'blue', %s, ST_GeomFromText('LINESTRING(-71.5 43.1, -71.499 43.101, -71.498 43.1)', 4326)) RETURNING id",
                        (status,))
            ids.append(cur.fetchone()[0])
        conn.commit()
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            assert (await client.get(f"/api/submissions/{ids[0]}/osm-gpx")).status_code == 404
            ok = await client.get(f"/api/submissions/{ids[1]}/osm-gpx")
            assert ok.status_code == 200 and ok.headers["content-type"].startswith("application/gpx+xml")
            assert "<trkpt" in ok.text and "TEST export" in ok.text
    finally:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM trail_submissions WHERE id = ANY(%s)", (ids,))
            cur.execute("DELETE FROM users WHERE id = 'r7gpx_user'")
            conn.commit()
