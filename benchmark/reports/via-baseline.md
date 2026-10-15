# Midpoint routing benchmark: baseline: main's routing code (HEAD 57957fe, before any routing change)

Every returned option is checked (C1 closes/ends, C2 passes every midpoint, C3 in order, C4 real ways, C5 not an out-and-back, C6 distance, C7 road share, C8 honest notice). Public trailheads only.

| kind | scenarios | options | ok | C1 | C2 | C3 | C4 | C5 | C6 | C7 | C8 | no options | errors | p50 s | p95 s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| adversarial | 6 | 13 | 0 | 13 | 9 | 13 | 13 | 13 | 7 | 8 | 6 | 4 | 0 | 2.4 | 4.9 |
| one_via | 24 | 95 | 22 | 95 | 86 | 95 | 95 | 47 | 53 | 59 | 95 | 8 | 0 | 2.7 | 4.6 |
| p2p_one_via | 2 | 10 | 1 | 10 | 10 | 10 | 10 | 10 | 8 | 1 | 10 | 0 | 0 | 0.9 | 1.3 |
| p2p_two_vias | 2 | 2 | 0 | 2 | 2 | 2 | 2 | 2 | 1 | 0 | 2 | 1 | 0 | 0.5 | 0.8 |
| plain_loop | 7 | 47 | 37 | 47 | 47 | 47 | 47 | 47 | 43 | 39 | 47 | 0 | 0 | 6.5 | 10.3 |
| three_vias | 1 | 1 | 0 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 1 | 0 | 0 | 2.7 | 2.7 |
| two_vias | 7 | 18 | 0 | 18 | 16 | 17 | 18 | 10 | 10 | 5 | 18 | 1 | 0 | 3.4 | 5.5 |
| two_vias_reversed | 7 | 19 | 0 | 19 | 16 | 19 | 19 | 10 | 10 | 7 | 19 | 1 | 0 | 2.5 | 2.8 |
| **all** | 56 | 205 | 60 | 205 | 186 | 204 | 205 | 139 | 133 | 120 | 198 | 15 | 0 | 2.7 | 6.8 |

## Per scenario

| scenario | opts | ok | failing rules | worst retrace | miles | latency s | notice / error |
|---|---|---|---|---|---|---|---|
| v1_bear_brook_5mi_b45 | 10 | 4 | C2x4, C5x4, C6x2 | 0.5 | 3.8-5.7 | 1.62 |  |
| v1_bear_brook_5mi_b135 | 6 | 5 | C6x1, C7x1 | 0.194 | 4.7-7.0 | 0.78 |  |
| v1_bear_brook_5mi_b315 | 10 | 4 | C2x2, C5x4, C6x4 | 0.5 | 3.7-6.5 | 0.76 |  |
| v1_bear_brook_10mi_b45 | 9 | 0 | C5x8, C6x6, C7x9 | 0.5 | 9.2-13.8 | 3.94 |  |
| v1_bear_brook_10mi_b135 | 7 | 4 | C5x3, C6x1 | 0.5 | 8.8-11.6 | 2.89 |  |
| v1_bear_brook_10mi_b225 | 0 | 0 | - | - | - | 1.81 | Only 0 routes match; try a different start or distance. Start 0.3 mi away at Podunk Road f |
| v1_bear_brook_10mi_b315 | 5 | 0 | C5x4, C6x3, C7x4 | 0.5 | 7.3-12.8 | 2.13 |  |
| v1_bear_brook_15mi_b45 | 0 | 0 | - | - | - | 2.1 | Only 0 routes match; try a different start or distance. Start 0.7 mi away at Podunk Road f |
| v1_bear_brook_15mi_b135 | 0 | 0 | - | - | - | 2.11 | Only 0 routes match; try a different start or distance. Start 0.7 mi away at Podunk Road f |
| v1_bear_brook_15mi_b225 | 9 | 0 | C5x8, C6x6, C7x1 | 0.5 | 15.2-22.2 | 2.95 |  |
| v1_bear_brook_15mi_b315 | 0 | 0 | - | - | - | 2.32 | Only 0 routes match; try a different start or distance. Start 0.7 mi away at Podunk Road f |
| v1_bow_10mi_b135 | 0 | 0 | - | - | - | 4.62 | Only 0 routes match; try a different start or distance. Start 1.8 mi away at Single Circui |
| v1_bow_10mi_b225 | 4 | 1 | C5x3, C6x3 | 0.498 | 11.1-14.0 | 3.04 | Only 4 routes match; try a different start or distance. |
| v1_bow_10mi_b315 | 4 | 2 | C2x2 | 0.194 | 9.1-10.6 | 2.79 | Only 4 routes match; try a different start or distance. Start 1.8 mi away at Single Circui |
| v1_knox_10mi_b135 | 10 | 2 | C2x1, C5x6, C6x5, C7x1 | 0.5 | 7.2-13.1 | 5.45 |  |
| v1_knox_10mi_b225 | 5 | 0 | C5x2, C6x4, C7x4 | 0.5 | 5.5-14.1 | 3.09 |  |
| v1_knox_10mi_b315 | 1 | 0 | C7x1 | 0.197 | 11.2-11.2 | 2.52 | Only 1 route match; try a different start or distance. Start 0.5 mi away at Pond Trail for |
| v1_oak_hill_10mi_b45 | 4 | 0 | C5x2, C6x1, C7x4 | 0.5 | 6.8-10.6 | 4.04 | Only 4 routes match; try a different start or distance. |
| v1_oak_hill_10mi_b225 | 3 | 0 | C5x2, C6x2, C7x3 | 0.5 | 8.2-11.6 | 2.66 | Only 3 routes match; try a different start or distance. |
| v1_oak_hill_10mi_b315 | 0 | 0 | - | - | - | 2.06 | Only 0 routes match; try a different start or distance. |
| v1_white_park_10mi_b45 | 4 | 0 | C5x2, C6x1, C7x4 | 0.424 | 9.1-14.8 | 3.45 | Only 4 routes match; try a different start or distance. |
| v1_white_park_10mi_b135 | 4 | 0 | C6x3, C7x4 | 0.238 | 7.1-13.3 | 2.91 | Only 4 routes match; try a different start or distance. |
| v1_white_park_10mi_b225 | 0 | 0 | - | - | - | 2.84 | Only 0 routes match; try a different start or distance. |
| v1_white_park_10mi_b315 | 0 | 0 | - | - | - | 2.07 | Only 0 routes match; try a different start or distance. |
| v2_bear_brook_10mi_b30 | 2 | 0 | C5x1, C6x2 | 0.44 | 8.5-12.3 | 5.27 | Only 2 routes match; try a different start or distance. Start 0.3 mi away at Podunk Road f |
| v2r_bear_brook_10mi_b30 | 2 | 0 | C5x1, C6x2 | 0.44 | 8.5-12.3 | 2.6 | Only 2 routes match; try a different start or distance. Start 0.3 mi away at Podunk Road f |
| v2_bear_brook_10mi_b150 | 0 | 0 | - | - | - | 2.13 | Only 0 routes match; try a different start or distance. Start 0.3 mi away at Podunk Road f |
| v2r_bear_brook_10mi_b150 | 0 | 0 | - | - | - | 2.12 | Only 0 routes match; try a different start or distance. Start 0.3 mi away at Podunk Road f |
| v2_bow_10mi_b30 | 1 | 0 | C6x1, C7x1 | 0.16 | 5.0-5.0 | 4.27 | Only 1 route match; try a different start or distance. Start 1.8 mi away at Single Circuit |
| v2r_bow_10mi_b30 | 1 | 0 | C6x1, C7x1 | 0.16 | 5.0-5.0 | 2.32 | Only 1 route match; try a different start or distance. Start 1.8 mi away at Single Circuit |
| v2_knox_10mi_b30 | 2 | 0 | C2x2, C5x2 | 0.491 | 9.1-10.2 | 5.49 | Only 2 routes match; try a different start or distance. Start 0.5 mi away at Pond Trail fo |
| v2r_knox_10mi_b30 | 3 | 0 | C2x3, C5x3, C6x1 | 0.5 | 7.1-10.3 | 2.45 | Only 3 routes match; try a different start or distance. Start 0.5 mi away at Pond Trail fo |
| v2_knox_10mi_b150 | 3 | 0 | C3x1, C5x2, C6x1, C7x2 | 0.536 | 9.5-14.7 | 2.45 | Only 3 routes match; try a different start or distance. |
| v2r_knox_10mi_b150 | 3 | 0 | C5x2, C6x1, C7x1 | 0.539 | 8.7-14.7 | 2.45 | Only 3 routes match; try a different start or distance. |
| v2_oak_hill_10mi_b30 | 6 | 0 | C5x1, C6x2, C7x6 | 0.301 | 9.2-12.5 | 3.41 |  |
| v2r_oak_hill_10mi_b30 | 6 | 0 | C5x1, C6x2, C7x6 | 0.301 | 9.2-12.5 | 2.79 |  |
| v2_oak_hill_10mi_b150 | 4 | 0 | C5x2, C6x2, C7x4 | 0.416 | 7.5-10.1 | 3.12 | Only 4 routes match; try a different start or distance. |
| v2r_oak_hill_10mi_b150 | 4 | 0 | C5x2, C6x2, C7x4 | 0.416 | 7.2-10.1 | 2.81 | Only 4 routes match; try a different start or distance. |
| v3_knox_10mi | 1 | 0 | C2x1, C5x1 | 0.643 | 9.9-9.9 | 2.68 | Only 1 route match; try a different start or distance. Start 0.5 mi away at Pond Trail for |
| adv_dead_end_bear_brook | 9 | 0 | C6x6, C7x5, C8x7 | 0.5 | 6.3-12.8 | 4.37 |  |
| adv_paved_via_bear_brook | 0 | 0 | - | - | - | 2.15 | Only 0 routes match; try a different start or distance. Start 0.3 mi away at Podunk Road f |
| adv_far_via_bear_brook | 0 | 0 | - | - | - | 0.33 | Only 0 routes match; try a different start or distance. Start 0.3 mi away at Podunk Road f |
| adv_off_network_franklin | 0 | 0 | - | - | - | 2.15 | Only 0 routes match; try a different start or distance. |
| adv_two_vias_50m_bow | 0 | 0 | - | - | - | 4.88 | Only 0 routes match; try a different start or distance. Start 1.8 mi away at Single Circui |
| adv_via_at_start_bow | 4 | 0 | C2x4 | 0.194 | 9.1-10.6 | 2.68 | Only 4 routes match; try a different start or distance. Start 1.8 mi away at Single Circui |
| p2p1_bow_knox | 1 | 1 | - | 0.021 | 4.9-4.9 | 0.6 | Only 1 route match; try a different start or distance. |
| p2p2_bow_knox | 0 | 0 | - | - | - | 0.31 | Only 0 routes match; try a different start or distance. |
| p2p1_knox_white_park | 9 | 0 | C6x2, C7x9 | 0.056 | 4.5-6.0 | 1.26 |  |
| p2p2_knox_white_park | 2 | 0 | C6x1, C7x2 | 0.125 | 5.7-6.0 | 0.76 | Only 2 routes match; try a different start or distance. |
| plain_bear_brook_10mi | 10 | 10 | - | 0.069 | 9.6-11.5 | 5.24 |  |
| plain_bow_10mi | 5 | 5 | - | 0.194 | 9.2-10.7 | 5.82 |  |
| plain_knox_10mi | 1 | 0 | C6x1 | 0.087 | 7.6-7.6 | 9.2 | Only 1 route match; try a different start or distance. |
| plain_oak_hill_10mi | 1 | 1 | - | 0.138 | 8.9-8.9 | 6.55 | Only 1 route match; try a different start or distance. Start 1.0 mi away at Tower Trail fo |
| plain_white_park_10mi | 10 | 1 | C6x3, C7x8 | 0.042 | 5.3-14.2 | 6.83 |  |
| plain_bear_brook_5mi | 10 | 10 | - | 0.1 | 4.3-5.6 | 3.52 |  |
| plain_bear_brook_15mi | 10 | 10 | - | 0.087 | 13.3-16.5 | 10.26 |  |
