# Round 7 feature audit

Sources: `README.md` (vision V1-6, key features K1-6, UI, API table), `docs/trail-route-builder-plan.md` (PLAN §), `docs/agent-build-brief.md` (BRIEF) and decisions from the issue chat (CHAT).

Status: **works** (a test or a manual check ran), **partial**, **fake**, **missing**, **removed-by-user**. "Works" in a UI row needs a browser check; the rows marked *UI check pending* are built and compile, and get their Playwright check in Phase 9, after which this table is updated.

Last updated: end of Phase 8 code. Test names are in `tests/`.

## README: vision and key features

| Feature | Source | Status | Evidence | Action this round |
|---|---|---|---|---|
| 12-month window, 6-month half-life recency decay | V1, K3 | works | `test_exponential_recency_decay_formula`, `test_ghost_trails_avoided_vs_active_trails_favored` (test_stage4_heat.py) | Heat sport grouping fixed (Phase 5) |
| Coverage-aware zero-heat penalty | K3, PLAN §7 | works | `test_coverage_aware_zero_heat_penalty`; coverage recalculation `'activity_id'` bug fixed in Phase 7 (29 cells locally) | Fixed |
| "Tested against verified NH trail datasets (Bear Brook, Highland, Fort Rock, Franklin Falls)" | K3 | fake | Those names are start points in the Round 5 synthetic benchmark (`benchmark/scenarios.json`); no verified trail dataset exists in the repo | README claim removed. The real benchmark is `benchmark/reports/round7.md` (OSM-scored); known ghost / good trail sets from you are still needed (Manual steps) |
| Surface strip: singletrack / doubletrack / gravel / paved from OSM tags | V2, K1 | works | `test_builder_strip_breakdown_and_access`, `test_singletrack_branches` etc. (test_round7_surface_and_osm.py) | One classifier (`app/surface.py`); colors now green / yellow / brown / grey (PLAN §18) |
| Elevation profile from USGS 3DEP | V2 | works | `test_route_response_uses_dem`, `test_no_ascend_without_a_dem_sample` (test_round7_elevation.py); EPQS point check within 0.2 m | 3DEP only; unknown stays unknown |
| Terrain-mix control (stacked bar, draggable dividers, presets) | V2, PLAN §18 | partial | Was presets plus a read-only bar. `TerrainMixBar.tsx` now has pointer and keyboard dividers | Built this round. *UI check pending* (drag on touch) |
| ~10 distinct candidates in sectors, deduped, repetition penalty | V3, K2 | works | `test_bow_town_forest_10mi_mtb_loop` (7 options, see worklog), `test_bear_brook_true_loops` (10), `test_select_options_dedups_by_shared_length` | "Up to 10"; README no longer promises exactly 10 |
| Scoring 60/15/10/10/5 | K2 | works | `test_scoring_formula_weights` | README formula kept |
| Hard geometry gate (route follows the OSM ways it claims) | PLAN §6 | works | `test_screenshot_route_fails_the_geometry_gate` | New this round |
| One-tap check-ins, confidence refresh | V4, K4 | works (API) | `test_rider_checkin_refreshes_confidence_and_recency` | UI button exists in ResultsPanel. *UI check pending* |
| Community flags with abuse-resistant voting | V4, K4 | works (API) | `test_community_flags_creation_and_voting` | *UI check pending* |
| Hard blocks (`access`, `bicycle=no`), snowmobile warnings | K4, PLAN §8 | works | `test_hard_block_rejection_and_prior_ride_waiver`, `test_access_controls_and_snowmobile_warnings`, `test_graph_excludes_blocked_ways` | Wilderness / PAD-US polygons are not ingested; see Deferred |
| Personal DNR (soft with override log, hard) | K4 | works | `test_user_dnr_crud_and_override_logging`, `test_route_options_soft_dnr_and_override` | DNR UI in You panel |
| Overrides feed back as a weaker penalty for others | PLAN §2 | missing | The override is logged (`dnr_override_logs`) but nothing aggregates it into others' penalty | Deferred, needs user OK (it is a modelling choice with little data) |
| Find New Trails | V5, K5 | works (API) | `test_find_new_trails_scoring_and_unridden_boost`, `test_find_new_trails_api_and_exploration_endpoint` | *UI check pending* |
| 3-rider threshold | V5, K6 | works | `test_unique_riders_privacy_threshold_aggregation`, `test_heat_scoring_privacy_threshold`, `test_recalculation_uses_the_threshold`. Temporary override `HEAT_MIN_UNIQUE_RIDERS` (prod 1 for now) | Return to 3 before public launch (README checklist) |
| 0.2 mi start/finish trimming | K6 | works | `test_endpoint_trimming_distance`, `test_short_ride_trimmed_completely`; no client switch to skip it (Phase 6) | Plain-text note in You panel |
| Privacy zones | V5, K6 | partial | API `test_privacy_zone_exclusion`, `test_privacy_zone_crud_and_consent_api`; no UI existed | `PrivacyControls.tsx` added (zone list, add at my location, remove). *UI check pending* |
| Contribution consent / opt-out | K6, PLAN §7 | partial | `test_privacy_opt_out_export_and_account_deletion`; only a per-upload checkbox existed | Account-level toggle added in `PrivacyControls.tsx`. *UI check pending* |
| Export data / delete account | K6 | works (API) | `test_user_export_gps_data`, `test_privacy_opt_out_export_and_account_deletion` | In You panel. *UI check pending* |
| GPX 1.1 and FIT course export | V6 | works | `test_garmin_gpx_export`, `test_garmin_fenix_fit_export` | Opens on a fenix: untested by me (needs the device) |
| Share to Garmin Connect | V6 | partial | `shareRouteGarmin` hands the file to the browser share sheet | Behaves as the plan's MVP (no credentials). Not testable here |
| Garmin export import to heat | CHAT #34 | works | `test_import_stores_no_points_is_idempotent_and_seeds_a_loop`; local import 375 matched, 34 unmatchable | Phase 5 |
| Real loop seeds from rides | CHAT #32 | works | same test; `test_seed_catalog_empty_without_imported_rides` | Phase 5; prod has none until Firebase sign-in works |

## README: user interface

| Feature | Source | Status | Evidence | Action |
|---|---|---|---|---|
| Design tokens (Fog / Spruce / Blaze / Lichen / Slate) | UI | partial | README listed Blaze `#E05A2B` and Lichen `#8FA382`; the plan and the CSS use `#FF5B14` and `#A9BF7A` | README corrected |
| Phone-first PWA, installable | UI, PLAN §18 | partial | Manifest and icons existed; no service worker | `vite-plugin-pwa` 1.3.0 (pinned) precaches the shell. *UI check pending* (install, offline reload) |
| Offline: saved routes and last results | PLAN §18 | partial | There was no offline behaviour | Last 10 viewed routes in IndexedDB (`offlineRoutes.ts`), listed under Saved; offline banner; GPX fallback was already client-side. API responses and map tiles are not cached by the service worker. FIT export needs a connection |
| Shareable URL for every search | PLAN §18 | missing | Not in the code | `urlState.ts`: start, end, midpoints, mode, miles, terrain, flags in the query string; opening re-runs the search. *UI check pending* |
| Midpoints in Plan | PLAN §11, §18 | missing | `waypoints` was a constant empty array in `App.tsx` | UI to add up to 5 midpoints (point-to-point), honored by routing: `test_point_to_point_honors_midpoint` |
| Loop with midpoints | PLAN §5 | missing | Loops ignore waypoints | Deferred, needs user OK (the plan's wording is "honored by point-to-point") |
| Imperial units | UI | works | All UI copy in mi and ft (`format.ts`); units setting removed in Phase 6 | |
| Dark mode only, no light mode | CHAT | removed-by-user | | Kept removed |
| Start-location preset dropdown, bike types that don't change routing | CHAT | removed-by-user | | Kept removed |
| Heat layer toggle with legend, own hue ramp | PLAN §18 | partial | Toggle existed; ramp was red/orange | Ramp changed to teal-to-pale. Legend: *UI check pending* |
| Retraced stretches red on map | CHAT #32 | works (data) | `retraced_coordinates` in the response; layer in `MapView.tsx` | *UI check pending* |
| "Report bad route" | CHAT #34 | works | `tests/test_round7_reports.py` (6) | Phase 7; needs `GITHUB_FEEDBACK_TOKEN` on the Pi |
| Atkinson Hyperlegible, tabular numerals | PLAN §18 | works | `index.css`, `num-tabular` | |

## README: API table

| Endpoint (README) | Status | Evidence / correction |
|---|---|---|
| `GET /health` | works | `test_health_endpoint` |
| `POST /api/route/options` | works | `test_route_options_endpoint_bear_brook` |
| `POST /api/routes/options/stream` | wrong path | The real path is `POST /api/route/options/stream`; `test_route_options_streaming_endpoint`. README fixed |
| `POST /api/export/fit`, `/api/export/gpx` | works | `test_garmin_fenix_fit_export`, `test_garmin_gpx_export` |
| `POST /api/activities/upload` | works | `test_gpx_upload_and_ingestion`, `test_fit_upload_and_ingestion`, `test_defensive_xxe_attack_rejection`, `test_oversized_file_rejection` |
| `POST /api/trails/{edge_id}/checkin` | works | param is `edge_osm_id`; `test_rider_checkin_refreshes_confidence_and_recency` |
| `POST /api/flags` | works | `test_community_flags_creation_and_voting` |
| `GET /api/trails/new-to-me` | works | `test_find_new_trails_api_and_exploration_endpoint` |
| `GET /api/connectors` | works | `test_connectors_disabled_by_default_and_status_list` |
| `DELETE /api/privacy/account` | works | `test_privacy_opt_out_export_and_account_deletion` |
| `GET /api/privacy/export` | works | `test_user_export_gps_data` |
| Not in README: `POST /api/reports/bad-route`, `GET /api/admin/reports/{id}`, `POST /api/admin/heat/bulk-import`, `GET /api/heat/meta` | works | test_round7_reports.py, test_round7_heat.py. Added to README |

## docs/trail-route-builder-plan.md decisions

| Decision | Status | Evidence / note |
|---|---|---|
| Firebase Auth, Pi verifies ID tokens | works (Pi pending Firebase web app) | test_round7_auth.py (13 tests: forged, expired, wrong audience, unverified email, header identity gives nothing). Firebase web app registration is a manual step |
| MTB and trail running | works | `test_sport_profiles`, `test_trail_running_profile_custom_model_and_scoring`. Bike sub-types that don't change routing were removed by the user |
| Zero-heat: avoid, user can override | partial | Avoidance works (coverage-aware); the override feeding others is missing (above) |
| Hard blocks, wilderness / PAD-US polygons | partial | OSM `access` and `bicycle` blocks work; no PAD-US ingestion. Deferred, needs user OK |
| Combined score, input match first | works | `test_scoring_formula_weights` |
| Export GPX/FIT; official Garmin API not used | works | |
| No paid tier, donations only | removed-by-user | No paid code exists |
| Units miles | works | |
| Trail submissions auto-verify / crowd-confirm, no moderation | works (API) | `test_trail_submission_creation_and_auto_verification`, `test_submission_auto_verification_blocked_by_hard_restriction`, `test_admin_moderation_interface`. Submit and moderation UI is in `ExplorePanel.tsx`. *UI check pending* |
| 6 routing profiles (hardtail, full-sus, gravel, fat, e-MTB, run) | partial | Backend profiles exist; the UI offers MTB and Run only (user removed profiles that don't change routing) |
| Midpoints, round trip, loop, out-and-back | partial | Loop, out-and-back and P2P with midpoints work; round trip is the loop mode |
| 40-60 candidates, ±10% distance | partial | Candidate pool 40+ before selection; the distance window is wider (−50%/+50% hard, scored inside it) after Round 6 tuning |
| Heat inside the router | works | Heat applied in ranking; documented in `docs/spikes-report.md` |
| Heat sources: uploads, Garmin, Strava (off), Trailforks (off), OSM freshness, check-ins | works / off | Strava and Trailforks default off; Garmin login connector is flagged; CubeTrek demo fallback is gone (Phase 2) |
| Delete raw files after map-matching unless kept | works | `raw_file_retained=false` asserted in `test_import_stores_no_points_is_idempotent_and_seeds_a_loop` |
| Nightly job: recalc heat and coverage | works | `test_nightly_worker_execution`; now also retries pending bad-route reports |
| Caddy, port forward, `api.` subdomain | removed-by-user | The Pi is served on the tailnet domain `core-node.tailcd5892.ts.net` |
| Pi nightly PostGIS backup | partial | One-off `pg_dump -Fc` taken before this round; no nightly job found. Deferred, needs user OK |
| Weather, water/shop markers, offline maps, turn-by-turn, friends, leaderboards, contributor perks, other regions | missing | "Later" items in PLAN §11. Deferred, needs user OK |
| OSM export of confirmed trails | missing | PLAN §10 "later phase". Deferred |
| Tile provider: not tile.openstreetmap.org | works | `test_carto_tile_url_and_key_in_frontend` |
| Mobile bottom sheet, desktop 400 px panel | works (code) | *UI check pending* |

## docs/agent-build-brief.md

The brief's stage list (foundation to differentiators) matches the six README stages; each stage's acceptance tests are in `tests/test_stage*_*.py`. The brief's items that this round changed: real OSM topology (Phase 3), no fabricated data (Phase 2), geometry gate (Phase 4). No unaddressed decisions beyond those above.
