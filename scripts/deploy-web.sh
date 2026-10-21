#!/usr/bin/env bash
# ==============================================================================
# Loam: web app deployment to Firebase Hosting (https://loam.thepfisters.com)
# Builds frontend/dist with the production settings and deploys HOSTING ONLY.
#
# Usage: ./scripts/deploy-web.sh
#
# The Firebase project `thepfisters` is shared with other apps: this script never deploys Firestore rules or
# indexes, Functions or Storage (firebase.json has only a "hosting" block, and the command says --only hosting).
# HOSTING_TARGET (default prod; staging is the loamstaging site) picks the .firebaserc target; CI sets it too.
# First time: log in once with   npx --yes firebase-tools@15.33.0 login
# ==============================================================================

set -euo pipefail

FIREBASE_TOOLS_VERSION="15.33.0"
HOSTING_TARGET="${HOSTING_TARGET:-prod}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

die() { echo "ERROR: $*" >&2; exit 1; }

case "${HOSTING_TARGET}" in prod|staging) ;; *) die "HOSTING_TARGET must be prod or staging (is ${HOSTING_TARGET})";; esac

# shellcheck source=scripts/web-build-env.sh
. "${ROOT}/scripts/web-build-env.sh"

echo "[1/3] Building the web app (API ${VITE_API_BASE}, app ${VITE_PUBLIC_APP_ORIGIN})..."
build_web_app "${ROOT}"

echo "[2/3] Checking the build..."
[ -f "${ROOT}/frontend/dist/index.html" ] || die "frontend/dist/index.html is missing"
if find "${ROOT}/frontend/dist" -name '*.map' | grep -q .; then
    die "source maps found in frontend/dist; the public site ships none"
fi
grep -q "${VITE_API_BASE#https://}" "${ROOT}/frontend/dist/assets/"*.js \
    || die "the bundle does not contain the API base ${VITE_API_BASE}; was VITE_API_BASE overridden?"

echo "[3/3] Deploying to Firebase Hosting (hosting only)..."
cd "${ROOT}"
# shellcheck disable=SC2086  # HOSTING_TARGET is checked above
npx --yes "firebase-tools@${FIREBASE_TOOLS_VERSION}" deploy --only hosting:${HOSTING_TARGET} --project thepfisters

echo "Done: ${VITE_PUBLIC_APP_ORIGIN}"
