# Round 2 holdout (evaluated once)

| config | mean score | gate pass | road cap met | fake lollipop | mean q1 | infeasible | median ms |
|---|---|---|---|---|---|---|---|
| baseline (Round 4 approx) | 49.8367 | 56.2% | 77.8% | 4.5% | 44.496 | 2 | 297.27 |
| best (best_v2.json) | 71.8386 | 87.5% | 100.0% | 0.0% | 69.102 | 2 | 55.36 |

Reproducible (re-run hash equal): **True** (hash `9b99451f109fd042`).

## Stop conditions

| condition | status | value |
|---|---|---|
| holdout gate pass >= 98% | FAIL | 87.5% |
| road cap met >= 95% of routes | PASS | 100.0% |
| fake-lollipop rate == 0% | PASS | 0.0% |
| Justin top-3 agreement >= 85% | NOT MEASURED | no human labels collected |
| latency target (<10 s first result) | PASS | 55.36 ms (offline ranking only, GraphHopper time not included) |
| two consecutive rounds improve < 1% | NOT MEASURED | history=[54.2404, 62.0229] |
