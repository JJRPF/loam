#!/usr/bin/env bash
# Production build of the web app for the browser tests: the same bundle as production, but pointed at the
# local API (127.0.0.1:8089), the Hosting stand-in's origin, and the Auth emulator (project demo-loam).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export VITE_API_BASE="http://127.0.0.1:8089"
export VITE_PUBLIC_APP_ORIGIN="http://127.0.0.1:5180"
export VITE_FIREBASE_API_KEY="fake-api-key" VITE_FIREBASE_AUTH_DOMAIN="127.0.0.1" VITE_FIREBASE_PROJECT_ID="demo-loam"
export VITE_FIREBASE_APP_ID="1:000000000000:web:0000000000000000"
export VITE_FIREBASE_AUTH_EMULATOR="127.0.0.1:9099"
# shellcheck source=scripts/web-build-env.sh
. "${ROOT}/scripts/web-build-env.sh"   # keeps the values above (it only fills in unset ones)
build_web_app "${ROOT}"
