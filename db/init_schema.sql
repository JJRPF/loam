-- Loam PostGIS Database Schema
-- Defines core tables per Project Plan Section 4

CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Core OSM Edges
CREATE TABLE IF NOT EXISTS edges (
    osm_id BIGINT PRIMARY KEY,
    name TEXT,
    highway TEXT,
    surface TEXT,
    tracktype TEXT,
    mtb_scale INT,
    mtb_scale_uphill INT,
    sac_scale TEXT,
    bicycle TEXT,
    foot TEXT,
    snowmobile BOOLEAN DEFAULT FALSE,
    geom GEOMETRY(LineString, 4326),
    length_m DOUBLE PRECISION,
    last_osm_edit DATE,
    check_date DATE
);

CREATE INDEX IF NOT EXISTS idx_edges_geom ON edges USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_edges_highway ON edges (highway);
CREATE INDEX IF NOT EXISTS idx_edges_surface ON edges (surface);

-- Edge Heat Layer (recency weighted heat per sport)
CREATE TABLE IF NOT EXISTS edge_heat (
    edge_osm_id BIGINT REFERENCES edges(osm_id) ON DELETE CASCADE,
    sport TEXT NOT NULL, -- 'mtb', 'trail_run', 'gravel'
    unique_riders_12mo INT DEFAULT 0,
    total_passes_12mo INT DEFAULT 0,
    weighted_score DOUBLE PRECISION DEFAULT 0.0,
    last_ridden_date DATE,
    is_public BOOLEAN DEFAULT FALSE,
    contributor_ids TEXT[] DEFAULT '{}',
    PRIMARY KEY (edge_osm_id, sport)
);

CREATE INDEX IF NOT EXISTS idx_edge_heat_score ON edge_heat (sport, weighted_score);
CREATE INDEX IF NOT EXISTS idx_edge_heat_public ON edge_heat (sport, is_public);

-- User Activities (GPX / FIT uploads)
CREATE TABLE IF NOT EXISTS activities (
    id TEXT PRIMARY KEY,
    user_id TEXT REFERENCES users(id) ON DELETE CASCADE,
    sport TEXT NOT NULL,
    activity_date TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    distance_miles DOUBLE PRECISION DEFAULT 0.0,
    duration_minutes DOUBLE PRECISION DEFAULT 0.0,
    file_format TEXT NOT NULL, -- 'gpx' or 'fit'
    raw_file_retained BOOLEAN DEFAULT FALSE,
    raw_file_path TEXT,
    consent_given BOOLEAN DEFAULT TRUE,
    matched_edge_count INT DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_activities_user ON activities (user_id);
CREATE INDEX IF NOT EXISTS idx_activities_date ON activities (activity_date);

-- Activity Edge Visits (per-edge traversal records)
CREATE TABLE IF NOT EXISTS activity_edge_visits (
    id SERIAL PRIMARY KEY,
    activity_id TEXT REFERENCES activities(id) ON DELETE CASCADE,
    edge_osm_id BIGINT REFERENCES edges(osm_id) ON DELETE CASCADE,
    user_id TEXT REFERENCES users(id) ON DELETE CASCADE,
    sport TEXT NOT NULL,
    visited_at TIMESTAMP WITH TIME ZONE NOT NULL,
    pass_count INT DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_edge_visits_edge_sport ON activity_edge_visits (edge_osm_id, sport);
CREATE INDEX IF NOT EXISTS idx_edge_visits_user ON activity_edge_visits (user_id);
CREATE INDEX IF NOT EXISTS idx_edge_visits_date ON activity_edge_visits (visited_at);

-- Regional Heat Coverage Grid (coverage-aware zero-heat penalty)
CREATE TABLE IF NOT EXISTS regional_coverage (
    cell_id TEXT PRIMARY KEY,
    min_lat DOUBLE PRECISION,
    min_lon DOUBLE PRECISION,
    max_lat DOUBLE PRECISION,
    max_lon DOUBLE PRECISION,
    activity_count_12mo INT DEFAULT 0,
    is_sufficient BOOLEAN DEFAULT FALSE,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- User Privacy Zones
CREATE TABLE IF NOT EXISTS user_privacy_zones (
    id SERIAL PRIMARY KEY,
    user_id TEXT REFERENCES users(id) ON DELETE CASCADE,
    name TEXT DEFAULT 'Home/Work',
    lat DOUBLE PRECISION NOT NULL,
    lon DOUBLE PRECISION NOT NULL,
    radius_m DOUBLE PRECISION DEFAULT 320.0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_privacy_zones_user ON user_privacy_zones (user_id);


-- Trail Community Flags (closed, gone, blocked, seasonal)
CREATE TABLE IF NOT EXISTS flags (
    id SERIAL PRIMARY KEY,
    edge_osm_id BIGINT,
    flag_type TEXT NOT NULL, -- 'gone', 'blocked', 'closed', 'seasonal'
    user_id TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    confirmed_count INT DEFAULT 1,
    details TEXT
);

CREATE INDEX IF NOT EXISTS idx_flags_edge ON flags (edge_osm_id);

-- Land Restrictions and DNR
CREATE TABLE IF NOT EXISTS restrictions (
    id SERIAL PRIMARY KEY,
    name TEXT,
    restriction_type TEXT NOT NULL, -- 'dnr', 'closure', 'sensitive_wildlife', 'private'
    source TEXT,
    is_hard BOOLEAN DEFAULT FALSE, -- hard blocks cannot be overridden
    geom GEOMETRY(Geometry, 4326)
);

CREATE INDEX IF NOT EXISTS idx_restrictions_geom ON restrictions USING GIST (geom);

-- Users
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY, -- Firebase Auth UID
    email TEXT,
    display_name TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Saved Routes
CREATE TABLE IF NOT EXISTS saved_routes (
    id TEXT PRIMARY KEY,
    user_id TEXT REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    sport TEXT NOT NULL,
    distance_miles DOUBLE PRECISION,
    elevation_gain_ft DOUBLE PRECISION,
    elevation_loss_ft DOUBLE PRECISION,
    geom GEOMETRY(LineString, 4326),
    surface_summary JSONB,
    waypoints JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_saved_routes_user ON saved_routes (user_id);

-- User Contribution and Privacy Settings
CREATE TABLE IF NOT EXISTS contribution_consent (
    user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    consent_given BOOLEAN DEFAULT FALSE,
    consented_at TIMESTAMP WITH TIME ZONE,
    privacy_zone_lat DOUBLE PRECISION,
    privacy_zone_lon DOUBLE PRECISION,
    privacy_zone_radius_m DOUBLE PRECISION DEFAULT 320.0 -- ~0.2 miles
);

-- Trail Submissions
CREATE TABLE IF NOT EXISTS trail_submissions (
    id SERIAL PRIMARY KEY,
    user_id TEXT REFERENCES users(id),
    name TEXT,
    sport TEXT NOT NULL,
    difficulty TEXT,
    geom GEOMETRY(LineString, 4326),
    status TEXT DEFAULT 'pending', -- 'pending', 'verified', 'rejected'
    verifier_count INT DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_trail_submissions_geom ON trail_submissions USING GIST (geom);
