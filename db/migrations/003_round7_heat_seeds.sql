-- Round 7 (GH-34) phase 5: Garmin export heat import and real loop seeds.

ALTER TABLE activities ADD COLUMN IF NOT EXISTS source TEXT;

-- Heat is kept per heat sport (mtb, gravel, trail_run). Earlier rows used routing profiles
-- (mtb_gravel, foot, ...), which routing lookups never matched. Normalize the visits; edge_heat
-- is derived from visits and is rebuilt by the next heat recalculation.
UPDATE activity_edge_visits SET sport = CASE
    WHEN sport IN ('mtb_hardtail', 'mtb_fullsus', 'mtb_fat', 'mtb_emtb') THEN 'mtb'
    WHEN sport IN ('mtb_gravel', 'bike') THEN 'gravel'
    WHEN sport IN ('foot', 'run', 'hike') THEN 'trail_run'
    ELSE sport END
WHERE sport NOT IN ('mtb', 'gravel', 'trail_run');
UPDATE activities SET sport = CASE
    WHEN sport IN ('mtb_hardtail', 'mtb_fullsus', 'mtb_fat', 'mtb_emtb') THEN 'mtb'
    WHEN sport IN ('mtb_gravel', 'bike') THEN 'gravel'
    WHEN sport IN ('foot', 'run', 'hike') THEN 'trail_run'
    ELSE sport END
WHERE sport NOT IN ('mtb', 'gravel', 'trail_run');
DELETE FROM edge_heat WHERE sport NOT IN ('mtb', 'gravel', 'trail_run');

-- Loops riders actually rode (start and end within 300 m), as OSM topology only: the ordered
-- OSM node ids at segment ends and the way ids. No GPS points, no start location.
CREATE TABLE IF NOT EXISTS seed_loops (
    id SERIAL PRIMARY KEY,
    user_id TEXT REFERENCES users(id) ON DELETE CASCADE,
    activity_id TEXT REFERENCES activities(id) ON DELETE CASCADE,
    sport TEXT NOT NULL,
    way_ids BIGINT[] NOT NULL,
    node_path BIGINT[] NOT NULL,
    segment_ids BIGINT[] NOT NULL,       -- as of osm_import_id; node_path resolves after re-imports
    osm_import_id INT,
    distance_m DOUBLE PRECISION NOT NULL,
    retrace DOUBLE PRECISION NOT NULL,
    centroid_rounded TEXT,               -- 2 decimals (~1 km), for reporting only
    rider_ids TEXT[] NOT NULL DEFAULT '{}',
    rides INT NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_seed_loops_sport ON seed_loops (sport);
CREATE INDEX IF NOT EXISTS idx_seed_loops_user ON seed_loops (user_id);
