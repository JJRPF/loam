#!/usr/bin/env bash
# Smoke check of a production deploy: the web app on Firebase Hosting, the API through the Funnel, and the two
# together (the API must answer the app's origin with CORS). Exits non-zero on the first failure.
set -euo pipefail

APP_URL="${APP_URL:-https://loam.thepfisters.com}"
API_URL="${API_URL:-https://core-node.tailcd5892.ts.net}"
fail() { echo "::error::smoke check failed: $*" >&2; exit 1; }
retry=(--retry 5 --retry-delay 3 --retry-all-errors --max-time 20)

curl -fsS "${retry[@]}" "${APP_URL}/" | grep -q 'id="root"' || fail "${APP_URL}/ does not serve the app"
curl -fsS "${retry[@]}" "${APP_URL}/legal/privacy/" -o /dev/null || fail "${APP_URL}/legal/privacy/"
curl -fsS "${retry[@]}" "${API_URL}/health" | grep -q '"status":"ok"' || fail "${API_URL}/health is not ok"
curl -fsS "${retry[@]}" "${API_URL}/api/config" | jq -e '.source_url' >/dev/null || fail "${API_URL}/api/config"
curl -fsSI "${retry[@]}" -H "Origin: ${APP_URL}" "${API_URL}/api/config" \
    | grep -qi "^access-control-allow-origin: ${APP_URL}" || fail "the API does not answer ${APP_URL} with CORS"
echo "smoke check passed"
