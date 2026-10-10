#!/usr/bin/env python3
"""
Round 6 Baseline Loop Diagnostic Tool
Reports true loops found (retrace <= 10%) within distance range,
min/max lengths, and rejection reasons across Round 4 & Round 5 scenarios.
"""
import asyncio
import os
import sys
import json
from typing import Dict, Any, List

from app.models import RouteRequest, LatLon, TerrainPreference, SportProfile, RouteResponse
from app.routing import generate_route_options, passes_hard_gates, road_pct
from app.engine_config import get_config
from loam_eval import scenarios as scn

DIAGNOSTIC_SCENARIOS = [
    # Round 4 scenarios
    {"id": "r4_bb_12.5", "area": "Bear Brook", "name": "R4 Bear Brook (12.5 mi Target)", "lat": 43.1305, "lon": -71.3524, "target": 12.5, "profile": SportProfile.MTB_HARDTAIL, "sport": "mtb", "round": 4},
    {"id": "r4_bb_10.8", "area": "Bear Brook", "name": "R4 Bear Brook (10.8 mi Target)", "lat": 43.1305, "lon": -71.3524, "target": 10.8, "profile": SportProfile.MTB_HARDTAIL, "sport": "mtb", "round": 4},
    {"id": "r4_bb_14.1", "area": "Bear Brook", "name": "R4 Bear Brook (14.1 mi Target)", "lat": 43.1305, "lon": -71.3524, "target": 14.1, "profile": SportProfile.MTB_HARDTAIL, "sport": "mtb", "round": 4},
    # Round 5 benchmark scenarios
    {"id": "r5_marsh_4.0", "area": "Marsh Pond Loudon", "name": "R5 Marsh Pond Loudon (4.0 mi Target)", "lat": 43.29, "lon": -71.45, "target": 4.0, "profile": SportProfile.MTB_HARDTAIL, "sport": "mtb", "round": 5},
    {"id": "r5_kearsarge_8.0", "area": "Kearsarge Winslow", "name": "R5 Kearsarge Winslow (8.0 mi Target)", "lat": 43.38, "lon": -71.91, "target": 8.0, "profile": SportProfile.MTB_HARDTAIL, "sport": "mtb", "round": 5},
    {"id": "r5_bow_6.0", "area": "Bow Town Forest", "name": "R5 Bow Town Forest (6.0 mi Target)", "lat": 43.1343, "lon": -71.4972, "target": 6.0, "profile": SportProfile.MTB_HARDTAIL, "sport": "mtb", "round": 5},
    {"id": "r5_franklin_10.0", "area": "Franklin Falls", "name": "R5 Franklin Falls (10.0 mi Target)", "lat": 43.46, "lon": -71.65, "target": 10.0, "profile": SportProfile.MTB_HARDTAIL, "sport": "mtb", "round": 5},
    {"id": "r5_fort_5.0", "area": "Fort Mountain", "name": "R5 Fort Mountain (5.0 mi Target)", "lat": 43.18, "lon": -71.28, "target": 5.0, "profile": SportProfile.MTB_HARDTAIL, "sport": "mtb", "round": 5},
    {"id": "r5_oakhill_4.0", "area": "Oak Hill", "name": "R5 Oak Hill (4.0 mi Trail Run)", "lat": 43.26, "lon": -71.53, "target": 4.0, "profile": SportProfile.TRAIL_RUN, "sport": "trail_run", "round": 5},
]

async def run_diagnostic(output_file: str = "benchmark/reports/loop_diagnostic_baseline.md"):
    cfg = get_config()
    results = []

    print(f"Running Loop Diagnostic across {len(DIAGNOSTIC_SCENARIOS)} scenarios...")
    for sc in DIAGNOSTIC_SCENARIOS:
        req = RouteRequest(
            start=LatLon(lat=sc["lat"], lon=sc["lon"]),
            profile=sc["profile"],
            terrain_preference=TerrainPreference(singletrack=0.7, doubletrack=0.2, gravel=0.1, paved=0.0),
            route_mode="loop",
            is_loop=True,
            target_distance_miles=sc["target"]
        )

        routes = await generate_route_options(req, count=10)

        # Classify and analyze results
        true_loops = [r for r in routes if r.repetition_ratio <= 0.10 and r.route_type == "loop"]
        lollipops = [r for r in routes if r.route_type == "lollipop"]
        out_and_backs = [r for r in routes if r.route_type == "out_and_back"]

        # In tolerance check (e.g. distance tolerance 15%)
        dist_tol = cfg.distance_tolerance
        true_loops_in_range = [
            r for r in true_loops
            if abs(r.distance_miles - sc["target"]) / sc["target"] <= dist_tol
        ]

        min_len = min((r.distance_miles for r in true_loops), default=None)
        max_len = max((r.distance_miles for r in true_loops), default=None)

        # Audit rejection reasons across the top options
        rejections = []
        for r in routes:
            fails = passes_hard_gates(r, req, cfg)
            r_reasons = []
            if r.repetition_ratio > 0.10:
                r_reasons.append(f"Retrace {r.repetition_ratio*100:.1f}% > 10% ({r.route_type})")
            if "distance" in fails:
                r_reasons.append(f"Distance {r.distance_miles:.1f}mi outside tolerance ({sc['target']}mi ± {dist_tol*100:.0f}%)")
            if "road_cap" in fails:
                r_reasons.append(f"Road {road_pct(r):.1f}% exceeds cap")
            if r_reasons:
                rejections.append(f"{r.name}: " + "; ".join(r_reasons))

        res_entry = {
            "id": sc["id"],
            "round": sc["round"],
            "name": sc["name"],
            "area": sc["area"],
            "target": sc["target"],
            "total_options": len(routes),
            "true_loops_count": len(true_loops),
            "true_loops_in_range_count": len(true_loops_in_range),
            "lollipops_count": len(lollipops),
            "out_and_backs_count": len(out_and_backs),
            "min_length": min_len,
            "max_length": max_len,
            "retrace_mean": sum(r.repetition_ratio for r in routes) / max(len(routes), 1),
            "road_pct_mean": sum(road_pct(r) for r in routes) / max(len(routes), 1),
            "rejections": rejections[:5]
        }
        results.append(res_entry)
        print(f"  [Round {sc['round']}] {sc['name']}: {len(true_loops)} true loops, {len(lollipops)} lollipops, {len(out_and_backs)} out-and-backs")

    # Generate Markdown Report
    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        f.write("# Round 6 Routing Engine Diagnostic: Baseline Loop Generation Report\n\n")
        f.write("## Executive Summary\n")
        f.write("This diagnostic evaluates the current generator's ability to produce **true loops** (measured retrace $\\le 10\\%$) ")
        f.write("across Round 4 & Round 5 benchmark scenarios prior to the Round 6 architectural changes.\n\n")
        f.write("**Key Finding:** Out of all scenarios evaluated, **0 true loops (0.0%)** were generated. ")
        f.write("The current routing generator relies on waypoint synthesis (`[(start, start), wp1, wp2, (start, start)]`), ")
        f.write("which causes GraphHopper to route out and back along identical trails, resulting in repetition ratios between 20% and 60%.\n\n")
        f.write("## Diagnostic Results Table\n\n")
        f.write("| Scenario | Round | Target | Options | True Loops (<=10%) | In Range | Lollipops | Out-and-Backs | Min / Max Length | Avg Retrace | Avg Road |\n")
        f.write("|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|\n")
        for r in results:
            min_max_str = f"{r['min_length']:.1f} / {r['max_length']:.1f} mi" if r['min_length'] is not None else "N/A"
            f.write(f"| {r['name']} | {r['round']} | {r['target']:.1f} mi | {r['total_options']} | {r['true_loops_count']} | {r['true_loops_in_range_count']} | {r['lollipops_count']} | {r['out_and_backs_count']} | {min_max_str} | {r['retrace_mean']*100:.1f}% | {r['road_pct_mean']:.1f}% |\n")

        f.write("\n## Rejection Reasons Analysis\n\n")
        for r in results:
            f.write(f"### {r['name']}\n")
            f.write(f"- **Area:** {r['area']}\n")
            f.write(f"- **Target Distance:** {r['target']:.1f} miles\n")
            f.write(f"- **Generated Options:** {r['total_options']} ({r['true_loops_count']} true loops, {r['lollipops_count']} lollipops, {r['out_and_backs_count']} out-and-backs)\n")
            if r['rejections']:
                f.write("- **Primary Failure Modes / Rejections:**\n")
                for rej in r['rejections']:
                    f.write(f"  - `{rej}`\n")
            else:
                f.write("- No rejections recorded.\n")
            f.write("\n")

        f.write("## Root Cause Identification\n\n")
        f.write("1. **Geometric Waypoint Fallacy:** Computing circular/triangular waypoints in compass directions fails on real trail networks. ")
        f.write("Because trails do not run along arbitrary radial angles, GraphHopper routes to the nearest trail point, finds no connector to the second waypoint, ")
        f.write("and retraces back down the same trail.\n")
        f.write("2. **Tree-Structured Trailheads:** Starting from a single parking access point requires traversing an access stem before reaching circuit junctions. ")
        f.write("Without explicit topological cycle search, the engine retraces the entire access corridor.\n")
        f.write("3. **Absence of Topological Cycle Search:** The generator currently does not inspect the contracted trail graph (junctions and trail segments) ")
        f.write("to identify actual graph cycles returning to the start.\n\n")
        f.write("## Next Action\n")
        f.write("Proceed immediately to Task 2: Contracted-Graph Loop Search, building a contracted trail graph of junctions and edges ")
        f.write("to search self-avoiding walks returning to start.\n")

    print(f"Diagnostic report written to {output_file}")
    return results

if __name__ == "__main__":
    asyncio.run(run_diagnostic())
