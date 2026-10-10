"""Search loop: Latin-hypercube warm start, then Optuna TPE over EngineConfig.

Round protocol (issue #30):
  1. evaluate baseline  2. ~40 variants (LHS -> TPE)  3. train (Layers 0-1), Pareto
  4. top 10% -> validation, optional judge on top 5  5. pick best, cluster failures
The holdout is NEVER touched here (see ``final`` in cli.py, which logs every use).
"""
from __future__ import annotations

import random
from typing import Any, Dict, List, Tuple

from app.engine_config import EngineConfig, SEARCH_SPACE
from loam_eval.evaluator import aggregate, evaluate_scenario, result_hash

FAKE_PENALTY = 100.0


def objective(agg: Dict[str, Any]) -> float:
    """Scalar to maximise. Gates are already inside mean_score (gate failure => q=0)."""
    return agg["mean_score"] - FAKE_PENALTY * agg["fake_lollipop_rate"]


def evaluate_config(cfg: EngineConfig, scenarios: List[Dict[str, Any]]) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    rows = [evaluate_scenario(sc, cfg) for sc in scenarios]
    return aggregate(rows), rows


def config_from_params(params: Dict[str, float]) -> EngineConfig:
    d = EngineConfig().to_dict()
    d.update(params)
    # keep the shape ladder valid: lollipop cap strictly above the loop cap
    d["lollipop_max_retrace"] = max(d["lollipop_max_retrace"], d["loop_max_retrace"] + 0.05)
    return EngineConfig.from_dict(d)


def latin_hypercube(n: int, seed: int) -> List[Dict[str, float]]:
    rng = random.Random(seed)
    names = sorted(SEARCH_SPACE)
    cols = {}
    for name in names:
        lo, hi = SEARCH_SPACE[name]
        strata = list(range(n))
        rng.shuffle(strata)
        cols[name] = [lo + (hi - lo) * (s + rng.random()) / n for s in strata]
    return [{name: round(cols[name][i], 6) for name in names} for i in range(n)]


def pareto_front(points: List[Dict[str, Any]], q: str = "train_score", lat: str = "latency_ms") -> List[Dict[str, Any]]:
    """Maximise quality, minimise latency."""
    front = []
    for p in points:
        dominated = any(
            o[q] >= p[q] and o[lat] <= p[lat] and (o[q] > p[q] or o[lat] < p[lat]) for o in points)
        if not dominated:
            front.append(p)
    return sorted(front, key=lambda p: -p[q])


def cluster_failures(rows: List[Dict[str, Any]]) -> List[Tuple[str, int, List[str]]]:
    clusters: Dict[str, List[str]] = {}
    for r in rows:
        if r["infeasible"]:
            key = "infeasible (no candidate passes Layer 0)"
        elif r["top1_fails"]:
            key = "+".join(sorted(r["top1_fails"]))
        else:
            continue
        clusters.setdefault(key, []).append(r["id"])
    return sorted(((k, len(v), v) for k, v in clusters.items()), key=lambda x: -x[1])


def run_search(
    train: List[Dict[str, Any]],
    val: List[Dict[str, Any]],
    n_trials: int = 40,
    seed: int = 30,
    n_lhs: int = 16,
    log=None,
) -> Dict[str, Any]:
    import optuna
    optuna.logging.set_verbosity(optuna.logging.WARNING)

    trials: List[Dict[str, Any]] = []

    def record(tag: str, number: int, cfg: EngineConfig, params: Dict[str, float]):
        agg, rows = evaluate_config(cfg, train)
        entry = {"trial": number, "kind": tag, "params": params, "split": "train",
                 "train_score": agg["mean_score"], "objective": round(objective(agg), 4),
                 "latency_ms": agg["latency_ms_median"], "agg": agg, "hash": result_hash(rows)}
        trials.append(entry)
        if log:
            log(entry)
        return entry

    lhs = latin_hypercube(n_lhs, seed)
    sampler = optuna.samplers.TPESampler(seed=seed, n_startup_trials=n_lhs + 1, multivariate=True)
    study = optuna.create_study(direction="maximize", sampler=sampler)
    defaults = {k: getattr(EngineConfig(), k) for k in sorted(SEARCH_SPACE)}
    study.enqueue_trial(defaults)
    for p in lhs[: max(0, n_trials - 1)]:
        study.enqueue_trial(p)

    def _obj(trial: "optuna.Trial") -> float:
        params = {}
        for name in sorted(SEARCH_SPACE):
            lo, hi = SEARCH_SPACE[name]
            params[name] = trial.suggest_float(name, lo, hi)
        cfg = config_from_params(params)
        kind = "default" if trial.number == 0 else ("lhs" if trial.number <= n_lhs else "tpe")
        return record(kind, trial.number, cfg, {k: round(v, 6) for k, v in params.items()})["objective"]

    study.optimize(_obj, n_trials=n_trials)

    ranked = sorted(trials, key=lambda t: -t["objective"])
    k = max(3, round(0.10 * len(trials)))
    finalists = ranked[:k]
    for t in finalists:
        cfg = config_from_params(t["params"])
        agg, rows = evaluate_config(cfg, val)
        t["val_agg"] = agg
        t["val_objective"] = round(objective(agg), 4)
        t["val_hash"] = result_hash(rows)
        if log:
            log({"trial": t["trial"], "kind": "validation", "split": "val", "val_objective": t["val_objective"],
                 "agg": agg})
    best = max(finalists, key=lambda t: (t["val_objective"], t["objective"], -t["trial"]))
    return {"trials": trials, "finalists": finalists, "best": best,
            "pareto": pareto_front(trials), "seed": seed}
