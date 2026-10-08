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

class SurfaceSegment(BaseModel):
    start_index: int
    end_index: int
    surface_type: str # 'singletrack', 'doubletrack', 'gravel', 'paved', 'unpaved', 'unknown'
    raw_surface: Optional[str] = None
    raw_road_class: Optional[str] = None

class RouteResponse(BaseModel):
    id: Optional[str] = None
    name: Optional[str] = "Loam Route"
    sport: str = "mtb"
    sector: Optional[str] = None
    distance_miles: float
    duration_minutes: float
    elevation_gain_ft: float
    elevation_loss_ft: float
    surface_breakdown: Dict[str, float] # percentage per category e.g. {"singletrack": 65.2, "gravel": 25.0, ...}
    surface_strip: List[SurfaceSegment]
    coordinates: List[List[float]] # [[lon, lat], [lon, lat], ...] GeoJSON style or [[lon, lat, ele]]
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
    verbal_summary: Optional[str] = None

class RouteOptionsRequest(RouteRequest):
    candidate_count: int = Field(default=10, ge=1, le=25)

class RouteOptionsResponse(BaseModel):
    options: List[RouteResponse]
    count: int
    requested_target_miles: Optional[float] = None
    start_name: Optional[str] = None

class EdgeHeatRecord(BaseModel):
    edge_osm_id: int
    sport: SportProfile
    unique_riders: int = 1
    weighted_score: float = 1.0

class SavedRouteCreate(BaseModel):
    name: str
    sport: str = "mtb"
    distance_miles: float
    elevation_gain_ft: float = 0.0
    elevation_loss_ft: float = 0.0
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
    elevation_gain_ft: float
    elevation_loss_ft: float
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
    elevation_gain_ft: float = 0.0
    elevation_loss_ft: float = 0.0
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
    duration_minutes: float
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
    exported_at: str



