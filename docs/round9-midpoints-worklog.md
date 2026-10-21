# Round 9 (GH-41): midpoint loops that are actually correct

Plan: the comment on issue #41 (supersedes the issue body). Privacy: public trailheads only; nothing
from `data/` is committed. Local stack only (never the Pi, never Firebase). `ENABLE_MIDPOINTS` stays
default `false` in code.

## Phase 0: "correct" as an executable checker

`loam_eval/via_check.py::check_via_route(coords, start, vias, end=None, target_miles=None, way_ids=None)`
reports C1-C8 and an overall `ok`. Thresholds as in the plan; where the plan left a number open:

- C6 `dist_err` limit is **0.15**, the engine's `distance_tolerance` (`app/engine_config.py`). (`evaluate_option`'s own
  0.5 `passes` gate is a looser benchmark filter, not used here.)
- C7 `road_pct` cap defaults to 15 (what `evaluate_option.passes` uses); callers pass the profile's cap.
- C2 limit is `min(snap + 25 m, VIA_TOLERANCE_M)`: the snap distance is supplied by the caller (`snap_m`).
- C8 needs the caller to say which vias are dead ends (`dead_end_vias`) and pass the response `notice`; a dead-end
  via waives C5 only if the notice is present.
- Network lookups (`evaluate`, `offset`) are injectable so the checker's tests run without PostGIS.

Tests: `tests/test_round9_via_check.py` (12, synthetic). Mutation check: each of C1, C2 (both the check and the
150 m cap), C3, C4, C5, C6 (both halves), C7, C8 was broken in turn in the checker and a test went red each time;
restored afterwards, 12 pass.

C1 limit, decided in phase 1: the plan said 60 m from the start. A trailhead's coordinate is often tens of metres
from the nearest way and the engine's loops start on the nearest off-road trail (Bow: 16 m to a road, 78 m to
trail). C1 is 60 m plus that snap (capped at 150 m), and a loop must also close on itself within 60 m.

C3, decided in phase 3: "indices of closest approach increase" failed a route that passes a midpoint early on
the way to another and again later in the right order. C3 is an ordered subsequence (each midpoint reached,
within its C2 limit, after the previous one). The engine applies the same rule (`passes_vias_in_order`).

## Phase 1: scenarios, runner, baseline

`python -m loam_eval via-scenarios` writes `benchmark/via_scenarios.json` (public trailheads from
`frontend/src/data/trailheads.json`; midpoints picked from `trail_segments` by bearing and distance). To make the
tests, generate the trailheads first: `PYTHONPATH=. .venv/bin/python scripts/build_trailheads.py
$DATA_DIR/osm/new-hampshire-latest.osm.pbf` (git-ignored, as for the live tests of Round 7).
`python -m loam_eval via --out <path> [--baseline <json>]` runs `plan_route_options` and checks every option;
`python -m loam_eval via-diag <id>` shows one scenario candidate by candidate.

Feasible by construction: a scenario is kept only if the plain start -> midpoints -> start loop, routed with the
engine's own GraphHopper profile and custom model, is 0.6-1.1x the target, within the 15% road cap, and passes
every midpoint on the network the profile can ride. Midpoints are tried at scale 1.0, 0.8, 0.65, 0.5, 0.4, 0.3 of
the plan's distance (so "about 1/4 of the target" often became less) and the scenario is dropped if none fits.
The first set (63) had midpoints 200-900 m from anything the mtb profile can use and loops of 15 mi for a 10 mi
target; they measured the scenarios, not the engine. The kept set is 37-55 scenarios depending on the stack state
(one_via 11-24, two_vias 4-7 and reversed, three_vias 1, 6 adversarial, 4 point to point, 7 plain loops). Each
midpoint's `snap_m` is how close the plain route passes it (the profile's snap), not the OSM table's distance.
This makes the benchmark easier than the plan's; the unfiltered numbers are in git history (63 scenarios).

Baseline (`benchmark/reports/via-baseline.{json,md}`, run from a copy of the tree with main's `app/` at 57957fe):
C5 (not an out-and-back) held on 29 of 63 one-midpoint options and 4 of 9 two-midpoint options, and C2/C3 missed
some midpoints (154/158, 153/158). On the first, infeasible scenario set most 2-3 midpoint scenarios returned
nothing.

## Phase 2: what was tried (all inside the via branch of `plan_route_options`)

- Opposite-side detour waypoints (the plan's item 1), sized from a length formula, then from the measured plain
  loop: detour waypoints snap to whatever way is nearest, so a 7 mi plain loop became 15-24 mi. Kept only as a
  ladder of heights (0.08-0.4 of the chord) used when the loops below come out short; the distance gate picks.
- Return avoids outbound (item 2), done with GraphHopper custom-model `areas`: each leg after the first is routed
  with a priority penalty (x0.05 / x0.25) on a corridor (35 m / 90 m) around the legs already ridden, minus a
  120 m disc at the leg's own ends. Waypoints sampled every 500 m along that return path make one final request
  per variant, so the route goes through the normal builder. This is what fixes the loops: where a loop exists the
  way back differs, where only a spur exists it repeats and the filter says so.
- Order (item 3): never changed; the direction-flip option is off (owner ask a).
- Engine uses the checker's rules (item 4): ordered subsequence, per-midpoint tolerance = the plain route's own
  approach + 25 m (cap 150 m), repetition = max(geometric ratio, share of steps ridden twice) <= 0.28; if no
  candidate passes the repetition rule the least repetitive are kept and the notice says a midpoint is reached by a
  spur ridden out and back (`DEAD_END_NOTICE`). A midpoint the profile cannot reach (plain route passes > 150 m
  away) or that has no way within 150 m (`/nearest`) is a `MidpointError`: HTTP 422 with the reason, an `error`
  event on the stream. Point to point (item 5) is unchanged: Phase 1 showed no C5 failure there.
- `/api/route` (the single-route path) does not search for a loop, so it adds the notice when the route it builds
  from the midpoints repeats itself.

## Results (benchmark/reports/via-after.md, same scenarios as the baseline)

On every option the engine now returns (124, baseline 158): C1 C2 C3 C4 C5 C8 all pass. Baseline: C5 112/158, C2
154/158, C3 153/158. Plain loops: 39 of 49 options pass every rule before and after; the same C6 (45/45) and C7
(41/41). p95 latency 10.0 s before, 9.3 s after (all scenarios); the extra GraphHopper calls
(plain, 3 probe chains of n+1 legs, up to ~20 detour specs when short) did not raise p95.

Not met: the plan's acceptance of C6 and C7 on every option of every non-adversarial scenario.
- C6 (distance within 15%): 94 of 124. Most failures are loops shorter than the target (8 mi for 10); the engine
  returns them (its own distance gate shows them as outside tolerance) because nothing closer exists, and the
  existing fallback tier does not warn on distance (shared selection code, left alone for #44).
- C7 (road share by OSM category, excluding the access run): 93 of 124. The failures cluster in Knox, Oak Hill and
  the Knox to White Park point to point (a fixed ~33% road stretch). The same measure fails 8 of the 49 unchanged
  plain-loop options, so it is the benchmark's independent measure disagreeing with the engine's own road count,
  not something this change introduced.
- The dead-end notice never fired in the benchmark (the picked "dead end" scenario found loops of its own); it is
  covered by unit tests and a stubbed browser test, not by a live route.

## Phases 3-4

Live tests (`tests/test_round9_midpoints_live.py`, 8): every option checked; Bear Brook one midpoint (10 mi, two
bearings), two midpoints and the same two reversed, three midpoints (Knox), the dead-end scenario, the off-network
error, a point to point, and a plain loop. C1-C5 and C8 asserted on every option; C6 asserted as "if out of
tolerance the engine's own distance gate agrees"; C7 is reported by the benchmark, not asserted.
`tests/test_round9_midpoints_api.py` (4): the notice on `/api/route`, 422 on `/api/route/options`, the error event.
`tests/test_round9_midpoints_exports.py` (3): GPX and FIT of a via loop have the API route's point count and
start/end within 1 m, and the GPX passes every midpoint in order (C2, C3 on the GPX track).
Browser (`tests/browser/midpoints.spec.ts`, 5, with a third API on :8092 with `ENABLE_MIDPOINTS=true` and every
`/api` request of the page redirected to it; the flag-off suite is unchanged): tap the map to add a midpoint and
the route passes it; remove it and rebuild; reorder two midpoints and the route passes them in the new order (the
share link carries the new `via=` order); a shared link with `via=` reproduces the same routes; the dead-end notice
is shown; at 360 px the midpoint controls are 44 px and do not overlap. The Plan panel gained move up/down buttons
and 44 px targets for add and remove.
Two harness fixes found on the way: `scripts/browser-test-server.sh` now overrides `GRAPHHOPPER_URL` like it already
did `DATABASE_URL` (`.env` names the compose-internal host; the flag-off suite never needed GraphHopper, midpoint
routing does and its calls failed silently), and `scripts/run-browser-tests.sh` sets `NODE_PATH` so
`tests/browser` finds `frontend/node_modules`.

## Owner asks

(a) allow the loop to be ridden in the other direction when that lowers retrace (off; order is always kept);
(b) a midpoint farther than the target allows: today the shortest loop comes back flagged by the engine as outside
the distance tolerance, or a 422 if the midpoint is unreachable by the profile; say if you want a notice instead;
(c) turn `ENABLE_MIDPOINTS` on in production (Pi `.env`; yours to do, the default stays `false`).
