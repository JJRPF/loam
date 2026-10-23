#!/usr/bin/env bash
# The Playwright browser suite (tests/browser): builds the production bundle against the local API, then runs
# everything. Playwright starts the Firebase Auth emulator (:9099), two APIs on loopback (:8089, :8091) and the
# Hosting stand-in (:5180) itself, and reuses any that are already running.
#   npm run test:browser            from frontend/ (extra arguments go to playwright, e.g. -g "axe")
# Needs: docker compose up -d postgis graphhopper, the dev data, a system Chromium.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
"${ROOT}/scripts/browser-test-build.sh"
cd "${ROOT}/frontend"
# tests/browser sits beside frontend/, so its imports (@playwright/test) resolve from frontend/node_modules
export NODE_PATH="${ROOT}/frontend/node_modules${NODE_PATH:+:${NODE_PATH}}"
exec node_modules/.bin/playwright test -c ../tests/browser/playwright.config.ts "$@"
