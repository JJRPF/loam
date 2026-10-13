# Legal claims audit (Round 8, GH-38)

One row per factual claim in `frontend/public/legal/{privacy,terms,attributions}/index.html`, with the code that makes it true (`path::symbol`; `tests/test_round8_legal.py` checks every referenced file exists and contains the symbol). Statements of policy (age 13+, governing law, no warranty) are not factual claims about the code and are not listed.

## Privacy policy

| Claim | Where it is true |
|---|---|
| Account data kept: Firebase UID, email, display name | `db/init_schema.sql::users`; `app/db.py::ensure_user_exists` (the only writer; no photo column) |
| The Google profile photo is not stored on the server | `db/init_schema.sql::users` has no photo column; the photo lives in the browser's cache only, `frontend/src/services/auth.ts::PROFILE_CACHE_KEY` |
| Uploads are read in memory, trimmed 0.2 mi at both ends and by privacy zones | `app/main.py::upload_activity`; `app/privacy.py::apply_privacy_filters`, `TRIM_METERS` |
| What is stored of an upload: date, sport, distance, duration, file type, trail segment visits; not the file or GPS points | `app/db.py::record_activity` (columns), `app/db.py::record_activity_edge_visits`; `raw_file_path` is always `None` in `upload_activity` (the "retain file" flag is recorded but nothing is written to disk); bulk import keeps no points either (`app/heat_import.py`) |
| Unchecking the contribution box records the activity but adds no heat | `app/main.py::upload_activity` (`if consent_given and matched_edges_count > 0`) |
| Saved routes include the route line | `db/init_schema.sql::saved_routes` (`geom`) |
| Flags, check-ins and submissions are public but do not show who made them | `app/main.py::list_flags`, `list_trail_checkins`, `check_trail_status`, `list_submissions`, `get_submission` (user id blanked); `tests/test_round8_public_privacy.py`. **Fixed in Round 8:** these used to return the contributor's Firebase UID |
| Privacy zones and consent are stored per account | `db/init_schema.sql::user_privacy_zones`, `contribution_consent` |
| Connector session tokens are encrypted; passwords are not stored | `app/connectors/encryption.py::encrypt_token` (Fernet); `app/connectors/garmin.py` (credentials are used for the login call only). A CubeTrek link stores a marker, not a secret (`app/connectors/cubetrek.py`), which the policy words as "other connected-service records" |
| Server logs: time, URL, status, address; rotated by the OS | uvicorn's access log to the systemd journal (`loam-api` unit on the Pi, `ExecStart=... uvicorn app.main:app`); the journal rotates by size (journald default). The GET route stream carries the start point in its URL (`app/main.py::stream_route_options_get`). Not analysed: nothing reads the journal |
| Heat: per trail segment, 12 months, newer rides count more | `app/decay.py::WINDOW_DAYS`, `HALF_LIFE_DAYS`; `app/db.py::refresh_edge_heat` |
| 3-rider minimum for public heat; below it only the contributor sees their own contribution | `app/decay.py::heat_is_public`; `app/db.py::get_edges_heat`, `get_edge_heat`, `get_heat_trail_geojson`, `get_unridden_high_heat_trails`; `tests/test_round8_heat_privacy.py` |
| The creator's imported rides are public as seed heat, on trail-class edges only | `app/decay.py::TRAIL_CLASS_HIGHWAYS`, `heat_is_public`; `app/config.py::seed_heat_public`; migration `db/migrations/007_round8_seed_heat.sql` |
| Heat never shows who rode | `app/models.py::EdgeHeatDetailResponse` and `app/db.py::get_heat_trail_geojson` return counts and scores only; `contributor_ids` is never serialized |
| A route from the creator's rides starts from the rider's own start | `app/garmin_seeds.py::SeedLoopCatalog.build_candidate` (stem from `req.start`) |
| Bad-route reports are public GitHub issues with the line trimmed 0.5 mi at each end, no start/end/midpoint coordinates, a hash instead of the user | `app/reports.py::REPORT_TRIM_M`, `trimmed_line`, `_inputs`, `build_issue_body`, `user_hash` |
| The comment is posted word for word | `app/reports.py::build_issue_body` (only `@` is neutralized) |
| The full report is kept privately on the server | `db/migrations/004_round7_route_reports.sql::route_reports`; `app/reports.py::store_report` |
| No ads, no analytics, no tracking cookies | grep of `frontend/src`, `frontend/index.html` and `app/` finds no analytics SDK and no `document.cookie`; Firebase Analytics is not initialized (`frontend/src/services/firebase.ts`) |
| Third parties contacted by the browser: Firebase (Auth, Hosting), CARTO tiles, Google Fonts | `frontend/src/services/firebase.ts`; `frontend/src/components/MapView.tsx::buildMapStyle`; `frontend/index.html` (Google Fonts link) |
| Third parties contacted by the server: Photon, NWS, Overpass, GitHub | `app/main.py::photon_search`; `app/weather.py::NWS`; `app/otm.py::OVERPASS_API_URL`; `app/reports.py::GITHUB_API` |
| The server is a home computer reached through Tailscale Funnel | `scripts/funnel-start.sh`; plan context in `docs/round8-plan.md` |
| Browser storage: sign-in state, profile cache, email typed for a sign-in link, last routes offline, service worker cache | `frontend/src/services/auth.ts`; `frontend/src/services/offlineRoutes.ts`; `frontend/vite.config.ts` (PWA precache) |
| Export everything Loam holds about you | `app/main.py::export_my_data`; `app/db.py::export_user_data` (now also route reports and submissions) |
| Deletion removes activities, visits, routes, flags, check-ins, zones, consent, connectors, private report copies; heat is recalculated | `app/db.py::delete_user_account` (explicit deletes plus `ON DELETE CASCADE` from `users`); `tests/test_round8_public_privacy.py`, `tests/test_round8_heat_privacy.py::test_account_deletion_removes_a_contributors_effect`. **Fixed in Round 8:** deletion used to fail for anyone with a trail submission and left report snapshots behind |
| Unverified submissions are deleted, verified ones lose their author | `app/db.py::delete_user_account` |
| Public GitHub issues stay; Firebase sign-in record stays until the owner removes it | No GitHub or Firebase Admin call exists in `delete_user_account` or in the frontend (`deleteMyAccount` calls only `/api/privacy/account`) |
| Nightly backup, 7 days | `scripts/backup_db.sh` (`KEEP_DAYS=7`), installed in the Pi user crontab at 03:15. **Checked 2026-10-13:** the crontab entry exists; the first run is 03:15 on the 14th, so the first dump is confirmed in Phase 10 of the worklog |
| One-off backups are deleted when the change is verified | A practice, not code. The Pi currently holds two older one-off dumps (`loam-backups/loam-pre-round7-*.dump`, `loam-backups/pre-deploy2/`); removing them is an owner step in the PR checklist |

## Terms of use

| Claim | Where it is true |
|---|---|
| Routes are computer-generated and can include closed or non-existent trails | `app/route_builder.py`, `app/trail_graph.py` build from OSM tags; `app/db.py::check_route_trust_layer` warns but cannot know about closures |
| Rate limits apply | `app/ratelimit.py` (Phase 7), `tests/test_round8_ratelimit.py` |
| Accounts can be suspended | The operator can remove a user row or disable the account in Firebase; there is no in-app admin action, so the terms say "can be", not "will be" |
| Map data is ODbL, code is AGPL | `LICENSE`, `frontend/package.json::license` |

## Attributions

| Claim | Where it is true |
|---|---|
| OSM routing network, tags | `scripts/import_osm_graph.py` |
| CARTO basemaps | `frontend/src/components/MapView.tsx::buildMapStyle` |
| USGS 3DEP elevation | `scripts/fetch_3dep.py`, `app/elevation.py` |
| PAD-US land boundaries | `scripts/import_padus.py` |
| OpenTrailMap / Overpass | `app/otm.py` |
| Photon | `app/main.py::photon_search` |
| NWS | `app/weather.py` |
| GraphHopper | `docker-compose.yml` (graphhopper service) |
| MapLibre GL JS | `frontend/package.json` (`maplibre-gl`) |
| Firebase | `frontend/package.json` (`firebase`), `app/auth.py` |
| Font is loaded from Google Fonts, not bundled (SIL OFL) | `frontend/index.html`, `frontend/src/index.css::--font-family` |
| Dependency list generated from lock file and installed packages | `scripts/gen_third_party_licenses.py`, `frontend/public/legal/attributions/third-party.txt` |

## Observations the owner may want to act on

- The font comes from Google Fonts, so every visitor's browser contacts Google for it (disclosed in the policy). Self-hosting it would remove that contact; not done because it was outside the plan.
- `psycopg2-binary` is LGPL with the linking exception; compatible with AGPL. Everything else in `third-party.txt` is permissive except `certifi` (MPL-2.0, unmodified).
