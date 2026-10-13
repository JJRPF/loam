-- Round 7 (GH-34) phase 7: "Report bad route". The full snapshot stays here; the GitHub issue gets a trimmed copy.
CREATE TABLE IF NOT EXISTS route_reports (
    id UUID PRIMARY KEY,
    user_id TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    comment TEXT NOT NULL,
    request_json JSONB NOT NULL,
    route_json JSONB NOT NULL,
    options_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    engine_config_version INTEGER,
    git_sha TEXT,
    github_issue_number INTEGER,
    github_issue_url TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS route_reports_user_created ON route_reports (user_id, created_at);
CREATE INDEX IF NOT EXISTS route_reports_status ON route_reports (status);
