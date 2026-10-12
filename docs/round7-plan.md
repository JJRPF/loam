# Round 7 execution plan (GH-34)

This plan was written in the grove launcher after auditing the code, issue #34, the original planning chat (`~/Work/ClaudeChatLoam.md`), `docs/trail-route-builder-plan.md`, `docs/agent-build-brief.md`, the README and Rounds 1-6 (#17, #19, #26, #28, #30, #32). **Execute it; don't re-plan it.** If a step turns out to be wrong or impossible, stop that step, write down why in the PR description and the work log, do the nearest safe thing, and carry on with the rest. Never fill a gap with invented data.

Commit this file as `docs/round7-plan.md` in your first commit. Keep a running log in `docs/round7-worklog.md`: what you did, what you measured, and what you deviated from and why.

## 0. Ground rules (read first, they override convenience)

1. **No fabricated data, ever.** No hand-typed coordinates, invented distances, synthetic elevation, made-up heat, demo tracks, or "realistic fallbacks" shown to a user as real. If real data isn't available, the UI says so ("Elevation unavailable", "No true loop near here"). This round exists largely because earlier rounds broke this rule (section 1).
2. The guardrails in `docs/agent-build-brief.md` still apply. Don't change the router, firewall or DNS. Keep secrets out of the repo, logs and issue text. Keep dev and prod databases separate. Run `pg_dump` on the Pi **before** any prod migration or delete. Run no other destructive command without approval. This plan approves exactly the prod deletions in section 3.4, after the backup.
3. **Data lives once** (grove rule). Gitignored data, the Garmin export, stripped tracks, the 3DEP tiles and the OSM extract stay under `~/dev/loam/main/data/` (`DATA_DIR` is already that absolute path). Never copy them into the worktree, never commit them.
4. **Never commit, upload or copy the full Garmin export** (`~/Downloads/a638476f-fcb3-4ccf-b7d2-5621fcad15ac_1/`). Only stripped GPS tracks (lat, lon, time; trimmed; privacy-zone filtered) may leave this machine (section 6).
5. **Never commit the user's home or start locations.** Test scenarios use public trailheads and parking taken from OSM, not "Current GPS Location".
6. Explicit removals stay removed. Don't re-add: light mode or any theme toggle (#28), start-location preset dropdown (#17), bike types that don't change routing (#17), the official Garmin API, a paid or Pro tier (only donations and contributor perks), real-time safety features (chat: "no"), misleading "Connected Device" copy (#28), dev tools inside the You panel (#26).
7. Tests: `PYTHONPATH=. pytest -q` and `cd frontend && npm run build` must pass at every commit you push. New behaviour gets tests. Delete or rewrite tests that assert fabricated behaviour (e.g. curated seeds, mock-token auth in prod paths); say which in the work log.
8. Commit in small, labelled commits (`GH-34: <phase>: <what>`). Push the branch as you go. When everything in section 10 passes, run `/finish-ticket` (PR body includes `Closes #34`).

## 1. What's actually wrong (audit findings this plan acts on)

| # | Finding | Evidence |
|---|---|---|
| A | The route in the #34 screenshot ("Bow Forest Grand Loop", 10.0 mi, "100% singletrack", "True Loop") is a **hard-coded seed**: 11 typed coordinates, a fixed 9.97 mi, every segment labelled singletrack, ascent fixed at 150 m. That's why it draws as straight lines between about 7 points. | `app/garmin_seeds.py:_init_curated_seeds`, `app/routing.py` ~L963-985 |
| B | `edges` contains **hand-made "Bow Town Forest" trails** (about 5 made-up points each, invented `length_m`), a fake activity and invented heat (`passes: 22`, `is_public = TRUE`). | `app/db.py:ingest_bow_ride_data_and_trails`, `POST /api/dev/bow/ingest` |
| C | The Round 6 contracted-graph loop search is **never called** (`ContractedTrailGraph` is only imported). It also has bugs: edges walked backwards (v→u) aren't reversed; it snaps junctions within 35 m instead of using real OSM node topology; raw OSM `surface` values (`asphalt`, `ground` …) default to "singletrack"; the surface strip is one segment; elevation is `85 ft × miles`. | `app/contracted_graph.py` |
| D | `edges` geometry comes only from curated rows plus map-match captures. There's **no real OSM topology import**, so loops can't be found from data. | `app/db.py:upsert_edge_geometries`, no osmium/osm2pgsql |
| E | **Elevation is synthetic** whenever GraphHopper returns none, and GH has no elevation configured, so it's always synthetic. The README claims USGS 3DEP 10 m. | `app/routing.py` ~L286, `data/graphhopper/config.yml` |
| F | Options can come back as 3 cards, including a 0.3 mi "match 40" card. | screenshot, `select_options` final fallback |
| G | **Authentication is broken.** `X-User-Id` is trusted as identity. JWT signatures are never verified. A non-JWT bearer becomes the uid. Unauthenticated requests become `justin_default_user`. `X-User-Id: jjrpfister@gmail.com` grants admin. `DEVELOPER_ADMIN_KEY` has a default in code. Anyone can export or delete any account. The "email sign-in" just makes up `google_<email>` uids. | `app/main.py:verify_google_id_token`, `resolve_user_id`, ~L1440-1452; `frontend/src/services/auth.ts:loginWithRealCredentials`; `api.ts` `X-User-Id` |
| H | The settings panel shows non-settings: Display Theme, Units (fixed), Endpoint Trimming (mandatory, so the checkbox is misleading), Privacy Threshold. The UI also has "(Round 4)" copy. | `frontend/src/components/YouPanel.tsx` ~L375-440 |
| I | No service worker, so no offline PWA (the README and plan §18 claim offline support). | `frontend/` has `manifest.json` only |
| J | The CubeTrek connector returns a "realistic fallback demo track in Bear Brook". | `app/connectors/cubetrek.py` ~L152 |
| K | The Round 5 benchmark scenarios are synthetic archetypes (`loam_eval/synth.py`), so its tuning results don't show real routing quality. | `benchmark/scenarios.json` |
| L | The README is stale or wrong in places: "55 tests" badge, `/api/routes/options/stream` (the real path is `/api/route/options/stream`), claims of offline support and 3DEP. | `README.md` |

## 2. Execution order

Phase 1 Auth → Phase 2 remove fabricated data → Phase 3 real OSM topology and 3DEP elevation → Phase 4 routing (#1) → Phase 5 Garmin heat import (#4) and real loop seeds → Phase 6 settings (#3) → Phase 7 report bad route (#6) → Phase 8 README/plan feature audit → Phase 9 verify and deploy. Security goes first because the Pi is publicly reachable.

Work **locally first**: `docker compose up -d graphhopper postgis` from the worktree (volumes resolve to `main/data`), plus a local dev DB. Touch the Pi only in Phase 9 (and the section 3.4 backup and cleanup).

## 3. Phase 1: Authentication and authorization (#34 item 2)

**Decision (user, 2026-10-12): Firebase Auth on GCP project `thepfisters` with two providers: Google, and passwordless email link. No passwords.** Firebase (Identity Toolkit) is already enabled on that project.

### 3.1 Frontend
- Add the `firebase` npm package (modular SDK; pin an exact version at least two weeks old). Config comes from env: `VITE_FIREBASE_API_KEY`, `VITE_FIREBASE_AUTH_DOMAIN` (`thepfisters.firebaseapp.com`), `VITE_FIREBASE_PROJECT_ID=thepfisters`, `VITE_FIREBASE_APP_ID`. Add them to `.env.example` with no values. Get the web app config from the Firebase console or `gcloud`/Firebase REST read-only calls; if there's no web app registered for Loam, list that under "manual steps" and don't create one silently.
- New `frontend/src/services/firebase.ts`: `initializeApp`, `getAuth`, `browserLocalPersistence`.
- Rewrite `services/auth.ts`:
  - `signInWithGoogle()`: `signInWithPopup(GoogleAuthProvider)`, falling back to `signInWithRedirect` when the popup is blocked or on iOS standalone PWA.
  - `sendEmailLink(email)`: `sendSignInLinkToEmail` with `actionCodeSettings = { url: <current app origin, i.e. the Funnel URL in prod>/auth/finish, handleCodeInApp: true }`. Store the email in localStorage (`loam_email_for_signin`).
  - On app load: if `isSignInWithEmailLink(auth, location.href)`, finish with `signInWithEmailLink`. If the stored email is missing (opened on another device), ask for it. Then clean the URL with `history.replaceState`.
  - `onAuthStateChanged` drives app state. `getIdToken()` before every API call; refresh on 401 once.
  - `signOut()`.
  - Delete `loginWithRealCredentials`, `DEFAULT_GOOGLE_CLIENT_ID`, the GIS button code and the "enter any email" form in `YouPanel.tsx` and `DevToolsPage.tsx`.
- `services/api.ts`: one `authedFetch` that adds `Authorization: Bearer <idToken>`. **Remove every `X-User-Id` header.** Don't cache the user object as a source of truth; a localStorage copy may only pre-render the avatar.
- Sign-in UI (You panel): a "Continue with Google" button, plus an email field with "Email me a sign-in link". Then the message "Check your inbox. The link signs you in on this device." Show errors plainly. Follow the section 18 design tokens and dark-only styling.

### 3.2 Backend
- Add `google-auth` (and `requests` or `cachecontrol` for its transport) to `requirements.txt`. New `app/auth.py`:
  - `verify_firebase_token(token)` uses `google.oauth2.id_token.verify_firebase_token(token, request, audience=settings.firebase_project_id)`. That checks the signature against Google's securetoken certs (cached), `aud`, `iss = https://securetoken.google.com/<project>`, `exp` and `auth_time`. Require a non-empty `sub`. For email-link users, require `email_verified == true`.
  - `get_current_user` (FastAPI dependency, required: 401 if missing or invalid) and `get_optional_user` (None if there's no header; 401 if a header is present but invalid).
  - Admin = verified token email in `ADMIN_EMAILS` (env, comma-separated; set to `jjrpfister@gmail.com` on the Pi). Delete `developer_admin_key` and `X-Dev-Key` entirely, plus the hard-coded `admin@loam.local` and `jjrpfister@gmail.com` checks in `main.py`.
- `app/config.py`: add `firebase_project_id` (default `thepfisters`), `admin_emails`, `loam_env` (`production` | `development` | `test`), `cors_origins`. On startup in `production`, refuse to start if `CONNECTOR_SECRET_KEY` is the in-code default.
- Replace `resolve_user_id` and `verify_google_id_token` everywhere:
  - User-scoped endpoints require `get_current_user`: saved routes, activities upload, privacy zones and consent, export, account delete, DNR, flags, check-ins, votes, submissions and evidence, connectors, reports.
  - Admin endpoints (`/api/admin/*`, `/api/dev/*`, `/api/jobs/*`, submission approve/reject/reverse/takedown, `/api/heat/record`) require admin.
  - Route generation, export, geocode, heat/OTM tiles, coverage and trail status work anonymously via `get_optional_user`. Anonymous requests get no personal heat, DNR or "new to me".
  - `/api/auth/me` returns the real verified user (id, email, name, photo, `is_admin`).
- Test mode only: when `LOAM_ENV=test`, a pytest fixture overrides the dependency (`app.dependency_overrides`) to inject users. **No `mock_`/`dev_` token parsing in production code.** Update existing tests to use the fixture.
- CORS: only `cors_origins`: the Pi Funnel origin `https://core-node.tailcd5892.ts.net` and `http://localhost:5173`. **The app has no other domain.** `loam.thepfisters.com` is only the coming-soon landing site (Firebase Hosting) and must not be in CORS, authorized domains or email-link URLs.
- Rate-limit email-link UX on the client (one send per 60 s). Firebase rate-limits sends on its side.

### 3.3 Account migration
The existing user rows are keyed by the old Google `sub` (`102385574010410465390`) and some by made-up uids. Firebase uids differ. On the first verified login, if a legacy user has the same **verified** email, re-key that user's rows in one transaction (every table with `user_id`, plus `contributor_ids` arrays in `edge_heat`) to the Firebase uid, and log it. Write `scripts/migrate_user_ids.py` with `--dry-run`, which prints counts per table. Run the dry run on the Pi, put its output in the work log, then run it for real (after the 3.4 backup).

### 3.4 Prod safety steps (Pi)
1. `pg_dump -Fc` of the prod DB to `~/loam-backups/round7-pre-<date>.dump` on the Pi. Verify the file size and `pg_restore --list`.
2. Allowed deletions after the backup: users with no verified email that were created by the old fake flows (`google_*`, `token_*`, `*@example.com`, `justin_default_user`), **only after** their rows have been re-keyed or are empty. Log every count.

### 3.5 Acceptance
- A forged JWT (valid shape, bad signature), a non-JWT bearer, an `X-User-Id` header alone and an expired token each give **401** on `/api/saved-routes`, `/api/privacy/export` and `DELETE /api/privacy/account` (tests).
- `X-User-Id: jjrpfister@gmail.com` gives no admin anywhere (test).
- A real Google login and a real email-link login both work on the Pi URL from a phone on cellular (manual; screenshots in the PR).
- The old account's saved routes, activities and consent show up under the new login (manual check plus migration dry-run output).

## 4. Phase 2: Remove fabricated data and code (#34 item 1, rule 0.1)

- Delete `SeedLoopCatalog._init_curated_seeds` and every hard-coded seed. The seed catalog becomes empty until Phase 5 fills it from real map-matched rides.
- Delete `ingest_bow_ride_data_and_trails` and `POST /api/dev/bow/ingest`, plus any UI that calls them. Delete the hard-coded road-name UPDATE list there too. Road classification must come from OSM tags (Phase 3).
- Delete the synthetic elevation fallback (`routing.py` ~L286) and `gain_ft = dist * 85` (`contracted_graph.py`). With no elevation: `elevation_gain_ft = null`, the UI shows "Elevation unavailable", and climbing-fit scoring is skipped (not scored as 0 or 100).
- Delete the CubeTrek demo-track fallback. On failure, return an error the UI shows.
- Delete the "Bear Brook" default trailhead name in `generate_route_options` (`start_prefix`). Use the geocoded or reverse-geocoded name, else "Start".
- Audit `KNOWN_OSM_TRAIL_NAMES`: keep an entry only if the name matches the OSM `name` for that way id in the local extract. Otherwise drop it.
- Prod DB cleanup (after the 3.4 backup): delete the fake Bow activity, its `activity_edge_visits`, and the `edge_heat` rows that came only from it. Curated `edges` rows whose geometry didn't come from OSM get overwritten by the Phase 3 import. Then recalculate heat. Log the counts.
- `grep -rniE "mock|fake|synthetic|simulat|placeholder|demo|fallback"` across `app/` and `frontend/src/`: for each hit in a production path, delete it, or justify it in the work log (e.g. input placeholders, test fixtures).

**Acceptance:** no route returned by the API contains a coordinate list that didn't come from OSM ways or GraphHopper. There's a test that the seed catalog is empty without imported rides, and a test that no code path emits `ascend` without a DEM sample.

## 5. Phase 3: Real OSM topology and 3DEP elevation

### 5.1 OSM trail graph import
- Add `osmium` (pyosmium) to requirements. New `scripts/import_osm_graph.py` reads `data/osm/new-hampshire-latest.osm.pbf` (the same extract GraphHopper uses, so way ids match).
- Keep ways with `highway` in {path, track, footway, bridleway, cycleway, unclassified, residential, service, tertiary, secondary, primary, living_street, steps (flagged), pedestrian}, plus `route=snowmobile` / `snowmobile=*` ways. Store tags: `name`, `highway`, `surface`, `tracktype`, `mtb:scale`, `mtb:scale:imba`, `sac_scale`, `access`, `bicycle`, `foot`, `motor_vehicle`, `snowmobile`, `seasonal`, `informal`, `smoothness`, `check_date`, `osm_timestamp`.
- **Split ways into segments at every node shared by two or more kept ways, and at way endpoints.** New table `trail_segments(segment_id bigserial, osm_way_id bigint, seq int, from_node bigint, to_node bigint, geom geometry(LineString,4326), length_m float, ... tags)` with a GIST index. Keep `edges` keyed by `osm_id` = way id (heat stays per way). Upsert the `edges` rows' `geom`, `length_m` and tags **from OSM**, overwriting curated values.
- Classification is one function, `classify_surface(tags)` in `app/surface.py`, shared by GraphHopper paths, graph loops, map-match and the UI. It returns one of `singletrack | doubletrack | gravel | paved` (plus a `snowmobile` flag):
  - `paved` = any road class (`residential`, `service`, `tertiary`+, `unclassified` with no unpaved surface), or `surface` in {asphalt, paved, concrete, chipseal, paving_stones}.
  - `singletrack` = `path`/`bridleway`/`footway` with an unpaved or unknown surface and not `informal=yes`.
  - `doubletrack` = `track` grade2-5, or `track` with an unpaved surface.
  - `gravel` = `track` grade1, or `surface` in {gravel, fine_gravel, compacted}, or `unclassified` with an unpaved surface.
  - Unknown → `doubletrack` is **wrong**: unknown surface on a road class → `paved`; on path → `singletrack`; on track → `doubletrack`. Unit-test each branch, including the Round 4 regression roads (Grandview Road, Ridgewood Drive, Bettys Lane must be `paved`).
- Re-run it whenever the extract changes. Document it in the README.

### 5.2 Elevation: USGS 3DEP 1/3 arc-second (about 10 m)
- `scripts/fetch_3dep.py` downloads the 1°×1° GeoTIFF tiles that cover New Hampshire from `https://prd-tnm.s3.amazonaws.com/StagedProducts/Elevation/13/TIFF/current/<tile>/USGS_13_<tile>.tif`. The tiles are `n43..n46 × w071..w073` (tile names are the NW corner). Skip tiles that 404 (ocean). Save to `data/elevation/3dep13/`. Check that each file opens.
- `app/elevation.py` (add `rasterio` to requirements; it has arm64 wheels, so check it installs on the Pi too). `sample(coords) -> list[float|None]` uses bilinear sampling. Before sampling, densify the route to ≤10 m spacing. Compute gain and loss with a 3 m hysteresis threshold, and return the per-point profile for `ElevationProfile.tsx`. If a tile is missing, return None and the UI says unavailable.
- Use it for **every** route response (GH, graph loop, seed), so `elevation_gain_ft`, `elevation_loss_ft` and the profile are real. GraphHopper stays without elevation.
- Copy the tiles to the Pi in Phase 9 (`rsync data/elevation/3dep13` to the Pi's data dir; about 4-5 GB, tiles are 300-500 MB each; check free space on the Pi first and report).

**Acceptance:** for 3 real public routes, gain is within 15% of Garmin's `elevationCorrected` ascent for a similar activity, or of USGS EPQS point checks (a few points). Add a unit test with a small committed DEM fixture (a generated GeoTIFF, not real user data).

## 6. Phase 4: Routing (#34 item 1, plus finding F)

### 6.1 One route builder
`app/route_builder.py: build_route_response(coords, way_ids_per_segment, req, source, user_id)` is the **only** way a `RouteResponse` gets built. GraphHopper paths, graph loops and seed loops all go through it. It computes:
- distance from geometry
- surface breakdown and a **multi-segment** surface strip from `classify_surface` per segment
- real elevation (5.2)
- retrace % from directed segment reuse (the shape label uses the Round 6 thresholds: loop ≤10% retrace; lollipop stem <20% with loop part ≥60%; otherwise out-and-back)
- road % excluding the access segment, which is reported separately ("0.6 mi road to trail")
- trust layer, heat, new-to-me and composite score

### 6.2 Graph loop search (wire it in, fix it)
- Rebuild `ContractedTrailGraph.from_database` on `trail_segments`, using **OSM node ids as junctions** (no 35 m snapping). Contract degree-2 nodes into chains while keeping each chain's ordered segment list. Exclude segments that are hard-blocked (access=private/no, `bicycle=no` for bike sports, `foot=no` for running, restrictions, wilderness), DNR'd for this user, or over the road budget. Include roads only as connectors and count them against the road cap.
- When a chain is walked v→u, **reverse its coordinates**. Coordinates must be continuous (each next segment starts within 1 m of where the last one ended).
- Loop search: keep the self-avoiding DFS with distance-to-start pruning, but:
  - bound runtime (≤2 s, node-visit cap)
  - randomize neighbour order with a seeded RNG for diversity
  - de-duplicate by ≥70% shared length
  - allow a stem from the start to the base junction, using the real network path (Dijkstra over segments), not `2 × straight-line`
- Cache the graph per region tile (LRU, rebuild when the import changes).
- `generate_route_options` (loop mode) runs graph loops **and** the existing GH corridor/sector candidates **and** seed loops (Phase 5) in parallel, scores them all through 6.1, then calls `select_options`.

### 6.3 Geometry fidelity gate (fixes the screenshot class of bug for good)
Add to `passes_hard_gates`: **`geometry`** fails if any step between consecutive coordinates is >150 m and not along a known OSM segment, or if the Hausdorff distance between the route and the union of its claimed segments is >15 m. A route failing `geometry` is never shown, not even as a fallback.

### 6.4 Option count and quality (finding F)
- Aim for 10 options. Pool size before selection is ≥40 candidates; if that's not met, widen generation (more sectors, a second graph-search seed, nearby starts from `start_suggestions`).
- Drop candidates whose distance error is >50%, or under 25% of the target, **entirely**, including from the final fallback. Fewer than 10 honest options beats a 0.3 mi card. If fewer than 5 survive, show the count honestly ("Only 4 routes match; try a different start or distance") and the nearby-start suggestion.
- Keep the Round 6 composition (true loops first when they exist; "No true loop near here" otherwise).

### 6.5 Regression scenarios (real, public starts)
Add to `tests/test_round7_routing.py` (run against the local stack; skip with a clear reason if GH/PostGIS aren't up) and to the benchmark:
- **Bow Town Forest, 10 mi MTB loop**, from the public Bow Town Forest trailhead parking taken from OSM (`amenity=parking` nearest the forest; write its OSM id in the test), not the user's GPS position. Expect ≥8 options. Every option passes `geometry`. No option contains a coordinate from the deleted seeds. The top option's median vertex spacing is ≤40 m. Surface strip has >1 segment when surfaces change. Elevation is non-null.
- Bear Brook State Park, 10 mi and 14 mi MTB loops: true loops exist, so ≥7 of the top 10 are `loop` or `lollipop`.
- A trail run of 5 mi in Bow, `foot` profile.
- A point-to-point with one midpoint: the route passes within 25 m of the midpoint.
- The Round 4/5 regressions already written: the 10.8 mi route classifies as out-and-back; the 14.1 mi loop stays a loop.

### 6.6 Benchmark honesty (finding K)
Add a `real` scenario set to `loam_eval`, built from the 6.5 scenarios plus ~20 public trailheads across NH, run against the live local engine (not `synth.py`). Report Round 6 baseline vs Round 7 in `benchmark/reports/round7.md`: options returned, % passing gates, % true loops when loops exist, road %, retrace %, p50 and p95 latency. Keep the synthetic set, but label it synthetic in reports.

## 7. Phase 5: Garmin export → heat, and real loop seeds (#34 item 4, #32 task 7)

**Decision (user):** import trail-sport activities from **all years** (2020-10 → 2026-10). Heat still uses the 12-month window and 6-month half-life, so older rides count only as "ridden by you" (Find New Trails, DNR exemption) and as loop seeds. **Temporarily ignore the 3-rider minimum.** It exists only to seed the heatmap with the user's own rides, and it goes back to 3 when Loam goes public.

### 7.1 Local stripping (runs on this MacBook only)
`scripts/strip_garmin_export.py --export <dir> --out ~/dev/loam/main/data/garmin-stripped/`:
- Read `DI_CONNECT/DI-Connect-Fitness/*_summarizedActivities.json` (660 activities, 624 with start lat/lon). Select by `activityType`:
  - **bike → `mtb`:** `mountain_biking`, `e_bike_mountain`
  - **bike → `gravel`/`bike`:** `cycling`, `e_bike_fitness`
  - **foot → `trail_run`:** `trail_running`, `running`, `hiking`, `walking`
  - **Exclude:** `track_running`, `treadmill_running`, `resort_skiing*`, `indoor_climbing`, `breathwork`, `stop_watch`, `kayaking_v2`, `open_water_swimming`, `stand_up_paddleboarding_v2`, `rowing_v2`, `snowmobiling_ws`, `incident_detected`, `assistance`, `golf`, `other`
- Activity files are in `DI_CONNECT/DI-Connect-Uploaded-Files/UploadedFiles_0-_Part{1,2,3}.zip` (27,506 `.fit`, many likely non-GPS). Stream each zip member with `zipfile` (don't extract the whole archive). Parse with `fitparse`. Skip files whose `file_id.type` isn't activity or that have no `position_lat`. Match each to a selected summarized activity by start time (±90 s) and sport, using `activityId` as the stable key.
- Keep only `(lat, lon, timestamp)` per record. Drop HR, power, device and user fields. Apply `app/privacy.py` (`trim_ride_endpoints` 0.2 mi each end, plus the user's privacy zones, read from the prod API after Phase 1 login, or from `--privacy-zones` JSON). Drop tracks under 0.5 mi after trimming.
- Write one compact JSON per activity: `{activity_id, sport, start_time, points}`. Add a `manifest.json` with counts per sport and year, the number skipped and the reasons. **Print a summary and the manifest; don't upload anything in this step.**
- Use `python3 -I` and keep the script outside the export folder (downloaded data is untrusted input; parse defensively).

### 7.2 Upload
- New admin-only endpoint `POST /api/admin/heat/bulk-import` takes a batch (≤25) of stripped tracks for **the authenticated user**. It re-applies trimming server-side (defence in depth), map-matches via GH `/match` with a matching profile per sport, records `activities` (with `consent_given = true`, source `garmin_export`) and `activity_edge_visits`, and **stores no raw points** (the plan's "delete raw uploads after map-matching"). It's idempotent by `activity_id`.
- `scripts/upload_stripped.py` calls it with the user's Firebase ID token (paste-in prompt or `--token-file` outside the repo), resumes on failure and reports matched, failed and skipped counts.
- Run it against the local stack first, check heat on the map, then run it against prod.

### 7.3 Temporary 3-rider override
- `HEAT_MIN_UNIQUE_RIDERS` setting, default **3**. Set it to `1` in the Pi's `.env` only. `decay.py` and `db.py` read it instead of the literal `3`.
- While it's below 3, the heat layer and Explore show "Heat from one rider's seed data. The 3-rider privacy minimum is temporarily off." The README's pre-launch checklist says it goes back to 3 when Loam goes public.
- Test: the default is 3, and the override works.

### 7.4 Real loop seeds
- From the imported, map-matched activities, derive seed loops where start and end are within 300 m **before** trimming. Compute this locally in the strip step as a boolean only, never storing the start point. Retrace ≤10% on the way sequence.
- Store `seed_loops(user_id, sport, way_ids[], segment_ids[], distance_m, retrace, centroid_rounded)` in the DB, not in the repo.
- Cluster near-duplicates (≥70% shared length). `get_matching_seeds` returns loops whose geometry passes within 1.5 mi of the start. The candidate is a network stem plus the loop, built through 6.1.
- Report seed counts per area (rounded centroids, no coordinates) in the work log.

**Acceptance:** the manifest summary is in the work log. The heat layer in Bow and Bear Brook shows real traces that line up with OSM trails. A test confirms the bulk endpoint rejects non-admins and never persists raw points. `git status` shows no export-derived files.

## 8. Phase 6: Settings cleanup (#34 item 3)
In `YouPanel.tsx` "Preferences & Privacy": **remove** Display Theme, Distance & Elevation Units, Endpoint Trimming Protection and Privacy Threshold Invariant. Trimming and the threshold are not user settings. Mention them once as plain text in the privacy section ("We always trim 0.2 mi from the start and end of uploaded rides."). Remove any server parameter that lets a client skip trimming.

**Keep** only controls that change persisted state the backend uses: DNR list, privacy zones, contribution consent, connected services, data export, delete account. Remove all "(Round N)" or internal copy from user-facing text (`grep -rn "Round [0-9]" frontend/src`). Playwright check: the panel shows no control that doesn't persist.

## 9. Phase 7: "Report bad route" → GitHub issue (#34 item 6)

**Decision (user):** the issue contains the comment, inputs and scores, and route GeoJSON **trimmed 0.5 mi from each end**. The full snapshot stays on the server. The user is told plainly that other people can read it.

- **UI:** a "Report bad route" button on the route detail view (next to "Report Trail Issue") and in the candidate card overflow menu. It's visible only when signed in; signed-out users see "Sign in to report". The modal has:
  - a required textarea (10-2000 chars), with placeholder "What's wrong with this route?"
  - the notice, shown above the submit button: **"This report becomes an issue in Loam's GitHub repository. It includes your comment, your route settings and the route line with the first and last 0.5 mi removed; your start and end points are not included. People with access to the repository can read it, and it will become public when Loam's code is released. Don't include personal details."**
  - a "Submit report" button, then a confirmation with the issue link
- **Backend:** `POST /api/reports/bad-route` (auth required; 5 per user per day). The body has `comment`, the full `RouteRequest`, the selected `RouteResponse`, and the summary (id, name, score, shape, distance) of all options shown.
  - Store the full snapshot in a new table `route_reports(id uuid, user_id, created_at, comment, request_json, route_json, options_json, engine_config_version, git_sha, github_issue_number, status)`.
  - Build the issue:
    - **Title:** `In-app feedback: bad route — <route name> (<dist> mi <shape>, <sport>)`
    - **Labels:** `["in-app feedback"]`. Create the label once with `gh label create "in-app feedback" -R JJRPF/loam`, and have the server create it on 422.
    - **Body sections:**
      - the user comment in a fenced block, with `@` → `@​` so nobody gets pinged
      - inputs: sport, mode, target distance, terrain mix, loops-only, avoid-closed, DNR override. **Start, end and midpoint coordinates are withheld;** midpoints show only as count and order.
      - scores and breakdown, warnings, retrace %, road %
      - engine config version, git sha, report id
      - a `<details>` block holding GeoJSON of the route with **0.5 mi (805 m) trimmed from both ends** (reuse `trim_ride_endpoints` with a parameter), coordinates rounded to 5 decimals
    - Size-check: under 60,000 chars; simplify the geometry if needed.
    - Don't include the user's email or name; use a short hash of the user id.
  - Post with the GitHub REST API (`POST /repos/JJRPF/loam/issues`) using `GITHUB_FEEDBACK_TOKEN` (env; fine-grained PAT limited to JJRPF/loam with Issues read/write). If GitHub fails, keep `status=pending` and retry from `app/worker.py`; the user sees "Saved. It will be filed shortly."
  - Admin endpoint `GET /api/admin/reports/{id}` returns the full snapshot.
- **Tests:**
  - the GitHub call is mocked; the body has no start or end coordinates; the first and last 0.5 mi are removed
  - @mentions are neutralized
  - requests are rate-limited, and anonymous requests get 401

## 10. Phase 8: README and plan feature audit

Write `docs/round7-feature-audit.md`: one row per feature in the README (vision items 1-6, key features 1-6, the UI section, the API table), and per decision in `docs/trail-route-builder-plan.md`, `docs/agent-build-brief.md` and the chat. Columns: feature, source, status (**works / partial / fake / missing / removed-by-user**), evidence (file:line, endpoint, test name), action this round.

Rules:
- "Works" needs evidence that runs (a test or a manual check with a screenshot), not just that code exists.
- Anything "fake" gets fixed or removed this round.
- "Missing" items from the README get built this round unless the user explicitly removed them (rule 0.6).
- Items in the plan that were never in the README and are big (e.g. turn-by-turn, offline region downloads, Trailforks data ingestion) can be deferred with a reason. List them under "Deferred, needs user OK" in the PR.

Known items to fix in this phase (beyond Phases 1-7):
1. **Offline PWA (finding I):** a service worker (use `vite-plugin-pwa`, pinned) that precaches the app shell. Cache the last 10 viewed route responses and their GPX for offline viewing. Show an offline banner. Don't cache map tiles beyond the browser's default (provider terms). The manifest uses `docs/loam-brand` icons (check they're wired).
2. **Surface strip** on every card and the detail view uses the real multi-segment strip from 6.1, colors from section 18 (singletrack green, doubletrack yellow, gravel brown, paved grey), plus retraced sections in red on the map (from #32).
3. **Terrain mix control:** the plan calls for one stacked bar with draggable dividers plus presets, with 4 groups on mobile. Check it exists and works on touch; build it if it's only sliders.
4. **Midpoints:** start, end and any number of midpoints in the Plan UI, all honored by point-to-point routing (test in 6.5).
5. **Shareable URL for every search** (plan section 18): encode the request in the query string; opening it re-runs the search.
6. **Find New Trails, check-ins, flags with voting, DNR soft/hard with an override log, privacy zones, export/delete, GPX/FIT export, SSE streaming:** confirm each against prod-like data with a test or Playwright step. Fix what fails.
7. **Connectors:** per the plan, Strava and Trailforks stay **off by default** until the user confirms current terms. Set `ENABLE_*` defaults to false for Strava. Trailforks was turned on by the user in #19, so keep it on only if it works with real credentials, otherwise off with a UI note. Remove the CubeTrek demo fallback (Phase 2).
8. **README:** fix the stream path, test counts (no hard-coded badge numbers; say "see CI/pytest"), and the claims (3DEP, offline) so they match reality after this round. Add the OSM import, 3DEP fetch, Garmin strip/upload and Firebase setup steps.

## 11. Phase 9: Verify, deploy, hand off

1. Locally: run `pytest -q`, `npm run build`, the Playwright suite (`tests/test_browser_automation.cjs`, updated for Firebase test mode) and `loam_eval` real-set run. Attach `benchmark/reports/round7.md`.
2. Pi: the 3.4 backup is done → run the migrations (new tables, `trail_segments` import on the Pi or restore from a local dump, whichever fits in RAM; report which) → rsync the 3DEP tiles → update the Pi `.env` with `FIREBASE_PROJECT_ID`, `ADMIN_EMAILS`, `LOAM_ENV=production`, `CORS_ORIGINS`, `HEAT_MIN_UNIQUE_RIDERS=1`, `GITHUB_FEEDBACK_TOKEN` (copy the value from the local `.env`; never echo it) → `scripts/deploy-pi.sh` → health check.
3. From outside the network (phone on cellular, or `curl` via the Funnel URL), check:
   - the forged-token tests return 401 on prod
   - Google login and email-link login both work
   - the Bow Town Forest 10 mi loop shows ≥8 trail-following options with real elevation
   - the heat layer shows imported rides
   - Report bad route creates a labelled issue on JJRPF/loam (file one real test report, then close it with the comment "test report from Round 7 verification")

   Screenshot each.
4. `/finish-ticket` opens the PR. Its description has: a summary per #34 item, the audit table link, the benchmark before/after, the screenshots, the work-log deviations, "Deferred, needs user OK", and "Manual steps for the user" (below).

## 12. Manual steps only the user can do (list them in the PR; don't attempt them)
- Firebase console (project `thepfisters`) → Authentication → Sign-in method: enable **Google** and **Email/Password → Email link (passwordless sign-in)**. Settings → Authorized domains: add the Pi Funnel host `core-node.tailcd5892.ts.net` (localhost is there by default). Don't add `loam.thepfisters.com`: it's only the coming-soon site, not the app. Register a Loam web app if none exists and hand over the config.
- ~~Create a GitHub PAT~~ **Done:** the user supplied it. It's in the gitignored `.env` (main's original, copied into the worktree) as `GITHUB_FEEDBACK_TOKEN`. Copy it into the Pi `.env` in Phase 9. Never print, log, commit or post it.
- `HEAT_MIN_UNIQUE_RIDERS` goes back to 3 when Loam goes public (user decision). The bypass exists only to seed the heatmap with the user's own data. Add this to the README's pre-launch checklist.

