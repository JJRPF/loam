"""Layer 2: human pairwise labels -> Bradley-Terry / logistic scorer.

Label file (JSONL, one line per comparison; keep it OUT of git, see .gitignore):
    {"scenario_id": "s012", "a": "c03", "b": "c17", "winner": "a"}

The scorer predicts the human pick from Layer-1 feature components. We report
pairwise accuracy plus top-1 / top-3 agreement on held-out *scenarios*.
"""
from __future__ import annotations

import json
import random
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from loam_eval.evaluator import layer1, pool_for

FEATURES = ["distance", "terrain", "retrace", "road", "backtrack", "climb", "heat"]


def route_features(sc: Dict[str, Any], truth: Dict[str, Any]) -> np.ndarray:
    comps = layer1(sc, truth)
    return np.array([comps[k] / 100.0 for k in FEATURES], dtype=float)


def load_labels(path: str) -> List[Dict[str, Any]]:
    out = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def _features_by_id(scenarios: Dict[str, Dict[str, Any]], sid: str) -> Dict[str, np.ndarray]:
    sc = scenarios[sid]
    cands, _ = pool_for(sc)
    return {c.cid: route_features(sc, c.truth) for c in cands}


def fit_bradley_terry(diffs: np.ndarray, l2: float = 0.05, steps: int = 3000, lr: float = 0.5) -> np.ndarray:
    """Logistic regression on feature differences (winner - loser), no intercept (BT model)."""
    w = np.zeros(diffs.shape[1])
    n = max(len(diffs), 1)
    for _ in range(steps):
        z = diffs @ w
        p = 1.0 / (1.0 + np.exp(-np.clip(z, -30, 30)))
        grad = diffs.T @ (p - 1.0) / n + l2 * w
        w -= lr * grad
    return w


def fit_and_report(labels: List[Dict[str, Any]], scenarios: List[Dict[str, Any]], seed: int = 30,
                   test_frac: float = 0.3) -> Dict[str, Any]:
    sc_by_id = {s["id"]: s for s in scenarios}
    labels = [l for l in labels if l["scenario_id"] in sc_by_id]
    sids = sorted({l["scenario_id"] for l in labels})
    rng = random.Random(seed)
    rng.shuffle(sids)
    n_test = max(1, int(round(len(sids) * test_frac))) if len(sids) > 1 else 0
    test_ids = set(sids[:n_test])

    feats = {sid: _features_by_id(sc_by_id, sid) for sid in sids}

    def diff(l):
        fa, fb = feats[l["scenario_id"]][l["a"]], feats[l["scenario_id"]][l["b"]]
        return (fa - fb) if l["winner"] == "a" else (fb - fa)

    train = [diff(l) for l in labels if l["scenario_id"] not in test_ids]
    test_l = [l for l in labels if l["scenario_id"] in test_ids]
    if not train:
        return {"error": "no training labels"}
    w = fit_bradley_terry(np.array(train))

    correct = sum(1 for l in test_l if float(diff(l) @ w) > 0)
    pair_acc = correct / len(test_l) if test_l else None

    top1 = top3 = n_sc = 0
    for sid in test_ids:
        ls = [l for l in test_l if l["scenario_id"] == sid]
        wins: Dict[str, int] = {}
        for l in ls:
            wins[l["a"]] = wins.get(l["a"], 0) + (l["winner"] == "a")
            wins[l["b"]] = wins.get(l["b"], 0) + (l["winner"] == "b")
        if not wins:
            continue
        human_best = max(wins, key=lambda k: (wins[k], k))
        ranked = sorted(wins, key=lambda k: (-float(feats[sid][k] @ w), k))
        n_sc += 1
        top1 += ranked[0] == human_best
        top3 += human_best in ranked[:3]
    return {
        "n_labels": len(labels), "n_train_labels": len(train), "n_test_labels": len(test_l),
        "weights": {k: round(float(v), 4) for k, v in zip(FEATURES, w)},
        "pairwise_accuracy": pair_acc,
        "top1_agreement": (top1 / n_sc) if n_sc else None,
        "top3_agreement": (top3 / n_sc) if n_sc else None,
        "n_test_scenarios": n_sc,
    }
