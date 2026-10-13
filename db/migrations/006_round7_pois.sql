-- Round 7 (GH-34): water, bike shops and bike repair stations from OSM, for map markers.
CREATE TABLE IF NOT EXISTS pois (
    osm_type TEXT NOT NULL,          -- 'node' | 'way'
    osm_id BIGINT NOT NULL,
    kind TEXT NOT NULL,              -- 'water' | 'bike_shop' | 'bike_repair' | 'toilets'
    name TEXT,
    geom GEOMETRY(Point, 4326) NOT NULL,
    PRIMARY KEY (osm_type, osm_id)
);
CREATE INDEX IF NOT EXISTS pois_geom ON pois USING GIST (geom);
