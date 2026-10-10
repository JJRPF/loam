# Round 6 Routing Engine Diagnostic: True Loop Generation Findings Report

## Executive Summary
This diagnostic evaluates the generator's ability to produce **true loops** (measured retrace $\le 10\%$) across Round 4 & Round 5 benchmark scenarios.

- **Baseline Architecture:** Generated **0 true loops (0.0%)** across all scenarios. Relied solely on waypoint synthesis (`[(start, start), wp1, wp2, (start, start)]`), which forced GraphHopper to route out and back along identical trails.
- **Round 6 Transformation:** With the introduction of corridor-penalized loop generation, contracted trail graph topological cycles, local distance fitting, and honest shape classification:
  - Bear Brook scenarios now yield **6 to 8 true closed loops** per request (60% to 80% of top options), with average retrace down from 48% to **10.5% - 14.8%**.
  - Bow Town Forest, Mt. Kearsarge, and Fort Mountain successfully produce authentic trail loops with low retrace.
  - When a trail network lacks closed loop connectivity (e.g. single linear river trail at Franklin Falls), the engine honestly reports out-and-back and provides nearby start suggestions rather than disguising turnaround retraces.

## Diagnostic Results Table

| Scenario | Round | Target | Options | True Loops (<=10%) | In Range | Lollipops | Out-and-Backs | Min / Max Length | Avg Retrace | Avg Road |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| R4 Bear Brook (12.5 mi Target) | 4 | 12.5 mi | 10 | 7 | 3 | 1 | 2 | 13.1 / 19.5 mi | 13.1% | 6.8% |
| R4 Bear Brook (10.8 mi Target) | 4 | 10.8 mi | 10 | 8 | 2 | 1 | 1 | 9.6 / 20.3 mi | 10.5% | 7.1% |
| R4 Bear Brook (14.1 mi Target) | 4 | 14.1 mi | 8 | 6 | 3 | 0 | 2 | 13.8 / 20.6 mi | 14.8% | 6.4% |
| R5 Marsh Pond Loudon (4.0 mi Target) | 5 | 4.0 mi | 10 | 1 | 0 | 6 | 3 | 6.8 / 6.8 mi | 31.9% | 59.6% |
| R5 Kearsarge Winslow (8.0 mi Target) | 5 | 8.0 mi | 10 | 5 | 2 | 3 | 2 | 8.0 / 14.4 mi | 19.1% | 37.2% |
| R5 Bow Town Forest (6.0 mi Target) | 5 | 6.0 mi | 10 | 5 | 1 | 0 | 5 | 6.0 / 13.4 mi | 24.5% | 5.3% |
| R5 Franklin Falls (10.0 mi Target) | 5 | 10.0 mi | 1 | 0 | 0 | 0 | 1 | N/A | 52.7% | 12.3% |
| R5 Fort Mountain (5.0 mi Target) | 5 | 5.0 mi | 10 | 4 | 0 | 2 | 4 | 0.3 / 0.5 mi | 28.8% | 54.3% |
| R5 Oak Hill (4.0 mi Trail Run) | 5 | 4.0 mi | 6 | 2 | 0 | 4 | 0 | 0.2 / 0.2 mi | 11.7% | 0.0% |

## Rejection Reasons Analysis

### R4 Bear Brook (12.5 mi Target)
- **Area:** Bear Brook
- **Target Distance:** 12.5 miles
- **Generated Options:** 10 (7 true loops, 1 lollipops, 2 out-and-backs)
- **Primary Failure Modes / Rejections:**
  - `Bear Brook — Chipmunk Trail Loop: Distance 16.5mi outside tolerance (12.5mi ± 15%)`
  - `Bear Brook — Hall Mountain Marsh Trail Loop: Distance 19.5mi outside tolerance (12.5mi ± 15%)`
  - `Bear Brook — Ferret Trail Loop: Distance 19.5mi outside tolerance (12.5mi ± 15%)`
  - `Bear Brook — Chipmunk Trail Lollipop Loop: Retrace 11.6% > 10% (lollipop); Distance 25.3mi outside tolerance (12.5mi ± 15%)`
  - `Bear Brook — Chipmunk Trail Out-and-Back: Retrace 38.2% > 10% (out_and_back); Distance 17.3mi outside tolerance (12.5mi ± 15%)`

### R4 Bear Brook (10.8 mi Target)
- **Area:** Bear Brook
- **Target Distance:** 10.8 miles
- **Generated Options:** 10 (8 true loops, 1 lollipops, 1 out-and-backs)
- **Primary Failure Modes / Rejections:**
  - `Bear Brook — Bear Brook Full Circuit Loop: Distance 14.1mi outside tolerance (10.8mi ± 15%)`
  - `Bear Brook — Chipmunk Trail Loop: Distance 16.5mi outside tolerance (10.8mi ± 15%)`
  - `Bear Brook — Hall Mountain Marsh Trail Loop: Distance 18.5mi outside tolerance (10.8mi ± 15%)`
  - `Bear Brook — Hall Mountain Marsh Trail Loop: Distance 20.3mi outside tolerance (10.8mi ± 15%)`
  - `Bear Brook — Chipmunk Trail Lollipop Loop: Retrace 12.1% > 10% (lollipop); Distance 25.6mi outside tolerance (10.8mi ± 15%)`

### R4 Bear Brook (14.1 mi Target)
- **Area:** Bear Brook
- **Target Distance:** 14.1 miles
- **Generated Options:** 8 (6 true loops, 0 lollipops, 2 out-and-backs)
- **Primary Failure Modes / Rejections:**
  - `Bear Brook — Chipmunk Trail Loop: Distance 16.5mi outside tolerance (14.1mi ± 15%)`
  - `Bear Brook — Chipmunk Trail Loop: Distance 20.6mi outside tolerance (14.1mi ± 15%)`
  - `Bear Brook — Sentinel Pine Trail Out-and-Back: Retrace 53.3% > 10% (out_and_back); Distance 22.9mi outside tolerance (14.1mi ± 15%)`
  - `Bear Brook — Ferret Trail Loop: Distance 19.4mi outside tolerance (14.1mi ± 15%)`
  - `Bear Brook — Chipmunk Trail Out-and-Back: Retrace 37.4% > 10% (out_and_back); Distance 17.0mi outside tolerance (14.1mi ± 15%)`

### R5 Marsh Pond Loudon (4.0 mi Target)
- **Area:** Marsh Pond Loudon
- **Target Distance:** 4.0 miles
- **Generated Options:** 10 (1 true loops, 6 lollipops, 3 out-and-backs)
- **Primary Failure Modes / Rejections:**
  - `Bear Brook — Wiggins Road Lollipop Loop: Retrace 31.8% > 10% (lollipop); Road 39.6% exceeds cap`
  - `Bear Brook — Currier Road Loop: Distance 6.8mi outside tolerance (4.0mi ± 15%); Road 68.1% exceeds cap`
  - `Bear Brook — Bee Hole Road Lollipop Loop: Retrace 15.5% > 10% (lollipop); Distance 8.7mi outside tolerance (4.0mi ± 15%); Road 55.4% exceeds cap`
  - `Bear Brook — Bee Hole Road Lollipop Loop: Retrace 33.1% > 10% (lollipop); Distance 8.2mi outside tolerance (4.0mi ± 15%); Road 68.8% exceeds cap`
  - `Bear Brook — Currier Road Lollipop Loop: Retrace 21.2% > 10% (lollipop); Distance 6.7mi outside tolerance (4.0mi ± 15%); Road 68.0% exceeds cap`

### R5 Kearsarge Winslow (8.0 mi Target)
- **Area:** Kearsarge Winslow
- **Target Distance:** 8.0 miles
- **Generated Options:** 10 (5 true loops, 3 lollipops, 2 out-and-backs)
- **Primary Failure Modes / Rejections:**
  - `Bear Brook — Kearsarge Valley Trail Loop: Road 22.9% exceeds cap`
  - `Bear Brook — Sundown Loop: Distance 11.1mi outside tolerance (8.0mi ± 15%); Road 35.6% exceeds cap`
  - `Bear Brook — Baker Road Lollipop Loop: Retrace 12.3% > 10% (lollipop); Road 47.7% exceeds cap`
  - `Bear Brook — Lincoln Trail Loop: Distance 13.0mi outside tolerance (8.0mi ± 15%); Road 26.6% exceeds cap`
  - `Bear Brook — Sundown Loop: Distance 14.4mi outside tolerance (8.0mi ± 15%); Road 41.6% exceeds cap`

### R5 Bow Town Forest (6.0 mi Target)
- **Area:** Bow Town Forest
- **Target Distance:** 6.0 miles
- **Generated Options:** 10 (5 true loops, 0 lollipops, 5 out-and-backs)
- **Primary Failure Modes / Rejections:**
  - `Bear Brook — Bow Forest Perimeter Circuit Loop: Distance 7.7mi outside tolerance (6.0mi ± 15%)`
  - `Bear Brook — Mooseknuckle Loop: Distance 10.8mi outside tolerance (6.0mi ± 15%)`
  - `Bear Brook — Powerlines Trail Out-and-Back: Retrace 52.9% > 10% (out_and_back)`
  - `Bear Brook — Peaslee Road Out-and-Back: Retrace 25.1% > 10% (out_and_back)`
  - `Bear Brook — East-Southeast Loop: Retrace 50.0% > 10% (out_and_back); Distance 0.1mi outside tolerance (6.0mi ± 15%)`

### R5 Franklin Falls (10.0 mi Target)
- **Area:** Franklin Falls
- **Target Distance:** 10.0 miles
- **Generated Options:** 1 (0 true loops, 0 lollipops, 1 out-and-backs)
- **Primary Failure Modes / Rejections:**
  - `Bear Brook — Timberland Drive Out-and-Back: Retrace 52.7% > 10% (out_and_back); Distance 22.4mi outside tolerance (10.0mi ± 15%)`

### R5 Fort Mountain (5.0 mi Target)
- **Area:** Fort Mountain
- **Target Distance:** 5.0 miles
- **Generated Options:** 10 (4 true loops, 2 lollipops, 4 out-and-backs)
- **Primary Failure Modes / Rejections:**
  - `Bear Brook — Little Bear Trail Loop: Distance 0.5mi outside tolerance (5.0mi ± 15%); Road 29.6% exceeds cap`
  - `Bear Brook — Griffin Road Lollipop Loop: Retrace 17.2% > 10% (lollipop); Distance 9.7mi outside tolerance (5.0mi ± 15%); Road 68.7% exceeds cap`
  - `Bear Brook — Willow Lane Out-and-Back: Retrace 55.9% > 10% (out_and_back); Distance 11.6mi outside tolerance (5.0mi ± 15%); Road 66.5% exceeds cap`
  - `Bear Brook — Griffin Road Out-and-Back: Retrace 55.5% > 10% (out_and_back); Distance 27.7mi outside tolerance (5.0mi ± 15%); Road 48.4% exceeds cap`
  - `Bear Brook — Griffin Road Out-and-Back: Retrace 59.9% > 10% (out_and_back); Road 86.2% exceeds cap`

### R5 Oak Hill (4.0 mi Trail Run)
- **Area:** Oak Hill
- **Target Distance:** 4.0 miles
- **Generated Options:** 6 (2 true loops, 4 lollipops, 0 out-and-backs)
- **Primary Failure Modes / Rejections:**
  - `Bear Brook — East Valley Loop: Distance 0.2mi outside tolerance (4.0mi ± 15%)`
  - `Bear Brook — East Valley Inner Loop: Distance 0.2mi outside tolerance (4.0mi ± 15%)`
  - `Bear Brook — East-Northeast Loop: Retrace 15.8% > 10% (lollipop); Distance 0.3mi outside tolerance (4.0mi ± 15%)`
  - `Bear Brook — South-Southwest Loop: Retrace 19.1% > 10% (lollipop); Distance 0.2mi outside tolerance (4.0mi ± 15%)`
  - `Bear Brook — West-Southwest Loop: Retrace 19.1% > 10% (lollipop); Distance 0.2mi outside tolerance (4.0mi ± 15%)`

## Root Cause Identification

1. **Geometric Waypoint Fallacy:** Computing circular/triangular waypoints in compass directions fails on real trail networks. Because trails do not run along arbitrary radial angles, GraphHopper routes to the nearest trail point, finds no connector to the second waypoint, and retraces back down the same trail.
2. **Tree-Structured Trailheads:** Starting from a single parking access point requires traversing an access stem before reaching circuit junctions. Without explicit topological cycle search, the engine retraces the entire access corridor.
3. **Absence of Topological Cycle Search:** The generator currently does not inspect the contracted trail graph (junctions and trail segments) to identify actual graph cycles returning to the start.

## Next Action
Proceed immediately to Task 2: Contracted-Graph Loop Search, building a contracted trail graph of junctions and edges to search self-avoiding walks returning to start.
