"""Layered evaluator (Layers 0-1) and the engine runner used by the benchmark.

Layer 0 hard gates -> score 0 for that route.
Layer 1 deterministic quality score from independently-known route truth.
Layers 2 (human labels) and 3 (LLM judge) live in ``labels.py`` / ``judge.py``.

The evaluator's own weights are FIXED. Only EngineConfig is tuned; otherwise the
search could simply rewrite the yardstick.
"""
from __future__ import annotations

import hashlib
import json
import statistics
import time
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple

from app.engine_config import EngineConfig, use_config
from app.models import LatLon, RouteRequest, TerrainPreference, RouteResponse
from app.routing import process_graphhopper_path, select_options
from loam_eval.synth import Candidate, build_pool

DISTANCE_GATE = 0.15
LOOP_GATE_RETRACE = 0.10
LOLLIPOP_GATE_RETRACE = 0.35
FAKE_LOLLIPOP_RETRACE = 0.35

# Layer-1 fixed weights (sum 100)
L1_WEIGHTS = {
    "distance": 20.0, "terrain": 15.0, "retrace": 20.0, "road": 15.0,
    "backtrack": 10.0, "climb": 5.0, "heat": 10.0, "access_gap": 5.0,
}


def request_for(sc: Dict[str, Any]) -> RouteRequest:
    shape = sc["shape"]
    mode = {"loop": "loop", "lollipop_ok": "loop", "out_and_back": "out_and_back",
            "point_to_point": "point_to_point"}[shape]
    end = None
    if shape == "point_to_point":
        end = LatLon(lat=sc["end"]["lat"], lon=sc["end"]["lon"])
    return RouteRequest(
        start=LatLon(lat=sc["start"]["lat"], lon=sc["start"]["lon"]),
        end=end,
        profile=sc["sport_profile"],
        terrain_preference=TerrainPreference(**sc["terrain"]),
        route_mode=mode,
        is_loop=shape in ("loop", "lollipop_ok"),
        target_distance_miles=sc["target_miles"],
    )


@lru_cache(maxsize=512)
def _pool_cached(scenario_json: str) -> Tuple[List[Candidate], Dict[int, Dict[str, float]]]:
    return build_pool(json.loads(scenario_json))


def pool_for(sc: Dict[str, Any]) -> Tuple[List[Candidate], Dict[int, Dict[str, float]]]:
    return _pool_cached(json.dumps(sc, sort_keys=True))


@dataclass
class EngineRun:
    routes: List[RouteResponse]
    truth: Dict[str, Dict[str, Any]]     # route id -> candidate truth
    all_truth: List[Dict[str, Any]]      # whole pool
    latency_ms: float = 0.0


def run_engine(sc: Dict[str, Any], cfg: EngineConfig) -> EngineRun:
    cands, heat = pool_for(sc)
    req = request_for(sc)
    t0 = time.perf_counter()
    scored = []
    truth: Dict[str, Dict[str, Any]] = {}
    with use_config(cfg):
        for i, c in enumerate(cands):
            r = process_graphhopper_path(
                path=c.path, req=req, cand_id=c.cid, sector_name=f"cand {c.cid}",
                edge_heat_cache=heat, additional_warnings=[], user_id=None,
                is_covered_region=bool(sc.get("covered", True)),
            )
            scored.append((r, set(c.truth["way_ids"])))
            truth[c.cid] = c.truth
        is_loop = req.is_loop or req.route_mode in ("loop", "round_trip")
        routes = select_options(scored, req, cfg.candidate_count, is_loop)
    return EngineRun(routes, truth, [c.truth for c in cands], (time.perf_counter() - t0) * 1000.0)


# ---------------------------------------------------------------- Layer 0
def layer0(sc: Dict[str, Any], t: Dict[str, Any]) -> List[str]:
    fails = []
    cap = max(float(sc.get("road_cap_pct", 15.0)), sc["terrain"].get("paved", 0.0) * 100.0)
    if t["road_pct"] > cap + 0.05:
        fails.append("road_cap")
    shape = sc["shape"]
    r = t["true_retrace"]
    if shape == "loop" and r > LOOP_GATE_RETRACE:
        fails.append("shape_mismatch")
    elif shape == "lollipop_ok" and r > LOLLIPOP_GATE_RETRACE:
        fails.append("shape_mismatch")
    elif shape == "out_and_back" and t["true_shape"] == "point_to_point":
        fails.append("shape_mismatch")
    elif shape == "point_to_point" and t["true_shape"] != "point_to_point":
        fails.append("shape_mismatch")
    err = abs(t["distance_m"] / 1609.344 - sc["target_miles"]) / sc["target_miles"]
    if err > DISTANCE_GATE:
        fails.append("distance")
    if t.get("ghost_ways"):
        fails.append("ghost_trail")
    if t.get("dnr_ways"):
        fails.append("dnr")
    return fails


# ---------------------------------------------------------------- Layer 1
def layer1(sc: Dict[str, Any], t: Dict[str, Any]) -> Dict[str, float]:
    miles = t["distance_m"] / 1609.344
    err = abs(miles - sc["target_miles"]) / sc["target_miles"]
    pref = sc["terrain"]
    l1 = 0.5 * sum(abs(t["mix_pct"].get(k, 0.0) / 100.0 - pref.get(k, 0.0)) for k in ("singletrack", "doubletrack", "gravel", "paved"))
    way_len = t["way_len"]
    total_len = sum(way_len.values()) or 1.0
    heat_len = sum(l for w, l in way_len.items() if str(w) in {str(x) for x in t["heat"]})
    tgt_climb = sc.get("climb_ft_per_mile", 85.0) * miles
    comps = {
        "distance": 100.0 * max(0.0, 1.0 - err / 0.30),
        "terrain": 100.0 * max(0.0, 1.0 - l1),
        "retrace": 100.0 * max(0.0, 1.0 - t["true_retrace"] / 0.50),
        "road": 100.0 * max(0.0, 1.0 - t["road_pct"] / 30.0),
        "backtrack": max(0.0, 100.0 - 40.0 * (t["u_turns"] + t["spurs"]) / max(miles, 0.5)),
        "climb": 100.0 * max(0.0, 1.0 - abs(t["climb_ft"] - tgt_climb) / max(tgt_climb, 1.0)),
        "heat": 100.0 * heat_len / total_len,
        "access_gap": 100.0,
    }
    comps["score"] = sum(L1_WEIGHTS[k] * comps[k] for k in L1_WEIGHTS) / sum(L1_WEIGHTS.values())
    return comps


def route_quality(sc: Dict[str, Any], t: Dict[str, Any]) -> Tuple[float, List[str], Dict[str, float]]:
    fails = layer0(sc, t)
    comps = layer1(sc, t)
    return (0.0 if fails else comps["score"]), fails, comps


def _overlap_diversity(truths: List[Dict[str, Any]]) -> float:
    if len(truths) < 2:
        return 100.0
    sets = [set(t["way_ids"]) for t in truths]
    tot, n = 0.0, 0
    for i in range(len(sets)):
        for j in range(i + 1, len(sets)):
            u = len(sets[i] | sets[j]) or 1
            tot += len(sets[i] & sets[j]) / u
            n += 1
    return 100.0 * (1.0 - tot / n)


def evaluate_scenario(sc: Dict[str, Any], cfg: EngineConfig) -> Dict[str, Any]:
    run = run_engine(sc, cfg)
    per_route = []
    for r in run.routes:
        t = run.truth[r.id]
        q, fails, comps = route_quality(sc, t)
        per_route.append({"id": r.id, "q": q, "fails": fails, "label": r.route_type,
                          "true_shape": t["true_shape"], "true_retrace": round(t["true_retrace"], 3),
                          "road_pct": round(t["road_pct"], 2), "miles": round(t["distance_m"] / 1609.344, 2),
                          "engine_score": r.match_score})
    oracle = max((route_quality(sc, t)[0] for t in run.all_truth), default=0.0)
    q1 = per_route[0]["q"] if per_route else 0.0
    q3 = [p["q"] for p in per_route[:3]]
    div = _overlap_diversity([run.truth[r.id] for r in run.routes[:10]])
    regret_term = 100.0 if oracle <= 0 else 100.0 * q1 / oracle
    score = 0.60 * q1 + 0.20 * (sum(q3) / len(q3) if q3 else 0.0) + 0.10 * div + 0.10 * regret_term
    fake = sum(1 for p in per_route if p["label"] in ("loop", "lollipop") and p["true_shape"] == "out_and_back"
               and sc["shape"] in ("loop", "lollipop_ok"))
    top1_fails = per_route[0]["fails"] if per_route else ["no_routes"]
    return {
        "id": sc["id"], "split": sc["split"], "score": round(score, 4), "q1": round(q1, 3),
        "oracle": round(oracle, 3), "diversity": round(div, 2),
        "gate_pass": not top1_fails, "top1_fails": top1_fails,
        "road_ok_routes": sum(1 for p in per_route[:3] if "road_cap" not in p["fails"]),
        "n_top3": len(per_route[:3]),
        "fake_lollipops": fake, "n_routes": len(per_route),
        "infeasible": oracle <= 0.0,
        "top3": per_route[:3], "latency_ms": run.latency_ms,
    }


def aggregate(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    n = len(rows) or 1
    feas = [r for r in rows if not r["infeasible"]] or rows
    n3 = sum(r["n_top3"] for r in rows) or 1
    nr = sum(r["n_routes"] for r in rows) or 1
    lat = [r["latency_ms"] for r in rows]
    return {
        "n_scenarios": len(rows),
        "mean_score": round(sum(r["score"] for r in rows) / n, 4),
        "gate_pass_rate": round(sum(1 for r in feas if r["gate_pass"]) / max(len(feas), 1), 4),
        "road_cap_met_rate": round(sum(r["road_ok_routes"] for r in rows) / n3, 4),
        "fake_lollipop_rate": round(sum(r["fake_lollipops"] for r in rows) / nr, 4),
        "mean_q1": round(sum(r["q1"] for r in rows) / n, 3),
        "mean_diversity": round(sum(r["diversity"] for r in rows) / n, 2),
        "infeasible_scenarios": sum(1 for r in rows if r["infeasible"]),
        "latency_ms_median": round(statistics.median(lat), 2) if lat else 0.0,
    }


def result_hash(rows: List[Dict[str, Any]]) -> str:
    """Hash of everything except wall-clock latency (the reproducibility check)."""
    stripped = [{k: v for k, v in r.items() if k != "latency_ms"} for r in rows]
    return hashlib.sha256(json.dumps(stripped, sort_keys=True).encode()).hexdigest()[:16]
