"""loam-eval command line.

    loam-eval scenarios                               regenerate benchmark/scenarios.json
    loam-eval run --config X --split val              evaluate one config (deterministic)
    loam-eval search --round N [--trials 40]          one tuning round (train -> val), writes report
    loam-eval final --round N                         ONE holdout evaluation: baseline vs best
    loam-eval label-sheet --split val                 HTML sheet for Layer-2 pairwise labels
    loam-eval label-fit --labels FILE                 fit the Bradley-Terry scorer, report agreement
    loam-eval real-scenarios --pbf FILE               regenerate benchmark/real_scenarios.json (public OSM trailheads)
    loam-eval real --engine NAME=TREE [...]           live-engine run of the real set, scored against OSM
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
from typing import Any, Dict, List

from app.engine_config import EngineConfig
from loam_eval import report, scenarios as scn
from loam_eval.evaluator import result_hash
from loam_eval.search import (cluster_failures, config_from_params, evaluate_config, objective, run_search)

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
BENCH = os.path.join(ROOT, "benchmark")
SCENARIOS = os.path.join(BENCH, "scenarios.json")
BASELINE = os.path.join(BENCH, "configs", "baseline_round4.json")
LOG = os.path.join(BENCH, "experiment_log.jsonl")
DEFAULT_LABELS = os.path.join(BENCH, "labels", "labels.local.jsonl")


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def log_event(entry: Dict[str, Any]) -> None:
    os.makedirs(BENCH, exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"ts": _now(), **entry}, sort_keys=True, default=str) + "\n")


def read_log() -> List[Dict[str, Any]]:
    if not os.path.exists(LOG):
        return []
    with open(LOG, "r", encoding="utf-8") as fh:
        return [json.loads(l) for l in fh if l.strip()]


def _holdout_used(round_no: int) -> bool:
    return any(e.get("kind") == "holdout" and e.get("round") == round_no for e in read_log())


def cmd_run(a) -> int:
    cfg = EngineConfig.load(a.config)
    if a.split == "holdout" and not a.allow_holdout:
        print("Refusing to run on holdout without --allow-holdout (never tune on it). Use `final`.", file=sys.stderr)
        return 2
    scs = scn.load(SCENARIOS, a.split)
    agg, rows = evaluate_config(cfg, scs)
    out = {"config": a.config, "split": a.split, "aggregate": agg, "result_hash": result_hash(rows), "rows": rows}
    print(json.dumps({k: out[k] for k in ("config", "split", "aggregate", "result_hash")}, indent=1))
    if a.out:
        report.write_json(out, os.path.join(a.out, f"results_{a.split}.json"))
        report.write_csv(rows, os.path.join(a.out, f"results_{a.split}.csv"))
    if a.split == "holdout":
        log_event({"kind": "holdout", "round": -1, "via": "run --allow-holdout", "config": a.config, "agg": agg})
    return 0


def cmd_search(a) -> int:
    train, val = scn.load(SCENARIOS, "train"), scn.load(SCENARIOS, "val")
    base = EngineConfig.load(BASELINE)
    base_train, _ = evaluate_config(base, train)
    base_val, _ = evaluate_config(base, val)
    log_event({"kind": "baseline", "round": a.round, "split": "train", "agg": base_train})
    log_event({"kind": "baseline", "round": a.round, "split": "val", "agg": base_val})

    res = run_search(train, val, n_trials=a.trials, seed=a.seed,
                     log=lambda e: log_event({"round": a.round, **e}))
    best = res["best"]
    cfg = config_from_params(best["params"])
    cfg_path = os.path.join(BENCH, "configs", f"best_v{a.round}.json")
    cfg.dump(cfg_path)
    with open(os.path.join(BENCH, "configs", "LATEST"), "w", encoding="utf-8") as fh:
        fh.write(f"best_v{a.round}.json\n")

    best_train, best_train_rows = evaluate_config(cfg, train)
    best_val, best_val_rows = evaluate_config(cfg, val)
    default_train, _ = evaluate_config(EngineConfig(), train)
    out_dir = os.path.join(BENCH, "reports", f"round-{a.round}")
    report.write_json({"best": best, "pareto": res["pareto"], "trials": res["trials"]}, os.path.join(out_dir, "search.json"))
    report.write_json(best_train_rows, os.path.join(out_dir, "results_train_best.json"))
    report.write_csv(best_train_rows, os.path.join(out_dir, "results_train_best.csv"))
    report.write_csv(best_val_rows, os.path.join(out_dir, "results_val_best.csv"))
    report.pareto_svg(res["trials"], res["pareto"], os.path.join(out_dir, "pareto.svg"))
    samples = report.write_sample_routes(val, cfg, os.path.join(out_dir, "routes"), seed=a.seed)

    labels_note, agreement = _layers23(a, train + val)
    history = [e["best_val_objective"] for e in read_log() if e.get("kind") == "round_summary"]
    log_event({"kind": "round_summary", "round": a.round, "best_trial": best["trial"],
               "best_val_objective": best["val_objective"], "config": os.path.relpath(cfg_path, ROOT)})
    summary = (f"{len(res['trials'])} variants (LHS warm start -> TPE, seed {a.seed}) scored on "
               f"{len(train)} train scenarios; top {len(res['finalists'])} validated on {len(val)}. "
               f"Best: trial {best['trial']} (val objective {best['val_objective']}). The holdout was not used.")
    report.round_report(os.path.join(out_dir, "report.md"), {
        "round": a.round, "summary": summary, "seed": a.seed, "best_trial": best["trial"],
        "best_config_file": os.path.relpath(cfg_path, ROOT), "best_hash": best["hash"],
        "compare_rows": [report._metrics_row("baseline (Round 4 approx) train", base_train),
                         report._metrics_row("default v1 train", default_train),
                         report._metrics_row("best train", best_train),
                         report._metrics_row("baseline val", base_val),
                         report._metrics_row("best val", best_val)],
        "clusters": cluster_failures(best_train_rows), "pareto": res["pareto"], "samples": samples,
        "layers23": labels_note, "notes": NOTES,
    })
    print(f"round {a.round}: best trial {best['trial']} -> {cfg_path}")
    print("baseline train:", base_train["mean_score"], "best train:", best_train["mean_score"],
          "| baseline val:", base_val["mean_score"], "best val:", best_val["mean_score"])
    return 0


NOTES = [
    "Benchmark candidates are synthetic and frozen (loam_eval/synth.py), pushed through the real "
    "process_graphhopper_path + select_options. Cost-model and waypoint-snapping parameters ([live] in "
    "EngineConfig) are NOT exercised offline and were not tuned.",
    "'baseline_round4.json' approximates Round 4 behaviour through config flags; it is not the old code.",
    "Retrace uses the engine's convention (distance covered a second time / total): a pure out-and-back is 0.50.",
    "DNR hard-blocks come from the DB-backed trust layer and are not simulated; the Layer-0 gate exists but never fires here.",
]


def _layers23(a, scenarios_used: List[Dict[str, Any]]):
    from loam_eval import labels as lab
    path = getattr(a, "labels", None) or DEFAULT_LABELS
    if os.path.exists(path):
        rep = lab.fit_and_report(lab.load_labels(path), scenarios_used)
        note = (f"Layer 2 (human labels): {rep.get('n_labels')} labels, held-out top-1 {rep.get('top1_agreement')}, "
                f"top-3 {rep.get('top3_agreement')}, pairwise {rep.get('pairwise_accuracy')}.")
        return note + " Layer 3 (LLM judge): not run; no approved spend.", rep.get("top3_agreement")
    return ("Layer 2: no human labels collected yet (generate a sheet with `loam-eval label-sheet`). "
            "Layer 3: not run. There is no approved spend and no labels to calibrate against, so the judge "
            "would be advisory only. Safeguards are in loam_eval/judge.py."), None


def cmd_final(a) -> int:
    if _holdout_used(a.round) and not a.force:
        print(f"Holdout already evaluated for round {a.round}. Use --force to log another look.", file=sys.stderr)
        return 2
    hold = scn.load(SCENARIOS, "holdout")
    base = EngineConfig.load(BASELINE)
    best_path = a.config or os.path.join(BENCH, "configs", open(os.path.join(BENCH, "configs", "LATEST")).read().strip())
    best = EngineConfig.load(best_path)
    b_agg, b_rows = evaluate_config(base, hold)
    n_agg, n_rows = evaluate_config(best, hold)
    again, again_rows = evaluate_config(best, hold)
    reproducible = result_hash(n_rows) == result_hash(again_rows)
    log_event({"kind": "holdout", "round": a.round, "config": os.path.relpath(best_path, ROOT),
               "baseline": b_agg, "best": n_agg, "reproducible": reproducible})
    history = [e["best_val_objective"] for e in read_log() if e.get("kind") == "round_summary"]
    _, agreement = _layers23(a, scn.load(SCENARIOS, "train") + scn.load(SCENARIOS, "val"))
    out_dir = os.path.join(BENCH, "reports", f"round-{a.round}")
    report.write_json({"baseline": b_rows, "best": n_rows}, os.path.join(out_dir, "results_holdout.json"))
    report.write_csv(n_rows, os.path.join(out_dir, "results_holdout_best.csv"))
    L = [f"# Round {a.round} holdout (evaluated once)", "",
         report._table([report._metrics_row("baseline (Round 4 approx)", b_agg),
                        report._metrics_row(f"best ({os.path.basename(best_path)})", n_agg)], report.METRIC_HEADER), "",
         f"Reproducible (re-run hash equal): **{reproducible}** (hash `{result_hash(n_rows)}`).", "",
         "## Stop conditions", "",
         report._table(report.stop_conditions(n_agg, history, agreement), ["condition", "status", "value"]), ""]
    with open(os.path.join(out_dir, "holdout.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(L))
    print("\n".join(L))
    return 0


def cmd_label_sheet(a) -> int:
    cfg = EngineConfig.load(a.config) if a.config else EngineConfig()
    n = report.label_sheet(scn.load(SCENARIOS, a.split), cfg, os.path.join(BENCH, "labels", f"sheet_{a.split}.html"), n=a.n)
    print(f"wrote {n} comparisons to benchmark/labels/sheet_{a.split}.html (git-ignored)")
    return 0


def cmd_label_fit(a) -> int:
    from loam_eval import labels as lab
    rep = lab.fit_and_report(lab.load_labels(a.labels), scn.load(SCENARIOS, None))
    print(json.dumps(rep, indent=1))
    return 0


def cmd_scenarios(a) -> int:
    scs = scn.write(SCENARIOS)
    print(f"wrote {len(scs)} scenarios to {SCENARIOS}")
    return 0


def cmd_real_scenarios(a) -> int:
    from loam_eval import real
    scs = real.write_scenarios(a.pbf)
    print(f"{len(scs)} real scenarios -> {real.REAL_SCENARIOS}")
    return 0


def cmd_real(a) -> int:
    """Each --engine NAME=TREE runs that source tree's engine in a subprocess over the real set."""
    from loam_eval import real
    scs = json.load(open(real.REAL_SCENARIOS))["scenarios"]
    runs = {}
    for spec in a.engine:
        name, _, tree = spec.partition("=")
        tree = os.path.abspath(tree or ROOT)
        out = os.path.join(a.workdir, f"real_{name}.json")
        runs[name] = real.run_engine(tree, real.REAL_SCENARIOS, out)
    result = real.evaluate(runs, scs)
    real.write_report(a.out, result, scs, a.note or [])
    with open(os.path.splitext(a.out)[0] + ".json", "w") as f:
        json.dump(result, f, indent=1)
    print(json.dumps(result["summary"], indent=1))
    log_event({"event": "real_benchmark", "engines": list(runs), "summary": result["summary"]})
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="loam-eval", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run"); r.add_argument("--config", required=True); r.add_argument("--split", default="val", choices=["train", "val", "holdout", "all"])
    r.add_argument("--out"); r.add_argument("--allow-holdout", action="store_true"); r.set_defaults(fn=cmd_run)
    s = sub.add_parser("search"); s.add_argument("--round", type=int, required=True); s.add_argument("--trials", type=int, default=40)
    s.add_argument("--seed", type=int, default=30); s.add_argument("--labels"); s.set_defaults(fn=cmd_search)
    f = sub.add_parser("final"); f.add_argument("--round", type=int, required=True); f.add_argument("--config"); f.add_argument("--force", action="store_true")
    f.add_argument("--labels"); f.set_defaults(fn=cmd_final)
    ls = sub.add_parser("label-sheet"); ls.add_argument("--split", default="val", choices=["train", "val"]); ls.add_argument("--n", type=int, default=50)
    ls.add_argument("--config"); ls.set_defaults(fn=cmd_label_sheet)
    lf = sub.add_parser("label-fit"); lf.add_argument("--labels", required=True); lf.set_defaults(fn=cmd_label_fit)
    rs = sub.add_parser("real-scenarios"); rs.add_argument("--pbf", required=True); rs.set_defaults(fn=cmd_real_scenarios)
    rr = sub.add_parser("real"); rr.add_argument("--engine", action="append", required=True)
    rr.add_argument("--out", default=os.path.join(BENCH, "reports", "round7.md"))
    rr.add_argument("--workdir", default=os.path.join(BENCH, "reports"))
    rr.add_argument("--note", action="append"); rr.set_defaults(fn=cmd_real)
    vs = sub.add_parser("via-scenarios"); vs.set_defaults(fn=lambda a: __import__("loam_eval.via_scenarios", fromlist=["write"]).write())
    vr = sub.add_parser("via"); vr.add_argument("--out", required=True); vr.add_argument("--only"); vr.add_argument("--label", default=""); vr.add_argument("--baseline")
    vr.set_defaults(fn=lambda a: __import__("loam_eval.via_run", fromlist=["main"]).main(a.out, a.only, a.label, a.baseline))
    vd = sub.add_parser("via-diag"); vd.add_argument("id")
    vd.set_defaults(fn=lambda a: __import__("loam_eval.via_diag", fromlist=["main"]).main(a.id))
    vm = sub.add_parser("via-maps"); vm.add_argument("--before", required=True); vm.add_argument("--out", default="docs/screenshots/round9-midpoints")
    vm.set_defaults(fn=lambda a: __import__("loam_eval.via_maps", fromlist=["main"]).main(a.before, a.out))
    sc = sub.add_parser("scenarios"); sc.set_defaults(fn=cmd_scenarios)
    a = p.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    raise SystemExit(main())
