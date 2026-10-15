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
