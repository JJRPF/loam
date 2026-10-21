#!/usr/bin/env bash
# Shared by deploy-pi.sh and deploy-web.sh: builds frontend/dist with the production settings, so the bundle
# served from Firebase Hosting and the one the Pi serves on the LAN are the same.
#
#   VITE_API_BASE            the API's public origin (the Pi behind Tailscale Funnel); '' in dev (Vite proxy)
#   VITE_PUBLIC_APP_ORIGIN   where the app lives; an app opened on another origin redirects here
#   VITE_FIREBASE_AUTH_DOMAIN  the app's own domain: Firebase Hosting serves /__/auth/* there, which keeps
#                              redirect sign-in working where Safari blocks third-party storage
# The rest of the Firebase web config (VITE_FIREBASE_*) comes from the repo-root .env (the API's file), or, in GitHub
# Actions, from the repository variables VITE_FIREBASE_API_KEY and VITE_FIREBASE_APP_ID (public web config).
#
# WEB_ENV=staging (default production) builds the staging app: its own API (the Pi's staging port), its own origin
# (loamstaging.thepfisters.com), VITE_APP_ENV=staging (the banner), and a robots.txt that disallows everything.

WEB_ENV="${WEB_ENV:-production}"
case "${WEB_ENV}" in
    production)
        export VITE_API_BASE="${VITE_API_BASE:-https://core-node.tailcd5892.ts.net}"
        export VITE_PUBLIC_APP_ORIGIN="${VITE_PUBLIC_APP_ORIGIN:-https://loam.thepfisters.com}"
        export VITE_FIREBASE_AUTH_DOMAIN="${VITE_FIREBASE_AUTH_DOMAIN:-loam.thepfisters.com}"
        ;;
    staging)
        export VITE_API_BASE="${VITE_API_BASE:-https://core-node.tailcd5892.ts.net:8443}"
        export VITE_PUBLIC_APP_ORIGIN="${VITE_PUBLIC_APP_ORIGIN:-https://loamstaging.thepfisters.com}"
        export VITE_FIREBASE_AUTH_DOMAIN="${VITE_FIREBASE_AUTH_DOMAIN:-loamstaging.thepfisters.com}"
        export VITE_APP_ENV=staging
        ;;
    *) echo "ERROR: WEB_ENV must be production or staging (is ${WEB_ENV})" >&2; return 1 2>/dev/null || exit 1 ;;
esac

build_web_app() {
    local root="$1"
    # trailheads.json is generated from the OSM extract (it is git-ignored with the data/ rule)
    if [ ! -f "${root}/frontend/src/data/trailheads.json" ]; then
        local osm="${LOAM_OSM_PBF:-${HOME}/dev/loam/main/data/osm/new-hampshire-latest.osm.pbf}"
        [ -f "${osm}" ] || { echo "ERROR: frontend/src/data/trailheads.json is missing and ${osm} (LOAM_OSM_PBF) is not there to build it" >&2; return 1; }
        PYTHONPATH="${root}" "${root}/.venv/bin/python" "${root}/scripts/build_trailheads.py" "${osm}"
    fi
    (cd "${root}/frontend" && npm ci --silent && npm run build)
    if [ "${WEB_ENV}" = staging ]; then
        # staging is never indexed: no sitemap, a robots.txt that disallows everything (firebase.json adds X-Robots-Tag)
        printf 'User-agent: *\nDisallow: /\n' > "${root}/frontend/dist/robots.txt"
        rm -f "${root}/frontend/dist/sitemap.xml"
    fi
}
