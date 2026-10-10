"""Reports: CSV/JSON results, markdown round report, route SVGs, Pareto plot, label sheet."""
from __future__ import annotations

import csv
import html
import json
import os
import random
from typing import Any, Dict, List, Optional

from app.engine_config import EngineConfig
from loam_eval.evaluator import run_engine

SURFACE_COLORS = {"singletrack": "#2E6F40", "doubletrack": "#8D6E63", "gravel": "#D4A373",
                  "paved": "#E63946", "unpaved": "#78909C"}


def write_json(obj: Any, path: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=1, sort_keys=True, default=str)
        fh.write("\n")


def write_csv(rows: List[Dict[str, Any]], path: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    cols = ["id", "split", "score", "q1", "oracle", "diversity", "gate_pass", "top1_fails",
            "road_ok_routes", "fake_lollipops", "n_routes", "infeasible", "latency_ms"]
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(cols)
        for r in rows:
            w.writerow([("|".join(r[c]) if c == "top1_fails" else r[c]) for c in cols])


def route_svg(route, size: int = 220) -> str:
    pts = route.coordinates
    lons = [p[0] for p in pts]
    lats = [p[1] for p in pts]
    x0, x1, y0, y1 = min(lons), max(lons), min(lats), max(lats)
    span = max(x1 - x0, y1 - y0, 1e-9)
    pad = 10

    def proj(p):
        return (pad + (p[0] - x0) / span * (size - 2 * pad), size - pad - (p[1] - y0) / span * (size - 2 * pad))

    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" '
             f'style="background:#122420;border-radius:8px">']
    for seg in route.surface_strip:
        seg_pts = pts[seg.start_index:seg.end_index + 1]
        if len(seg_pts) < 2:
            continue
        d = " ".join(f"{proj(p)[0]:.1f},{proj(p)[1]:.1f}" for p in seg_pts)
        c = SURFACE_COLORS.get(seg.surface_type, "#78909C")
        parts.append(f'<polyline points="{d}" fill="none" stroke="{c}" stroke-width="3" stroke-linecap="round"/>')
    sx, sy = proj(pts[0])
    parts.append(f'<circle cx="{sx:.1f}" cy="{sy:.1f}" r="5" fill="#FF5B14"/>')
    parts.append("</svg>")
    return "".join(parts)


def write_sample_routes(scenarios: List[Dict[str, Any]], cfg: EngineConfig, out_dir: str, k: int = 6, seed: int = 30) -> List[str]:
    """Random sample of winning routes, for the 'review by eye every round' guardrail."""
    rng = random.Random(seed)
    picks = rng.sample(scenarios, min(k, len(scenarios)))
    os.makedirs(out_dir, exist_ok=True)
    written = []
    for sc in picks:
        run = run_engine(sc, cfg)
        if not run.routes:
            continue
        r = run.routes[0]
        t = run.truth[r.id]
        p = os.path.join(out_dir, f"{sc['id']}_top1.svg")
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(route_svg(r))
        written.append(f"{sc['id']}: {r.route_type}, {r.distance_miles} mi, true retrace "
                       f"{t['true_retrace']:.0%}, road {t['road_pct']:.0f}% -> {os.path.basename(p)}")
    return written


def pareto_svg(trials: List[Dict[str, Any]], front: List[Dict[str, Any]], path: str) -> None:
    w, h, pad = 520, 320, 40
    xs = [t["latency_ms"] for t in trials]
    ys = [t["train_score"] for t in trials]
    xmin, xmax, ymin, ymax = min(xs), max(xs) or 1, min(ys), max(ys)
    xr, yr = (xmax - xmin) or 1, (ymax - ymin) or 1
    fn = {t["trial"] for t in front}

    def px(t):
        return pad + (t["latency_ms"] - xmin) / xr * (w - 2 * pad), h - pad - (t["train_score"] - ymin) / yr * (h - 2 * pad)

    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" style="background:#fff">',
           f'<text x="{pad}" y="18" font-size="12">Pareto: train quality (up) vs median latency ms (right)</text>']
    for t in trials:
        x, y = px(t)
        c = "#FF5B14" if t["trial"] in fn else "#9aa"
        out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{5 if t["trial"] in fn else 3}" fill="{c}"/>')
    out.append("</svg>")
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("".join(out))


def label_sheet(scenarios: List[Dict[str, Any]], cfg: EngineConfig, path: str, n: int = 50, seed: int = 30) -> int:
    """Self-contained HTML: two routes side by side, tap the better one, download JSONL."""
    rng = random.Random(seed)
    pairs = []
    pool = list(scenarios)
    rng.shuffle(pool)
    for sc in pool:
        run = run_engine(sc, cfg)
        rs = run.routes[:6]
        if len(rs) < 2:
            continue
        a, b = rng.sample(rs, 2)
        if rng.random() < 0.5:
            a, b = b, a        # randomise side
        pairs.append((sc, a, b))
        if len(pairs) >= n:
            break
    cards = []
    for i, (sc, a, b) in enumerate(pairs):
        def info(r):
            return f"{r.distance_miles} mi · {r.elevation_gain_ft:.0f} ft · {r.surface_breakdown}"
        cards.append(
            f'<section data-sid="{html.escape(sc["id"])}" data-a="{html.escape(a.id)}" data-b="{html.escape(b.id)}">'
            f'<h3>#{i + 1} · {html.escape(sc["area"])} · target {sc["target_miles"]} mi · {sc["shape"]}</h3>'
            f'<div class="row"><button data-w="a">{route_svg(a)}<small>{html.escape(info(a))}</small></button>'
            f'<button data-w="b">{route_svg(b)}<small>{html.escape(info(b))}</small></button></div></section>')
    page = ("<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width'>"
            "<title>Loam route labels</title><style>body{background:#122420;color:#E7ECEC;font-family:sans-serif}"
            ".row{display:flex;gap:12px;flex-wrap:wrap}button{background:#1B3630;border:2px solid #264A42;"
            "color:#E7ECEC;border-radius:10px;padding:8px}button.sel{border-color:#FF5B14}small{display:block;"
            "max-width:220px}</style><h1>Which route would you ride?</h1>" + "".join(cards) +
            "<p><button id=dl>Download labels.jsonl</button></p><script>"
            "document.querySelectorAll('section').forEach(s=>s.querySelectorAll('button').forEach(b=>b.onclick=()=>{"
            "s.querySelectorAll('button').forEach(x=>x.classList.remove('sel'));b.classList.add('sel');s.dataset.w=b.dataset.w;}));"
            "dl.onclick=()=>{const L=[...document.querySelectorAll('section')].filter(s=>s.dataset.w).map(s=>JSON.stringify("
            "{scenario_id:s.dataset.sid,a:s.dataset.a,b:s.dataset.b,winner:s.dataset.w})).join('\\n');"
            "const u=URL.createObjectURL(new Blob([L+'\\n']));const a=document.createElement('a');a.href=u;"
            "a.download='labels.jsonl';a.click();};</script>")
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(page)
    return len(pairs)


def _table(rows: List[List[Any]], header: List[str]) -> str:
    out = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def _metrics_row(label: str, agg: Dict[str, Any]) -> List[Any]:
    return [label, agg["mean_score"], f"{agg['gate_pass_rate']:.1%}", f"{agg['road_cap_met_rate']:.1%}",
            f"{agg['fake_lollipop_rate']:.1%}", agg["mean_q1"], agg["infeasible_scenarios"], agg["latency_ms_median"]]


METRIC_HEADER = ["config", "mean score", "gate pass", "road cap met", "fake lollipop", "mean q1", "infeasible", "median ms"]


def stop_conditions(holdout_agg: Dict[str, Any], history: List[float], labels_agreement: Optional[float]) -> List[List[str]]:
    def row(name, ok, val):
        return [name, "PASS" if ok else ("NOT MEASURED" if ok is None else "FAIL"), val]
    improves = None
    if len(history) >= 3:
        improves = all(abs(history[-i] - history[-i - 1]) / max(abs(history[-i - 1]), 1e-9) < 0.01 for i in (1, 2))
    return [
        row("holdout gate pass >= 98%", holdout_agg["gate_pass_rate"] >= 0.98, f"{holdout_agg['gate_pass_rate']:.1%}"),
        row("road cap met >= 95% of routes", holdout_agg["road_cap_met_rate"] >= 0.95, f"{holdout_agg['road_cap_met_rate']:.1%}"),
        row("fake-lollipop rate == 0%", holdout_agg["fake_lollipop_rate"] == 0.0, f"{holdout_agg['fake_lollipop_rate']:.1%}"),
        row("Justin top-3 agreement >= 85%", None if labels_agreement is None else labels_agreement >= 0.85,
            "no human labels collected" if labels_agreement is None else f"{labels_agreement:.1%}"),
        row("latency target (<10 s first result)", holdout_agg["latency_ms_median"] < 10000.0,
            f"{holdout_agg['latency_ms_median']} ms (offline ranking only, GraphHopper time not included)"),
        row("two consecutive rounds improve < 1%", improves, f"history={history}"),
    ]


def round_report(path: str, ctx: Dict[str, Any]) -> None:
    L: List[str] = [f"# Round {ctx['round']} tuning report", ""]
    L += ["## Summary", "", ctx["summary"], ""]
    L += ["## Baseline vs best (same scenarios)", "",
          _table(ctx["compare_rows"], METRIC_HEADER), ""]
    L += [f"Best config: `{ctx['best_config_file']}` (trial {ctx['best_trial']}, seed {ctx['seed']}, "
          f"result hash train `{ctx['best_hash']}`).", ""]
    L += ["## Failure clusters (best config, train)", ""]
    if ctx["clusters"]:
        L += [_table([[k, n, ", ".join(ids[:8]) + (" …" if len(ids) > 8 else "")] for k, n, ids in ctx["clusters"]],
                     ["gate failure on top-1", "scenarios", "ids"]), ""]
    else:
        L += ["None.", ""]
    L += ["## Pareto front (quality vs latency)", "",
          _table([[t["trial"], t["kind"], t["train_score"], t["latency_ms"]] for t in ctx["pareto"]],
                 ["trial", "kind", "train mean score", "median ms"]), "",
          "![pareto](pareto.svg)", "",
          "Latency is wall-clock of the ranking pipeline only and varies run to run; it is excluded from the "
          "reproducibility hash. Real GraphHopper latency needs a live run.", ""]
    L += ["## Layer 2 / Layer 3", "", ctx["layers23"], ""]
    L += ["## Sample of winning routes (review by eye)", ""] + [f"- {s}" for s in ctx["samples"]] + [""]
    if ctx.get("stop"):
        L += ["## Stop conditions (holdout)", "", _table(ctx["stop"], ["condition", "status", "value"]), ""]
    if ctx.get("notes"):
        L += ["## Notes and caveats", ""] + [f"- {n}" for n in ctx["notes"]] + [""]
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L))
