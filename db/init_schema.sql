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
    weighted_score DOUBLE PRECISION DEFAULT 0.0,
    last_ridden_date DATE,
    PRIMARY KEY (edge_osm_id, sport)
);

CREATE INDEX IF NOT EXISTS idx_edge_heat_score ON edge_heat (sport, weighted_score);

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
