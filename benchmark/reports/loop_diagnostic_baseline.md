# Round 6 Routing Engine Diagnostic: Baseline Loop Generation Report

## Executive Summary
This diagnostic evaluates the current generator's ability to produce **true loops** (measured retrace $\le 10\%$) across Round 4 & Round 5 benchmark scenarios prior to the Round 6 architectural changes.

**Key Finding:** Out of all scenarios evaluated, **0 true loops (0.0%)** were generated. The current routing generator relies on waypoint synthesis (`[(start, start), wp1, wp2, (start, start)]`), which causes GraphHopper to route out and back along identical trails, resulting in repetition ratios between 20% and 60%.

## Diagnostic Results Table

| Scenario | Round | Target | Options | True Loops (<=10%) | In Range | Lollipops | Out-and-Backs | Min / Max Length | Avg Retrace | Avg Road |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| R4 Bear Brook (12.5 mi Target) | 4 | 12.5 mi | 1 | 0 | 0 | 1 | 0 | N/A | 22.7% | 13.9% |
| R4 Bear Brook (10.8 mi Target) | 4 | 10.8 mi | 3 | 0 | 0 | 3 | 0 | N/A | 24.9% | 6.5% |
| R4 Bear Brook (14.1 mi Target) | 4 | 14.1 mi | 3 | 0 | 0 | 3 | 0 | N/A | 31.6% | 11.6% |
| R5 Marsh Pond Loudon (4.0 mi Target) | 5 | 4.0 mi | 5 | 0 | 0 | 0 | 5 | N/A | 50.0% | 9.3% |
| R5 Kearsarge Winslow (8.0 mi Target) | 5 | 8.0 mi | 1 | 0 | 0 | 1 | 0 | N/A | 32.1% | 0.0% |
| R5 Bow Town Forest (6.0 mi Target) | 5 | 6.0 mi | 10 | 0 | 0 | 0 | 10 | N/A | 50.7% | 6.4% |
| R5 Franklin Falls (10.0 mi Target) | 5 | 10.0 mi | 6 | 0 | 0 | 0 | 6 | N/A | 50.7% | 14.0% |
| R5 Fort Mountain (5.0 mi Target) | 5 | 5.0 mi | 10 | 0 | 0 | 10 | 0 | N/A | 26.1% | 65.8% |
| R5 Oak Hill (4.0 mi Trail Run) | 5 | 4.0 mi | 6 | 0 | 0 | 6 | 0 | N/A | 29.8% | 82.2% |

## Rejection Reasons Analysis

### R4 Bear Brook (12.5 mi Target)
- **Area:** Bear Brook
- **Target Distance:** 12.5 miles
- **Generated Options:** 1 (0 true loops, 1 lollipops, 0 out-and-backs)
- **Primary Failure Modes / Rejections:**
  - `Bear Brook — Chipmunk Trail Lollipop Loop: Retrace 22.7% > 10% (lollipop); Distance 19.9mi outside tolerance (12.5mi ± 15%)`

### R4 Bear Brook (10.8 mi Target)
- **Area:** Bear Brook
- **Target Distance:** 10.8 miles
- **Generated Options:** 3 (0 true loops, 3 lollipops, 0 out-and-backs)
- **Primary Failure Modes / Rejections:**
  - `Bear Brook — Beaver Pond Trail Lollipop Loop: Retrace 15.9% > 10% (lollipop); Distance 14.0mi outside tolerance (10.8mi ± 15%)`
  - `Bear Brook — Chipmunk Trail Lollipop Loop: Retrace 34.2% > 10% (lollipop); Distance 15.7mi outside tolerance (10.8mi ± 15%)`
  - `Bear Brook — Chipmunk Trail Lollipop Loop: Retrace 24.5% > 10% (lollipop); Distance 19.0mi outside tolerance (10.8mi ± 15%)`

### R4 Bear Brook (14.1 mi Target)
- **Area:** Bear Brook
- **Target Distance:** 14.1 miles
- **Generated Options:** 3 (0 true loops, 3 lollipops, 0 out-and-backs)
- **Primary Failure Modes / Rejections:**
  - `Bear Brook — Chipmunk Trail Lollipop Loop: Retrace 29.6% > 10% (lollipop)`
  - `Bear Brook — Chipmunk Trail Lollipop Loop: Retrace 33.5% > 10% (lollipop)`
  - `Bear Brook — Chipmunk Trail Lollipop Loop: Retrace 31.6% > 10% (lollipop)`

### R5 Marsh Pond Loudon (4.0 mi Target)
- **Area:** Marsh Pond Loudon
- **Target Distance:** 4.0 miles
- **Generated Options:** 5 (0 true loops, 0 lollipops, 5 out-and-backs)
- **Primary Failure Modes / Rejections:**
  - `Bear Brook — Wiggins Road Out-and-Back: Retrace 50.0% > 10% (out_and_back)`
  - `Bear Brook — Wiggins Road Out-and-Back: Retrace 50.0% > 10% (out_and_back)`
  - `Bear Brook — Wiggins Road Out-and-Back: Retrace 50.0% > 10% (out_and_back)`
  - `Bear Brook — Wiggins Road Out-and-Back: Retrace 50.0% > 10% (out_and_back); Distance 5.0mi outside tolerance (4.0mi ± 15%)`
  - `Bear Brook — Wiggins Road Out-and-Back: Retrace 50.0% > 10% (out_and_back); Distance 5.0mi outside tolerance (4.0mi ± 15%)`

### R5 Kearsarge Winslow (8.0 mi Target)
- **Area:** Kearsarge Winslow
- **Target Distance:** 8.0 miles
- **Generated Options:** 1 (0 true loops, 1 lollipops, 0 out-and-backs)
- **Primary Failure Modes / Rejections:**
  - `Bear Brook — Baker Road Lollipop Loop: Retrace 32.1% > 10% (lollipop); Distance 5.4mi outside tolerance (8.0mi ± 15%)`

### R5 Bow Town Forest (6.0 mi Target)
- **Area:** Bow Town Forest
- **Target Distance:** 6.0 miles
- **Generated Options:** 10 (0 true loops, 0 lollipops, 10 out-and-backs)
- **Primary Failure Modes / Rejections:**
  - `Bear Brook — Powerlines Trail Out-and-Back: Retrace 52.5% > 10% (out_and_back)`
  - `Bear Brook — Single Circuit Out-and-Back: Retrace 51.3% > 10% (out_and_back)`
  - `Bear Brook — Single Circuit Out-and-Back: Retrace 50.0% > 10% (out_and_back); Distance 7.3mi outside tolerance (6.0mi ± 15%)`
  - `Bear Brook — Snowmobile trail Out-and-Back: Retrace 50.0% > 10% (out_and_back); Distance 7.4mi outside tolerance (6.0mi ± 15%)`
  - `Bear Brook — Morgan Drive Out-and-Back: Retrace 46.8% > 10% (out_and_back); Distance 4.3mi outside tolerance (6.0mi ± 15%)`

### R5 Franklin Falls (10.0 mi Target)
- **Area:** Franklin Falls
- **Target Distance:** 10.0 miles
- **Generated Options:** 6 (0 true loops, 0 lollipops, 6 out-and-backs)
- **Primary Failure Modes / Rejections:**
  - `Bear Brook — Timberland Drive Out-and-Back: Retrace 50.1% > 10% (out_and_back); Distance 32.0mi outside tolerance (10.0mi ± 15%)`
  - `Bear Brook — Northern Rail Trail Out-and-Back: Retrace 50.0% > 10% (out_and_back); Distance 33.4mi outside tolerance (10.0mi ± 15%)`
  - `Bear Brook — Timberland Drive Out-and-Back: Retrace 50.0% > 10% (out_and_back); Distance 32.0mi outside tolerance (10.0mi ± 15%)`
  - `Bear Brook — Timberland Drive Out-and-Back: Retrace 51.6% > 10% (out_and_back); Distance 31.3mi outside tolerance (10.0mi ± 15%)`
  - `Bear Brook — Timberland Drive Out-and-Back: Retrace 50.3% > 10% (out_and_back); Distance 31.3mi outside tolerance (10.0mi ± 15%)`

### R5 Fort Mountain (5.0 mi Target)
- **Area:** Fort Mountain
- **Target Distance:** 5.0 miles
- **Generated Options:** 10 (0 true loops, 10 lollipops, 0 out-and-backs)
- **Primary Failure Modes / Rejections:**
  - `Bear Brook — Mount Delight Road Lollipop Loop: Retrace 28.4% > 10% (lollipop); Distance 18.8mi outside tolerance (5.0mi ± 15%); Road 61.5% exceeds cap`
  - `Bear Brook — Griffin Road Lollipop Loop: Retrace 15.7% > 10% (lollipop); Distance 9.3mi outside tolerance (5.0mi ± 15%); Road 71.6% exceeds cap`
  - `Bear Brook — Mount Delight Road Lollipop Loop: Retrace 26.4% > 10% (lollipop); Distance 18.6mi outside tolerance (5.0mi ± 15%); Road 63.0% exceeds cap`
  - `Bear Brook — Mount Delight Road Lollipop Loop: Retrace 30.4% > 10% (lollipop); Distance 18.6mi outside tolerance (5.0mi ± 15%); Road 63.0% exceeds cap`
  - `Bear Brook — Mount Delight Road Lollipop Loop: Retrace 23.6% > 10% (lollipop); Distance 18.3mi outside tolerance (5.0mi ± 15%); Road 63.3% exceeds cap`

### R5 Oak Hill (4.0 mi Trail Run)
- **Area:** Oak Hill
- **Target Distance:** 4.0 miles
- **Generated Options:** 6 (0 true loops, 6 lollipops, 0 out-and-backs)
- **Primary Failure Modes / Rejections:**
  - `Bear Brook — Shaker Road Lollipop Loop: Retrace 28.0% > 10% (lollipop); Distance 5.5mi outside tolerance (4.0mi ± 15%); Road 77.4% exceeds cap`
  - `Bear Brook — River Trail Lollipop Loop: Retrace 32.8% > 10% (lollipop); Distance 16.7mi outside tolerance (4.0mi ± 15%); Road 84.5% exceeds cap`
  - `Bear Brook — River Trail Lollipop Loop: Retrace 31.6% > 10% (lollipop); Distance 13.2mi outside tolerance (4.0mi ± 15%); Road 80.7% exceeds cap`
  - `Bear Brook — Knowlton Trail Lollipop Loop: Retrace 22.1% > 10% (lollipop); Distance 11.3mi outside tolerance (4.0mi ± 15%); Road 81.7% exceeds cap`
  - `Bear Brook — Oak Hill Road Lollipop Loop: Retrace 30.1% > 10% (lollipop); Distance 7.8mi outside tolerance (4.0mi ± 15%); Road 84.2% exceeds cap`

## Root Cause Identification

1. **Geometric Waypoint Fallacy:** Computing circular/triangular waypoints in compass directions fails on real trail networks. Because trails do not run along arbitrary radial angles, GraphHopper routes to the nearest trail point, finds no connector to the second waypoint, and retraces back down the same trail.
2. **Tree-Structured Trailheads:** Starting from a single parking access point requires traversing an access stem before reaching circuit junctions. Without explicit topological cycle search, the engine retraces the entire access corridor.
3. **Absence of Topological Cycle Search:** The generator currently does not inspect the contracted trail graph (junctions and trail segments) to identify actual graph cycles returning to the start.

## Next Action
Proceed immediately to Task 2: Contracted-Graph Loop Search, building a contracted trail graph of junctions and edges to search self-avoiding walks returning to start.
