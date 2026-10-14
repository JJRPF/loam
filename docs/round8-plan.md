# Loam Round 8: prerelease (public launch on loam.thepfisters.com)

This plan was written in the grove launcher with the owner. The builder agent **executes it; it does not re-plan.** When reality differs from the plan (a file moved, a check fails, a step is impossible), take the smallest change that keeps the plan's intent, log it in `docs/round8-worklog.md` under the phase as **Deviation:** with the reason, and keep going. Stop and ask the owner only where this plan says **ASK** or before anything listed under "Hard rules".

First commit: this file verbatim as `docs/round8-plan.md`, plus an empty `docs/round8-worklog.md` with one heading per phase. Each phase ends with a worklog entry (what changed, files, tests run with counts, deviations) and a commit `GH-38 phase <k>: <summary>`.

## 0. Context

- Repo `JJRPF/loam`, private today. Prod is the Raspberry Pi `core-node.local` (API on port 8085, systemd unit `loam-api`, Postgres in the `loam-postgis` container), public through Tailscale Funnel at `https://core-node.tailcd5892.ts.net`. Dev is the local docker stack (`docker compose up -d`: PostGIS + GraphHopper) with data under `~/dev/loam/main/data/` (worktrees must resolve `data/` there, as Round 7 set up).
- Round 7 (PR #36) shipped Firebase auth, the real OSM graph, 3DEP elevation, Garmin seed heat, bad-route reports, the PWA. Read `docs/round7-worklog.md` and `docs/round7-feature-audit.md` before starting.
- Firebase/GCP project `thepfisters` is **shared with the owner's family** (other apps may use its Firestore, Auth, Hosting). Touch only what this plan names.
- `loam.thepfisters.com` is already a Firebase Hosting custom domain on site `thepfisters` (CNAME `thepfisters.web.app`, status active), currently serving an old coming-soon page that never worked. `https://loam.thepfisters.com/__/auth/handler` already answers 200.

### Owner decisions (final)

1. **Hosting:** Firebase Hosting serves the built PWA at `https://loam.thepfisters.com` (replacing the coming-soon page). The API stays on the Pi behind the Funnel URL, called cross-origin. No DNS, router or firewall changes.
2. **Heat threshold:** `HEAT_MIN_UNIQUE_RIDERS` back to **3** everywhere (remove the Pi override). The owner's imported Garmin heat stays as a **seed**: seed heat is public **on trail-class edges only** (`highway` in `path`, `track`, `bridleway`, `cycleway`), never on roads, footways or sidewalks. Everyone else's heat still needs 3 riders.
3. **Midpoints:** disabled in production for now (they produce out-and-backs). Behind a flag; off on the Pi.
4. **Water & shops layer:** removed entirely.
5. **Map credit:** bottom of the map on mobile (it overlaps the layer toggles today; see the owner's screenshot: badge top-left over "Heatmap ON").
6. **Legal:** privacy policy, terms of use, attributions/licenses; links where users sign in and in the app.
7. **Connectors:** Strava and Trailforks (and any connector) are hidden from the UI when disabled.
8. **Open source:** the repo goes public at launch under **AGPL-3.0-or-later**. The agent prepares and audits; **the owner flips visibility**.
9. **Coming-soon site and waitlist:** remove both. The waitlist holds only the owner's own address; no launch email.
10. **README:** rewritten, stylish, branded, with Playwright screenshots taken during testing.

## Hard rules (carried from Rounds 6-7, plus new)

- Never print, log, commit, or post secrets: `GITHUB_FEEDBACK_TOKEN`, Firebase/Google credentials, anything in any `.env`. When editing the Pi's `.env`, back it up first (`cp .env .env.bak-round8`), change keys with `sed`/a script, and never `cat` it.
- Never commit, upload, or copy the Garmin export or stripped tracks; never commit coordinates of the owner's home or of activity starts. Data lives once under `~/dev/loam/main/data/`.
- Do not edit files in `~/dev/loam/main` (its `.env` included; your worktree has its own `.env` copy, edit that one for dev).
- No router, firewall, DNS, or Tailscale ACL changes. No changes to the Pi's SSH or sudo configuration (the owner does those; see Owner steps).
- Separate dev and prod databases. **`pg_dump` the Pi database before any prod migration, heat recalculation, or delete** (`scripts/backup_db.sh`, then confirm the file exists and is non-empty).
- Firebase project `thepfisters`: you may deploy **Hosting** only (`--only hosting`). Never deploy Firestore rules, indexes, Functions, or Storage from this repo. Anything else in that project is **ASK**.
- No git history rewrites, no `--force` pushes, no repo visibility change.
- No fabricated data, ever (the Round 7 rule): no invented routes, trails, heat, elevation, names, screenshots, or test results. If something can't be produced honestly, say so in the worklog.
- Authorship: commit as the configured git user; never override `user.name`/`user.email`.

## Phase 1: Heat privacy back to 3, owner's heat kept as a trails-only seed

### 1.1 Find every heat writer and reader
`grep -n "edge_heat\|is_public\|unique_riders" app/*.py` and list each function in the worklog as writer/reader. Known problems to fix:
- `app/db.py::record_activity_edge_visits` (around line 388) upserts `edge_heat` with `is_public = TRUE` unconditionally: **any single upload makes heat public** until the next recalculation.
- `app/db.py::record_edge_heat` (around line 85) hard-codes `>= 3` instead of the setting.
- `app/db.py::get_unridden_high_heat_trails` (around line 1990) filters `unique_riders_12mo >= 1 OR weighted_score >= 1.0`, so it exposes one-rider heat through `/api/...` "unexplored trails" (find its route in `app/main.py`, around line 1083).
- Routing/scoring readers: check whether the heat used to score a route for user X includes non-public heat from other users. Allowed: public heat, plus X's own contributions. Anything else is a leak; fix it.

### 1.2 One publication rule
Add to `app/decay.py`:

```python
TRAIL_CLASS_HIGHWAYS = ("path", "track", "bridleway", "cycleway")

def heat_is_public(unique_riders: int, has_seed: bool, highway: Optional[str]) -> bool:
    """>= HEAT_MIN_UNIQUE_RIDERS riders, or seed heat (the owner's imported rides) on a trail-class edge."""
    if unique_riders >= min_unique_riders():
        return True
    return bool(has_seed and settings.seed_heat_public and (highway or "") in TRAIL_CLASS_HIGHWAYS)
```

- "Seed" = a visit whose activity has `activities.source = 'garmin_export'` (only the admin bulk import sets it, `app/heat_import.py:215`). Add `activity_edge_visits.is_seed BOOLEAN NOT NULL DEFAULT FALSE` in migration `db/migrations/007_round8_seed_heat.sql`, backfilled from `activities.source`, and set it on insert in the import path. Add `edge_heat.has_seed BOOLEAN NOT NULL DEFAULT FALSE`.
- `app/config.py`: `seed_heat_public: bool` from `SEED_HEAT_PUBLIC` (default `true`); `heat_min_unique_riders` default stays `3` (unchanged).
- Every writer (`record_edge_heat`, `record_activity_edge_visits`, `recalculate_all_edge_heat`) computes `is_public` and `has_seed` through `heat_is_public`, joining `edges.highway`. Simplest correct approach: writers insert visits and mark touched edges; `is_public` is computed only in one place (a helper `refresh_edge_heat(edge_ids)` that `recalculate_all_edge_heat` also uses). Use that unless it's clearly worse.
- Readers: every public-facing read filters `is_public = TRUE` (or the requesting user's own contributions where the feature is "your heat").
- **Seed loops** (`seed_loops`, offered to others "only when enough distinct riders rode it"): also offer a seed loop to everyone when it is seed-sourced and **≥ 85 % of its length is trail-class**. The candidate's start is always the requester's own start (existing bridging); never expose the seed's original start.
- Privacy zones: confirm (and say in the worklog) that the stripped tracks were clipped by the owner's privacy zones (Round 7 worklog: "Home and start zones are removed"). Do not re-import anything.

### 1.3 UI copy
- Replace `SEED_HEAT_NOTICE` (`frontend/src/services/api.ts:1004`) and its uses in `MapView.tsx` and `ExplorePanel.tsx`. New behaviour: `/api/heat/meta` returns `{min_unique_riders, seed_heat_public}`; when `seed_heat_public` is true, show this small info text in the heat legend or the Explore panel (**not** as a chip in the map's top toggle row):
  "Heat shows trails ridden by 3 or more people in the past year. To get started, it also includes Loam's creator's own rides on trails."
- Remove the "3-rider privacy minimum is temporarily off" wording everywhere (grep the repo, README and docs too).

### 1.4 Tests: `tests/test_round8_heat_privacy.py`
With a test DB and real edges (follow existing test fixtures; no fake geometry beyond what the existing tests use):
- One non-seed rider on a trail edge: not public through **every** reader (heat GeoJSON, unexplored trails, routing heat lookup for another user, `/api/heat/trails`), including immediately after upload (before any recalculation).
- Three distinct riders: public.
- Seed visit on `highway=path`/`track`/`bridleway`/`cycleway`: public. Seed visit on `residential`, `footway`, `service`, `unclassified`: not public.
- `SEED_HEAT_PUBLIC=false`: seed heat on trails is not public.
- Account deletion of a contributor removes their effect after recalculation.
- Seed loop gating: ≥ 85 % trail seed loop offered to another user; a road-heavy one is not.
- Existing heat tests still pass (update any that assumed threshold 1 or forced-public).

## Phase 2: Midpoints behind a flag (off in production)

- `app/config.py`: `enable_midpoints: bool` from `ENABLE_MIDPOINTS`, **default `false`**. `.env.example`: `ENABLE_MIDPOINTS=true  # dev only; off in production until midpoint routing is fixed`. Set `ENABLE_MIDPOINTS=true` in your worktree `.env` for dev work.
- New public endpoint `GET /api/config` returning `{"midpoints_enabled": bool, "min_unique_riders": int, "seed_heat_public": bool, "connectors": {"<provider>": enabled_bool, ...}, "source_url": "https://github.com/JJRPF/loam"}`. Keep `/api/heat/meta` working (the frontend may switch to `/api/config`).
- Server: when disabled, every route endpoint (`/api/route`, `/api/route/options`, `/api/route/options/stream` GET and POST) ignores `waypoints` and returns `notice: "Midpoints are turned off for now, so this route ignores them."` when any were sent. No 400s (old shared links must still work).
- Frontend: when `midpoints_enabled` is false, hide the Midpoints block in `PlanPanel.tsx` (around line 534), the map tap mode `'mid'`, midpoint markers in `MapView.tsx`; `urlState.ts` drops `via=` on parse and never writes it. Saved routes that already contain waypoints still display.
- Tests: `tests/test_round8_midpoints_flag.py`: flag off, waypoints ignored with notice, all four endpoints; flag on, Round 7's `test_loop_honors_midpoint` behaviour unchanged. Browser check in Phase 9.

## Phase 3: Remove the water & shops layer

- Frontend: delete `showPois` state, refs, `loadPoisForView`, the `pois-source`/`pois-circles`/`pois-labels` layers, the toggle button, the `moveend` hook part, `fetchPois` in `api.ts` and any POI types.
- Backend: delete `GET /api/pois` (`app/main.py:669`), `scripts/import_osm_pois.py`, and POI tests in `tests/test_round7_extras.py` and `tests/test_round7_browser.cjs`. New migration `db/migrations/008_round8_drop_pois.sql`: `DROP TABLE IF EXISTS pois;` (keep `006` as history). The Pi gets `pg_dump` before it runs.
- Remove POIs from the README and mark them "removed by owner in Round 8" in the feature audit (Phase 8).
- `grep -rni "poi\|water\|shop" app frontend/src scripts tests README.md`; nothing related may remain (unrelated "water" in surface or weather code is fine).

## Phase 4: Mobile map layout

### 4.1 Map credit
- `frontend/src/index.css` (`.map-attribution-badge`, around lines 152-182) and `MapView.tsx:896`. Below 800 px, the badge sits at the **bottom-left of the visible map**, 8 px above the top edge of the bottom sheet, and moves with the sheet's snap state (`peek`/`half`/`full`, `App.tsx` around line 58, `getSheetHeight`). Implement with a CSS custom property (e.g. `--sheet-offset`) set from `App.tsx` on the map container. In `full`, the map isn't visible, so hiding the badge is fine. It must not overlap the zoom/compass/locate controls on the right. Desktop placement (bottom-right) is unchanged.
- Shorten on narrow screens if needed: "© OpenStreetMap · © CARTO" (both still links). Add a third link, "Legal", to `/legal/` (Phase 6).

### 4.2 Top toggle row
After the POI toggle is gone, the row holds Heatmap and OTM Trails (and whatever else exists). At 360 px wide nothing may overlap or clip. The seed notice is no longer a chip (Phase 1.3). Toggles keep ≥ 44 px tap targets.

### 4.3 Small fixes
- `ResultsPanel.tsx:299`: "1 Candidate Routes" becomes "1 candidate route" / "N candidate routes" (sentence case, matching the rest of the UI).

## Phase 5: Hide disabled connectors

- `YouPanel.tsx`: render only connectors with `enabled === true` (around lines 656-770). The Strava and Trailforks modals and their state are rendered only when that connector is enabled. The intro copy (line 656, "Connect Garmin Connect and Trailforks …") is built from the enabled list (e.g. only Garmin today: "Connect Garmin Connect to sync your activities into your private heat. Passwords are never stored; tokens are encrypted at rest.").
- `grep -rni "strava\|trailforks" frontend/src`: any other UI mention (Explore, reports, attribution "© Trailforks") shows only when that connector is enabled.
- Applies to every connector generically (CubeTrek too): disabled means invisible, not "Disabled" badges.
- Backend unchanged except `/api/config` exposing the enabled map. Test: `tests/test_round8_connectors_hidden.py` (API) and browser check.

## Phase 6: Legal pages, license, source link

### 6.1 Pages
Static HTML, no JS required, styled with the brand (dark, Atkinson Hyperlegible if already bundled, else system font), in `frontend/public/legal/`:
- `/legal/` index (links to the three below, plus "Source code")
- `/legal/privacy/index.html`
- `/legal/terms/index.html`
- `/legal/attributions/index.html`

Using directory `index.html` files makes `/legal/privacy/` work on both Firebase Hosting and the Pi's StaticFiles. Exclude `/legal/` from the service worker's `navigateFallback` (add to `navigateFallbackDenylist` in `frontend/vite.config.ts`) so the SPA doesn't swallow them.

Every statement must be true of the code. Write `docs/round8-legal-claims.md`: one row per claim with the file/function that makes it true. Verify, don't assume: e.g. what an upload stores (Round 7: bulk import keeps no points; check the ordinary `/api/activities/upload` path too), what deletion removes, retention of backups (nightly, 7 days), which third parties the browser and the server contact.

**Privacy policy** must cover: who runs Loam (Justin Pfister, New Hampshire, USA; contact `jjrpfister@gmail.com`, built in JS like the old landing page, with a plain-text fallback "jjrpfister at gmail dot com"); what is collected (Firebase account: UID, email, display name/photo from Google; uploaded activities and what is kept of them; saved routes; flags/check-ins; privacy zones; consent; connector tokens, encrypted); how heat works (aggregated per trail segment, 12-month window, 0.2 mi start/finish trimming, privacy zones, **3-rider minimum**, and the disclosure that **heat also includes the creator's own rides on trails** as seed data); bad-route reports (filed as **public GitHub issues** with the route trimmed 0.5 mi at each end, the full snapshot kept privately on the server); third parties (Google Firebase Authentication and Hosting; CARTO for map tiles, which receives your IP when your browser loads tiles; Photon by komoot for search; US National Weather Service; Overpass API/OpenTrailMap; GitHub for reports; the owner's home server reached through Tailscale Funnel); no ads, no analytics, no selling data; browser storage (Firebase sign-in state, offline routes, service worker cache) and no tracking cookies; your rights: export (`/api/privacy/export`) and delete account (`/api/privacy/account`), with what deletion does to heat; backups kept 7 days; age 13+; changes; effective date.

**Terms of use** must cover: acceptance; 13+; **safety and land access** (computer-generated routes can include closed, private, unsafe, seasonally restricted or non-existent trails and roads; obey signs, closures, land manager rules and local laws; check conditions; you ride/run at your own risk; not a navigation or emergency tool); user content (flags, check-ins, reports: you grant Loam a license to use and publish them; reports are public); acceptable use (no scraping, abuse, automated mass route generation, attacks; rate limits apply); accounts can be suspended for abuse; map data © OpenStreetMap contributors (ODbL), code under AGPL-3.0; **no warranty**; limitation of liability; governing law New Hampshire; changes; contact.

**Attributions** must list: OpenStreetMap contributors (ODbL, link to copyright page; note that OSM-derived data Loam publishes is available under the ODbL on request); CARTO basemaps; USGS 3DEP elevation (public domain); PAD-US (USGS GAP, public domain); OpenTrailMap / Overpass API; Photon by komoot; NWS api.weather.gov; GraphHopper (Apache-2.0); MapLibre GL JS (BSD-3-Clause); Firebase; the font's license (SIL OFL, if bundled); plus a generated list of npm and Python dependencies with licenses (script it, `scripts/gen_third_party_licenses.py`, from `frontend/package-lock.json` and the Python lock/requirements; commit the output under `frontend/public/legal/attributions/third-party.txt`).

Top of each page: "Effective <launch date>" and a one-line plain-language summary. Do not claim GDPR/CCPA compliance or certifications.

### 6.2 Links
- Sign-in UI (Google button and email-link form): "By continuing you agree to the Terms and acknowledge the Privacy Policy." (both links).
- You panel footer and the desktop sidebar footer: Privacy · Terms · Attributions · Source code (`https://github.com/JJRPF/loam`, required by AGPL §13 for network users).
- The heat-contribution consent text and the report-bad-route modal link to the privacy policy.

### 6.3 License
- `LICENSE`: the exact GNU AGPL v3 text (download from `https://www.gnu.org/licenses/agpl-3.0.txt`, check its SHA-256 against a second source such as `https://raw.githubusercontent.com/spdx/license-list-data/main/text/AGPL-3.0-or-later.txt`, normalized for whitespace).
- `frontend/package.json` `"license": "AGPL-3.0-or-later"`, and the Python project metadata if there is one. No per-file headers.

## Phase 7: Production hardening for a public launch

### 7.1 Rate limits and load
No limiter exists today. Add a small in-process limiter (`app/ratelimit.py`, token bucket, no new service). Key: Firebase UID when signed in, else client IP. Behind Funnel, the client IP comes from `X-Forwarded-For` **only when the direct peer is 127.0.0.1/::1** (Funnel proxies locally); otherwise use the peer address. Limits (config-overridable):
- route options / stream / single route: 20 per 10 min per key, plus a global concurrency cap of 2 route generations at once (asyncio semaphore; extra requests wait up to 20 s, then 429)
- `/api/geocode`: 60 per min per key
- bad-route reports: 5 per day per user and 30 per day globally (GitHub issue spam)
- activity uploads: 30 per hour per user
- flags/check-ins: 60 per hour per user

429 responses carry `Retry-After` and a friendly `detail`; the UI shows it inline (not `alert()`). Tests: `tests/test_round8_ratelimit.py`.

### 7.2 Third-party etiquette
One shared User-Agent `Loam/1.0 (+https://loam.thepfisters.com; jjrpfister@gmail.com)` for NWS (`app/weather.py:12`), Overpass (`app/otm.py:114`), Photon, and any other outbound HTTP client. Confirm caching exists for Overpass (per bbox tile, ≥ 24 h), Photon (≥ 1 h) and NWS (per their headers); add a simple TTL cache where missing. Respect Photon's and Overpass's fair-use limits (the limiter above covers geocode).

### 7.3 Deploy script
`scripts/deploy-pi.sh` uses the username as SSH and sudo password via `sshpass` (lines ~33-56). Rewrite it to plain `ssh`/`rsync` with key auth (`-o BatchMode=yes`) and `sudo -n systemctl restart loam-api`. Fail early with a clear message if key auth or passwordless sudo for that one command is not set up, pointing to the owner steps in the README. Remove the default password everywhere (`grep -rn sshpass`). Update `scripts/funnel-start.sh`'s "Funnel is strictly for developer testing, NEVER for production" comment to the real architecture.

### 7.4 Admin/dev surfaces
Confirm `/api/dev/*` and `/api/admin/*` all use `get_admin_user` (they did in Round 7) and the Dev tools page is unreachable/hidden for non-admins in the production build. One test that walks the FastAPI route table and fails on any `/api/dev` or `/api/admin` route without the admin dependency.

## Phase 8: Hosting on loam.thepfisters.com

### 8.1 Frontend build
- `VITE_API_BASE` (build-time): `''` in dev (Vite proxy), `https://core-node.tailcd5892.ts.net` for the production build. `frontend/src/services/api.ts:22` reads it. `grep -rn "'/api\|\"/api\|\`/api" frontend/src` and route every call through `API_BASE`, including `authedFetch`, the SSE stream, GPX/FIT downloads and anything in the service worker.
- `VITE_PUBLIC_APP_ORIGIN=https://loam.thepfisters.com` (build-time). If the app ever loads on another origin in production mode (e.g. an old installed PWA on the Funnel origin), it calls `location.replace(VITE_PUBLIC_APP_ORIGIN + path + search + hash)`. Not on `localhost`/`127.0.0.1`/`core-node.local`.
- Firebase `authDomain` for the production build: `loam.thepfisters.com` (Firebase Hosting serves `/__/auth/*` there; this avoids third-party-storage problems with redirect sign-in on Safari). Email-link `url` = `window.location.origin` + the existing finish path; confirm.
- `frontend/index.html`: production meta from the old landing page, minus "coming soon": title "Loam: mountain bike and trail running route builder", description, canonical `https://loam.thepfisters.com/`, `theme-color #1D3B34`, Open Graph + Twitter card using the existing `frontend/public/brand/png/social-card-1200x630.png` (absolute URL), JSON-LD `WebSite` + `SoftwareApplication` (free, no "not yet released"). `frontend/public/robots.txt` (allow all, sitemap link) and `sitemap.xml` (`/`, `/legal/`, `/legal/privacy/`, `/legal/terms/`, `/legal/attributions/`).
- Manifest `start_url`/`scope` stay relative.

### 8.2 API (Pi)
- `CORS_ORIGINS` on the Pi: `https://loam.thepfisters.com,https://core-node.tailcd5892.ts.net,http://localhost:5173`. Update the default in `app/config.py` and `.env.example` the same way. `allow_headers` must include `Authorization` and `Content-Type`; `allow_credentials` stays false (bearer tokens, no cookies). Confirm the SSE endpoint works cross-origin.
- New setting `PUBLIC_APP_ORIGIN` (Pi: `https://loam.thepfisters.com`, unset in dev). When set and the request's `Host` is the Funnel host, browser navigations (GET, not `/api/*`, `/health`, `/sw.js`, `/legal/*` assets excluded as needed) answer **301** to `PUBLIC_APP_ORIGIN` + path + query. LAN access (`core-node.local:8085`) is not redirected.
- **Old service worker:** browsers that installed the PWA from the Funnel origin keep a service worker there. A redirected `/sw.js` doesn't update it, so on the Funnel host serve a tiny kill-switch `/sw.js` (no redirect, `Cache-Control: no-store`) that calls `self.registration.unregister()` and navigates open clients to the new origin. Test it with Playwright: install the old SW from a local build, then switch to the kill-switch and confirm it unregisters.
- Offline routes saved on the old origin don't carry over (different origin storage). Note it in the worklog and release notes; the only real user is the owner.

### 8.3 Firebase Hosting config (repo root)
- `firebase.json` with **only** a `hosting` block: `"site": "thepfisters"`, `"public": "frontend/dist"`, SPA rewrite `{"source": "**", "destination": "/index.html"}` (the `/legal/**` files exist, so they are served as files first), `cleanUrls: false`, `trailingSlash: true` for `/legal/*` if needed.
- Headers: `/assets/**` `Cache-Control: public, max-age=31536000, immutable`; `index.html`, `sw.js`, `registerSW.js`, `manifest.json`, `workbox-*.js` `no-cache`; everywhere `X-Content-Type-Options: nosniff`, `Referrer-Policy: strict-origin-when-cross-origin`, `Permissions-Policy: geolocation=(self), camera=(), microphone=()`, and a **Content-Security-Policy derived from what the app actually loads** (record every request host in the Playwright run of a production build: CARTO tiles, the Funnel API, Firebase Auth endpoints such as `identitytoolkit.googleapis.com`, `securetoken.googleapis.com`, `apis.google.com`, frames for `loam.thepfisters.com/__/auth/` and `accounts.google.com`; MapLibre needs `worker-src 'self' blob:` and `img-src data: blob:`). The Playwright suite must report zero CSP violations (`securitypolicyviolation` listener) across all flows, signed in and out.
- `.firebaserc`: `{"projects": {"default": "thepfisters"}}`.
- **Do not include `firestore`, `storage`, `functions` or `database` keys.** The old landing page's Firestore rules belong to a shared project; leave them alone (the Owner steps cover the waitlist).
- Deploy command (Phase 10): `npx --yes firebase-tools@<pin a current version, record it> deploy --only hosting --project thepfisters`. If not logged in, **ASK** the owner to run `! npx --yes firebase-tools@<same version> login` in this tab.
- `scripts/deploy-web.sh`: `npm ci && npm run build` with the production `VITE_*` values, check `dist/` has no `.map` source maps unless intended, then the deploy command above. README documents it.

### 8.4 Dev and Pi parity
- The Pi still builds and serves `frontend/dist` (LAN use, tests). `deploy-pi.sh` builds with the same production `VITE_*` values so both bundles match.

## Phase 9: Playwright UI testing, screenshots, README

### 9.1 Test harness
- New `tests/browser/` suite with `@playwright/test` (add as a frontend devDependency, pinned) and `@axe-core/playwright` (pinned). Keep `tests/test_round7_browser.cjs` passing or fold its checks into the new suite (say which in the worklog). Use the system Chromium path the Round 7 test uses (`/usr/local/bin/chromium` or whatever exists on this machine; check, and log it).
- Target: a **production build** (`npm run build` with prod-like `VITE_*`, but `VITE_API_BASE` pointing at the local API) served by the local uvicorn against the **dev** database with the real OSM graph, 3DEP and GraphHopper. Never against prod data except the read-only smoke test (9.4).
- **Signed-in flows** use the Firebase Auth **emulator** (`firebase-tools emulators:start --only auth`, project id `demo-loam`). The backend accepts emulator tokens only when `FIREBASE_AUTH_EMULATOR_HOST` is set **and** `APP_ENV != "production"` **and** the server is bound to localhost; at startup with `APP_ENV=production` and the emulator variable set, refuse to start. Test that rule (`tests/test_round8_auth_emulator_guard.py`). The Pi `.env` gets `APP_ENV=production`.
- Viewports: 360×740, 390×844, 412×915 (mobile: `isMobile`, `hasTouch`), 768×1024, 1280×900, 1440×900. The app is dark-only.

### 9.2 Checks (each a named test)
- No pairwise overlap between the map credit, every top toggle, the heat info, the zoom/compass/locate controls and the sheet handle, in each sheet snap state, at every mobile viewport (bounding-box intersection, not visual guesswork).
- No horizontal page scroll at any viewport; tap targets ≥ 44×44 px for buttons/toggles.
- axe: zero serious/critical violations on Plan, Results, Explore, Saved, You, sign-in, and the four legal pages.
- No console errors, no failed requests (excluding deliberately blocked ones), no CSP violations.
- Midpoint UI absent (flag off); a `?via=` link loads without midpoints and shows the notice.
- No water/shops toggle anywhere.
- Strava/Trailforks absent with flags off; present with flags on (dev run).
- Legal pages load directly (cold, no SW), from the footer links, and from the sign-in screen; "Source code" link present.
- Results heading pluralization (1 and N).
- Heat info text shown when seed heat is public; no "temporarily off" text anywhere.
- Route planning end-to-end at a public trail network (below): loop builds, options listed, elevation profile and surface strip render, GPX and FIT download succeed (signed in through the emulator), report-bad-route modal shows the public-visibility notice (do not submit to GitHub from tests; stub the GitHub call at the server with the existing test fake).
- Rate-limit 429 shows a friendly inline message.
- Old-origin redirect + SW kill-switch test (8.2).

### 9.3 Screenshots for the README
- Location: a **public** trail network, not near the owner's home: **Bear Brook State Park, Allenstown NH** (the main parking area; Round 7 tested 10 and 14 mi loops there). If it doesn't produce good options, use another state park inside the 3DEP coverage and log which.
- Signed-in screenshots use an emulator test account (`rider@example.com`); no real email, UID, or token may be visible. Hide the dev/admin UI.
- Shots (save to `docs/screenshots/`, PNG, optimized to ≤ 400 KB each with `oxipng`/`pngquant` if installed, else Pillow quantize; log which):
  1. `hero-desktop.png`: 1440×900, Results with a loop selected over the heat layer, surface strip and elevation visible.
  2. `mobile-results.png`: 390×844, results sheet half-open with the route on the map (credit visible at the bottom, no overlap).
  3. `mobile-plan.png`: 390×844, Plan panel (sport, distance, terrain mix).
  4. `heatmap.png`: desktop or mobile, heat layer on with the new info text.
  5. `route-detail.png`: elevation profile + surface strip close-up of one candidate.
  6. `export.png`: GPX/FIT export menu.
  7. `you-privacy.png`: You panel with privacy controls (emulator account).
- Real app output only. No editing beyond cropping and resizing.

### 9.4 Read-only production smoke test (after Phase 10 deploy)
`tests/browser/smoke.prod.spec.ts`, run manually with `BASE_URL=https://loam.thepfisters.com`: page loads, map renders, no console/CSP errors, legal pages 200, `/api/config` reachable cross-origin with `midpoints_enabled=false`, `min_unique_riders=3`, the Funnel origin 301s to the new domain, an anonymous route request at Bear Brook succeeds if anonymous routing is allowed (else stop at the sign-in prompt). It must not sign in, save, upload or report.

### 9.5 README
Rewrite `README.md` completely; every claim backed by code (extend the audit: `docs/round8-feature-audit.md`, one row per README feature with code and test references; features the owner removed (POIs, Round 7 settings) and those hidden (midpoints, Strava, Trailforks) are listed as such, not advertised).
Structure:
1. Centered header: `<picture>` with `frontend/public/brand/loam-logo-horizontal-reversed.svg` for dark and `loam-logo-horizontal.svg` for light (`prefers-color-scheme` sources), tagline from `frontend/public/brand/BRAND.md` voice, one line: **Try it at https://loam.thepfisters.com**.
2. Badges (shields.io, brand colors from BRAND.md): License AGPL-3.0, live app, Python, FastAPI, PostGIS, MapLibre. No fake test-count or coverage badges.
3. `hero-desktop.png` full width, then a 3-up row of mobile shots (HTML table or `<p align="center">` with fixed widths).
4. "Why Loam" (3-5 short bullets: recency heat, honest loops on real OSM trails, surface strip + real elevation, privacy, Garmin export).
5. Features (screenshot-backed sections, concise).
6. Privacy (the 3-rider rule, the seed-heat disclosure, trimming, zones, export/delete, public reports).
7. How it works: a Mermaid diagram (browser → Firebase Hosting; browser → Tailscale Funnel → FastAPI on a Raspberry Pi → PostGIS + GraphHopper; Firebase Auth; 3DEP; OSM).
8. Self-hosting quickstart (docker compose, data setup steps from the current README, kept accurate), configuration table of env vars (including `ENABLE_MIDPOINTS`, `SEED_HEAT_PUBLIC`, `HEAT_MIN_UNIQUE_RIDERS`, `PUBLIC_APP_ORIGIN`, `APP_ENV`, `VITE_API_BASE`, `VITE_PUBLIC_APP_ORIGIN`, connectors), without values of secrets.
9. Development and tests (pytest, Playwright suite, emulator).
10. Deploying (Pi script with key auth setup steps; `deploy-web.sh`).
11. Data and attribution (short; links to `/legal/attributions/`).
12. License (AGPL-3.0-or-later) and contact/issues.
Remove: the old `frontend/src/assets/hero.png` if unused elsewhere, "Section 18 Guidelines", the pre-launch checklist (move what remains to `docs/launch-checklist.md`, updated), the "Open Source" generic badge. Check the README renders on GitHub (`gh api markdown` or a preview) and every image path resolves.

## Phase 10: Deploy and verify

Run in this order; log each step's result.
1. Full local suite green: `pytest -q`, `npm run build`, `npm run lint` (if configured), the Playwright suite. Paste counts in the worklog.
2. Pi backup: `scripts/backup_db.sh` on the Pi; confirm the dump file and size.
3. Pi `.env` (backup first, edit keys only, never print): remove `HEAT_MIN_UNIQUE_RIDERS` (default 3), set `ENABLE_MIDPOINTS=false`, `SEED_HEAT_PUBLIC=true`, `APP_ENV=production`, `PUBLIC_APP_ORIGIN=https://loam.thepfisters.com`, `CORS_ORIGINS` as in 8.2. Strava/Trailforks flags stay false. **Requires the Owner steps (end of this plan) 1-3 to be done** (SSH keys/sudo); if `ssh -o BatchMode=yes` fails, **ASK**.
4. `scripts/deploy-pi.sh`, run migrations 007 and 008 on the Pi, then the admin heat recalculation (`/api/dev/heat/recalculate` or the function directly on the Pi). Log public vs private edge counts per sport before and after.
5. Check the Pi directly: `/health`, `/api/config` values, the Funnel 301, the SW kill-switch.
6. `scripts/deploy-web.sh` (Firebase Hosting). This replaces the coming-soon page.
7. Smoke test 9.4 against production. Also `curl -I` the legal pages and check the CSP header.
8. **ASK** the owner to sign in with Google and with an email link on `https://loam.thepfisters.com` (phone and desktop), build a Bear Brook loop, and download a GPX. Record the result.
9. Rollback notes in the worklog: Firebase Hosting previous release (`firebase hosting:channel`/console rollback), `git revert` + `deploy-pi.sh`, `pg_restore` from step 2's dump, `.env.bak-round8`.

## Phase 11: Public-repo readiness audit (the owner flips visibility)

- Install/run a secret scanner over the **full history** (`gitleaks detect --log-opts="--all"` via its release binary or container; record the version). Also grep the history for: `github_pat_`, `ghp_`, `AIza`, `BEGIN .*PRIVATE KEY`, `sshpass -p`, `.env` files, `*.fit`, `*.gpx`, `*.tcx`, Garmin export paths, and the Pi's username used as a password.
- Coordinates: list every distinct lat/lon cluster (rounded to 0.01°) appearing in tracked files across history (`benchmark/`, `tests/`, `docs/`, `app/`) with file and first commit.
- Write the findings to **`~/dev/loam/main/data/round8-public-audit.md`** (gitignored data dir, not committed, not posted). The PR body only says the audit exists and lists counts by category, never the findings themselves.
- If anything sensitive is in history: **do not rewrite history**; recommend options in the audit (rotate; or publish a fresh single-commit repo). The owner decides.
- Repo hygiene for going public: `.github/ISSUE_TEMPLATE/` (bug report, route problem pointing to the in-app button), `SECURITY.md` (report privately to the contact email), `CONTRIBUTING.md` (short), the repo description and topics as **suggested text in the PR body** (the agent doesn't change repo settings).

## Phase 12: Finish

- Worklog complete; `docs/round8-feature-audit.md`, `docs/round8-legal-claims.md`, `docs/launch-checklist.md` committed.
- `/finish-ticket`: PR `GH-38: Round 8 prerelease: public launch on loam.thepfisters.com`, body with `Closes #38`, a summary per phase, test counts, deployed state, and the remaining Owner steps as a checklist.

## Owner steps (the agent asks for these when it reaches them; listed in the issue too)

Before Phase 10:
1. Pi SSH key login: `ssh-copy-id jjrpfister@core-node.local`.
2. Pi passwordless sudo for one command only: `echo 'jjrpfister ALL=(root) NOPASSWD: /usr/bin/systemctl restart loam-api' | sudo tee /etc/sudoers.d/loam-deploy && sudo chmod 440 /etc/sudoers.d/loam-deploy && sudo visudo -c`.
3. Change the Pi user's password (it equals the username, and the old deploy script that shows that becomes public with the repo).
4. Firebase console → Authentication → Settings → Authorized domains: add `loam.thepfisters.com`.
5. Google Cloud console → APIs & Services → Credentials → the OAuth client "Web client (auto created by Google Service)": add authorized JavaScript origin `https://loam.thepfisters.com` and redirect URI `https://loam.thepfisters.com/__/auth/handler`.
6. Firebase console → Firestore → delete the `waitlist` collection (only the owner's address). Optionally remove the `match /waitlist/{id}` block from the project's Firestore rules in the console, checking nothing else in the shared project depends on that rules file.
7. `firebase-tools login` when the agent asks.

After the PR merges:
8. Read the legal pages (templates written to match the code, not legal advice).
9. Review `~/dev/loam/main/data/round8-public-audit.md`, then make the repo public: `gh repo edit JJRPF/loam --visibility public --accept-visibility-change-consequences`.
10. Replace `GITHUB_FEEDBACK_TOKEN` (fine-grained PAT, JJRPF/loam only, Issues read/write) in the Pi `.env` and `~/dev/loam/main/.env`; revoke the old one (it was pasted into a chat).

