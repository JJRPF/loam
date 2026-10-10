"""Benchmark scenario generator (seeded, stratified 60/20/20 split).

Areas are public parks/trail networks only: no personal GPS and no sensitive-trail
coordinates. Run ``loam-eval scenarios`` to regenerate ``benchmark/scenarios.json``.
"""
from __future__ import annotations

import json
import os
import random
from typing import Any, Dict, List

SPLIT_SEED = 30

# (name, lat, lon) - public networks in New Hampshire (approximate trailhead areas)
AREAS = [
    ("Bear Brook", 43.1305, -71.3524),
    ("Bow Town Forest", 43.1343, -71.4972),
    ("Pawtuckaway", 43.0830, -71.1770),
    ("Hall Mountain", 43.1350, -71.3450),
    ("Highland Mountain", 43.4357, -71.6111),
    ("Kearsarge Winslow", 43.3720, -71.8560),
    ("Great Brook Goffstown", 43.0170, -71.5950),
    ("Oak Hill Concord", 43.2360, -71.5230),
    ("Marsh Pond Loudon", 43.2900, -71.4500),
    ("Bedford Town Forest", 43.0000, -71.5200),
    ("Pisgah Winchester", 42.8000, -72.4100),
    ("Gunstock", 43.5400, -71.3700),
]

TERRAIN_PRESETS = [
    {"singletrack": 0.6, "doubletrack": 0.2, "gravel": 0.15, "paved": 0.05},
    {"singletrack": 0.8, "doubletrack": 0.1, "gravel": 0.10, "paved": 0.00},
    {"singletrack": 0.4, "doubletrack": 0.3, "gravel": 0.20, "paved": 0.10},
    {"singletrack": 0.5, "doubletrack": 0.2, "gravel": 0.10, "paved": 0.20},
]

BASE_WEIGHTS = {"loop": 3.0, "loop_spurs": 2.0, "lollipop": 3.0, "fake_lollipop": 2.0,
                "out_and_back": 2.0, "road_loop": 1.5, "point_to_point": 0.3}

SHAPE_COUNTS = [("loop", 52), ("lollipop_ok", 14), ("out_and_back", 7), ("point_to_point", 7)]


def _round4_scenarios() -> List[Dict[str, Any]]:
    """Seed scenarios from the Round 4 screenshots (see issue #30)."""
    base = dict(area="Bear Brook", start={"lat": 43.1305, "lon": -71.3524}, shape="lollipop_ok",
                target_miles=12.5, sport="mtb", sport_profile="mtb_hardtail",
                terrain=TERRAIN_PRESETS[0], road_cap_pct=15.0, covered=True, ghost_frac=0.0,
                road_prevalence=0.05, climb_ft_per_mile=85.0, tags=["round4"])
    # The issue's 14.1 mi "best" route has 25% repeat: under the 10%/35% thresholds that is a
    # lollipop-class route, so this scenario accepts lollipop (<=35% retrace) but never out-and-back.
    r4a = dict(base, id="r4_true_loop_vs_retraced", seed=40001, notes=(
        "14.1 mi 25%-retrace lollipop must outrank a 10.8 mi out-and-back and fake lollipops (47% repeat; engine convention caps repeat at 50%)."),
        pool_spec=[
            {"archetype": "lollipop", "miles": 14.1, "retrace": 0.25},
            {"archetype": "out_and_back", "miles": 10.8},
            {"archetype": "fake_lollipop", "miles": 12.6, "retrace": 0.47},
            {"archetype": "fake_lollipop", "miles": 12.0, "retrace": 0.47},
            {"archetype": "road_loop", "miles": 12.5},
        ])
    r4b = dict(base, id="r4_road_cap", seed=40002, shape="loop", notes=(
        "A loop with ~45% road must never beat a lower-road alternative."),
        pool_spec=[
            {"archetype": "road_loop", "miles": 12.4},
            {"archetype": "road_loop", "miles": 12.6},
            {"archetype": "loop", "miles": 13.5, "road_share": 0.0},
            {"archetype": "loop", "miles": 11.8, "road_share": 0.05},
        ])
    r4c = dict(base, id="r4_oab_label", seed=40003, notes="10.8 mi out-and-back must be labelled out_and_back.",
               shape="out_and_back", target_miles=10.8,
               pool_spec=[{"archetype": "out_and_back", "miles": 10.8},
                          {"archetype": "fake_lollipop", "miles": 10.9, "retrace": 0.47}])
    return [r4a, r4b, r4c]


def generate() -> List[Dict[str, Any]]:
    rng = random.Random(SPLIT_SEED)
    scenarios: List[Dict[str, Any]] = []
    idx = 0
    for shape, n in SHAPE_COUNTS:
        for _ in range(n):
            idx += 1
            area = AREAS[rng.randrange(len(AREAS))]
            sport = "trail_run" if rng.random() < 0.2 else "mtb"
            target = rng.choice([4, 5, 6, 8, 10, 12, 14, 16]) if sport == "mtb" else rng.choice([3, 4, 5, 6, 8, 10])
            terrain = TERRAIN_PRESETS[rng.randrange(len(TERRAIN_PRESETS))]
            w = {k: round(v * rng.uniform(0.5, 1.5), 3) for k, v in BASE_WEIGHTS.items()}
            if rng.random() < 0.3:        # sparse network: few true loops available
                w["loop"] = round(w["loop"] * 0.3, 3)
                w["loop_spurs"] = round(w["loop_spurs"] * 0.5, 3)
            if shape == "point_to_point":
                w["point_to_point"] = 8.0
            sc = {
                "id": f"s{idx:03d}", "seed": 10000 + idx, "area": area[0],
                "start": {"lat": area[1], "lon": area[2]},
                "shape": shape, "target_miles": float(target), "sport": sport,
                "sport_profile": "trail_run" if sport == "trail_run" else "mtb_hardtail",
                "terrain": terrain,
                "road_cap_pct": 15.0 if terrain["paved"] < 0.15 else 25.0,
                "covered": rng.random() < 0.7, "ghost_frac": rng.choice([0.0, 0.0, 0.1, 0.2]),
                "road_prevalence": rng.choice([0.03, 0.08, 0.15, 0.25]),
                "climb_ft_per_mile": float(rng.choice([60, 85, 110])),
                "archetype_weights": w, "tags": [shape, area[0].split()[0].lower()],
            }
            if shape == "point_to_point":
                sc["end"] = {"lat": round(area[1] + 0.01 * rng.uniform(0.5, 1.5), 5),
                             "lon": round(area[2] + 0.01 * rng.uniform(0.5, 1.5), 5)}
            scenarios.append(sc)

    # Stratified 60/20/20 split by shape (deterministic)
    by_shape: Dict[str, List[Dict[str, Any]]] = {}
    for sc in scenarios:
        by_shape.setdefault(sc["shape"], []).append(sc)
    for shape, group in by_shape.items():
        order = list(group)
        rng.shuffle(order)
        n = len(order)
        n_train, n_val = round(n * 0.6), round(n * 0.2)
        for i, sc in enumerate(order):
            sc["split"] = "train" if i < n_train else ("val" if i < n_train + n_val else "holdout")

    # Round-4 seeds live in train/val only: the holdout stays free of hand-written cases.
    for i, sc in enumerate(_round4_scenarios()):
        sc["split"] = "val" if sc["id"] == "r4_road_cap" else "train"
        scenarios.append(sc)
    return scenarios


def write(path: str) -> List[Dict[str, Any]]:
    scs = generate()
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"version": 1, "split_seed": SPLIT_SEED, "scenarios": scs}, fh, indent=1, sort_keys=True)
        fh.write("\n")
    return scs


def load(path: str, split: str | None = None) -> List[Dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)["scenarios"]
    if split in (None, "all"):
        return data
    return [s for s in data if s["split"] == split]
