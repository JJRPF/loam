import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.routing import classify_surface

@pytest.mark.asyncio
async def test_health_endpoint():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert "status" in data
        assert "graphhopper" in data
        assert "postgis" in data
        assert data["graphhopper"] is True
        assert data["postgis"] is True

@pytest.mark.asyncio
async def test_calculate_route_endpoint():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {
            "start": {"lat": 43.1305, "lon": -71.3524},
            "end": {"lat": 43.1482, "lon": -71.3651},
            "profile": "mtb"
        }
        resp = await client.post("/api/route", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert "distance_miles" in data
        assert data["distance_miles"] > 0.0
        assert "duration_minutes" in data
        assert "surface_breakdown" in data
        assert "surface_strip" in data
        assert len(data["surface_strip"]) > 0
        assert "coordinates" in data
        assert len(data["coordinates"]) > 0

def test_surface_classification():
    # Singletrack paths
    assert classify_surface("path", "ground", "") == "singletrack"
    assert classify_surface("path", "dirt", "") == "singletrack"
    assert classify_surface("bridleway", "ground", "") == "singletrack"
    
    # Doubletrack
    assert classify_surface("track", "ground", "grade3") == "doubletrack"
    assert classify_surface("track", "dirt", "") == "doubletrack"
    
    # Gravel
    assert classify_surface("track", "gravel", "grade1") == "gravel"
    assert classify_surface("residential", "gravel", "") == "gravel"
    
    # Paved
    assert classify_surface("tertiary", "asphalt", "") == "paved"
    assert classify_surface("primary", "paved", "") == "paved"

@pytest.mark.asyncio
async def test_heat_record_and_query():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        record_payload = {
            "edge_osm_id": 999999999,
            "sport": "mtb",
            "unique_riders": 1,
            "weighted_score": 1.5
        }
        resp = await client.post("/api/heat/record", json=record_payload, headers={"X-Test-User": "round7_admin", "X-Test-Admin": "1"})
        assert resp.status_code == 200
        
        # Query edge
        get_resp = await client.get("/api/edges/999999999?sport=mtb")
        assert get_resp.status_code == 200
        edge_data = get_resp.json()
        assert edge_data["edge_osm_id"] == 999999999
        assert edge_data["weighted_score"] >= 1.5
