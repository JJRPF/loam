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

## Phase 5: Hide disabled connectors

## Phase 6: Legal pages, license, source link

## Phase 7: Production hardening for a public launch

## Phase 8: Hosting on loam.thepfisters.com

## Phase 9: Playwright UI testing, screenshots, README

## Phase 10: Deploy and verify

## Phase 11: Public-repo readiness audit

## Phase 12: Finish
