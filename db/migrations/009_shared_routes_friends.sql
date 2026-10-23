-- Round 9 (GH-42): shared route links and friends. Planned routes only; rides are never shared.
-- Idempotent, like every migration.

ALTER TABLE saved_routes ADD COLUMN IF NOT EXISTS visibility TEXT NOT NULL DEFAULT 'private';
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'saved_routes_visibility_check') THEN
        ALTER TABLE saved_routes ADD CONSTRAINT saved_routes_visibility_check
            CHECK (visibility IN ('private', 'link', 'friends'));
    END IF;
END $$;

-- The name other people see next to a shared route. NULL means "A Loam rider".
ALTER TABLE users ADD COLUMN IF NOT EXISTS share_display_name TEXT;

-- A snapshot of a saved route, so later edits do not leak and deleting the route revokes the share.
-- `link` shares carry a token hash; `friends` shares do not.
CREATE TABLE IF NOT EXISTS route_shares (
    id BIGSERIAL PRIMARY KEY,
    route_id TEXT NOT NULL REFERENCES saved_routes(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    mode TEXT NOT NULL CHECK (mode IN ('link', 'friends')),
    token_hash TEXT UNIQUE,                 -- sha256 hex of the token; the raw token is never stored
    name TEXT NOT NULL,
    sport TEXT NOT NULL,
    distance_miles DOUBLE PRECISION,
    elevation_gain_ft DOUBLE PRECISION,
    elevation_loss_ft DOUBLE PRECISION,
    geom GEOMETRY(LineString, 4326),
    surface_summary JSONB,
    trimmed BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    last_viewed_at TIMESTAMP WITH TIME ZONE,
    view_count INT NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_route_shares_route ON route_shares (route_id);
CREATE INDEX IF NOT EXISTS idx_route_shares_user ON route_shares (user_id);
-- One share per route; revoking deletes it (the line, the token and the counters go with it).
CREATE UNIQUE INDEX IF NOT EXISTS uq_route_shares_route ON route_shares (route_id);

CREATE TABLE IF NOT EXISTS friend_invites (
    id BIGSERIAL PRIMARY KEY,
    token_hash TEXT NOT NULL UNIQUE,
    inviter_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    used_by TEXT REFERENCES users(id) ON DELETE SET NULL,
    used_at TIMESTAMP WITH TIME ZONE
);
CREATE INDEX IF NOT EXISTS idx_friend_invites_inviter ON friend_invites (inviter_id);

-- An ordered pair (user_a < user_b, byte order: the API sorts the same way), so a friendship is one row.
-- Firebase uids are mixed case, and a locale collation would order them differently from the API.
-- `id` is the handle the API uses, so a friend's user id is never sent to anyone.
CREATE TABLE IF NOT EXISTS friendships (
    id BIGSERIAL UNIQUE,
    user_a TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    user_b TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_a, user_b),
    CHECK (user_a < user_b COLLATE "C")
);
CREATE INDEX IF NOT EXISTS idx_friendships_b ON friendships (user_b);

CREATE TABLE IF NOT EXISTS blocks (
    id BIGSERIAL UNIQUE,
    blocker TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    blocked TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    PRIMARY KEY (blocker, blocked),
    CHECK (blocker <> blocked)
);
