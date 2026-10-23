# Midpoint routing benchmark: after: loops through midpoints (GH-41)

Every returned option is checked (C1 closes/ends, C2 passes every midpoint, C3 in order, C4 real ways, C5 not an out-and-back, C6 distance, C7 road share, C8 honest notice). Public trailheads only.

| kind | scenarios | options | ok | C1 | C2 | C3 | C4 | C5 | C6 | C7 | C8 | no options | errors | p50 s | p95 s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| adversarial | 6 | 8 | 5 | 8 | 8 | 8 | 8 | 8 | 5 | 7 | 8 | 4 | 2 | 1.6 | 4.0 |
| one_via | 11 | 31 | 23 | 31 | 31 | 31 | 31 | 31 | 24 | 28 | 31 | 1 | 0 | 2.5 | 4.4 |
| p2p_one_via | 2 | 10 | 1 | 10 | 10 | 10 | 10 | 10 | 8 | 1 | 10 | 0 | 0 | 1.3 | 1.7 |
| p2p_two_vias | 2 | 2 | 0 | 2 | 2 | 2 | 2 | 2 | 1 | 0 | 2 | 1 | 0 | 0.8 | 1.2 |
| plain_loop | 7 | 49 | 39 | 49 | 49 | 49 | 49 | 49 | 45 | 41 | 49 | 0 | 0 | 8.3 | 12.0 |
| three_vias | 1 | 2 | 0 | 2 | 2 | 2 | 2 | 2 | 1 | 0 | 2 | 0 | 0 | 2.7 | 2.7 |
| two_vias | 4 | 11 | 4 | 11 | 11 | 11 | 11 | 11 | 5 | 9 | 11 | 0 | 0 | 2.5 | 3.6 |
| two_vias_reversed | 4 | 11 | 3 | 11 | 11 | 11 | 11 | 11 | 5 | 7 | 11 | 0 | 0 | 2.5 | 2.8 |
| **all** | 37 | 124 | 75 | 124 | 124 | 124 | 124 | 124 | 94 | 93 | 124 | 6 | 2 | 2.5 | 9.3 |

## Per scenario

| scenario | opts | ok | failing rules | worst retrace | miles | latency s | notice / error |
|---|---|---|---|---|---|---|---|
| v1_bear_brook_5mi_b135 | 4 | 4 | - | 0.115 | 4.5-5.6 | 1.3 | Only 4 routes match; try a different start or distance. |
| v1_bear_brook_5mi_b315 | 5 | 5 | - | 0.209 | 4.6-5.5 | 0.9 |  |
| v1_bear_brook_10mi_b135 | 6 | 6 | - | 0.088 | 9.7-11.2 | 3.37 |  |
| v1_bear_brook_10mi_b225 | 1 | 0 | C6x1 | 0.086 | 13.1-13.1 | 1.81 | Only 1 route match; try a different start or distance. |
| v1_bear_brook_10mi_b315 | 1 | 0 | C6x1 | 0.103 | 8.2-8.2 | 1.91 | Only 1 route match; try a different start or distance. Start 0.3 mi away at Podunk Road fo |
| v1_bear_brook_15mi_b135 | 6 | 4 | C6x2 | 0.152 | 11.6-16.2 | 4.38 |  |
| v1_bear_brook_15mi_b225 | 2 | 1 | C6x1, C7x1 | 0.133 | 15.1-21.4 | 2.67 | Only 2 routes match; try a different start or distance. |
| v1_bear_brook_15mi_b315 | 2 | 0 | C6x2, C7x1 | 0.13 | 12.4-21.2 | 2.49 | Only 2 routes match; try a different start or distance. |
| v1_bow_10mi_b135 | 0 | 0 | - | - | - | 4.42 | Only 0 routes match; try a different start or distance. Start 1.8 mi away at Single Circui |
| v1_bow_10mi_b225 | 1 | 1 | - | 0.02 | 11.1-11.1 | 2.36 | Only 1 route match; try a different start or distance. |
| v1_knox_10mi_b135 | 3 | 2 | C7x1 | 0.076 | 10.2-11.2 | 4.1 | Only 3 routes match; try a different start or distance. |
| v2_bear_brook_10mi_b30 | 6 | 2 | C6x4 | 0.173 | 6.1-10.2 | 2.53 |  |
| v2r_bear_brook_10mi_b30 | 6 | 3 | C6x3 | 0.242 | 7.0-11.3 | 2.51 |  |
| v2_bear_brook_10mi_b150 | 2 | 1 | C6x1 | 0.253 | 5.4-10.2 | 1.72 | Only 2 routes match; try a different start or distance. |
| v2r_bear_brook_10mi_b150 | 1 | 0 | C6x1 | 0.216 | 12.0-12.0 | 1.71 | Only 1 route match; try a different start or distance. Start 0.3 mi away at Podunk Road fo |
| v2_knox_10mi_b30 | 2 | 1 | C6x1, C7x1 | 0.195 | 8.1-9.0 | 2.42 | Only 2 routes match; try a different start or distance. |
| v2r_knox_10mi_b30 | 2 | 0 | C6x2, C7x2 | 0.142 | 7.5-8.1 | 2.44 | Only 2 routes match; try a different start or distance. |
| v2_oak_hill_10mi_b30 | 1 | 0 | C7x1 | 0.025 | 9.3-9.3 | 3.6 | Only 1 route match; try a different start or distance. |
| v2r_oak_hill_10mi_b30 | 2 | 0 | C7x2 | 0.233 | 8.8-9.3 | 2.76 | Only 2 routes match; try a different start or distance. |
| v3_knox_10mi | 2 | 0 | C6x1, C7x2 | 0.246 | 7.8-8.6 | 2.71 | Only 2 routes match; try a different start or distance. Start 0.5 mi away at Pond Trail fo |
| adv_dead_end_bear_brook | 3 | 0 | C6x3, C7x1 | 0.143 | 6.8-8.4 | 2.78 | Only 3 routes match; try a different start or distance. |
| adv_paved_via_bear_brook | 0 | 0 | - | - | - | 0.03 | MidpointError: Midpoint 1 is not on a way this profile can ride (the route passes 285 m aw |
| adv_far_via_bear_brook | 0 | 0 | - | - | - | 0.51 | Only 0 routes match; try a different start or distance. Start 0.3 mi away at Podunk Road f |
| adv_off_network_franklin | 0 | 0 | - | - | - | 0.01 | MidpointError: Midpoint 1 is 651 m from the nearest way. Move it onto a trail or road. |
| adv_two_vias_50m_bow | 0 | 0 | - | - | - | 4.0 | Only 0 routes match; try a different start or distance. Start 1.8 mi away at Single Circui |
| adv_via_at_start_bow | 5 | 5 | - | 0.194 | 9.2-10.6 | 2.75 |  |
| p2p1_bow_knox | 1 | 1 | - | 0.021 | 4.9-4.9 | 0.83 | Only 1 route match; try a different start or distance. |
| p2p2_bow_knox | 0 | 0 | - | - | - | 0.37 | Only 0 routes match; try a different start or distance. |
| p2p1_knox_white_park | 9 | 0 | C6x2, C7x9 | 0.056 | 4.5-6.0 | 1.71 |  |
| p2p2_knox_white_park | 2 | 0 | C6x1, C7x2 | 0.125 | 5.7-6.0 | 1.22 | Only 2 routes match; try a different start or distance. |
| plain_bear_brook_10mi | 10 | 10 | - | 0.088 | 9.4-10.6 | 5.7 |  |
| plain_bow_10mi | 7 | 7 | - | 0.194 | 9.2-10.7 | 6.15 |  |
| plain_knox_10mi | 1 | 0 | C6x1 | 0.087 | 7.6-7.6 | 9.28 | Only 1 route match; try a different start or distance. |
| plain_oak_hill_10mi | 1 | 1 | - | 0.138 | 8.9-8.9 | 8.69 | Only 1 route match; try a different start or distance. Start 1.0 mi away at Tower Trail fo |
| plain_white_park_10mi | 10 | 1 | C6x3, C7x8 | 0.042 | 5.3-14.2 | 8.33 |  |
| plain_bear_brook_5mi | 10 | 10 | - | 0.075 | 4.4-5.5 | 4.27 |  |
| plain_bear_brook_15mi | 10 | 10 | - | 0.095 | 13.3-16.2 | 12.03 |  |

## Before / after (before = via-baseline.json, same scenarios)

Options passing each rule, as passed / returned. `ok` = every rule.

| kind | options before | options after | ok before | ok after | C1 b/a | C2 b/a | C3 b/a | C4 b/a | C5 b/a | C6 b/a | C7 b/a | C8 b/a | p95 s b/a |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| adversarial | 14 | 8 | 4 | 5 | 14/8 | 14/8 | 14/8 | 14/8 | 14/8 | 8/5 | 8/7 | 7/8 | 3.8/4.0 |
| one_via | 63 | 31 | 18 | 23 | 63/31 | 61/31 | 61/31 | 63/31 | 29/31 | 35/24 | 52/28 | 63/31 | 5.9/4.4 |
| p2p_one_via | 10 | 10 | 1 | 1 | 10/10 | 10/10 | 10/10 | 10/10 | 10/10 | 8/8 | 1/1 | 10/10 | 1.9/1.7 |
| p2p_two_vias | 2 | 2 | 0 | 0 | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 | 1/1 | 0/0 | 2/2 | 1.5/1.2 |
| plain_loop | 49 | 49 | 39 | 39 | 49/49 | 49/49 | 49/49 | 49/49 | 49/49 | 45/45 | 41/41 | 49/49 | 12.9/12.0 |
| three_vias | 1 | 2 | 0 | 0 | 1/2 | 1/2 | 1/2 | 1/2 | 0/2 | 1/1 | 1/0 | 1/2 | 2.9/2.7 |
| two_vias | 9 | 11 | 1 | 4 | 9/11 | 8/11 | 7/11 | 9/11 | 4/11 | 5/5 | 9/9 | 9/11 | 3.8/3.6 |
| two_vias_reversed | 10 | 11 | 2 | 3 | 10/11 | 9/11 | 9/11 | 10/11 | 4/11 | 5/5 | 10/7 | 10/11 | 2.7/2.8 |
| **all** | 158 | 124 | 65 | 75 | 158/124 | 154/124 | 153/124 | 158/124 | 112/124 | 108/94 | 122/93 | 151/124 | 10.0/9.3 |
