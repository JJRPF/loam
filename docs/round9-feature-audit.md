# Round 9 feature audit (GH-41): midpoints

| Feature | State | Evidence | Notes |
|---|---|---|---|
| Loop through midpoints, in the rider's order | works behind `ENABLE_MIDPOINTS` (default off) | `loam_eval via`: C1-C5, C8 hold on every returned option (124/124; baseline C5 112/158); `tests/test_round9_midpoints_live.py` | The way back avoids the way out where the network allows; order is never changed |
| Dead-end midpoint | works | unit tests, stubbed browser test | The route may ride a spur twice and the response `notice` says so |
| Midpoint the profile cannot reach | works | `tests/test_round9_midpoints.py`, `_api.py`, live | HTTP 422 with the reason (stream: an `error` event); no fabricated line |
| Distance within 15% of the target | partial | C6 94/124 | Shorter-than-asked loops come back; the engine's own gate marks them outside tolerance |
| Road share within the cap (OSM measure) | partial | C7 93/124 | Same rate as unchanged plain loops (41/49); Knox, Oak Hill cluster |
| Reorder / remove midpoints in the Plan panel | works | `tests/browser/midpoints.spec.ts` | 44 px targets at 360 px |
| GPX and FIT of a via loop | works | `tests/test_round9_midpoints_exports.py` | Same track as the API route; GPX passes every midpoint in order |
| Point to point with midpoints | unchanged | benchmark: no C5 failure at baseline or after | |
