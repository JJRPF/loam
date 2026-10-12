import os
import time
import uuid
import datetime
import json
import httpx
from fastapi import FastAPI, HTTPException, Depends, Response, status, UploadFile, File, Form, Query
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from typing import Dict, Any, Optional, List

from app.config import settings, check_production_config
from app.auth import AuthUser, get_current_user, get_optional_user, get_admin_user
from app.models import (
    RouteRequest, RouteResponse, HealthResponse,
    EdgeHeatRecord, SavedRouteCreate, SavedRouteItem,
    ExportRequest, RouteOptionsRequest, RouteOptionsResponse,
    LatLon, SportProfile, ActivityUploadResponse,
    PrivacyZoneCreate, PrivacyZoneResponse, RegionalCoverageResponse,
    RecalculateHeatResponse, EdgeHeatDetailResponse,
    FlagCreate, FlagResponse, FlagVoteCreate, FlagVoteResponse,
    TrailCheckinCreate, TrailCheckinResponse, TrailStatusResponse,
    UserDNRCreate, UserDNRResponse, DNROverrideLogItem,
    RestrictionCreate, RestrictionUpdate, RestrictionResponse, TakedownRequest,
    UserDataExportResponse,
    # Stage 6: Differentiators models
    TrailSubmissionCreate, TrailSubmissionResponse,
    TrailSubmissionEvidenceCreate, TrailSubmissionEvidenceResponse,
    TrailSubmissionReviewRequest, UnriddenTrailItem,
    ConnectorStatus, GarminLoginRequest, GarminMfaVerifyRequest,
    StravaAuthRequest, TrailforksAuthRequest,
    CubeTrekAuthRequest, CubeTrekImportRequest,
    ConnectorSyncRequest, ConnectorSyncResponse, DevConsoleStatusResponse
)
from app.routing import fetch_route, generate_route_options, generate_route_options_stream
from app.db import (
    get_connection,
    check_db_health, get_edge_heat, record_edge_heat,
    save_route_to_db, get_saved_routes_from_db,
    get_saved_route_by_id, delete_saved_route_from_db,
    ensure_user_exists, record_activity, record_activity_edge_visits,
    get_privacy_zones, create_privacy_zone, delete_privacy_zone,
    get_user_consent, set_user_consent, get_regional_coverage_cell,
    is_region_covered,
    create_community_flag, vote_community_flag, get_community_flags,
    record_trail_checkin, get_trail_checkins, get_trail_status,
    create_user_dnr, get_user_dnr_list, delete_user_dnr, get_dnr_override_logs,
    get_all_restrictions, create_restriction, update_restriction, delete_restriction,
    create_takedown, export_user_data, delete_user_account,
    # Stage 6: Differentiators db methods
    get_unridden_high_heat_trails, create_trail_submission,
    get_trail_submission_by_id, get_trail_submissions,
    record_submission_evidence, evaluate_and_verify_submission,
    admin_update_submission_status, list_user_connected_services,
    recalculate_all_edge_heat, get_heat_trail_geojson
)
from app.connectors import connector_manager
from app.gpx_export import build_gpx_track
from app.fit_export import build_fit_course
from app.activity_parser import parse_activity_file, MAX_FILE_SIZE
from app.privacy import apply_privacy_filters, haversine_m
from app.map_matching import map_match_activity
from app.worker import run_nightly_job
from app.elevation import tile_count


APP_START_TIME = datetime.datetime.now(datetime.timezone.utc)

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Trail Route Builder backend with surface strip profiling and Garmin GPX/FIT export."
)

check_production_config()

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
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
        elevation_provider=f"{settings.elevation_provider} ({tile_count()} DEM tiles)"
    )

@app.post("/api/route", response_model=RouteResponse)
async def calculate_route(
    request: RouteRequest,
    user: Optional[AuthUser] = Depends(get_optional_user)
):
    try:
        uid = user.uid if user else None
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
    user: Optional[AuthUser] = Depends(get_optional_user)
):
    try:
        uid = user.uid if user else None
        options = await generate_route_options(request, count=request.candidate_count, user_id=uid)
        is_loop_req = request.is_loop or request.route_mode in ("loop", "round_trip") or (request.end is None and request.route_mode != "out_and_back")
        has_true_loops = any(opt.route_type in ("loop", "lollipop") for opt in options)
        no_true_loop = bool(is_loop_req and not has_true_loops)
        nearby_sugg = None
        if options and options[0].nearby_start_suggestion:
            nearby_sugg = options[0].nearby_start_suggestion

        return RouteOptionsResponse(
            options=options,
            count=len(options),
            requested_target_miles=request.target_distance_miles,
            start_name=request.start.name,
            loops_only=request.loops_only,
            no_true_loop_near_here=no_true_loop,
            nearby_start_suggestion=nearby_sugg
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )

@app.post("/api/route/options/stream")
async def stream_route_options_post(
    request: RouteOptionsRequest,
    user: Optional[AuthUser] = Depends(get_optional_user)
):
    uid = user.uid if user else None
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
    # EventSource cannot send an Authorization header, so this GET form is anonymous.
    return await stream_route_options_post(req, user=None)

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
    user: AuthUser = Depends(get_current_user)
):
    user_id = user.uid
    route_id = save_route_to_db(user_id, data.model_dump())
    if not route_id:
        raise HTTPException(status_code=500, detail="Failed to save route to database")
    return {"status": "saved", "id": route_id, "user_id": user_id}

@app.get("/api/saved-routes")
async def list_saved_routes(
    user: AuthUser = Depends(get_current_user)
):
    user_id = user.uid
    routes = get_saved_routes_from_db(user_id)
    return {"routes": routes}

@app.get("/api/saved-routes/{route_id}")
async def get_saved_route(
    route_id: str,
    user: AuthUser = Depends(get_current_user)
):
    route = get_saved_route_by_id(route_id, user_id=user.uid)
    if not route:
        raise HTTPException(status_code=404, detail="Saved route not found")
    return route

@app.delete("/api/saved-routes/{route_id}")
async def delete_saved_route(
    route_id: str,
    user: AuthUser = Depends(get_current_user)
):
    user_id = user.uid
    deleted = delete_saved_route_from_db(route_id, user_id=user_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Route not found or delete unauthorized")
    return {"status": "deleted", "id": route_id}

# --- Auth ---

@app.get("/api/auth/me")
async def get_me(
    user: AuthUser = Depends(get_current_user)
):
    """The verified Firebase user behind the bearer token."""
    return {
        "id": user.uid,
        "email": user.email,
        "email_verified": user.email_verified,
        "display_name": user.name,
        "photo_url": user.picture,
        "is_admin": user.is_admin,
    }

# --- Geocoding / Location Search Endpoint ---

# OSM-derived trailhead parking (scripts/build_trailheads.py), shared with the frontend.
TRAILHEADS_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                               "frontend", "src", "data", "trailheads.json")


def load_trailheads() -> List[Dict[str, Any]]:
    try:
        with open(TRAILHEADS_PATH) as f:
            return json.load(f).get("trailheads", [])
    except (OSError, ValueError):
        return []

async def photon_search(query: str) -> List[Dict[str, Any]]:
    """Photon (komoot, OSM data) search; [] when it can't be reached."""
    out = []
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get("https://photon.komoot.io/api/", params={"q": query, "limit": 5})
        if resp.status_code != 200:
            return []
        for feat in resp.json().get("features", []):
            props = feat.get("properties", {})
            coords = feat.get("geometry", {}).get("coordinates", [])
            if len(coords) >= 2:
                name = props.get("name") or props.get("street") or query
                city = props.get("city") or props.get("town") or props.get("state") or ""
                out.append({"name": name, "display_name": f"{name}, {city}".strip(", "),
                            "lat": coords[1], "lon": coords[0]})
    except Exception:
        return []
    return out


@app.get("/api/geocode")
async def geocode_location(q: str):
    """
    Geocodes a search string: OSM-derived trailhead parking first, then the Photon
    (OpenStreetMap) geocoder. Returns no results rather than guessed coordinates.
    """
    query = (q or "").strip()
    if not query:
        return {"results": []}

    results = []
    q_lower = query.lower()

    # 1. OSM-derived trailhead parking
    for item in load_trailheads():
        if q_lower in item["area"].lower() or q_lower in item["name"].lower():
            results.append({
                "name": item["name"],
                "display_name": f"{item['name']} ({item['town']}, NH)",
                "lat": item["lat"],
                "lon": item["lon"]
            })

    # 2. Photon (OpenStreetMap geocoder) for everything else
    for r in await photon_search(query):
        if not any(abs(x["lat"] - r["lat"]) < 0.001 and abs(x["lon"] - r["lon"]) < 0.001 for x in results):
            results.append(r)

    return {"results": results[:8]}

# --- Stage 4: Activity Ingestion, Heat & Privacy Endpoints ---

@app.post("/api/activities/upload", response_model=ActivityUploadResponse)
async def upload_activity(
    file: UploadFile = File(...),
    sport: Optional[str] = Form(None),
    consent_given: bool = Form(True),
    retain_file: bool = Form(False),
    user: AuthUser = Depends(get_current_user)
):
    """
    Defensively parses uploaded GPX or FIT activity traces.
    Applies endpoint trimming (first/last 0.2 mi) and privacy zone exclusions.
    Deletes raw file unless explicit user retention is requested.
    Map-matches GPS trackpoints to OSM/GraphHopper edges.
    """
    uid = user.uid
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

    # Duration only from the file's own timestamps; unknown otherwise.
    duration_min = None
    if act_time and raw_pts[-1].time and raw_pts[-1].time > act_time:
        duration_min = round((raw_pts[-1].time - act_time).total_seconds() / 60.0, 1)

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

    # Record activity in db
    # Retention rule: raw file deleted after processing unless retain_file requested
    record_activity({
        "id": act_id,
        "user_id": uid,
        "sport": chosen_sport,
        "activity_date": act_time,
        "distance_miles": raw_dist_mi,
        "duration_minutes": duration_min,
        "file_format": "fit" if (file.filename or "").lower().endswith(".fit") else "gpx",
        "raw_file_retained": retain_file,
        "raw_file_path": None,  # Deleted per privacy rules unless retain_file requested
        "consent_given": consent_given,
        "matched_edge_count": matched_edges_count
    })

    # Record edge visits if consent is granted
    if consent_given and matched_edges_count > 0:
        record_activity_edge_visits(
            activity_id=act_id,
            edge_counts=edge_counts,
            user_id=uid,
            sport=chosen_sport,
            visited_at=act_time
        )

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
    user: Optional[AuthUser] = Depends(get_optional_user)
):
    uid = user.uid if user else None
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
    admin: AuthUser = Depends(get_admin_user)
):
    uid = admin.uid
    ok = record_edge_heat(record.edge_osm_id, record.sport.value, record.weighted_score, user_id=uid)
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to record heat to database")
    return {"status": "recorded", "edge_osm_id": record.edge_osm_id, "sport": record.sport}

@app.get("/api/heat/trails")
async def get_heat_trails(sport: Optional[str] = None):
    """
    Returns GeoJSON FeatureCollection of traversed / heat trails for rendering on map heatmap layers.
    """
    return get_heat_trail_geojson(sport=sport)

# --- OpenTrailMap (OTM) Integration Endpoints ---
from app.otm import fetch_otm_trails_by_bbox, get_otm_trail_details

@app.get("/api/otm/trails")
async def get_otm_trails(
    min_lat: float = Query(..., description="South bounding latitude"),
    min_lon: float = Query(..., description="West bounding longitude"),
    max_lat: float = Query(..., description="North bounding latitude"),
    max_lon: float = Query(..., description="East bounding longitude"),
    sport: Optional[str] = Query("mtb", description="Sport preference"),
    limit: int = Query(150, description="Max trail segments")
):
    """
    Returns OpenTrailMap (OTM) GeoJSON FeatureCollection of designated trails, difficulties, and surfaces.
    """
    return await fetch_otm_trails_by_bbox(
        min_lat=min_lat,
        min_lon=min_lon,
        max_lat=max_lat,
        max_lon=max_lon,
        sport=sport,
        limit=limit
    )

@app.get("/api/otm/trail/{osm_way_id}")
async def get_otm_trail(osm_way_id: int):
    """
    Returns OSM metadata for a specific trail way from the local import.
    """
    details = get_otm_trail_details(osm_way_id)
    if details is None:
        raise HTTPException(status_code=404, detail="Trail not in the local OSM import")
    return details

# --- Privacy Zones & Consent Management ---

@app.get("/api/privacy/zones", response_model=List[PrivacyZoneResponse])
async def list_privacy_zones(
    user: AuthUser = Depends(get_current_user)
):
    uid = user.uid
    return get_privacy_zones(uid)

@app.post("/api/privacy/zones", response_model=PrivacyZoneResponse)
async def add_privacy_zone(
    zone: PrivacyZoneCreate,
    user: AuthUser = Depends(get_current_user)
):
    uid = user.uid
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
    user: AuthUser = Depends(get_current_user)
):
    uid = user.uid
    ok = delete_privacy_zone(zone_id, uid)
    if not ok:
        raise HTTPException(status_code=404, detail="Privacy zone not found or deletion failed")
    return {"status": "deleted", "id": zone_id}

@app.get("/api/privacy/consent")
async def check_consent(
    user: AuthUser = Depends(get_current_user)
):
    uid = user.uid
    return {"user_id": uid, "consent_given": get_user_consent(uid)}

@app.post("/api/privacy/consent")
async def update_consent(
    consent_given: bool = True,
    user: AuthUser = Depends(get_current_user)
):
    uid = user.uid
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
async def trigger_heat_recalculation(
    admin: AuthUser = Depends(get_admin_user)
):
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

# =========================================================================
# Stage 5: Trust Layer Endpoints (Flags, Check-ins, DNR, Restrictions, Export)
# =========================================================================

# --- Community Trail Flags ---

@app.post("/api/flags", response_model=FlagResponse)
async def report_trail_flag(
    flag: FlagCreate,
    user: AuthUser = Depends(get_current_user)
):
    """Submits a community flag for a trail edge (gone, blocked, closed, seasonal)."""
    uid = user.uid
    created = create_community_flag(
        edge_osm_id=flag.edge_osm_id,
        flag_type=flag.flag_type.value,
        user_id=uid,
        details=flag.details
    )
    return FlagResponse(**created)

@app.get("/api/flags", response_model=List[FlagResponse])
async def list_flags(
    edge_osm_id: Optional[int] = None,
    status: Optional[str] = "active",
    limit: int = 100
):
    """Lists community trail flags with optional edge_osm_id and status filters."""
    flags = get_community_flags(edge_osm_id=edge_osm_id, status=status, limit=limit)
    return [FlagResponse(**f) for f in flags]

@app.post("/api/flags/{flag_id}/vote", response_model=FlagVoteResponse)
async def vote_flag(
    flag_id: int,
    vote: FlagVoteCreate,
    user: AuthUser = Depends(get_current_user)
):
    """Registers an abuse-resistant vote (confirm or dispute) on a community flag."""
    uid = user.uid
    try:
        updated = vote_community_flag(flag_id=flag_id, user_id=uid, vote_type=vote.vote_type)
        return FlagVoteResponse(
            flag_id=flag_id,
            user_id=uid,
            vote_type=vote.vote_type,
            confirmed_count=updated["confirmed_count"],
            disputed_count=updated["disputed_count"],
            status=updated["status"]
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

# --- Rider Trail Check-ins ("still open") ---

@app.post("/api/trails/{edge_osm_id}/checkin", response_model=TrailCheckinResponse)
async def submit_trail_checkin(
    edge_osm_id: int,
    checkin: TrailCheckinCreate,
    user: AuthUser = Depends(get_current_user)
):
    """
    One-tap rider check-in ("still open") verifying active trail status.
    Refreshes trail confidence and recency date.
    """
    uid = user.uid
    res = record_trail_checkin(
        edge_osm_id=edge_osm_id,
        user_id=uid,
        status=checkin.status,
        note=checkin.note
    )
    return TrailCheckinResponse(
        id=res["id"],
        edge_osm_id=res["edge_osm_id"],
        user_id=res["user_id"],
        status=res["status"],
        note=res.get("note"),
        checked_in_at=res["checked_in_at"],
        confidence_score=res.get("confidence_score", 1.0)
    )

@app.get("/api/trails/{edge_osm_id}/checkins", response_model=List[TrailCheckinResponse])
async def list_trail_checkins(edge_osm_id: int, limit: int = 20):
    """Returns recent check-in history for an edge."""
    checkins = get_trail_checkins(edge_osm_id=edge_osm_id, limit=limit)
    return [TrailCheckinResponse(confidence_score=1.0, **c) for c in checkins]

@app.get("/api/trails/{edge_osm_id}/status", response_model=TrailStatusResponse)
async def check_trail_status(edge_osm_id: int):
    """Aggregated status of a trail edge including confidence, check-ins, flags, access, and snowmobile info."""
    st = get_trail_status(edge_osm_id)
    return TrailStatusResponse(
        edge_osm_id=st["edge_osm_id"],
        status=st["status"],
        confidence_score=st["confidence_score"],
        check_date=st["check_date"],
        snowmobile=st["snowmobile"],
        access=st.get("access"),
        bicycle=st.get("bicycle"),
        recent_checkins_count=st["recent_checkins_count"],
        active_flags=[FlagResponse(**f) for f in st["active_flags"]]
    )

# --- User DNR (Do Not Ride) System ---

@app.get("/api/user/dnr", response_model=List[UserDNRResponse])
async def list_user_dnr(
    user: AuthUser = Depends(get_current_user)
):
    """Lists user's configured DNR trails and areas."""
    uid = user.uid
    dnrs = get_user_dnr_list(uid)
    return [UserDNRResponse(**d) for d in dnrs]

@app.post("/api/user/dnr", response_model=UserDNRResponse)
async def add_user_dnr(
    dnr: UserDNRCreate,
    user: AuthUser = Depends(get_current_user)
):
    """Adds a trail or area to the user's personal DNR list."""
    uid = user.uid
    created = create_user_dnr(
        user_id=uid,
        name=dnr.name,
        dnr_type=dnr.dnr_type,
        edge_osm_id=dnr.edge_osm_id,
        geom=dnr.geom,
        is_soft=dnr.is_soft,
        reason=dnr.reason
    )
    return UserDNRResponse(**created)

@app.delete("/api/user/dnr/{dnr_id}")
async def remove_user_dnr(
    dnr_id: int,
    user: AuthUser = Depends(get_current_user)
):
    """Removes an item from the user's DNR list."""
    uid = user.uid
    deleted = delete_user_dnr(dnr_id=dnr_id, user_id=uid)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="DNR item not found")
    return {"status": "deleted", "id": dnr_id}

@app.get("/api/user/dnr/overrides", response_model=List[DNROverrideLogItem])
async def list_dnr_override_logs(
    limit: int = 50,
    user: AuthUser = Depends(get_current_user)
):
    """Fetches logged audit records for soft DNR overrides."""
    uid = user.uid
    logs = get_dnr_override_logs(user_id=uid, limit=limit)
    return [DNROverrideLogItem(**l) for l in logs]

# --- Admin Restrictions & Land Manager Takedowns ---

@app.get("/api/admin/restrictions", response_model=List[RestrictionResponse])
async def list_admin_restrictions(
    admin: AuthUser = Depends(get_admin_user)
):
    """Lists all active land restrictions and closures."""
    restrs = get_all_restrictions()
    return [RestrictionResponse(**r) for r in restrs]

@app.post("/api/admin/restrictions", response_model=RestrictionResponse)
async def add_admin_restriction(
    restr: RestrictionCreate,
    admin: AuthUser = Depends(get_admin_user)
):
    """Creates a land restriction (closure, wildlife, private, wilderness, dnr)."""
    created = create_restriction(
        name=restr.name,
        restriction_type=restr.restriction_type,
        source=restr.source or "Admin",
        is_hard=restr.is_hard,
        edge_osm_id=restr.edge_osm_id,
        geom=restr.geom,
        seasonal_start_month=restr.seasonal_start_month,
        seasonal_end_month=restr.seasonal_end_month,
        seasonal_tag=restr.seasonal_tag,
        description=restr.description
    )
    return RestrictionResponse(**created)

@app.put("/api/admin/restrictions/{restriction_id}", response_model=RestrictionResponse)
async def modify_admin_restriction(
    restriction_id: int,
    restr: RestrictionUpdate,
    admin: AuthUser = Depends(get_admin_user)
):
    """Updates an existing restriction."""
    updated = update_restriction(
        restriction_id=restriction_id,
        name=restr.name,
        restriction_type=restr.restriction_type,
        source=restr.source,
        is_hard=restr.is_hard,
        edge_osm_id=restr.edge_osm_id,
        geom=restr.geom,
        seasonal_start_month=restr.seasonal_start_month,
        seasonal_end_month=restr.seasonal_end_month,
        seasonal_tag=restr.seasonal_tag,
        description=restr.description
    )
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Restriction not found")
    return RestrictionResponse(**updated)

@app.delete("/api/admin/restrictions/{restriction_id}")
async def remove_admin_restriction(
    restriction_id: int,
    admin: AuthUser = Depends(get_admin_user)
):
    """Deletes a restriction."""
    ok = delete_restriction(restriction_id)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Restriction not found")
    return {"status": "deleted", "id": restriction_id}

@app.post("/api/admin/takedowns", response_model=RestrictionResponse)
async def execute_land_manager_takedown(
    takedown: TakedownRequest,
    admin: AuthUser = Depends(get_admin_user)
):
    """Fulfills an immediate land manager takedown request per Section 8 & 14."""
    created = create_takedown(
        name=takedown.name,
        edge_osm_id=takedown.edge_osm_id,
        geom=takedown.geom,
        reason=takedown.reason,
        requested_by=takedown.requested_by
    )
    return RestrictionResponse(**created)

# --- Privacy Compliance: Data Export & Account Deletion ---

@app.get("/api/privacy/export", response_model=UserDataExportResponse)
async def export_my_data(
    user: AuthUser = Depends(get_current_user)
):
    """
    Exports all personal data stored for the user in a JSON bundle.
    Guarantees strict privacy: never exposes any other rider's data.
    """
    uid = user.uid
    data = export_user_data(uid)
    return UserDataExportResponse(**data)

@app.delete("/api/privacy/account")
async def delete_my_account(
    user: AuthUser = Depends(get_current_user)
):
    """
    Permanently purges all user account records and personal data.
    Deletes privacy zones, DNR entries, override logs, check-ins, flags,
    activities, saved routes, and contribution consent.
    """
    uid = user.uid
    ok = delete_user_account(uid)
    return {"status": "account_deleted", "user_id": uid}


# =========================================================================
# Stage 6: Differentiators (Find New Trails, Submissions, Connectors)
# =========================================================================

# --- 1. Find New Trails Mode & Exploration ---

@app.get("/api/trails/new-to-me", response_model=List[UnriddenTrailItem])
async def get_unridden_trails(
    lat: float,
    lon: float,
    radius_miles: float = 15.0,
    sport: str = "mtb",
    user: AuthUser = Depends(get_current_user)
):
    """
    Highlights trails with strong recent heat that the user has not yet ridden or run
    (tracked via user's activity history / visits in activity_edge_visits).
    """
    uid = user.uid
    items = get_unridden_high_heat_trails(
        user_id=uid,
        lat=lat,
        lon=lon,
        radius_miles=radius_miles,
        sport=sport
    )
    return [UnriddenTrailItem(**item) for item in items]


# --- 2. Trail Submissions & Auto-Verification ---

@app.post("/api/submissions", response_model=TrailSubmissionResponse)
async def submit_trail(
    submission: TrailSubmissionCreate,
    user: AuthUser = Depends(get_current_user)
):
    """
    Trail submission workflow: users trace or upload trail geometry with name,
    sport, and difficulty rating. Automatically verified if >= 3 unique riders'
    activities overlap the geometry within 12 months and no restricted areas are intersected.
    """
    uid = user.uid
    record = create_trail_submission(
        user_id=uid,
        name=submission.name,
        sport=submission.sport,
        difficulty=submission.difficulty,
        coordinates=submission.coordinates,
        description=submission.description
    )
    if not record:
        raise HTTPException(status_code=500, detail="Failed to create trail submission.")
    return TrailSubmissionResponse(**record)

@app.get("/api/submissions", response_model=List[TrailSubmissionResponse])
async def list_submissions(
    status: Optional[str] = None
):
    """Lists trail submissions (filtered by status: pending, verified, rejected, taken_down, or all)."""
    records = get_trail_submissions(status_filter=status)
    return [TrailSubmissionResponse(**r) for r in records]

@app.get("/api/submissions/{submission_id}", response_model=TrailSubmissionResponse)
async def get_submission(submission_id: int):
    """Retrieves a single trail submission by ID."""
    record = get_trail_submission_by_id(submission_id)
    if not record:
        raise HTTPException(status_code=404, detail="Trail submission not found.")
    return TrailSubmissionResponse(**record)

@app.post("/api/submissions/{submission_id}/evidence", response_model=TrailSubmissionEvidenceResponse)
async def submit_trail_evidence(
    submission_id: int,
    evidence: TrailSubmissionEvidenceCreate,
    user: AuthUser = Depends(get_current_user)
):
    """
    Submits GPS-backed evidence (overlapping ride activity) confirming a trail submission.
    Provides GPS-backed abuse resistance (requiring overlapping ride evidence, not raw votes).
    """
    uid = user.uid
    sub = get_trail_submission_by_id(submission_id)
    if not sub:
        raise HTTPException(status_code=404, detail="Trail submission not found.")

    res = record_submission_evidence(
        submission_id=submission_id,
        user_id=uid,
        activity_id=evidence.activity_id,
        coordinates=evidence.coordinates
    )
    if "error" in res:
        raise HTTPException(status_code=400, detail=res["error"])

    updated = get_trail_submission_by_id(submission_id)
    return TrailSubmissionEvidenceResponse(
        id=submission_id,
        submission_id=submission_id,
        user_id=uid,
        activity_id=evidence.activity_id,
        verified_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        is_overlapping=True,
        new_status=updated.get("status", "pending")
    )

@app.post("/api/submissions/{submission_id}/verify-check")
async def verify_submission_check(
    submission_id: int,
    user: AuthUser = Depends(get_current_user)
):
    """Runs auto-verification check on a submission."""
    res = evaluate_and_verify_submission(submission_id)
    if "error" in res:
        raise HTTPException(status_code=400, detail=res["error"])
    return res

# Admin moderation interface
@app.post("/api/submissions/{submission_id}/approve", response_model=TrailSubmissionResponse)
async def admin_approve_submission(
    submission_id: int,
    body: Optional[TrailSubmissionReviewRequest] = None,
    admin: AuthUser = Depends(get_admin_user)
):
    """Admin moderation endpoint: manually approve a trail submission."""
    ok = admin_update_submission_status(submission_id, "verified")
    if not ok:
        raise HTTPException(status_code=400, detail="Failed to approve submission.")
    sub = get_trail_submission_by_id(submission_id)
    return TrailSubmissionResponse(**sub)

@app.post("/api/submissions/{submission_id}/reject", response_model=TrailSubmissionResponse)
async def admin_reject_submission(
    submission_id: int,
    body: Optional[TrailSubmissionReviewRequest] = None,
    admin: AuthUser = Depends(get_admin_user)
):
    """Admin moderation endpoint: reject a trail submission."""
    reason = body.reason if body else "Rejected by admin"
    ok = admin_update_submission_status(submission_id, "rejected", reason=reason)
    if not ok:
        raise HTTPException(status_code=400, detail="Failed to reject submission.")
    sub = get_trail_submission_by_id(submission_id)
    return TrailSubmissionResponse(**sub)

@app.post("/api/submissions/{submission_id}/reverse", response_model=TrailSubmissionResponse)
async def admin_reverse_submission(
    submission_id: int,
    body: Optional[TrailSubmissionReviewRequest] = None,
    admin: AuthUser = Depends(get_admin_user)
):
    """Admin moderation endpoint: reverse a submission back to pending status."""
    ok = admin_update_submission_status(submission_id, "pending")
    if not ok:
        raise HTTPException(status_code=400, detail="Failed to reverse submission.")
    sub = get_trail_submission_by_id(submission_id)
    return TrailSubmissionResponse(**sub)

@app.post("/api/submissions/{submission_id}/takedown", response_model=TrailSubmissionResponse)
async def admin_takedown_submission(
    submission_id: int,
    body: Optional[TrailSubmissionReviewRequest] = None,
    admin: AuthUser = Depends(get_admin_user)
):
    """Admin moderation endpoint: take down a trail submission."""
    reason = body.reason if body else "Taken down by admin / land manager request"
    ok = admin_update_submission_status(submission_id, "taken_down", reason=reason)
    if not ok:
        raise HTTPException(status_code=400, detail="Failed to take down submission.")
    sub = get_trail_submission_by_id(submission_id)
    return TrailSubmissionResponse(**sub)


# --- 3. Optional Connectors (Interfaces & Feature Flags) ---

@app.get("/api/connectors", response_model=List[ConnectorStatus])
async def get_connectors(
    user: AuthUser = Depends(get_current_user)
):
    """
    Returns available connectors (Strava, Garmin, Trailforks) and connection status.
    All third-party connectors are decoupled, swappable, and off by default.
    """
    uid = user.uid
    statuses = connector_manager.list_connectors(uid)
    return [ConnectorStatus(**s) for s in statuses]

@app.post("/api/connectors/garmin/login")
async def connect_garmin(
    req: GarminLoginRequest,
    user: AuthUser = Depends(get_current_user)
):
    """
    Garmin login connector: exchanges credentials for session tokens.
    INVARIANTS:
    - Never stores passwords anywhere.
    - Password is discarded immediately.
    - Tokens encrypted at rest with AES Fernet.
    - Bulk imports activities to heat if user agrees (import_to_heat=True).
    """
    uid = user.uid
    res = await connector_manager.authenticate(
        "garmin", uid, username=req.username, password=req.password,
        mfa_code=req.mfa_code, mfa_session_id=req.mfa_session_id
    )
    if res.get("needs_mfa"):
        return res
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=res.get("error", "Garmin login failed"))
    
    # Bulk import to heat if user agreed
    sync_res = await connector_manager.sync("garmin", uid, import_to_heat=req.import_to_heat)
    res["bulk_sync"] = sync_res
    res["message"] = f"Connected to Garmin Connect. {sync_res.get('message', '')}"
    return res

@app.post("/api/connectors/garmin/verify-mfa")
async def verify_garmin_mfa(
    req: GarminMfaVerifyRequest,
    user: AuthUser = Depends(get_current_user)
):
    """Submits Garmin 2FA verification code to complete connection."""
    uid = user.uid
    res = await connector_manager.authenticate(
        "garmin", uid, mfa_session_id=req.mfa_session_id, mfa_code=req.mfa_code
    )
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=res.get("error", "Garmin 2FA verification failed"))
    if req.import_to_heat:
        sync_res = await connector_manager.sync("garmin", uid, import_to_heat=True)
        res["bulk_sync"] = sync_res
        res["message"] = f"Connected to Garmin Connect. {sync_res.get('message', '')}"
    return res

@app.post("/api/connectors/garmin/bulk-import", response_model=ConnectorSyncResponse)
async def garmin_bulk_import(
    req: Optional[ConnectorSyncRequest] = None,
    user: AuthUser = Depends(get_current_user)
):
    """Bulk imports all activities from Garmin Connect to heat layer if user agrees."""
    uid = user.uid
    import_heat = req.import_to_heat if req else True
    res = await connector_manager.sync("garmin", uid, import_to_heat=import_heat)
    return ConnectorSyncResponse(**res)

@app.post("/api/connectors/trailforks/auth")
async def connect_trailforks(
    req: TrailforksAuthRequest,
    user: AuthUser = Depends(get_current_user)
):
    """Trailforks connector: authorizes and links trail metadata service (© Trailforks)."""
    uid = user.uid
    res = await connector_manager.authenticate("trailforks", uid, token=req.token, username=req.username)
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=res.get("error", "Trailforks connection failed"))
    return res

@app.post("/api/connectors/strava/auth")
async def connect_strava(
    req: StravaAuthRequest,
    user: AuthUser = Depends(get_current_user)
):
    """
    Strava connector: connects via user personal API token or authorization code.
    No app-wide OAuth client required.
    """
    uid = user.uid
    res = await connector_manager.authenticate(
        "strava", uid, code=req.code, personal_token=req.personal_token, scope=req.scope
    )
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=res.get("error", "Strava authentication failed"))
    return res

@app.post("/api/connectors/cubetrek/auth")
async def connect_cubetrek(
    req: CubeTrekAuthRequest,
    user: AuthUser = Depends(get_current_user)
):
    """CubeTrek connector: links account / profile."""
    uid = user.uid
    res = await connector_manager.authenticate("cubetrek", uid, username=req.username)
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=res.get("error", "CubeTrek connection failed"))
    return res

@app.post("/api/connectors/cubetrek/import")
async def import_cubetrek_activity(
    req: CubeTrekImportRequest,
    user: AuthUser = Depends(get_current_user)
):
    """Imports a 3D GPS track from CubeTrek URL or track ID."""
    uid = user.uid
    connector = connector_manager.get_connector("cubetrek")
    if not connector:
        raise HTTPException(status_code=404, detail="CubeTrek connector not available")
    res = await connector.import_activity(
        user_id=uid,
        url_or_id=req.url_or_id,
        sport=req.sport,
        activity_name=req.name,
        import_to_heat=req.import_to_heat
    )
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=res.get("error", "CubeTrek import failed"))
    return res

@app.post("/api/connectors/{provider}/sync", response_model=ConnectorSyncResponse)
async def sync_connector_activities(
    provider: str,
    req: Optional[ConnectorSyncRequest] = None,
    user: AuthUser = Depends(get_current_user)
):
    """Syncs activities from a connected third-party provider."""
    uid = user.uid
    import_heat = req.import_to_heat if req else True
    res = await connector_manager.sync(provider, uid, import_to_heat=import_heat)
    return ConnectorSyncResponse(**res)

@app.delete("/api/connectors/{provider}")
async def disconnect_connector(
    provider: str,
    user: AuthUser = Depends(get_current_user)
):
    """Disconnects a service and purges stored encrypted tokens."""
    uid = user.uid
    ok = await connector_manager.disconnect(provider, uid)
    return {"success": ok, "provider": provider, "status": "disconnected"}

# --- Developer Console Routes ---

@app.get("/api/dev/status", response_model=DevConsoleStatusResponse)
async def get_developer_status(
    admin: AuthUser = Depends(get_admin_user)
):
    """System health & developer metrics."""

    db_ok = check_db_health()
    uptime = (datetime.datetime.now(datetime.timezone.utc) - APP_START_TIME).total_seconds()

    edge_cnt, act_cnt, heat_cnt, route_cnt = 0, 0, 0, 0
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT count(*) FROM edges;")
                edge_cnt = cur.fetchone()[0]
                cur.execute("SELECT count(*) FROM activities;")
                act_cnt = cur.fetchone()[0]
                cur.execute("SELECT count(*) FROM edge_heat;")
                heat_cnt = cur.fetchone()[0]
                cur.execute("SELECT count(*) FROM saved_routes;")
                route_cnt = cur.fetchone()[0]
    except Exception:
        pass

    connectors = connector_manager.list_connectors(admin.uid)

    return DevConsoleStatusResponse(
        status="healthy" if db_ok else "degraded",
        app_name=settings.app_name,
        app_version=settings.app_version,
        database_connected=db_ok,
        edge_count=edge_cnt,
        activity_count=act_cnt,
        heat_edge_count=heat_cnt,
        saved_route_count=route_cnt,
        connectors=connectors,
        developer_email=admin.email or "",
        uptime_seconds=uptime
    )

@app.post("/api/dev/cache/clear")
async def clear_dev_cache(
    admin: AuthUser = Depends(get_admin_user)
):
    """Developer action: Clears transient route and connector caches."""
    return {"status": "success", "message": "All transient caches cleared."}

@app.post("/api/dev/heat/recalculate")
async def recalculate_dev_heat(
    admin: AuthUser = Depends(get_admin_user)
):
    """Developer action: Triggers recalculation of the trail heat layer."""
    res = recalculate_all_edge_heat()
    return {"status": "success", "updated_edges": res.get("updated_edges", 0), "message": "Heat layer recalculation complete."}


# --- Static Files / Frontend PWA ---
import os
from fastapi.staticfiles import StaticFiles

frontend_dist = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend", "dist")
if os.path.exists(frontend_dist):
    from fastapi.responses import FileResponse

    @app.get("/auth/finish", include_in_schema=False)
    async def auth_finish_page():
        """Landing page for Firebase email sign-in links; the SPA finishes the sign-in."""
        return FileResponse(os.path.join(frontend_dist, "index.html"))

    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=True)
