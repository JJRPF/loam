#!/usr/bin/env bash
# Firebase Auth emulator for the browser tests (project demo-loam; no Google account, no network sign-in).
# Runs from a temporary directory so it never reads the repo's firebase.json or writes next to it.
set -euo pipefail
FIREBASE_TOOLS_VERSION="15.33.0"
dir="$(mktemp -d)"
trap 'rm -rf "${dir}"' EXIT
cat > "${dir}/firebase.json" <<JSON
{ "emulators": { "auth": { "host": "127.0.0.1", "port": 9099 }, "ui": { "enabled": false }, "singleProjectMode": true } }
JSON
cd "${dir}"
exec npx --yes "firebase-tools@${FIREBASE_TOOLS_VERSION}" emulators:start --only auth --project demo-loam
