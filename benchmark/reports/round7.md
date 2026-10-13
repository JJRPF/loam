# Round 7 benchmark: real scenarios (GH-34)

Real set: the plan 6.5 scenarios plus named OSM `highway=trailhead` nodes across NH (`benchmark/real_scenarios.json`), run against the live local engine (GraphHopper + PostGIS with the OSM import + 3DEP). Every engine's routes are scored by the same OSM-based evaluator (`loam_eval/real.py`), not by the engine's own labels. The Round 5 set (`benchmark/scenarios.json`, `loam_eval/synth.py`) is **synthetic** and is not used here.

Gates: every point within 15 m of an OSM segment; road ≤ 15% excluding the access stretch; distance within 50% of the target.

| metric | round6 | round7 |
|---|---|---|
| options returned (mean of 10 asked) | 5.6 | 5.7 |
| % options passing gates | 20.7 | 49.0 |
| % options off the OSM network (> 15 m) | 15.7 | 0.0 |
| % loop/lollipop options where loops exist | 39.1 | 80.0 |
| road % (mean, excl. access) | 29.8 | 28.4 |
| retrace % (mean) | 15.4 | 12.4 |
| latency p50 (s) | 1.1 | 5.9 |
| latency p95 (s) | 1.5 | 7.4 |
| errors | 0 | 0 |

## Per scenario

| scenario | round6: options / passing / loops / p50 s | round7: options / passing / loops / p50 s |
|---|---|---|
| `bow_10_mtb` Bow Town Forest parking (mtb_hardtail, 10.0 mi) | 2 / 0 / 2 / 1.4 | 7 / 7 / 7 / 7.36 |
| `bear_brook_10_mtb` Bear Brook State Park parking (mtb_hardtail, 10.0 mi) | 9 / 5 / 6 / 1.14 | 10 / 10 / 10 / 7.21 |
| `bear_brook_14_mtb` Bear Brook State Park parking (mtb_hardtail, 14.0 mi) | 8 / 4 / 6 / 1.23 | 10 / 9 / 10 / 7.26 |
| `bow_5_run` Bow Town Forest parking (trail_run, 5.0 mi) | 10 / 0 / 7 / 1.08 | 4 / 0 / 3 / 1.37 |
| `p2p_midpoint` Bear Brook State Park parking (mtb_hardtail, p2p mi) | 10 / 0 / 0 / 0.92 | 7 / 0 / 0 / 2.28 |
| `th_194679000` Deer Mountain (mtb_hardtail, 10.0 mi) | 10 / 3 / 3 / 1.07 | 3 / 3 / 0 / 5.43 |
| `th_5656746911` Mount Crag Trailhead (mtb_hardtail, 10.0 mi) | 1 / 1 / 0 / 1.12 | 1 / 1 / 0 / 6.54 |
| `th_194628036` Appalachia (mtb_hardtail, 10.0 mi) | 7 / 0 / 5 / 0.88 | 0 / 0 / 0 / 1.97 |
| `th_8140114775` Owl's Head Trailhead (trail_run, 6.0 mi) | 8 / 3 / 3 / 1.39 | 7 / 5 / 2 / 5.49 |
| `th_9152673905` Skookumchuck Trailhead (mtb_hardtail, 10.0 mi) | 10 / 0 / 9 / 1.11 | 1 / 1 / 1 / 5.79 |
| `th_2133151582` Kearsarge North Trailhead (mtb_hardtail, 10.0 mi) | 5 / 3 / 4 / 1.29 | 10 / 10 / 10 / 9.62 |
| `th_8770165708` Diana's Bath Trailhead (mtb_hardtail, 10.0 mi) | 4 / 3 / 3 / 1.25 | 10 / 5 / 10 / 5.83 |
| `th_1997702798` Sabbaday Falls Trailhead (trail_run, 6.0 mi) | 3 / 1 / 2 / 1.38 | 2 / 2 / 0 / 4.63 |
| `th_7557484425` Chaffee Wildlife Sanctuary Trailhead (mtb_hardtail, 10.0 mi) | 1 / 1 / 1 / 1.54 | 10 / 4 / 10 / 5.43 |
| `th_7818421740` The Dismal at Pressey Brook Conservation Area (mtb_hardtail, 10.0 mi) | 7 / 1 / 3 / 1.12 | 2 / 1 / 1 / 5.54 |
| `th_11732393315` Lower Trailhead Kiosk (mtb_hardtail, 10.0 mi) | 5 / 4 / 4 / 1.19 | 10 / 9 / 10 / 5.42 |
| `th_7589880281` Whitten Woods Trailhead (trail_run, 6.0 mi) | 2 / 0 / 2 / 1.11 | 2 / 2 / 1 / 5.83 |
| `th_13395414645` Spectacle Pond Cartop Access (mtb_hardtail, 10.0 mi) | 1 / 0 / 1 / 1.48 | 5 / 0 / 4 / 6.0 |
| `th_5470792150` Sewall Woods Trailhead (mtb_hardtail, 10.0 mi) | 4 / 0 / 0 / 0.96 | 10 / 0 / 9 / 6.32 |
| `th_194652368` Bicknell Brook Trail (mtb_hardtail, 10.0 mi) | 2 / 0 / 1 / 1.2 | 2 / 1 / 1 / 5.91 |
| `th_13796708325` This is My Song (Blue) 1mi (trail_run, 6.0 mi) | 7 / 0 / 5 / 0.86 | 9 / 0 / 7 / 6.07 |
| `th_4813668256` Gonic Trails Falls (mtb_hardtail, 10.0 mi) | 10 / 0 / 9 / 1.15 | 3 / 0 / 1 / 6.45 |
| `th_3817468228` Gate 5 (mtb_hardtail, 10.0 mi) | 10 / 0 / 9 / 1.03 | 10 / 0 / 8 / 6.9 |
| `th_11248539138` Wapack Trail (mtb_hardtail, 10.0 mi) | 1 / 0 / 1 / 1.37 | 8 / 0 / 5 / 6.38 |
| `th_9062846278` Moore's Falls Trailhead (trail_run, 6.0 mi) | 3 / 0 / 0 / 1.15 | 0 / 0 / 0 / 6.29 |
