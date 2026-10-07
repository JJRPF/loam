import time
import httpx
from fastapi import FastAPI, HTTPException, Header, Response, status
from fastapi.middleware.cors import CORSMiddleware
from typing import Dict, Any, Optional, List

from app.config import settings
from app.models import (
    RouteRequest, RouteResponse, HealthResponse,
    EdgeHeatRecord, SavedRouteCreate, SavedRouteItem,
    ExportRequest
)
from app.routing import fetch_route
from app.db import (
    check_db_health, get_edge_heat, record_edge_heat,
    save_route_to_db, get_saved_routes_from_db,
    get_saved_route_by_id, delete_saved_route_from_db,
    ensure_user_exists
)
from app.gpx_export import build_gpx_track
from app.fit_export import build_fit_course

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Trail Route Builder backend with surface strip profiling and Garmin GPX/FIT export."
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def resolve_user_id(authorization: Optional[str] = Header(None), x_user_id: Optional[str] = Header(None)) -> str:
    """Extracts or assigns user ID from header (Firebase token or dev ID)."""
    if x_user_id:
        return x_user_id
    if authorization and authorization.startswith("Bearer "):
        token = authorization[7:].strip()
        if token and token != "undefined" and token != "null":
            # For Firebase auth in production, decode token; in dev/skeleton return token or dev ID
            return token.split("_")[-1] if "_" in token else token[:32]
    return "justin_default_user"

@app.get("/health", response_model=HealthResponse)
async def health():
    # Check GraphHopper
    gh_ok = False
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            r = await client.get(f"{settings.graphhopper_url}/health")
            gh_ok = (r.status_code == 200)
    except Exception:
        gh_ok = False

    # Check PostGIS
    db_ok = check_db_health()

    return HealthResponse(
        status="ok" if (gh_ok and db_ok) else "degraded",
        version=settings.app_version,
        graphhopper=gh_ok,
        postgis=db_ok,
        elevation_provider=settings.elevation_provider
    )

@app.post("/api/route", response_model=RouteResponse)
async def calculate_route(request: RouteRequest):
    try:
        t0 = time.perf_counter()
        route = await fetch_route(request)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        return route
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )

# --- GPX and FIT Route Exports ---

@app.post("/api/export/gpx")
async def export_gpx(req: ExportRequest):
    """Exports route as standard GPX 1.1 file for Garmin watches and GPS devices."""
    try:
        gpx_xml = build_gpx_track(
            name=req.name or "Loam Route",
            sport=req.sport or "mtb",
            coordinates=req.coordinates,
            distance_miles=req.distance_miles,
            duration_minutes=req.duration_minutes,
            elevation_gain_ft=req.elevation_gain_ft,
            elevation_loss_ft=req.elevation_loss_ft,
            waypoints=req.waypoints
        )
        filename = f"{(req.name or 'loam_route').lower().replace(' ', '_')}.gpx"
        return Response(
            content=gpx_xml,
            media_type="application/gpx+xml",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate GPX: {str(e)}")

@app.post("/api/export/fit")
async def export_fit(req: ExportRequest):
    """Exports route as binary Garmin FIT Course file (.fit) for Garmin fenix 7 Pro / Edge."""
    try:
        fit_bytes = build_fit_course(
            name=req.name or "Loam Route",
            sport=req.sport or "mtb",
            coordinates=req.coordinates,
            distance_miles=req.distance_miles,
            duration_minutes=req.duration_minutes,
            elevation_gain_ft=req.elevation_gain_ft,
            elevation_loss_ft=req.elevation_loss_ft
        )
        filename = f"{(req.name or 'loam_route').lower().replace(' ', '_')}.fit"
        return Response(
            content=fit_bytes,
            media_type="application/vnd.ant.fit",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate FIT: {str(e)}")

@app.get("/api/export/gpx/{route_id}")
async def export_saved_route_gpx(route_id: str):
    route = get_saved_route_by_id(route_id)
    if not route:
        raise HTTPException(status_code=404, detail="Route not found")
    
    gpx_xml = build_gpx_track(
        name=route.get("name", "Loam Route"),
        sport=route.get("sport", "mtb"),
        coordinates=route.get("coordinates", []),
        distance_miles=route.get("distance_miles", 0.0),
        duration_minutes=max(route.get("distance_miles", 0.0) * 6.0, 10.0),
        elevation_gain_ft=route.get("elevation_gain_ft", 0.0),
        elevation_loss_ft=route.get("elevation_loss_ft", 0.0),
        waypoints=route.get("waypoints")
    )
    filename = f"{(route.get('name') or 'loam_route').lower().replace(' ', '_')}.gpx"
    return Response(
        content=gpx_xml,
        media_type="application/gpx+xml",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )

@app.get("/api/export/fit/{route_id}")
async def export_saved_route_fit(route_id: str):
    route = get_saved_route_by_id(route_id)
    if not route:
        raise HTTPException(status_code=404, detail="Route not found")

    fit_bytes = build_fit_course(
        name=route.get("name", "Loam Route"),
        sport=route.get("sport", "mtb"),
        coordinates=route.get("coordinates", []),
        distance_miles=route.get("distance_miles", 0.0),
        duration_minutes=max(route.get("distance_miles", 0.0) * 6.0, 10.0),
        elevation_gain_ft=route.get("elevation_gain_ft", 0.0),
        elevation_loss_ft=route.get("elevation_loss_ft", 0.0)
    )
    filename = f"{(route.get('name') or 'loam_route').lower().replace(' ', '_')}.fit"
    return Response(
        content=fit_bytes,
        media_type="application/vnd.ant.fit",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )

# --- Saved Routes Endpoints ---

@app.post("/api/saved-routes")
async def save_route(
    data: SavedRouteCreate,
    authorization: Optional[str] = Header(None),
    x_user_id: Optional[str] = Header(None)
):
    user_id = resolve_user_id(authorization, x_user_id)
    route_id = save_route_to_db(user_id, data.model_dump())
    if not route_id:
        raise HTTPException(status_code=500, detail="Failed to save route to database")
    return {"status": "saved", "id": route_id, "user_id": user_id}

@app.get("/api/saved-routes")
async def list_saved_routes(
    authorization: Optional[str] = Header(None),
    x_user_id: Optional[str] = Header(None)
):
    user_id = resolve_user_id(authorization, x_user_id)
    routes = get_saved_routes_from_db(user_id)
    return {"routes": routes}

@app.get("/api/saved-routes/{route_id}")
async def get_saved_route(
    route_id: str,
    authorization: Optional[str] = Header(None),
    x_user_id: Optional[str] = Header(None)
):
    user_id = resolve_user_id(authorization, x_user_id)
    route = get_saved_route_by_id(route_id, user_id=None)
    if not route:
        raise HTTPException(status_code=404, detail="Saved route not found")
    return route

@app.delete("/api/saved-routes/{route_id}")
async def delete_saved_route(
    route_id: str,
    authorization: Optional[str] = Header(None),
    x_user_id: Optional[str] = Header(None)
):
    user_id = resolve_user_id(authorization, x_user_id)
    deleted = delete_saved_route_from_db(route_id, user_id=user_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Route not found or delete unauthorized")
    return {"status": "deleted", "id": route_id}

# --- Auth Skeleton ---

@app.post("/api/auth/verify")
async def verify_auth_token(
    payload: Dict[str, Any],
    authorization: Optional[str] = Header(None)
):
    uid = payload.get("uid") or resolve_user_id(authorization, None)
    email = payload.get("email", "justin@example.com")
    display_name = payload.get("display_name", "Justin Pfister")
    ensure_user_exists(uid, email=email, display_name=display_name)
    return {
        "status": "authenticated",
        "user": {
            "id": uid,
            "email": email,
            "display_name": display_name
        }
    }

@app.get("/api/auth/me")
async def get_current_user(
    authorization: Optional[str] = Header(None),
    x_user_id: Optional[str] = Header(None)
):
    uid = resolve_user_id(authorization, x_user_id)
    return {
        "id": uid,
        "email": "justin@example.com",
        "display_name": "Justin Pfister",
        "role": "rider"
    }

# --- Edges & Heat ---

@app.get("/api/edges/{osm_id}")
async def get_edge_info(osm_id: int, sport: str = "mtb"):
    heat = get_edge_heat(osm_id, sport)
    if not heat:
        return {"osm_id": osm_id, "sport": sport, "heat": None, "message": "No recent heat data"}
    return heat

@app.post("/api/heat/record")
async def record_heat(record: EdgeHeatRecord):
    ok = record_edge_heat(record.edge_osm_id, record.sport.value, record.weighted_score)
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to record heat to database")
    return {"status": "recorded", "edge_osm_id": record.edge_osm_id, "sport": record.sport}

# --- Static Files / Frontend PWA ---
import os
from fastapi.staticfiles import StaticFiles

frontend_dist = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend", "dist")
if os.path.exists(frontend_dist):
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=True)
