# Midpoint routing benchmark: baseline: main's routing code (57957fe), before any routing change

Every returned option is checked (C1 closes/ends, C2 passes every midpoint, C3 in order, C4 real ways, C5 not an out-and-back, C6 distance, C7 road share, C8 honest notice). Public trailheads only.

| kind | scenarios | options | ok | C1 | C2 | C3 | C4 | C5 | C6 | C7 | C8 | no options | errors | p50 s | p95 s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| adversarial | 6 | 14 | 4 | 14 | 14 | 14 | 14 | 14 | 8 | 8 | 7 | 4 | 0 | 2.4 | 3.8 |
| one_via | 11 | 63 | 18 | 63 | 61 | 61 | 63 | 29 | 35 | 52 | 63 | 1 | 0 | 3.1 | 5.9 |
| p2p_one_via | 2 | 10 | 1 | 10 | 10 | 10 | 10 | 10 | 8 | 1 | 10 | 0 | 0 | 1.4 | 1.9 |
| p2p_two_vias | 2 | 2 | 0 | 2 | 2 | 2 | 2 | 2 | 1 | 0 | 2 | 1 | 0 | 1.0 | 1.5 |
| plain_loop | 7 | 49 | 39 | 49 | 49 | 49 | 49 | 49 | 45 | 41 | 49 | 0 | 0 | 8.1 | 12.9 |
| three_vias | 1 | 1 | 0 | 1 | 1 | 1 | 1 | 0 | 1 | 1 | 1 | 0 | 0 | 2.9 | 2.9 |
| two_vias | 4 | 9 | 1 | 9 | 8 | 7 | 9 | 4 | 5 | 9 | 9 | 0 | 0 | 2.9 | 3.8 |
| two_vias_reversed | 4 | 10 | 2 | 10 | 9 | 9 | 10 | 4 | 5 | 10 | 10 | 0 | 0 | 2.5 | 2.7 |
| **all** | 37 | 158 | 65 | 158 | 154 | 153 | 158 | 112 | 108 | 122 | 151 | 6 | 0 | 2.9 | 10.0 |

## Per scenario

| scenario | opts | ok | failing rules | worst retrace | miles | latency s | notice / error |
|---|---|---|---|---|---|---|---|
| v1_bear_brook_5mi_b135 | 6 | 5 | C6x1, C7x1 | 0.194 | 4.7-7.0 | 1.83 |  |
| v1_bear_brook_5mi_b315 | 10 | 4 | C2x2, C3x2, C5x4, C6x4 | 0.5 | 3.7-6.5 | 1.47 |  |
| v1_bear_brook_10mi_b135 | 9 | 6 | C5x3, C6x1 | 0.5 | 8.8-11.6 | 4.35 |  |
| v1_bear_brook_10mi_b225 | 4 | 0 | C5x4 | 0.5 | 9.6-11.2 | 1.73 | Only 4 routes match; try a different start or distance. Start 0.3 mi away at Podunk Road f |
| v1_bear_brook_10mi_b315 | 5 | 0 | C5x4, C6x3, C7x4 | 0.5 | 7.3-12.8 | 2.25 |  |
| v1_bear_brook_15mi_b135 | 4 | 0 | C5x2, C6x3, C7x1 | 0.5 | 10.0-13.1 | 3.62 | Only 4 routes match; try a different start or distance. |
| v1_bear_brook_15mi_b225 | 9 | 0 | C5x8, C6x6, C7x1 | 0.5 | 15.2-22.2 | 3.06 |  |
| v1_bear_brook_15mi_b315 | 2 | 0 | C6x2, C7x2 | 0.141 | 17.8-21.3 | 2.87 | Only 2 routes match; try a different start or distance. |
| v1_bow_10mi_b135 | 0 | 0 | - | - | - | 4.62 | Only 0 routes match; try a different start or distance. Start 1.8 mi away at Single Circui |
| v1_bow_10mi_b225 | 4 | 1 | C5x3, C6x3 | 0.498 | 11.1-14.0 | 3.6 | Only 4 routes match; try a different start or distance. |
| v1_knox_10mi_b135 | 10 | 2 | C5x6, C6x5, C7x2 | 0.5 | 7.2-13.1 | 5.93 |  |
| v2_bear_brook_10mi_b30 | 4 | 0 | C2x1, C3x2, C5x1, C6x2 | 0.44 | 8.5-12.3 | 2.81 | Only 4 routes match; try a different start or distance. |
| v2r_bear_brook_10mi_b30 | 4 | 1 | C2x1, C3x1, C5x1, C6x2 | 0.44 | 8.5-12.3 | 2.42 | Only 4 routes match; try a different start or distance. |
| v2_bear_brook_10mi_b150 | 2 | 1 | C5x1, C6x1 | 0.396 | 8.3-10.3 | 1.83 | Only 2 routes match; try a different start or distance. Start 0.3 mi away at Podunk Road f |
| v2r_bear_brook_10mi_b150 | 2 | 1 | C5x1, C6x1 | 0.396 | 8.3-10.3 | 1.69 | Only 2 routes match; try a different start or distance. Start 0.3 mi away at Podunk Road f |
| v2_knox_10mi_b30 | 2 | 0 | C5x2 | 0.491 | 9.1-10.2 | 2.94 | Only 2 routes match; try a different start or distance. Start 0.5 mi away at Pond Trail fo |
| v2r_knox_10mi_b30 | 3 | 0 | C5x3, C6x1 | 0.5 | 7.1-10.3 | 2.61 | Only 3 routes match; try a different start or distance. Start 0.5 mi away at Pond Trail fo |
| v2_oak_hill_10mi_b30 | 1 | 0 | C5x1, C6x1 | 0.35 | 7.9-7.9 | 3.76 | Only 1 route match; try a different start or distance. |
| v2r_oak_hill_10mi_b30 | 1 | 0 | C5x1, C6x1 | 0.35 | 7.9-7.9 | 2.74 | Only 1 route match; try a different start or distance. |
| v3_knox_10mi | 1 | 0 | C5x1 | 0.643 | 9.9-9.9 | 2.92 | Only 1 route match; try a different start or distance. Start 0.5 mi away at Pond Trail for |
| adv_dead_end_bear_brook | 9 | 0 | C6x6, C7x5, C8x7 | 0.5 | 6.3-12.8 | 2.62 |  |
| adv_paved_via_bear_brook | 0 | 0 | - | - | - | 2.21 | Only 0 routes match; try a different start or distance. Start 0.3 mi away at Podunk Road f |
| adv_far_via_bear_brook | 0 | 0 | - | - | - | 0.45 | Only 0 routes match; try a different start or distance. Start 0.3 mi away at Podunk Road f |
| adv_off_network_franklin | 0 | 0 | - | - | - | 2.13 | Only 0 routes match; try a different start or distance. |
| adv_two_vias_50m_bow | 0 | 0 | - | - | - | 3.84 | Only 0 routes match; try a different start or distance. Start 1.8 mi away at Single Circui |
| adv_via_at_start_bow | 5 | 4 | C7x1 | 0.194 | 9.2-10.9 | 3.39 |  |
| p2p1_bow_knox | 1 | 1 | - | 0.021 | 4.9-4.9 | 0.87 | Only 1 route match; try a different start or distance. |
| p2p2_bow_knox | 0 | 0 | - | - | - | 0.43 | Only 0 routes match; try a different start or distance. |
| p2p1_knox_white_park | 9 | 0 | C6x2, C7x9 | 0.056 | 4.5-6.0 | 1.91 |  |
| p2p2_knox_white_park | 2 | 0 | C6x1, C7x2 | 0.125 | 5.7-6.0 | 1.51 | Only 2 routes match; try a different start or distance. |
| plain_bear_brook_10mi | 10 | 10 | - | 0.088 | 9.4-10.6 | 6.38 |  |
| plain_bow_10mi | 7 | 7 | - | 0.194 | 9.2-10.7 | 6.32 |  |
| plain_knox_10mi | 1 | 0 | C6x1 | 0.087 | 7.6-7.6 | 9.99 | Only 1 route match; try a different start or distance. |
| plain_oak_hill_10mi | 1 | 1 | - | 0.138 | 8.9-8.9 | 8.07 | Only 1 route match; try a different start or distance. Start 1.0 mi away at Tower Trail fo |
| plain_white_park_10mi | 10 | 1 | C6x3, C7x8 | 0.042 | 5.3-14.2 | 8.67 |  |
| plain_bear_brook_5mi | 10 | 10 | - | 0.075 | 4.4-5.5 | 4.64 |  |
| plain_bear_brook_15mi | 10 | 10 | - | 0.087 | 13.3-16.5 | 12.91 |  |
