#!/usr/bin/env bash
# Starts the API for the browser tests on loopback: the dev database and the real routing stack from .env
# (never printed), the Firebase Auth emulator instead of Google, no GitHub token, midpoints off, not production.
#   scripts/browser-test-server.sh <port> [VAR=value ...]   extra settings override everything else
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PORT="$1"; shift
set -a
[ -f "${ROOT}/.env" ] && . "${ROOT}/.env"
set +a
# the dev database (docker compose service, published on localhost), never the Pi: .env may name the compose-internal host
export DATABASE_URL="${LOAM_TEST_DATABASE_URL:-postgresql://loam:loam_dev_pw@localhost:5432/loam}"
export HOST=127.0.0.1 PORT="${PORT}" APP_ENV=development LOAM_ENV=development
export FIREBASE_PROJECT_ID=demo-loam FIREBASE_AUTH_EMULATOR_HOST="${FIREBASE_AUTH_EMULATOR_HOST:-127.0.0.1:9099}"
export ENABLE_MIDPOINTS=false GITHUB_FEEDBACK_TOKEN= ADMIN_EMAILS= PUBLIC_APP_ORIGIN=
export CORS_ORIGINS="http://127.0.0.1:5180,http://127.0.0.1:5181,http://localhost:5180"
export RATE_LIMIT_ROUTE=1000/60 RATE_LIMIT_GEOCODE=1000/60 RATE_LIMIT_UPLOAD=1000/60 RATE_LIMIT_FLAG=1000/60
for kv in "$@"; do export "$kv"; done
cd "${ROOT}"
PYTHONPATH="${ROOT}" exec "${ROOT}/.venv/bin/python" -m uvicorn app.main:app --host 127.0.0.1 --port "${PORT}" --log-level warning
