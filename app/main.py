import time
import httpx
from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from typing import Dict, Any

from app.config import settings
from app.models import (
    RouteRequest, RouteResponse, HealthResponse,
    EdgeHeatRecord
)
from app.routing import fetch_route
from app.db import check_db_health, get_edge_heat, record_edge_heat

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Trail Route Builder backend with surface strip profiling and recency heat layer."
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
        # If any warnings are needed
        if route.distance_miles > 100:
            route.warnings.append("Route distance exceeds 100 miles.")
        return route
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )

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

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=True)
