#!/bin/bash
#
# Rebuild the staging database from production's schema and PUBLIC, non-personal data. RUN AS ROOT ON THE PI by
# the owner; safe to rerun. Production is only read.
#
# Copied:   the schema (built from production's db/init_schema.sql and migrations), then the data of
#             edges, trail_segments, osm_imports   OpenStreetMap-derived trail geometry
#             restrictions                           land and closure rules
#             regional_coverage                      cell counts only
#             edge_heat WHERE is_public              heat already public to every visitor, with contributor_ids
#                                                    emptied (those are user ids)
# NEVER copied: users, activities, activity_edge_visits, saved_routes, user_privacy_zones, user_dnr, flags,
#               flag_votes, trail_checkins, contribution_consent, trail_submissions(+evidence), route_reports,
#               user_connected_services, seed_loops, anything else. Loam holds people's GPS history; staging
#               users sign in with Firebase and start empty. Changing this rule is the owner's call.
#
# The staging API is stopped while the database is rebuilt and restarted afterwards.

set -euo pipefail

PROD_USER="${LOAM_PROD_USER:-jjrpfister}"
STAGING_USER=loam-staging
PG_CONTAINER="${LOAM_PG_CONTAINER:-loam-postgis}"
LIB="${LOAM_LIB_DIR:-/usr/local/lib/loam-deploy}"
PUBLIC_TABLES=(edges trail_segments osm_imports restrictions regional_coverage)
SRC="${LOAM_PROD_SRC:-$PROD_HOME/loam-deploy/production/current}"
[ "$(id -u)" = 0 ] || { echo "❌ run as root" >&2; exit 1; }

PROD_HOME=$(getent passwd "$PROD_USER" | cut -d: -f6)
STAGING_HOME=$(getent passwd "$STAGING_USER" | cut -d: -f6)
PROD_ENV="${LOAM_PROD_ENV:-$PROD_HOME/loam-deploy/production/shared/.env}"
STAGING_ENV="${LOAM_STAGING_ENV:-$STAGING_HOME/loam-deploy/staging/shared/.env}"
[ -f "$STAGING_ENV" ] || { echo "❌ $STAGING_ENV not found; run provision.sh install first" >&2; exit 1; }

url_part() {  # url_part <env file> <user|password|dbname>
  "$LIB/loam-with-env" "$1" python3 -c '
import os, sys, urllib.parse as u
p = u.urlparse(os.environ["DATABASE_URL"])
print({"user": p.username, "password": u.unquote(p.password or ""), "dbname": p.path.lstrip("/").split("?")[0]}[sys.argv[1]])' "$2"
}
PROD_DB=$(url_part "$PROD_ENV" dbname); PROD_PG_USER=$(url_part "$PROD_ENV" user); PROD_PW=$(url_part "$PROD_ENV" password)
STG_DB=$(url_part "$STAGING_ENV" dbname); STG_PG_USER=$(url_part "$STAGING_ENV" user); STG_PW=$(url_part "$STAGING_ENV" password)
[ "$STG_DB" != "$PROD_DB" ] || { echo "❌ staging's DATABASE_URL names the production database ($PROD_DB); refusing" >&2; exit 1; }
[ "$STG_DB" = loam_staging ] || { echo "❌ expected staging's database to be loam_staging, got $STG_DB" >&2; exit 1; }

prod_psql() { docker exec -i -e PGPASSWORD="$PROD_PW" "$PG_CONTAINER" psql -v ON_ERROR_STOP=1 -q -h localhost -U "$PROD_PG_USER" -d "$PROD_DB" "$@"; }
prod_dump() { docker exec -e PGPASSWORD="$PROD_PW" "$PG_CONTAINER" pg_dump -h localhost -U "$PROD_PG_USER" -d "$PROD_DB" "$@"; }
stg_super() { docker exec -i -e PGPASSWORD="$PROD_PW" "$PG_CONTAINER" psql -v ON_ERROR_STOP=1 -q -h localhost -U "$PROD_PG_USER" -d "$1"; }
stg_psql() { docker exec -i -e PGPASSWORD="$STG_PW" "$PG_CONTAINER" psql -v ON_ERROR_STOP=1 -q -h localhost -U "$STG_PG_USER" -d "$STG_DB" "$@"; }

was_active=0
if systemctl is-active --quiet loam-api-staging; then was_active=1; systemctl stop loam-api-staging; fi

echo "• database: recreating $STG_DB"
stg_super postgres <<SQL
SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '$STG_DB' AND pid <> pg_backend_pid();
DROP DATABASE IF EXISTS "$STG_DB";
CREATE DATABASE "$STG_DB" OWNER "$STG_PG_USER";
SQL
stg_super "$STG_DB" <<'SQL'
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
SQL

echo "• schema: db/init_schema.sql and db/migrations/*.sql from production's code ($SRC)"
# Built from the code, not pg_dump'd: the PostGIS image carries legacy functions a dump would try to recreate.
stg_psql < "$SRC/db/init_schema.sql" >/dev/null
stg_psql <<'SQL'
CREATE TABLE IF NOT EXISTS schema_migrations (name TEXT PRIMARY KEY, applied_at TIMESTAMPTZ DEFAULT NOW());
SQL
for f in "$SRC"/db/migrations/*.sql; do
  n=$(basename "$f")
  { cat "$f"; printf "\nINSERT INTO schema_migrations (name) VALUES ('%s') ON CONFLICT DO NOTHING;\n" "$n"; } | stg_psql >/dev/null
done

columns() {  # columns <psql function> <table>: that database's columns, in order
  "$1" -At -c "SELECT column_name FROM information_schema.columns WHERE table_schema = 'public' AND table_name = '$2' ORDER BY ordinal_position"
}
copy_table() {  # copy_table <table> [WHERE ...]: the columns both sides have (a PR may add some to staging)
  local t="$1" where="${2:-}" cols
  cols=$(comm -12 <(columns prod_psql "$t" | sort) <(columns stg_psql "$t" | sort) | paste -sd, -)
  # keep staging's column order
  cols=$(columns stg_psql "$t" | grep -x -F -f <(echo "${cols//,/$'\n'}") | paste -sd, -)
  [ -n "$cols" ] || { echo "❌ no common columns for $t" >&2; exit 1; }
  echo "• data: $t"
  prod_psql -c "COPY (SELECT $cols FROM $t $where) TO STDOUT" | stg_psql -c "COPY $t ($cols) FROM STDIN"
}

for t in "${PUBLIC_TABLES[@]}"; do copy_table "$t"; done

echo "• data: edge_heat (public rows only, contributors removed)"
cols=$(comm -12 <(columns prod_psql edge_heat | sort) <(columns stg_psql edge_heat | sort) | grep -v '^contributor_ids$' | paste -sd, -)
prod_psql -c "COPY (SELECT $cols FROM edge_heat WHERE is_public) TO STDOUT" | stg_psql -c "COPY edge_heat ($cols) FROM STDIN"

echo "• counts"
stg_psql <<'SQL'
SELECT 'edges' AS tbl, count(*) FROM edges UNION ALL SELECT 'trail_segments', count(*) FROM trail_segments
UNION ALL SELECT 'edge_heat', count(*) FROM edge_heat UNION ALL SELECT 'users (must be 0)', count(*) FROM users
UNION ALL SELECT 'activities (must be 0)', count(*) FROM activities;
SQL

if [ "$was_active" = 1 ]; then systemctl start loam-api-staging; echo "• restarted loam-api-staging"; fi
echo "Done."
