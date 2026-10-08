import time
import uuid
import datetime
import httpx
from fastapi import FastAPI, HTTPException, Header, Response, status, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from typing import Dict, Any, Optional, List

from app.config import settings
from app.models import (
    RouteRequest, RouteResponse, HealthResponse,
    EdgeHeatRecord, SavedRouteCreate, SavedRouteItem,
    ExportRequest, RouteOptionsRequest, RouteOptionsResponse,
    LatLon, SportProfile, ActivityUploadResponse,
    PrivacyZoneCreate, PrivacyZoneResponse, RegionalCoverageResponse,
    RecalculateHeatResponse, EdgeHeatDetailResponse
)
from app.routing import fetch_route, generate_route_options, generate_route_options_stream
from app.db import (
    check_db_health, get_edge_heat, record_edge_heat,
    save_route_to_db, get_saved_routes_from_db,
    get_saved_route_by_id, delete_saved_route_from_db,
    ensure_user_exists, record_activity, record_activity_edge_visits,
    get_privacy_zones, create_privacy_zone, delete_privacy_zone,
    get_user_consent, set_user_consent, get_regional_coverage_cell,
    is_region_covered
)
from app.gpx_export import build_gpx_track
from app.fit_export import build_fit_course
from app.activity_parser import parse_activity_file, MAX_FILE_SIZE
from app.privacy import apply_privacy_filters, haversine_m
from app.map_matching import map_match_activity
from app.worker import run_nightly_job

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
async def calculate_route(
    request: RouteRequest,
    authorization: Optional[str] = Header(None),
    x_user_id: Optional[str] = Header(None)
):
    try:
        uid = resolve_user_id(authorization, x_user_id)
        t0 = time.perf_counter()
        route = await fetch_route(request, user_id=uid)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        return route
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )

@app.post("/api/route/options", response_model=RouteOptionsResponse)
async def calculate_route_options(
    request: RouteOptionsRequest,
    authorization: Optional[str] = Header(None),
    x_user_id: Optional[str] = Header(None)
):
    try:
        uid = resolve_user_id(authorization, x_user_id)
        options = await generate_route_options(request, count=request.candidate_count, user_id=uid)
        return RouteOptionsResponse(
            options=options,
            count=len(options),
            requested_target_miles=request.target_distance_miles,
            start_name=request.start.name
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )

@app.post("/api/route/options/stream")
async def stream_route_options_post(
    request: RouteOptionsRequest,
    authorization: Optional[str] = Header(None),
    x_user_id: Optional[str] = Header(None)
):
    uid = resolve_user_id(authorization, x_user_id)
    async def event_generator():
        try:
            count = 0
            async for opt in generate_route_options_stream(request, count=request.candidate_count, user_id=uid):
                count += 1
                yield f"event: candidate\ndata: {opt.model_dump_json()}\n\n"
            yield f"event: complete\ndata: {{\"status\": \"complete\", \"count\": {count}}}\n\n"
        except Exception as e:
            yield f"event: error\ndata: {{\"error\": \"{str(e)}\"}}\n\n"


    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )

@app.get("/api/route/options/stream")
async def stream_route_options_get(
    lat: float,
    lon: float,
    target_miles: float = 10.0,
    sport: SportProfile = SportProfile.MTB_HARDTAIL,
    count: int = 10,
    name: Optional[str] = None
):
    req = RouteOptionsRequest(
        start=LatLon(lat=lat, lon=lon, name=name),
        profile=sport,
        route_mode="loop",
        target_distance_miles=target_miles,
        candidate_count=count
    )
    return await stream_route_options_post(req)

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

# --- Stage 4: Activity Ingestion, Heat & Privacy Endpoints ---

@app.post("/api/activities/upload", response_model=ActivityUploadResponse)
async def upload_activity(
    file: UploadFile = File(...),
    sport: Optional[str] = Form(None),
    consent_given: bool = Form(True),
    retain_file: bool = Form(False),
    authorization: Optional[str] = Header(None),
    x_user_id: Optional[str] = Header(None)
):
    """
    Defensively parses uploaded GPX or FIT activity traces.
    Applies endpoint trimming (first/last 0.2 mi) and privacy zone exclusions.
    Deletes raw file unless explicit user retention is requested.
    Map-matches GPS trackpoints to OSM/GraphHopper edges.
    """
    uid = resolve_user_id(authorization, x_user_id)
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"Uploaded file exceeds maximum limit of {MAX_FILE_SIZE // (1024 * 1024)} MB."
        )


    try:
        raw_pts, detected_sport, act_time = parse_activity_file(content, file.filename or "upload.gpx")
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Failed to parse activity: {e}")

    chosen_sport = (sport or detected_sport or "mtb").lower()
    raw_cnt = len(raw_pts)

    # Calculate raw distance
    raw_dist_m = 0.0
    for i in range(raw_cnt - 1):
        raw_dist_m += haversine_m(raw_pts[i].lon, raw_pts[i].lat, raw_pts[i+1].lon, raw_pts[i+1].lat)
    raw_dist_mi = round(raw_dist_m * 0.000621371, 2)

    # Estimate duration in minutes
    if act_time and raw_pts[-1].time and raw_pts[-1].time > act_time:
        duration_min = round((raw_pts[-1].time - act_time).total_seconds() / 60.0, 1)
    else:
        duration_min = round((raw_dist_mi / 10.0) * 60.0, 1)

    # Fetch user privacy zones
    user_zones = get_privacy_zones(uid)

    # Apply privacy filters: 0.2 mi start/end trimming + privacy zones
    trimmed_pts, priv_stats = apply_privacy_filters(raw_pts, user_zones)

    act_id = str(uuid.uuid4())
    matched_edges_count = 0
    message = None

    if priv_stats["is_empty"] or len(trimmed_pts) < 2:
        message = "Activity trimmed completely due to endpoint trimming (first/last 0.2 mi) or privacy zones."
    else:
        # Map-matching against OSM road/trail network edges
        edge_counts = await map_match_activity(trimmed_pts, sport=chosen_sport)
        matched_edges_count = len(edge_counts)

        # Record edge visits if consent is granted
        if consent_given:
            record_activity_edge_visits(
                activity_id=act_id,
                edge_counts=edge_counts,
                user_id=uid,
                sport=chosen_sport,
                visited_at=act_time
            )

    # Record activity in db
    # Retention rule: raw file deleted after processing unless retain_file requested
    record_activity({
        "id": act_id,
        "user_id": uid,
        "sport": chosen_sport,
        "activity_date": act_time,
        "distance_miles": raw_dist_mi,
        "duration_minutes": max(duration_min, 1.0),
        "file_format": "fit" if (file.filename or "").lower().endswith(".fit") else "gpx",
        "raw_file_retained": retain_file,
        "raw_file_path": None,  # Deleted per privacy rules unless retain_file requested
        "consent_given": consent_given,
        "matched_edge_count": matched_edges_count
    })

    return ActivityUploadResponse(
        activity_id=act_id,
        user_id=uid,
        sport=chosen_sport,
        distance_miles=raw_dist_mi,
        duration_minutes=duration_min,
        raw_points_count=raw_cnt,
        trimmed_points_count=len(trimmed_pts),
        matched_edges_count=matched_edges_count,
        consent_given=consent_given,
        raw_file_retained=retain_file,
        message=message
    )

@app.get("/api/edges/{osm_id}", response_model=EdgeHeatDetailResponse)
async def get_edge_info(
    osm_id: int,
    sport: str = "mtb",
    authorization: Optional[str] = Header(None),
    x_user_id: Optional[str] = Header(None)
):
    uid = resolve_user_id(authorization, x_user_id)
    heat = get_edge_heat(osm_id, sport, user_id=uid)
    if not heat:
        return EdgeHeatDetailResponse(
            edge_osm_id=osm_id,
            sport=sport,
            unique_riders_12mo=0,
            total_passes_12mo=0,
            weighted_score=0.0,
            is_public=False,
            last_ridden_date=None,
            is_contributor=False,
            coverage_sufficient=False,
            message="No recent heat data"
        )
    return EdgeHeatDetailResponse(
        edge_osm_id=heat["edge_osm_id"],
        sport=heat["sport"],
        unique_riders_12mo=heat.get("unique_riders_12mo", 0),
        total_passes_12mo=heat.get("total_passes_12mo", 0),
        weighted_score=heat.get("weighted_score", 0.0),
        is_public=heat.get("is_public", False),
        last_ridden_date=heat.get("last_ridden_date"),
        is_contributor=heat.get("is_contributor", False),
        coverage_sufficient=True,
        message=None if heat.get("is_accessible") else "Private to contributor (< 3 unique riders)"
    )

@app.post("/api/heat/record")
async def record_heat(
    record: EdgeHeatRecord,
    authorization: Optional[str] = Header(None),
    x_user_id: Optional[str] = Header(None)
):
    uid = resolve_user_id(authorization, x_user_id)
    ok = record_edge_heat(record.edge_osm_id, record.sport.value, record.weighted_score, user_id=uid)
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to record heat to database")
    return {"status": "recorded", "edge_osm_id": record.edge_osm_id, "sport": record.sport}

# --- Privacy Zones & Consent Management ---

@app.get("/api/privacy/zones", response_model=List[PrivacyZoneResponse])
async def list_privacy_zones(
    authorization: Optional[str] = Header(None),
    x_user_id: Optional[str] = Header(None)
):
    uid = resolve_user_id(authorization, x_user_id)
    return get_privacy_zones(uid)

@app.post("/api/privacy/zones", response_model=PrivacyZoneResponse)
async def add_privacy_zone(
    zone: PrivacyZoneCreate,
    authorization: Optional[str] = Header(None),
    x_user_id: Optional[str] = Header(None)
):
    uid = resolve_user_id(authorization, x_user_id)
    new_id = create_privacy_zone(uid, zone.name or "Home/Work", zone.lat, zone.lon, zone.radius_m)
    if not new_id:
        raise HTTPException(status_code=500, detail="Failed to create privacy zone")
    return PrivacyZoneResponse(
        id=new_id,
        user_id=uid,
        name=zone.name or "Home/Work",
        lat=zone.lat,
        lon=zone.lon,
        radius_m=zone.radius_m,
        created_at=datetime.datetime.now(datetime.timezone.utc).isoformat()
    )

@app.delete("/api/privacy/zones/{zone_id}")
async def remove_privacy_zone(
    zone_id: int,
    authorization: Optional[str] = Header(None),
    x_user_id: Optional[str] = Header(None)
):
    uid = resolve_user_id(authorization, x_user_id)
    ok = delete_privacy_zone(zone_id, uid)
    if not ok:
        raise HTTPException(status_code=404, detail="Privacy zone not found or deletion failed")
    return {"status": "deleted", "id": zone_id}

@app.get("/api/privacy/consent")
async def check_consent(
    authorization: Optional[str] = Header(None),
    x_user_id: Optional[str] = Header(None)
):
    uid = resolve_user_id(authorization, x_user_id)
    return {"user_id": uid, "consent_given": get_user_consent(uid)}

@app.post("/api/privacy/consent")
async def update_consent(
    consent_given: bool = True,
    authorization: Optional[str] = Header(None),
    x_user_id: Optional[str] = Header(None)
):
    uid = resolve_user_id(authorization, x_user_id)
    set_user_consent(uid, consent_given)
    return {"user_id": uid, "consent_given": consent_given}

# --- Regional Coverage & Nightly Worker ---

@app.get("/api/coverage", response_model=RegionalCoverageResponse)
async def get_regional_coverage(lat: float, lon: float):
    cell = get_regional_coverage_cell(lat, lon)
    if not cell:
        return RegionalCoverageResponse(
            cell_id=f"{lat:.2f}:{lon:.2f}",
            min_lat=lat,
            min_lon=lon,
            max_lat=lat + 0.05,
            max_lon=lon + 0.05,
            activity_count_12mo=0,
            is_sufficient=False,
            threshold=3
        )
    return RegionalCoverageResponse(
        cell_id=cell["cell_id"],
        min_lat=cell["min_lat"],
        min_lon=cell["min_lon"],
        max_lat=cell["max_lat"],
        max_lon=cell["max_lon"],
        activity_count_12mo=cell.get("activity_count_12mo", 0),
        is_sufficient=cell.get("is_sufficient", False),
        threshold=3
    )

@app.post("/api/jobs/recalculate-heat", response_model=RecalculateHeatResponse)
async def trigger_heat_recalculation():
    result = run_nightly_job()
    return RecalculateHeatResponse(
        status=result.get("status", "success"),
        edges_updated=result.get("edges_updated", 0),
        public_edges_count=result.get("public_edges_count", 0),
        private_edges_count=result.get("private_edges_count", 0),
        coverage_cells_updated=result.get("coverage_cells_updated", 0),
        ghost_trails_detected=result.get("ghost_trails_detected", 0),
        duration_seconds=result.get("duration_seconds", 0.0)
    )


# --- Static Files / Frontend PWA ---
import os
from fastapi.staticfiles import StaticFiles

frontend_dist = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend", "dist")
if os.path.exists(frontend_dist):
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=True)
