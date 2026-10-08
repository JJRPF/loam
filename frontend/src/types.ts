export type SportProfile = 
  | 'mtb'
  | 'mtb_hardtail'
  | 'mtb_fullsus'
  | 'mtb_gravel'
  | 'mtb_fat'
  | 'mtb_emtb'
  | 'trail_run'
  | 'bike'
  | 'foot';

export interface LatLon {
  lat: float;
  lon: float;
  name?: string;
}

export type float = number;

export interface TerrainPreference {
  singletrack: number; // 0.0 - 1.0
  doubletrack: number;
  gravel: number;
  paved: number;
}

export interface SurfaceSegment {
  start_index: number;
  end_index: number;
  surface_type: 'singletrack' | 'doubletrack' | 'gravel' | 'paved' | 'unpaved' | 'unknown';
  raw_surface?: string;
  raw_road_class?: string;
  is_unridden?: boolean;
}

export interface ScoreBreakdown {
  composite: number;
  input_match: number;
  heat: number;
  mode_value: number;
  quality: number;
  penalties: number;
  repetition_ratio: number;
  unridden_miles?: number;
  unridden_percent?: number;
}

export interface RouteResponse {
  id?: string;
  name?: string;
  sport: string;
  sector?: string;
  distance_miles: number;
  duration_minutes: number;
  elevation_gain_ft: number;
  elevation_loss_ft: number;
  surface_breakdown: Record<string, number>; // percentages e.g. { singletrack: 65.2, ... }
  surface_strip: SurfaceSegment[];
  coordinates: number[][]; // [[lon, lat], ...] or [[lon, lat, ele], ...]
  bbox: number[];
  minimap_bounds?: number[];
  minimap_svg?: string;
  warnings: string[];
  dnr_warnings?: string[];
  snowmobile_warnings?: string[];
  community_flag_warnings?: string[];
  hard_block_waived?: boolean;
  heat_score?: number | null;
  match_score?: number;
  score_breakdown?: ScoreBreakdown;
  repetition_ratio?: number;
  verbal_summary?: string;
  is_find_new_trails?: boolean;
  unridden_miles?: number;
  unridden_percent?: number;
  unridden_segments_count?: number;
}

export interface TrailSubmission {
  id: number;
  user_id?: string;
  name: string;
  sport: string;
  difficulty: string;
  status: 'pending' | 'verified' | 'rejected' | 'taken_down';
  verifier_count: number;
  coordinates: number[][];
  length_miles: number;
  description?: string;
  rejection_reason?: string;
  created_at: string;
  verified_at?: string;
}

export interface UnriddenTrailItem {
  edge_osm_id: number;
  name?: string;
  sport: string;
  distance_miles: number;
  heat_score: number;
  coordinates: number[][];
  surface?: string;
}

export interface ConnectorStatus {
  name: string;
  display_name: string;
  enabled: boolean;
  connected: boolean;
  last_synced_at?: string;
  activity_count: number;
  description: string;
}


export interface CommunityFlag {
  id: number;
  edge_osm_id: number;
  flag_type: 'gone' | 'blocked' | 'closed' | 'seasonal';
  user_id?: string;
  confirmed_count: number;
  disputed_count: number;
  status: string;
  details?: string;
  created_at: string;
}

export interface TrailCheckin {
  id: number;
  edge_osm_id: number;
  user_id: string;
  status: string;
  note?: string;
  checked_in_at: string;
  confidence_score: number;
}

export interface UserDNR {
  id: number;
  user_id: string;
  name: string;
  dnr_type: 'trail' | 'area';
  edge_osm_id?: number;
  geom?: any;
  is_soft: boolean;
  reason?: string;
  created_at: string;
}

export interface UserDataExport {
  user_id: string;
  email?: string;
  display_name?: string;
  consent: { consent_given: boolean; consented_at?: string };
  privacy_zones: any[];
  dnr_items: UserDNR[];
  checkins: TrailCheckin[];
  flags: CommunityFlag[];
  activities: any[];
  saved_routes: any[];
  exported_at: string;
}

export interface RouteOptionsResponse {
  options: RouteResponse[];
  count: number;
  requested_target_miles?: number;
  start_name?: string;
}

export interface SavedRoute {
  id: string;
  user_id: string;
  name: string;
  sport: string;
  distance_miles: number;
  elevation_gain_ft: number;
  elevation_loss_ft: number;
  created_at: string;
  surface_breakdown?: Record<string, number>;
  surface_strip?: SurfaceSegment[];
  coordinates?: number[][];
  waypoints?: any[];
  verbal_summary?: string;
}

export interface TrailheadPreset {
  name: string;
  region: string;
  lat: number;
  lon: number;
  description: string;
}

export const NH_TRAILHEAD_PRESETS: TrailheadPreset[] = [
  {
    name: "Bear Brook State Park (Podunk Rd)",
    region: "Allenstown, NH",
    lat: 43.1305,
    lon: -71.3524,
    description: "Hub of 40+ miles of prime singletrack, Little Bear, Bobcat, and Hedgehog."
  },
  {
    name: "Highland Mountain Bike Park",
    region: "Northfield, NH",
    lat: 43.4357,
    lon: -71.6111,
    description: "World-class dedicated downhill and cross-country mountain bike network."
  },
  {
    name: "Fort Mountain Trailhead",
    region: "Epsom, NH",
    lat: 43.2091,
    lon: -71.3289,
    description: "Rugged granite outcrops, doubletrack connectors, and scenic fire tower ridge."
  },
  {
    name: "Oak Hill Trailhead",
    region: "Concord, NH",
    lat: 43.2562,
    lon: -71.5031,
    description: "Flowy, undulating forest singletrack loops with scenic tower overlook."
  },
  {
    name: "Franklin Falls Dam",
    region: "Franklin, NH",
    lat: 43.4721,
    lon: -71.6508,
    description: "Fast, swoopy bermed singletrack along the Pemigewasset river basin."
  },
  {
    name: "Stratham Hill Park",
    region: "Stratham, NH",
    lat: 43.0185,
    lon: -70.9254,
    description: "Seacoast favorite with technical rock gardens and fast connector trails."
  }
];

export interface AuthUser {
  id: string;
  email: string;
  displayName: string;
  photoURL?: string;
  idToken?: string;
}

export interface GeocodeResult {
  name: string;
  display_name: string;
  lat: number;
  lon: number;
}

export interface TerrainPreset {
  name: string;
  description: string;
  weights: TerrainPreference;
}

export const TERRAIN_PRESETS: TerrainPreset[] = [
  {
    name: "Mostly Trail",
    description: "70% Singletrack, 15% Doubletrack, 10% Gravel, 5% Paved",
    weights: { singletrack: 0.70, doubletrack: 0.15, gravel: 0.10, paved: 0.05 }
  },
  {
    name: "Gravel Grind",
    description: "65% Gravel, 15% Doubletrack, 15% Paved, 5% Singletrack",
    weights: { singletrack: 0.05, doubletrack: 0.15, gravel: 0.65, paved: 0.15 }
  },
  {
    name: "Mixed Exploration",
    description: "35% Singletrack, 25% Doubletrack, 25% Gravel, 15% Paved",
    weights: { singletrack: 0.35, doubletrack: 0.25, gravel: 0.25, paved: 0.15 }
  },
  {
    name: "Road Transit",
    description: "Smooth connector routes with 70% Paved, 20% Gravel, 10% Doubletrack",
    weights: { singletrack: 0.00, doubletrack: 0.10, gravel: 0.20, paved: 0.70 }
  }
];


