import datetime
from typing import List, Optional, Dict, Any, Union
from enum import Enum
from pydantic import BaseModel, Field

class SportProfile(str, Enum):
    MTB = "mtb"
    MTB_HARDTAIL = "mtb_hardtail"
    MTB_FULLSUS = "mtb_fullsus"
    MTB_GRAVEL = "mtb_gravel"
    MTB_FAT = "mtb_fat"
    MTB_EMTB = "mtb_emtb"
    TRAIL_RUN = "trail_run"
    BIKE = "bike"
    FOOT = "foot"

class LatLon(BaseModel):
    lat: float = Field(..., ge=-90.0, le=90.0, description="Latitude")
    lon: float = Field(..., ge=-180.0, le=180.0, description="Longitude")
    name: Optional[str] = None

class TerrainPreference(BaseModel):
    singletrack: float = Field(default=0.6, ge=0.0, le=1.0)
    doubletrack: float = Field(default=0.2, ge=0.0, le=1.0)
    gravel: float = Field(default=0.15, ge=0.0, le=1.0)
    paved: float = Field(default=0.05, ge=0.0, le=1.0)

class RouteRequest(BaseModel):
    start: LatLon
    end: Optional[LatLon] = None
    waypoints: Optional[List[LatLon]] = Field(default_factory=list)
    profile: SportProfile = SportProfile.MTB
    terrain_preference: Optional[TerrainPreference] = None
    route_mode: str = "point_to_point" # "point_to_point", "loop", "round_trip"
    is_loop: bool = False
    target_distance_miles: Optional[float] = None
    name: Optional[str] = None
    avoid_closed: bool = True
    elevation_enriched: bool = True
    override_dnr: bool = False
    find_new_trails_mode: bool = False
    min_new_trail_percent: Optional[float] = Field(default=None, ge=0.0, le=100.0)
    min_new_trail_miles: Optional[float] = Field(default=None, ge=0.0)
    trail_run_steeper_grades: bool = False
    trail_run_avoid_mtb_flow: bool = True
    loops_only: bool = False

class SurfaceSegment(BaseModel):
    start_index: int
    end_index: int
    surface_type: str # 'singletrack', 'doubletrack', 'gravel', 'paved', 'unpaved', 'unknown'
    raw_surface: Optional[str] = None
    raw_road_class: Optional[str] = None
    is_unridden: bool = False

class RouteResponse(BaseModel):
    id: Optional[str] = None
    name: Optional[str] = "Loam Route"
    sport: str = "mtb"
    sector: Optional[str] = None
    distance_miles: float
    duration_minutes: float
    # None when no DEM sample is available ("Elevation unavailable"); never estimated.
    elevation_gain_ft: Optional[float] = None
    elevation_loss_ft: Optional[float] = None
    surface_breakdown: Dict[str, float] # percentage per category e.g. {"singletrack": 65.2, "gravel": 25.0, ...}
    surface_strip: List[SurfaceSegment]
    coordinates: List[List[float]] # [[lon, lat], ...] GeoJSON style or [[lon, lat, ele]]
    bbox: List[float] # [min_lon, min_lat, max_lon, max_lat]
    minimap_bounds: Optional[List[float]] = None
    minimap_svg: Optional[str] = None
    warnings: List[str] = Field(default_factory=list)
    dnr_warnings: List[str] = Field(default_factory=list)
    snowmobile_warnings: List[str] = Field(default_factory=list)
    community_flag_warnings: List[str] = Field(default_factory=list)
    hard_block_waived: bool = False
    heat_score: Optional[float] = None
    match_score: Optional[int] = 95
    score_breakdown: Optional[Dict[str, float]] = None
    repetition_ratio: Optional[float] = None
    retraced_miles: float = 0.0
    retraced_coordinates: List[List[List[float]]] = Field(default_factory=list)
    nearby_start_suggestion: Optional[str] = None
    verbal_summary: Optional[str] = None
    route_type: Optional[str] = "loop" # 'loop', 'lollipop', 'out_and_back', 'point_to_point'
    primary_trail_name: Optional[str] = None
    # Stage 6: Find New Trails stats
    is_find_new_trails: bool = False
    unridden_miles: float = 0.0
    unridden_percent: float = 0.0
    unridden_segments_count: int = 0


class RouteOptionsRequest(RouteRequest):
    candidate_count: int = Field(default=10, ge=1, le=25)

class RouteOptionsResponse(BaseModel):
    options: List[RouteResponse]
    count: int
    requested_target_miles: Optional[float] = None
    start_name: Optional[str] = None
    loops_only: bool = False
    no_true_loop_near_here: bool = False
    nearby_start_suggestion: Optional[str] = None

class EdgeHeatRecord(BaseModel):
    edge_osm_id: int
    sport: SportProfile
    unique_riders: int = 1
    weighted_score: float = 1.0

class SavedRouteCreate(BaseModel):
    name: str
    sport: str = "mtb"
    distance_miles: float
    elevation_gain_ft: Optional[float] = None
    elevation_loss_ft: Optional[float] = None
    coordinates: List[List[float]]
    surface_breakdown: Dict[str, float] = Field(default_factory=dict)
    surface_strip: List[SurfaceSegment] = Field(default_factory=list)
    waypoints: Optional[List[Dict[str, Any]]] = None
    verbal_summary: Optional[str] = None

class SavedRouteItem(BaseModel):
    id: str
    user_id: str
    name: str
    sport: str
    distance_miles: float
    elevation_gain_ft: Optional[float] = None
    elevation_loss_ft: Optional[float] = None
    created_at: str
    surface_breakdown: Optional[Dict[str, float]] = None
    surface_strip: Optional[List[SurfaceSegment]] = None
    coordinates: Optional[List[List[float]]] = None
    waypoints: Optional[List[Dict[str, Any]]] = None
    verbal_summary: Optional[str] = None

class ExportRequest(BaseModel):
    name: Optional[str] = "Loam Route"
    sport: Optional[str] = "mtb"
    distance_miles: float
    duration_minutes: float = 60.0
    elevation_gain_ft: Optional[float] = None
    elevation_loss_ft: Optional[float] = None
    coordinates: List[List[float]]
    waypoints: Optional[List[Dict[str, Any]]] = None

class HealthResponse(BaseModel):
    status: str
    version: str
    graphhopper: bool
    postgis: bool
    elevation_provider: str

class ActivityUploadResponse(BaseModel):
    activity_id: str
    user_id: str
    sport: str
    distance_miles: float
    duration_minutes: Optional[float] = None
    raw_points_count: int
    trimmed_points_count: int
    matched_edges_count: int
    consent_given: bool
    raw_file_retained: bool
    message: Optional[str] = None

class PrivacyZoneCreate(BaseModel):
    name: Optional[str] = "Home/Work"
    lat: float = Field(..., ge=-90.0, le=90.0)
    lon: float = Field(..., ge=-180.0, le=180.0)
    radius_m: float = Field(default=320.0, ge=50.0, le=5000.0)

class PrivacyZoneResponse(BaseModel):
    id: int
    user_id: str
    name: str
    lat: float
    lon: float
    radius_m: float
    created_at: str

class RegionalCoverageResponse(BaseModel):
    cell_id: str
    min_lat: float
    min_lon: float
    max_lat: float
    max_lon: float
    activity_count_12mo: int
    is_sufficient: bool
    threshold: int = 3

class RecalculateHeatResponse(BaseModel):
    status: str
    edges_updated: int
    public_edges_count: int
    private_edges_count: int
    coverage_cells_updated: int
    ghost_trails_detected: int
    duration_seconds: float

class EdgeHeatDetailResponse(BaseModel):
    edge_osm_id: int
    sport: str
    unique_riders_12mo: int
    total_passes_12mo: int
    weighted_score: float
    is_public: bool
    last_ridden_date: Optional[Union[str, datetime.date]] = None
    is_contributor: bool = False
    coverage_sufficient: bool = False
    message: Optional[str] = None

# =========================================================================
# Stage 5: Trust Layer Models (Flags, Check-ins, DNR, Restrictions, Export)
# =========================================================================

class FlagType(str, Enum):
    GONE = "gone"
    BLOCKED = "blocked"
    CLOSED = "closed"
    SEASONAL = "seasonal"

class FlagCreate(BaseModel):
    edge_osm_id: int
    flag_type: FlagType
    details: Optional[str] = None

class FlagResponse(BaseModel):
    id: int
    edge_osm_id: int
    flag_type: str
    user_id: Optional[str] = None
    confirmed_count: int = 1
    disputed_count: int = 0
    status: str = "active"
    details: Optional[str] = None
    created_at: str

class FlagVoteCreate(BaseModel):
    vote_type: str = Field(..., pattern="^(confirm|dispute)$")

class FlagVoteResponse(BaseModel):
    flag_id: int
    user_id: str
    vote_type: str
    confirmed_count: int
    disputed_count: int
    status: str

class TrailCheckinCreate(BaseModel):
    status: str = "open"
    note: Optional[str] = None

class TrailCheckinResponse(BaseModel):
    id: int
    edge_osm_id: int
    user_id: str
    status: str
    note: Optional[str] = None
    checked_in_at: str
    confidence_score: float = 1.0

class TrailStatusResponse(BaseModel):
    edge_osm_id: int
    status: str # "open", "caution", "closed", "gone", "blocked"
    confidence_score: float
    check_date: Optional[str] = None
    snowmobile: bool = False
    access: Optional[str] = None
    bicycle: Optional[str] = None
    recent_checkins_count: int = 0
    active_flags: List[FlagResponse] = Field(default_factory=list)

class UserDNRCreate(BaseModel):
    name: str
    dnr_type: str = Field(..., pattern="^(trail|area)$")
    edge_osm_id: Optional[int] = None
    geom: Optional[Dict[str, Any]] = None # GeoJSON Polygon or Geometry
    is_soft: bool = True
    reason: Optional[str] = None

class UserDNRResponse(BaseModel):
    id: int
    user_id: str
    name: str
    dnr_type: str
    edge_osm_id: Optional[int] = None
    geom: Optional[Dict[str, Any]] = None
    is_soft: bool = True
    reason: Optional[str] = None
    created_at: str

class DNROverrideLogItem(BaseModel):
    id: int
    user_id: str
    route_id: Optional[str] = None
    dnr_id: Optional[int] = None
    edge_osm_id: Optional[int] = None
    reason: Optional[str] = None
    logged_at: str

class RestrictionCreate(BaseModel):
    name: str
    restriction_type: str = Field(..., description="closure, sensitive_wildlife, private, wilderness, takedown, dnr")
    source: Optional[str] = "Admin"
    is_hard: bool = True
    edge_osm_id: Optional[int] = None
    geom: Optional[Dict[str, Any]] = None
    seasonal_start_month: Optional[int] = Field(default=None, ge=1, le=12)
    seasonal_end_month: Optional[int] = Field(default=None, ge=1, le=12)
    seasonal_tag: Optional[str] = None
    description: Optional[str] = None

class RestrictionUpdate(BaseModel):
    name: Optional[str] = None
    restriction_type: Optional[str] = None
    source: Optional[str] = None
    is_hard: Optional[bool] = None
    edge_osm_id: Optional[int] = None
    geom: Optional[Dict[str, Any]] = None
    seasonal_start_month: Optional[int] = None
    seasonal_end_month: Optional[int] = None
    seasonal_tag: Optional[str] = None
    description: Optional[str] = None

class RestrictionResponse(BaseModel):
    id: int
    name: str
    restriction_type: str
    source: Optional[str] = None
    is_hard: bool = True
    edge_osm_id: Optional[int] = None
    geom: Optional[Dict[str, Any]] = None
    seasonal_start_month: Optional[int] = None
    seasonal_end_month: Optional[int] = None
    seasonal_tag: Optional[str] = None
    description: Optional[str] = None
    created_at: str

class TakedownRequest(BaseModel):
    name: str
    edge_osm_id: Optional[int] = None
    geom: Optional[Dict[str, Any]] = None
    reason: str
    requested_by: str

class UserDataExportResponse(BaseModel):
    user_id: str
    email: Optional[str] = None
    display_name: Optional[str] = None
    consent: Dict[str, Any]
    privacy_zones: List[Dict[str, Any]]
    dnr_items: List[Dict[str, Any]]
    checkins: List[Dict[str, Any]]
    flags: List[Dict[str, Any]]
    activities: List[Dict[str, Any]]
    saved_routes: List[Dict[str, Any]]
    heat_trail_contributions: Optional[List[Dict[str, Any]]] = None
    exported_at: str

# =========================================================================
# Stage 6: Differentiators (Find New Trails, Submissions, Connectors)
# =========================================================================

class TrailSubmissionCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=120)
    sport: str = Field(default="mtb", description="mtb, trail_run, gravel, foot")
    difficulty: str = Field(default="intermediate", description="beginner, intermediate, advanced, expert")
    coordinates: List[List[float]] = Field(..., min_length=2, description="List of [lon, lat] coordinates")
    description: Optional[str] = None

class TrailSubmissionResponse(BaseModel):
    id: int
    user_id: Optional[str] = None
    name: str
    sport: str
    difficulty: str
    status: str # 'pending', 'verified', 'rejected', 'taken_down'
    verifier_count: int = 0
    coordinates: List[List[float]]
    length_miles: float = 0.0
    description: Optional[str] = None
    rejection_reason: Optional[str] = None
    created_at: str
    verified_at: Optional[str] = None

class TrailSubmissionEvidenceCreate(BaseModel):
    activity_id: Optional[str] = None
    coordinates: Optional[List[List[float]]] = None

class TrailSubmissionEvidenceResponse(BaseModel):
    id: int
    submission_id: int
    user_id: str
    activity_id: Optional[str] = None
    verified_at: str
    is_overlapping: bool = True
    new_status: str

class TrailSubmissionReviewRequest(BaseModel):
    action: str = Field(..., pattern="^(approve|reject|reverse|takedown)$")
    reason: Optional[str] = None

class UnriddenTrailItem(BaseModel):
    edge_osm_id: int
    name: Optional[str] = None
    sport: str
    distance_miles: float
    heat_score: float
    coordinates: List[List[float]]
    surface: Optional[str] = None

class ConnectorStatus(BaseModel):
    name: str # 'strava', 'garmin', 'trailforks'
    display_name: str
    enabled: bool
    connected: bool
    last_synced_at: Optional[str] = None
    activity_count: int = 0
    description: str

class GarminLoginRequest(BaseModel):
    username: str
    password: str
    import_to_heat: bool = True
    mfa_code: Optional[str] = None
    mfa_session_id: Optional[str] = None

class GarminMfaVerifyRequest(BaseModel):
    mfa_session_id: str
    mfa_code: str
    import_to_heat: bool = True

class StravaAuthRequest(BaseModel):
    code: Optional[str] = None
    personal_token: Optional[str] = None
    scope: Optional[str] = None

class TrailforksAuthRequest(BaseModel):
    token: Optional[str] = None
    username: Optional[str] = None

class ConnectorSyncRequest(BaseModel):
    import_to_heat: bool = True

class ConnectorSyncResponse(BaseModel):
    connector: str
    status: str # 'success', 'disabled', 'failed'
    activities_imported: int = 0
    heat_edges_updated: int = 0
    bulk_heat_imported: bool = False
    message: Optional[str] = None

class DevConsoleStatusResponse(BaseModel):
    status: str
    app_name: str
    app_version: str
    database_connected: bool
    edge_count: int = 0
    activity_count: int = 0
    heat_edge_count: int = 0
    saved_route_count: int = 0
    connectors: List[Dict[str, Any]] = []
    developer_email: str
    uptime_seconds: float = 0.0

class CubeTrekAuthRequest(BaseModel):
    username: Optional[str] = None

class CubeTrekImportRequest(BaseModel):
    url_or_id: str
    sport: str = "mtb"
    name: Optional[str] = None
    import_to_heat: bool = True
