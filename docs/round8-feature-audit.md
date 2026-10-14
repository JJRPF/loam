# Round 8 feature audit

One row per claim in `README.md`. Each row names the code and the test that backs it. "Browser" means a check in `tests/browser/` (Playwright, production build, Firebase Auth emulator). Rows for features that are hidden or removed are at the end; the README does not advertise them.

Status: **works** = a test ran and passed this round; **by hand** = checked in a browser by hand, no automated test; **not testable here** = needs hardware or a live account.

| README claim | Code | Test or check | Status |
|---|---|---|---|
| Loops built on the OSM trail network | `app/route_builder.py`, `app/trail_graph.py` | `test_builder_loop_out_and_back_and_lollipop_shapes`, `test_bear_brook_true_loops` (tests/test_round7_routing.py); browser: e2e Bear Brook route | works |
| A candidate is dropped if its line strays more than 15 m from the ways it claims | `app/route_builder.py` (geometry gate) | `test_screenshot_route_fails_the_geometry_gate`, `test_select_options_never_shows_geometry_failures_or_wild_distances` | works |
| Heat counts 12 months and halves every 6 | `app/decay.py` (`WINDOW_DAYS`, `HALF_LIFE_DAYS`) | `test_exponential_recency_decay_formula`, `test_ghost_trails_avoided_vs_active_trails_favored` (tests/test_stage4_heat.py) | works |
| Surface strip: singletrack, doubletrack, gravel, paved | `app/surface.py`, `frontend/src/components/SurfaceStrip.tsx` | `test_builder_strip_breakdown_and_access`, `test_singletrack_branches` (test_round7_surface_and_osm.py); browser: e2e "strip renders" | works |
| Elevation profile from USGS 3DEP; unavailable where no tile covers it | `app/elevation.py`, `ElevationProfile.tsx` | `test_route_response_uses_dem`, `test_no_ascend_without_a_dem_sample` (test_round7_elevation.py); browser: e2e "profile renders" | works |
| Terrain mix: stacked bar with draggable dividers | `TerrainMixBar.tsx` | Browser: "terrain mix dividers move with the keyboard and by dragging" | works (touch drag on a phone: by hand only) |
| Mountain bike or trail run; loop, point to point, out and back; shareable search link | `PlanPanel.tsx`, `urlState.ts` | Browser: "build, shared link and directions" at 390 and 1280 px | works |
| Up to 10 distinct candidates, fewer with a note | `app/routing.py` (`select_options`) | `test_select_options_dedups_by_shared_length`; browser: "N candidate routes", "1 candidate route" | works |
| Match score 60/15/10/10 minus penalties | `app/scoring.py` | `test_scoring_formula_weights` | works |
| Heat public only with 3+ riders; seed heat on trail-class ways only | `app/decay.py` (`heat_is_public`), `app/db.py` (`refresh_edge_heat`) | tests/test_round8_heat_privacy.py; browser: heat info text with and without the seed sentence | works |
| Below 3 riders you see only your own rides | `app/db.py` (`_own_heat`, `_apply_privacy`) | tests/test_round8_heat_privacy.py, tests/test_round8_public_privacy.py | works |
| Uploaded rides lose their first and last 0.2 mi; privacy zones cleared | `app/privacy.py` | `test_endpoint_trimming_distance`, `test_short_ride_trimmed_completely`, `test_privacy_zone_exclusion` | works |
| Contribution off switch, data export, one-tap account deletion | `app/main.py` (`/api/privacy/*`), `PrivacyControls.tsx` | `test_privacy_opt_out_export_and_account_deletion`; tests/test_round8_legal.py (deletion with submissions and reports); browser: signed-in You panel | works |
| Bad-route reports become public GitHub issues, no start or end point, route line minus 0.5 mi each end | `app/reports.py`, `ReportBadRouteModal.tsx` | `test_report_files_an_issue_without_endpoints_or_mentions`, `test_short_route_has_no_line_in_the_issue`; browser: report modal notice (nothing submitted) | works (GitHub itself is faked in tests) |
| GPX 1.1 and FIT course download | `app/gpx_export.py`, `app/fit_export.py`, `attachment_headers` in `app/main.py` | `test_garmin_gpx_export`, `test_garmin_fenix_fit_export`, tests/test_round8_exports.py; browser: e2e downloads, content checked (`<?xml`, `.FIT`) | works; opening a FIT on a Garmin device: not testable here |
| Share to Garmin Connect | `shareRouteGarmin` in `services/api.ts` | none beyond the button rendering | by hand: hands the file to the browser share sheet |
| Save routes; last 10 viewed available offline; installable PWA | `offlineRoutes.ts`, `vite.config.ts` (service worker) | Browser: "offline: the app shell loads and recently viewed routes are listed" | works |
| Personal do-not-route list; hazard flags shown as route warnings; the API takes flags, votes and check-ins (no app buttons yet) | `app/main.py` (`/api/flags`, `/checkin`, `/api/user/dnr`) | `test_community_flags_creation_and_voting`, `test_rider_checkin_refreshes_confidence_and_recency`, `test_user_dnr_crud_and_override_logging` | works (API); the app has no flag or check-in buttons (see the removed row below) |
| Private, no-bike and Wilderness ways never routed; snowmobile corridor caution | `app/trail_graph.py`, `app/main.py` | `test_graph_excludes_blocked_ways`, `test_wilderness_is_a_bike_only_hard_block`, `test_access_controls_and_snowmobile_warnings` | works |
| Sign in with Google or an emailed link, no passwords | `services/auth.ts`, `app/auth.py` | tests/test_round7_auth.py; browser: sign-in through the emulator email link; Google popup: not testable here | works (email link); Google: not testable here |
| API trusts only verified Firebase ID tokens; the emulator cannot run in production | `app/auth.py`, `app/config.py` (`check_auth_emulator_config`) | tests/test_round7_auth.py, tests/test_round8_auth_emulator_guard.py | works |
| Rate limits and a route concurrency cap | `app/ratelimit.py` | tests/test_round8_ratelimit.py; browser: real 429 with Retry-After, inline messages | works |
| Legal pages, AGPL license, source link | `frontend/public/legal/`, `LICENSE`, `LegalLinks.tsx` | tests/test_round8_legal.py; browser: legal pages cold, footer links, sign-in agreement, axe | works |
| Web app on Firebase Hosting, API behind a Funnel, old origin redirects | `firebase.json`, `app/main.py` (`old_origin_redirect`), `services/origin.ts` | tests/test_round8_hosting.py; browser: old-origin redirect and kill-switch worker; `smoke.prod.spec.ts` for the live site | works locally; live: see the Phase 10 worklog |
| Accessible: 44 px targets, axe clean, no sideways scroll | `index.css`, components | Browser: layout.spec.ts at six viewports | works |

## Hidden or removed (not advertised)

| Feature | State | Why |
|---|---|---|
| Midpoints (via points) | Off by default (`ENABLE_MIDPOINTS=false`); a link with `via=` loads without them and says so | Midpoint routing is being reworked. Tests: tests/test_round8_midpoints_flag.py; browser: midpoint UI absent, `via=` notice |
| Strava and Trailforks connectors | Off (`ENABLE_*_CONNECTOR=false`), not shown | Their current terms are not confirmed. Tests: tests/test_round8_connectors_hidden.py; browser: absent with flags off, present when the server reports them enabled |
| Water and shops layer | Removed (code, endpoint, import script; migration 008 drops the table) | Owner decision. Browser: "no water and shops toggle anywhere" |
| Round 7 preference controls (theme, units, trimming switch, privacy threshold) | Removed in Round 7 | They did nothing. Browser: the signed-out You panel has none |
| Results-panel "Still open" check-in and "Report trail issue" buttons | Removed this round | They posted to made-up trail IDs (999202, 999101). The API endpoints remain; a UI that picks a real trail from the route is future work |
