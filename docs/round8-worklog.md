# Round 8 worklog

Plan: `docs/round8-plan.md` (GH-38).

## Phase 1: Heat privacy back to 3, owner's heat kept as a trails-only seed

Setup: baseline `pytest -q` was 175 passed on a fresh worktree. The frontend build needs `frontend/src/data/trailheads.json`, which `.gitignore`'s bare `data/` rule ignores (and its directory doesn't exist in a new worktree). **Deviation:** `scripts/build_trailheads.py` now creates the directory; run it with the OSM extract path (`python scripts/build_trailheads.py ~/dev/loam/main/data/osm/new-hampshire-latest.osm.pbf`) before `npm run build`. The ignore rule stays, so Phase 8's `deploy-web.sh` must generate the file first (noted there).

Heat writers and readers (`grep -n "edge_heat\|is_public\|unique_riders" app/*.py`):
- Writers: `db.refresh_edge_heat` (new, the only place heat is derived from visits and `is_public` decided), called by `record_activity_edge_visits` (for the activity's edges and any edges of a replaced upload) and `recalculate_all_edge_heat` (all edges); `db.record_edge_heat` (admin `/api/heat/record`, no visit rows; sets `is_public` through `_publish_edge` -> `heat_is_public`); `delete_user_account` (deletes visits, then recalculates); `account_migration` (re-keys `contributor_ids`).
- Readers: `get_edge_heat` (`/api/edges/{id}`), `get_edges_heat` (routing and scoring: `routing.py`, `route_builder.py`), `get_heat_trail_geojson` (`/api/heat/trails`), `get_unridden_high_heat_trails` (Explore "new to you"), `SeedLoopCatalog.get_matching_seeds`, `scoring.score_heat`.

What changed:
- `app/decay.py`: `TRAIL_CLASS_HIGHWAYS` and `heat_is_public(unique_riders, has_seed, highway)`; `aggregate_edge_visits` uses it. `app/config.py`: `seed_heat_public` (`SEED_HEAT_PUBLIC`, default true); `heat_min_unique_riders` stays 3.
- Migration `007_round8_seed_heat.sql`: `activity_edge_visits.is_seed`, `edge_heat.has_seed`, backfilled from `activities.source = 'garmin_export'`. The visit insert sets `is_seed` from the activity's `source` (the import sets it before it records visits).
- Bugs fixed: any single upload set `is_public = TRUE` until the next recalculation; `record_edge_heat` hard-coded `>= 3`; `get_unridden_high_heat_trails` filtered `unique_riders >= 1 OR weighted_score >= 1.0` (now `is_public`).
- Further leaks found in the readers and fixed: `get_edge_heat` returned the counts, score and last-ridden date of a private edge to anyone (it now zeroes them unless the viewer contributed); and for a contributor on a private edge, `get_edges_heat`/`get_edge_heat` returned the edge's total score including other riders' passes, so they now return only the viewer's own contribution (`_own_heat`, from their visits).
- Seed loops: a loop is also offered to everyone when it comes from an admin-imported ride and >= 85% of its length (by `trail_segments.length_m`, `segment_ids`) is trail-class and `SEED_HEAT_PUBLIC` is on. The candidate still starts at the requester's own start (existing bridging); the seed's start is never exposed.
- `/api/heat/meta` returns `{min_unique_riders, seed_heat_public}`. `SEED_HEAT_NOTICE` and its chip are gone. The info text ("Heat shows trails ridden by 3 or more people in the past year. To get started, it also includes Loam's creator's own rides on trails.") is `heatInfoText(meta)` in `api.ts`, shown in the Explore panel and behind an "i" button (44 px) in the map's toggle row that opens a note under the row. README's checklist line was reworded; `docs/round7-*` are history and keep their old wording.
- Privacy zones: Round 7's strip step removed the home and start zones from the stripped tracks before upload (see the Garmin strip entry in `docs/round7-worklog.md`); nothing was re-imported.

Tests: new `tests/test_round8_heat_privacy.py` (17): rule unit; defaults; one non-seed rider is private through the heat GeoJSON, unexplored trails, a routing lookup for another user, `/api/edges`-style lookup and `/api/heat/trails`, right after upload and after recalculation; a contributor sees only their own contribution; 3 riders public; seed visits public on path/track/bridleway/cycleway and private on residential/footway/service/unclassified; `SEED_HEAT_PUBLIC=false`; account deletion; migration backfill; seed loop gating (trail loop offered to another user, off when the flag is off; road-heavy loop never). Mutation check: adding `residential` to the trail classes fails 2 of them. Updated: `test_round7_heat.py` (meta), `test_api.py::test_heat_record_and_query` (one rider is hidden from anonymous), `test_round7_no_fabrication.py` (the dev DB now holds real imported seed loops, so the test asserts they all trace to `garmin_export`). `pytest -q`: 192 passed. `npm run build`: OK.

## Phase 2: Midpoints behind a flag (off in production)

What changed:
- `app/config.py`: `enable_midpoints` from `ENABLE_MIDPOINTS`, default false; `.env.example` has the plan's line; my worktree `.env` has `ENABLE_MIDPOINTS=true` (not printed or committed).
- `GET /api/config` returns `{midpoints_enabled, min_unique_riders, seed_heat_public, connectors: {provider: enabled}, source_url}` (`ConnectorManager.enabled_map()`). `/api/heat/meta` still works.
- Server: `apply_midpoint_flag` runs in `/api/route`, `/api/route/options` and the POST stream. With the flag off it empties `waypoints` and the response carries `notice: "Midpoints are turned off for now, so this route ignores them."` (`RouteResponse.notice` is new for `/api/route`; the options response and the stream's `complete` event join it with any existing notice). No 400s. The flag is enforced at the endpoints, not in `plan_route_options`, so Round 7's `test_loop_honors_midpoint` is untouched. The GET stream takes no waypoints at all, so there is nothing to ignore there; a test covers it.
- Frontend: new `services/config.ts` (`useAppConfig`, `loadAppConfig`; defaults are midpoints and connectors off if `/api/config` is unreachable). The Midpoints block in `PlanPanel` and the `'mid'` tap mode only work when enabled. `urlState.encodeSearch` writes `via=` only when enabled. **Deviation:** the plan says `urlState.ts` drops `via=` on parse; it still parses it, and `App.handleBuildRoutes` ignores shared midpoints while the flag is off (so the same link works in a dev build with the flag on) and adds the notice. A shared-link search waits for `/api/config` before it runs. `MapView` has no midpoint markers (it accepts a `waypoints` prop it never drew), so there was nothing to hide; App passes it `[]` when the flag is off. Saved routes containing waypoints display as before.

Tests: new `tests/test_round8_midpoints_flag.py` (6): flag default; flag off ignores waypoints with the notice on `/api/route`, `/api/route/options` and the POST stream (the builder never sees them); no notice without waypoints; the GET stream; flag on passes them through; `/api/config` shape. `pytest -q`: 198 passed. `npm run build` OK, `npm run lint` clean. The browser check is in Phase 9.

## Phase 3: Remove the water & shops layer

What changed: `MapView.tsx` lost `showPois` and its ref/data ref, `loadPoisForView`, the `pois-source`/`pois-circles`/`pois-labels` layers, the `moveend` hook part, the sync effect and the "Water & shops" toggle; `api.ts` lost `fetchPois` (there were no separate POI types). Backend: `GET /api/pois` and `scripts/import_osm_pois.py` are deleted; migration `008_round8_drop_pois.sql` runs `DROP TABLE IF EXISTS pois` (006 stays as history; the Pi gets a `pg_dump` first in Phase 10). Tests: `test_pois_come_from_the_osm_import` removed from `test_round7_extras.py`; `test_round7_browser.cjs` now asserts the toggle is absent. README: the colour table no longer lists water as the Slate use. The feature audit's "marked removed by owner in Round 8" row is written in Phase 9 (`docs/round8-feature-audit.md`).

`grep -rniw "poi\|pois\|water\|shop\|shops" app frontend/src scripts tests README.md`: only the Garmin activity-type comment "Water sports & golf" (unrelated), the new absence assertion and a docstring remark. Note: `test_round7_browser.cjs` still exercises the midpoint UI, so it must run against a dev server with `ENABLE_MIDPOINTS=true`; Phase 9 folds it into the new suite. `pytest -q`: 197 passed (the POI test is gone). `npm run build` OK, lint clean.

## Phase 4: Mobile map layout

What changed:
- Map credit: `App.tsx` sets `--sheet-offset` (`calc(<sheet height> + 8px)`, per snap state; `0px` on desktop) and `data-sheet` on the map container. `index.css`: below 800 px `.map-attribution-badge` sits bottom-left at `bottom: var(--sheet-offset)` (animated with the sheet), with `max-width: calc(100% - 76px)` so it clears the right-hand controls; in `full` it is hidden. Desktop stays bottom-right. Mobile text: "© OpenStreetMap · © CARTO · Legal" (all links; "Legal" goes to `/legal/`, built in Phase 6); desktop keeps "contributors".
- Top row: `MapView` toggle row wraps and is capped at `100% - 76px`, so nothing runs under the zoom/compass/locate controls. Buttons already get `min-height: 44px` from `index.css`.
- `ResultsPanel`: "1 candidate route" / "N candidate routes" ("Selected route", "Building candidate routes..." in sentence case too).
- Quick check, not the Phase 9 suite: a Playwright run at 360x740, 390x844 and 412x915 (half-open sheet) measured the badge's bottom exactly 8 px above the sheet's top and well left of the right controls (badge right edge 205 px vs controls from 321 px at 360 wide), and no horizontal scroll. I also looked at the 360 px screenshot. The full overlap matrix in all snap states is Phase 9.
- The scale control is bottom-left and so sits behind the sheet on mobile; left as is. `MapView`'s unused `waypoints` prop is untouched.

`npm run build` OK.

## Phase 5: Hide disabled connectors

`YouPanel.tsx` renders only connectors whose status has `enabled === true` (from `/api/connectors`): no card, no "Disabled" badge (the "Enabled" badge went too, since it would always say so), and the Garmin, Trailforks, Strava and CubeTrek modals open only for an enabled connector. The section title is "Connected services", and the intro is built from the enabled names ("Connect Garmin Connect and CubeTrek to sync your activities into your private heat. Passwords are never stored; tokens are encrypted at rest."; "No services are available to connect right now." if none). `grep -rni "strava\|trailforks" frontend/src`: only `api.ts` (client functions) and `YouPanel.tsx` code reachable from an enabled connector; there is no Trailforks attribution elsewhere in the UI. Backend unchanged apart from `/api/config` (Phase 2). New `tests/test_round8_connectors_hidden.py` (2): `/api/config` connectors follow each flag; the signed-in connector list agrees with it and Strava/Trailforks default off. The browser check (absent with flags off, present with flags on) is in Phase 9. `npm run build` OK, lint clean.

## Phase 6: Legal pages, license, source link

Pages (`frontend/public/legal/`): `/legal/` index and `privacy/`, `terms/`, `attributions/` as directory `index.html` files, plus `legal.css` and `contact.js` (the contact address is assembled in the browser from parts; without JS the pages show "jjrpfister at gmail dot com"; an external script rather than inline so a strict CSP in Phase 8 works). Dark, system font. **Deviation:** the plan says Atkinson Hyperlegible "if already bundled"; it is not bundled (the app loads it from Google Fonts in `index.html`), so the legal pages use the system font, and the privacy policy discloses the Google Fonts request. The effective date is the build date, October 13, 2026 (`gen` script was a throwaway; edit the dates in the four pages if the launch day differs, see Phase 10). `vite.config.ts`: `/legal/` added to `navigateFallbackDenylist`. Served by the Pi's `StaticFiles(html=True)` and (Phase 8) Firebase Hosting; a local check returned 200 for each page, the `.txt`, the CSS and JS, and a redirect from `/legal/privacy` to `/legal/privacy/`.

Claims audit (`docs/round8-legal-claims.md`, checked by `tests/test_round8_legal.py`). Verifying the claims against the code found real problems, fixed here (**Deviation:** outside the written plan, needed for the policy to be true before the repo goes public):
- Public endpoints returned contributors' Firebase UIDs: `/api/flags`, `/api/trails/{id}/checkins`, `/api/trails/{id}/status` and `/api/submissions` (list and single). They now return `user_id: null` (a rider's own POST responses still carry theirs).
- `DELETE /api/privacy/account` raised a foreign-key error for anyone with a trail submission (`trail_submissions.user_id` has no cascade), and the endpoint ignored the result. It now removes unverified submissions, unlinks verified ones, deletes the private `route_reports` snapshots (they were left behind with the full route), and returns a 500 with "nothing was removed" if deletion fails.
- `/api/privacy/export` now also includes route reports and trail submissions.
- The 3-rider and seed claims are covered by Phase 1's tests.
Findings I did not change: the browser loads Google Fonts (disclosed; self-hosting would remove it); the nightly backup cron is installed on the Pi (checked by `ssh`, read-only) but its first run is 03:15 on the 14th, so I confirm the dump in Phase 10; two older one-off dumps sit on the Pi (`loam-pre-round7-*`, `pre-deploy2/`), listed as an owner step; uvicorn's request log (journal, rotated by size) includes the start point of GET route-stream URLs, which the policy states; the Firebase Authentication record is not deleted by account deletion (no Admin SDK), also stated in the policy. `psycopg2-binary` is LGPL with the linking exception (compatible with AGPL).

Links: `LegalLinks` (Privacy, Terms, Attributions, Source code) in the You panel footer and the desktop sidebar footer; `SignInAgreement` ("By continuing you agree to the Terms and acknowledge the Privacy Policy.") in the sign-in card; "How heat works" links (to `/legal/privacy/#heat`) next to the upload "Contribute Heat" checkbox and the You-panel consent toggle; the report-bad-route modal's notice now says the report is filed as a public GitHub issue and links `/legal/privacy/#reports` (the old text said it would become public only when the code is released). The source link comes from `/api/config` (`source_url`). The map credit's "Legal" link is Phase 4's.

Licenses: `LICENSE` is the GNU AGPL v3 text from gnu.org (SHA-256 of whitespace-normalized text `2cd0fb78...c86c46`). Checked against SPDX's `AGPL-3.0-or-later.txt`: identical after whitespace normalization except that SPDX has `http://` where gnu.org now has `https://` in three URLs (fsf.org, two gnu.org/licenses), so I kept the gnu.org text. `frontend/package.json` and the lock file carry `"license": "AGPL-3.0-or-later"`; there is no Python project metadata file to update. `scripts/gen_third_party_licenses.py` writes `frontend/public/legal/attributions/third-party.txt` (114 production npm packages from the lock file; the Python packages from `requirements.txt` and their runtime dependencies from the installed metadata, skipping marker-excluded ones).

Tests: new `tests/test_round8_legal.py` (7), `tests/test_round8_public_privacy.py` (2; a mutation that stops blanking `user_id` on `/api/flags` fails it). `pytest -q`: 208 passed. `npm run build` OK, lint clean. Rendered check: `/legal/privacy/` at 390 px has no horizontal scroll and the contact link is built; the You panel shows the footer links. The sign-in sentence needs Firebase config to render and is checked with the emulator in Phase 9.

## Phase 7: Production hardening for a public launch

Rate limits: `app/ratelimit.py` (token bucket per client IP; `client_ip` trusts the last X-Forwarded-For entry only when the peer is loopback, i.e. the Funnel/proxy). Limits via env (`RATE_LIMIT_ROUTE=20/600`, `GEOCODE=60/60`, `UPLOAD=30/3600`, `FLAG=60/3600`) on route generation (all four endpoints), geocode, upload, flags, flag vote, check-in; a global cap of 30 bad-route reports per day (counted from the DB via `reports.count_recent_global`); a route-generation semaphore (2 at a time, waits up to 20 s, then 429). 429s carry `Retry-After` and a friendly message. Photon geocode results are cached for 1 hour; Overpass fallback uses a 0.05 degree tile cache (24 h; failures 5 min); NWS cache honors Cache-Control within 900 to 3600 s. One User-Agent (`settings.user_agent`) on every outbound call (NWS, Overpass, Photon, GitHub reports, Strava, CubeTrek). A test walks the route table and requires `get_admin_user` on every `/api/dev` and `/api/admin` route.

Frontend: `RateLimitError` handling in `services/api.ts`; rate-limit and route failures show inline (`setOptionsNotice`) instead of `alert`; geocode is debounced 350 ms with an inline notice; the "Developer Tools and Operations" link shows only for admins.

Scripts: `scripts/deploy-pi.sh` is key-auth only (`BatchMode`, preflight for the key and for passwordless `sudo systemctl restart loam-api`), builds via the new `scripts/web-build-env.sh`; `scripts/funnel-start.sh` header describes the real architecture; the password wording in `docs/round7-worklog.md` was removed.

Deviations:
- Removed the ResultsPanel "Still Open check-in" and "Report Trail Issue" buttons: they posted to fabricated edge IDs (999202, 999101), which breaks the no-fabrication rule. The YouPanel DNR placeholder no longer suggests a fake ID.
- Geocode debounce added (not itemised in the plan) because per-keystroke calls would burn the geocode limit.
- The global report cap is counted from the DB rather than kept in memory, so it survives restarts.
- The stream endpoint reports a 429 as an `event: error` (status, retry_after) since headers are already sent once streaming starts.
- Overpass tiles enlarge the queried bbox to tile bounds (more data per call, far fewer calls).
- The XFF "last entry" choice is verified through Funnel in Phase 10.

Tests: `tests/test_round8_ratelimit.py` (12). The legal-claims test no longer exempts the Phase 7 files. `pytest -q`: 220 passed. `npm run build` OK.

## Phase 8: Hosting on loam.thepfisters.com

Frontend: every API call already went through `API_BASE`; it now reads `VITE_API_BASE` (empty in dev). `services/origin.ts` + `main.tsx`: in a production build, a page loaded from any origin other than `VITE_PUBLIC_APP_ORIGIN` (not localhost, 127.0.0.1, core-node.local) does `location.replace(origin + path + search + hash)` before React renders. `scripts/web-build-env.sh` sets the production `VITE_*` values (API base, public origin, `VITE_FIREBASE_AUTH_DOMAIN=loam.thepfisters.com`); the email-link URL is `window.location.origin + /auth/finish`, so it follows the origin. `index.html` has the production title, description, canonical, Open Graph and Twitter tags (absolute social-card URL) and JSON-LD (`WebSite` and `SoftwareApplication`, free); `robots.txt` and `sitemap.xml` added.

API: `CORS_ORIGINS` default and `.env.example` now include `https://loam.thepfisters.com`; new `PUBLIC_APP_ORIGIN` (and `API_PUBLIC_HOST`, default the Funnel host). When set, GET/HEAD requests whose Host is the Funnel host (other than `/api/*` and `/health`) get a 301 to the public origin with path and query; `/sw.js` on that host is a no-store kill-switch worker (unregisters itself, navigates open tabs). LAN hosts are not redirected.

Hosting: `firebase.json` (hosting block only, site `thepfisters`, `frontend/dist`, SPA rewrite, cache headers, security headers and a CSP), `.firebaserc`, `scripts/deploy-web.sh` (pinned `firebase-tools@15.33.0`, `deploy --only hosting --project thepfisters`, refuses source maps, checks the bundle carries the API base). `deploy-pi.sh` builds through the same `web-build-env.sh`, so the Pi's bundle matches.

Deviations:
- The repo tracked `frontend/public/assets/maplibre-gl-worker-dev.mjs` and three `.map` files (about 6 MB) that the deploy would publish; I removed the dev worker and the maps from the repo and stripped the `sourceMappingURL` comment from the production worker. The oxlint config now ignores the vendored worker.
- The CSP is a first version from the code's known hosts (CARTO tiles, Funnel API, Google/Firebase auth hosts, Google Fonts); Phase 9 records real loads and zero CSP violations before it is final.
- The Playwright test for the kill-switch worker (plan 8.2) is part of Phase 9; Phase 8 tests the endpoint itself.
- Offline routes saved on the old Funnel origin do not carry over (different origin storage); the owner is the only user, so no migration.

Tests: `tests/test_round8_hosting.py` (7: redirect, exclusions, kill switch, CORS, firebase.json and deploy script hosting-only).

## Phase 9: Playwright UI testing, screenshots, README

## Phase 10: Deploy and verify

## Phase 11: Public-repo readiness audit

## Phase 12: Finish
