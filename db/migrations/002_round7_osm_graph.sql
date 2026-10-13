-- Round 7 (GH-34) phase 3: real OSM trail topology (scripts/import_osm_graph.py).

-- Way-level tags the import stores on edges (heat stays keyed by way id).
ALTER TABLE edges ADD COLUMN IF NOT EXISTS mtb_scale_raw TEXT;
ALTER TABLE edges ADD COLUMN IF NOT EXISTS mtb_scale_imba TEXT;
ALTER TABLE edges ADD COLUMN IF NOT EXISTS motor_vehicle TEXT;
ALTER TABLE edges ADD COLUMN IF NOT EXISTS seasonal TEXT;
ALTER TABLE edges ADD COLUMN IF NOT EXISTS informal TEXT;
ALTER TABLE edges ADD COLUMN IF NOT EXISTS smoothness TEXT;
ALTER TABLE edges ADD COLUMN IF NOT EXISTS osm_timestamp TIMESTAMPTZ;
ALTER TABLE edges ADD COLUMN IF NOT EXISTS category TEXT;
-- TRUE when geometry and tags came from the OSM import; FALSE for rows written any other way.
ALTER TABLE edges ADD COLUMN IF NOT EXISTS osm_source BOOLEAN DEFAULT FALSE;

-- Ways split at every node shared by two or more kept ways, and at way endpoints.
CREATE TABLE IF NOT EXISTS trail_segments (
    segment_id BIGSERIAL PRIMARY KEY,
    osm_way_id BIGINT NOT NULL,
    seq INT NOT NULL,
    from_node BIGINT NOT NULL,
    to_node BIGINT NOT NULL,
    geom GEOMETRY(LineString, 4326) NOT NULL,
    length_m DOUBLE PRECISION NOT NULL,
    name TEXT,
    highway TEXT,
    surface TEXT,
    tracktype TEXT,
    mtb_scale TEXT,
    mtb_scale_imba TEXT,
    sac_scale TEXT,
    access TEXT,
    bicycle TEXT,
    foot TEXT,
    motor_vehicle TEXT,
    snowmobile TEXT,
    seasonal TEXT,
    informal TEXT,
    smoothness TEXT,
    check_date TEXT,
    osm_timestamp TIMESTAMPTZ,
    category TEXT NOT NULL,
    is_snowmobile BOOLEAN NOT NULL DEFAULT FALSE,
    is_steps BOOLEAN NOT NULL DEFAULT FALSE,
    UNIQUE (osm_way_id, seq)
);
CREATE INDEX IF NOT EXISTS idx_trail_segments_geom ON trail_segments USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_trail_segments_from ON trail_segments (from_node);
CREATE INDEX IF NOT EXISTS idx_trail_segments_to ON trail_segments (to_node);
CREATE INDEX IF NOT EXISTS idx_trail_segments_way ON trail_segments (osm_way_id);

-- One row per import, so caches (the trail graph) can tell when the data changed.
CREATE TABLE IF NOT EXISTS osm_imports (
    id SERIAL PRIMARY KEY,
    pbf_path TEXT NOT NULL,
    pbf_size BIGINT,
    pbf_mtime TIMESTAMPTZ,
    imported_at TIMESTAMPTZ DEFAULT NOW(),
    ways_kept INT,
    segments INT,
    edges_upserted INT,
    edges_not_in_osm INT
);
