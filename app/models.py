from typing import List, Optional, Dict, Any
from enum import Enum
from pydantic import BaseModel, Field

class SportProfile(str, Enum):
    MTB = "mtb"
    BIKE = "bike"
    FOOT = "foot"

class LatLon(BaseModel):
    lat: float = Field(..., ge=-90.0, le=90.0, description="Latitude")
    lon: float = Field(..., ge=-180.0, le=180.0, description="Longitude")

class TerrainPreference(BaseModel):
    singletrack: float = Field(default=0.6, ge=0.0, le=1.0)
    doubletrack: float = Field(default=0.2, ge=0.0, le=1.0)
    gravel: float = Field(default=0.15, ge=0.0, le=1.0)
    paved: float = Field(default=0.05, ge=0.0, le=1.0)

class RouteRequest(BaseModel):
    start: LatLon
    end: LatLon
    waypoints: Optional[List[LatLon]] = Field(default_factory=list)
    profile: SportProfile = SportProfile.MTB
    terrain_preference: Optional[TerrainPreference] = None
    avoid_closed: bool = True
    elevation_enriched: bool = True

class SurfaceSegment(BaseModel):
    start_index: int
    end_index: int
    surface_type: str # 'singletrack', 'doubletrack', 'gravel', 'paved', 'unpaved', 'unknown'
    raw_surface: Optional[str] = None
    raw_road_class: Optional[str] = None

class RouteResponse(BaseModel):
    distance_miles: float
    duration_minutes: float
    elevation_gain_ft: float
    elevation_loss_ft: float
    surface_breakdown: Dict[str, float] # percentage per category e.g. {"singletrack": 65.2, "gravel": 25.0, ...}
    surface_strip: List[SurfaceSegment]
    coordinates: List[List[float]] # [[lon, lat], [lon, lat], ...] GeoJSON style or [[lon, lat, ele]]
    bbox: List[float] # [min_lon, min_lat, max_lon, max_lat]
    warnings: List[str] = Field(default_factory=list)
    heat_score: Optional[float] = None

class EdgeHeatRecord(BaseModel):
    edge_osm_id: int
    sport: SportProfile
    unique_riders: int = 1
    weighted_score: float = 1.0

class HealthResponse(BaseModel):
    status: str
    version: str
    graphhopper: bool
    postgis: bool
    elevation_provider: str
