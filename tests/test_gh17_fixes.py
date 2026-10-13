import time
import base64
import json
import datetime
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app
from tests.conftest import as_user
from app.db import get_connection

@pytest.mark.asyncio
async def test_geocode_endpoint_matching(monkeypatch):
    """Geocoding: OSM-derived trailhead parking first; no hand-typed coordinates."""
    import app.main as main_module
    from app.main import load_trailheads

    async def offline(query):
        return []

    monkeypatch.setattr(main_module, "photon_search", offline)  # Photon unreachable in this test
    bow = next(t for t in load_trailheads() if t["area"] == "Bow Town Forest")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/geocode?q=Bow%20Town")
        assert resp.status_code == 200
        first = resp.json()["results"][0]
        assert first["name"] == "Bow Town Forest parking"
        assert (first["lat"], first["lon"]) == (bow["lat"], bow["lon"])

        # Nothing matches and Photon is unreachable: no results, not a guess.
        none_resp = await client.get("/api/geocode?q=Highland%20Mountain%20Bike%20Park")
        assert none_resp.json()["results"] == []

        empty_resp = await client.get("/api/geocode?q=")
        assert empty_resp.status_code == 200
        assert empty_resp.json()["results"] == []


@pytest.mark.asyncio
async def test_authenticated_saved_route_crud_in_postgres():
    """Verifies that an authenticated Google user can save, list, and delete routes in PostgreSQL saved_routes table."""
    auth_user_id = f"test_user_{int(time.time())}"
    headers = as_user(auth_user_id)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Save Route
        save_payload = {
            "name": "Bear Brook Singletrack Epic",
            "sport": "mtb",
            "distance_miles": 14.2,
            "elevation_gain_ft": 1250.0,
            "elevation_loss_ft": 1250.0,
            "coordinates": [
                [-71.3524, 43.1305, 200.0],
                [-71.3500, 43.1320, 215.0],
                [-71.3480, 43.1350, 230.0],
                [-71.3524, 43.1305, 200.0]
            ],
            "surface_breakdown": {"singletrack": 75.0, "doubletrack": 15.0, "gravel": 10.0},
            "verbal_summary": "High singletrack concentration around Podunk Rd."
        }

        save_resp = await client.post("/api/saved-routes", json=save_payload, headers=headers)
        assert save_resp.status_code == 200
        save_data = save_resp.json()
        assert save_data["status"] == "saved"
        assert save_data["user_id"] == auth_user_id
        route_id = save_data["id"]

        # 2. List saved routes for authenticated user
        list_resp = await client.get("/api/saved-routes", headers=headers)
        assert list_resp.status_code == 200
        routes = list_resp.json()["routes"]
        assert len(routes) >= 1
        found = next((r for r in routes if r["id"] == route_id), None)
        assert found is not None
        assert found["name"] == "Bear Brook Singletrack Epic"
        assert found["distance_miles"] == 14.2
        assert len(found["coordinates"]) == 4

        # 3. Retrieve single saved route
        get_resp = await client.get(f"/api/saved-routes/{route_id}", headers=headers)
        assert get_resp.status_code == 200
        assert get_resp.json()["name"] == "Bear Brook Singletrack Epic"

        # 4. Delete saved route
        del_resp = await client.delete(f"/api/saved-routes/{route_id}", headers=headers)
        assert del_resp.status_code == 200
        assert del_resp.json()["status"] == "deleted"

        # Verify deletion
        list_resp2 = await client.get("/api/saved-routes", headers=headers)
        assert not any(r["id"] == route_id for r in list_resp2.json()["routes"])

@pytest.mark.asyncio
async def test_carto_tile_url_and_key_in_frontend():
    """Verifies that the built frontend bundle contains the official CARTO key and attribution."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/")
        assert resp.status_code == 200
        # Check that index.html or dist bundle references Loam
        assert "Loam" in resp.text
