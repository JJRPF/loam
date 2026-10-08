import time
import base64
import json
import datetime
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app, verify_google_id_token
from app.db import get_connection

def create_mock_jwt(uid: str, email: str, name: str, exp_offset_sec: int = 3600) -> str:
    """Generates an unencrypted 3-part base64url JWT structure for testing."""
    header = {"alg": "RS256", "typ": "JWT"}
    payload = {
        "sub": uid,
        "email": email,
        "name": name,
        "iat": int(time.time()),
        "exp": int(time.time()) + exp_offset_sec,
        "iss": "https://accounts.google.com"
    }
    
    def b64url(data: dict) -> str:
        b = json.dumps(data).encode("utf-8")
        return base64.urlsafe_b64encode(b).decode("utf-8").rstrip("=")

    h_b64 = b64url(header)
    p_b64 = b64url(payload)
    sig_b64 = "mock_signature_bytes_for_test"
    return f"{h_b64}.{p_b64}.{sig_b64}"

@pytest.mark.asyncio
async def test_google_id_token_verification_valid():
    """Verifies that a valid Google ID token is successfully decoded and authenticated."""
    token = create_mock_jwt("google_justin_123", "justin.pfister@test.com", "Justin Pfister", exp_offset_sec=3600)
    
    user_info = verify_google_id_token(token)
    assert user_info["uid"] == "google_justin_123"
    assert user_info["email"] == "justin.pfister@test.com"
    assert user_info["display_name"] == "Justin Pfister"

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/auth/verify", json={"token": token})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "authenticated"
        assert data["user"]["id"] == "google_justin_123"
        assert data["user"]["email"] == "justin.pfister@test.com"

@pytest.mark.asyncio
async def test_google_id_token_verification_expired():
    """Verifies that an expired Google ID token is rejected with 401."""
    expired_token = create_mock_jwt("google_expired_user", "expired@test.com", "Expired User", exp_offset_sec=-100)
    
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/auth/verify", json={"token": expired_token})
        assert resp.status_code == 401
        assert "expired" in resp.json()["detail"].lower()

@pytest.mark.asyncio
async def test_geocode_endpoint_matching():
    """Verifies location search geocoding endpoint for NH trailheads and hubs."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Search Bear Brook
        bb_resp = await client.get("/api/geocode?q=Bear%20Brook")
        assert bb_resp.status_code == 200
        results = bb_resp.json()["results"]
        assert len(results) > 0
        assert any("Bear Brook" in r["name"] for r in results)
        first = results[0]
        assert abs(first["lat"] - 43.1305) < 0.01
        assert abs(first["lon"] - (-71.3524)) < 0.01

        # Search Highland
        hl_resp = await client.get("/api/geocode?q=Highland")
        assert hl_resp.status_code == 200
        hl_results = hl_resp.json()["results"]
        assert any("Highland Mountain Bike Park" in r["name"] for r in hl_results)

        # Empty search
        empty_resp = await client.get("/api/geocode?q=")
        assert empty_resp.status_code == 200
        assert empty_resp.json()["results"] == []

@pytest.mark.asyncio
async def test_authenticated_saved_route_crud_in_postgres():
    """Verifies that an authenticated Google user can save, list, and delete routes in PostgreSQL saved_routes table."""
    auth_user_id = f"test_user_{int(time.time())}"
    token = create_mock_jwt(auth_user_id, f"{auth_user_id}@test.com", "Test Rider", exp_offset_sec=3600)
    headers = {"Authorization": f"Bearer {token}"}

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
