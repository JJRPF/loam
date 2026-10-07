from typing import List, Optional, Dict, Any
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
