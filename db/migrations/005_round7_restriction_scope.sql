-- Round 7 (GH-34): a restriction can apply to bikes only (federal wilderness bans bicycles, not feet).
ALTER TABLE restrictions ADD COLUMN IF NOT EXISTS applies_to TEXT NOT NULL DEFAULT 'all';  -- 'all' | 'bike'
