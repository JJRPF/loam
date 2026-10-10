"""Deterministic synthetic candidate routes.

The live engine needs GraphHopper + an OSM extract. For an offline, frozen,
reproducible benchmark we instead synthesise candidate pools as GraphHopper-style
``path`` dicts (points + osm_way_id / surface / road_class / street_name details)
and feed them through the *real* ``process_graphhopper_path`` and
``select_options``. Because we build each route from named legs we know the TRUE
retrace share, road share and shape independently of the engine's classifier.

Limits (stated in docs): cost-model and waypoint-snapping parameters are not
exercised here; they need a live GraphHopper run.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple

SPACING_M = 25.0

# surface kind -> (road_class, surface, street name suffix)
KINDS: Dict[str, Tuple[str, str, str]] = {
    "singletrack": ("path", "dirt", "Trail"),
    "doubletrack": ("track", "dirt", "Fire Lane"),
    "gravel": ("track", "gravel", "Gravel Way"),
    "paved": ("residential", "asphalt", "Road"),
}


@dataclass
class Leg:
    way_id: int
    pts_m: List[Tuple[float, float]]
    kind: str
    name: str
    ele: List[float]


@dataclass
class Candidate:
    cid: str
    archetype: str
    path: Dict[str, Any]
    truth: Dict[str, Any]


def _dist(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _poly(p0, p1, rng: random.Random) -> List[Tuple[float, float]]:
    d = max(_dist(p0, p1), 1.0)
    n = max(2, int(d // SPACING_M))
    ux, uy = (p1[0] - p0[0]) / d, (p1[1] - p0[1]) / d
    amp = min(d * 0.06, 25.0) * rng.uniform(-1, 1)
    out = []
    for i in range(n + 1):
        t = i / n
        wob = amp * math.sin(math.pi * t)
        out.append((p0[0] + (p1[0] - p0[0]) * t - uy * wob, p0[1] + (p1[1] - p0[1]) * t + ux * wob))
    return out


def _length(pts) -> float:
    return sum(_dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1))


class World:
    """A tiny trail network: ways with a fixed kind/name/heat, reusable across candidates."""

    def __init__(self, rng: random.Random, road_prevalence: float, area: str, ghost_frac: float = 0.0):
        self.rng = rng
        self.ghost_frac = ghost_frac
        self.ghost: set = set()
        self.road_prevalence = road_prevalence
        self.area = area
        self._next_id = 1_000_000 * (1 + rng.randrange(900))
        self.heat: Dict[int, Dict[str, float]] = {}

    def new_leg(self, p0, p1, kind: str | None = None) -> Leg:
        rng = self.rng
        if kind is None:
            r = rng.random()
            if r < self.road_prevalence:
                kind = "paved"
            else:
                kind = rng.choices(["singletrack", "doubletrack", "gravel"], [0.62, 0.22, 0.16])[0]
        self._next_id += 1
        wid = self._next_id
        pts = _poly(p0, p1, rng)
        base = rng.uniform(80, 250)
        grad = rng.uniform(-18, 22)
        ele = [base + grad * (i / max(len(pts) - 1, 1)) + rng.uniform(-1.5, 1.5) for i in range(len(pts))]
        suffix = KINDS[kind][2]
        name = f"{self.area} {suffix} {wid % 97}"
        if kind != "paved":
            # Ghost trails: mapped in OSM but nobody rides them -> no heat record.
            if rng.random() < self.ghost_frac:
                self.ghost.add(wid)
            else:
                self.heat[wid] = {"weighted_score": max(0.0, rng.gauss(2.2, 1.6))}
        return Leg(wid, pts, kind, name, ele)


def _assemble(legs: List[Tuple[Leg, bool]], origin: Tuple[float, float]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """legs: (leg, reversed). Returns (graphhopper_path, truth)."""
    lat0, lon0 = origin
    m_lat = 111132.0
    m_lon = 111320.0 * math.cos(math.radians(lat0))
    points: List[List[float]] = []
    details = {"surface": [], "road_class": [], "track_type": [], "osm_way_id": [], "street_name": []}
    seen: Dict[int, int] = {}
    way_len: Dict[int, float] = {}
    rep_m = 0.0
    total_m = 0.0
    kind_m = {k: 0.0 for k in KINDS}
    ascend = 0.0
    descend = 0.0
    way_ids: List[int] = []
    last_dir = None
    reversals = 0
    for leg, rev in legs:
        pts = list(reversed(leg.pts_m)) if rev else leg.pts_m
        ele = list(reversed(leg.ele)) if rev else leg.ele
        start_idx = max(len(points) - 1, 0) if points else 0
        for j, (x, y) in enumerate(pts):
            if points and j == 0:
                continue
            points.append([lon0 + x / m_lon, lat0 + y / m_lat, round(ele[j], 2)])
        end_idx = len(points)
        rc, sf, _ = KINDS[leg.kind]
        for key, val in (("surface", sf), ("road_class", rc), ("osm_way_id", leg.way_id), ("street_name", leg.name)):
            details[key].append([start_idx, end_idx, val])
        d = _length(pts)
        total_m += d
        kind_m[leg.kind] += d
        if leg.way_id in seen:
            rep_m += d
        seen[leg.way_id] = seen.get(leg.way_id, 0) + 1
        way_len[leg.way_id] = d
        way_ids.append(leg.way_id)
        for i in range(len(ele) - 1):
            de = ele[i + 1] - ele[i]
            ascend += max(de, 0.0)
            descend += max(-de, 0.0)
        direction = (leg.way_id, rev)
        if last_dir and last_dir[0] == leg.way_id and last_dir[1] != rev:
            reversals += 1
        last_dir = direction
    lons = [p[0] for p in points]
    lats = [p[1] for p in points]
    path = {
        "distance": total_m,
        "ascend": ascend,
        "descend": descend,
        "bbox": [min(lons), min(lats), max(lons), max(lats)],
        "points": {"type": "LineString", "coordinates": points},
        "details": details,
    }
    uniq = set(way_ids)
    truth = {
        "distance_m": total_m,
        "true_retrace": rep_m / total_m if total_m else 0.0,
        "road_pct": 100.0 * kind_m["paved"] / total_m if total_m else 0.0,
        "mix_pct": {k: 100.0 * v / total_m if total_m else 0.0 for k, v in kind_m.items()},
        "u_turns": reversals,
        "spurs": 0,  # filled by builders
        "way_ids": sorted(uniq),
        "way_len": way_len,
        "climb_ft": ascend * 3.280839895,
    }
    return path, truth


def _ring(world: World, center, radius: float, n: int, kinds: List[str | None] | None = None):
    rng = world.rng
    off = rng.uniform(0, 2 * math.pi)
    nodes = []
    for i in range(n):
        a = off + 2 * math.pi * i / n
        r = radius * rng.uniform(0.85, 1.15)
        nodes.append((center[0] + r * math.cos(a), center[1] + r * math.sin(a)))
    legs = []
    for i in range(n):
        k = kinds[i] if kinds else None
        legs.append(world.new_leg(nodes[i], nodes[(i + 1) % n], k))
    return nodes, legs


def _chain(world: World, p0, heading: float, length_m: float, n: int, kinds=None):
    pts = [p0]
    step = length_m / n
    legs = []
    h = heading
    for i in range(n):
        h += world.rng.uniform(-0.35, 0.35)
        nxt = (pts[-1][0] + step * math.cos(h), pts[-1][1] + step * math.sin(h))
        legs.append(world.new_leg(pts[-1], nxt, kinds[i] if kinds else None))
        pts.append(nxt)
    return pts, legs


def _kinds_for(world: World, n: int, road_share: float | None):
    if road_share is None:
        return None
    k = []
    for _ in range(n):
        k.append("paved" if world.rng.random() < road_share else None)
    return k


def _build_once(
    world: World, archetype: str, target_m: float, origin: Tuple[float, float], cid: str,
    size_jitter: float = 0.12, road_share: float | None = None, retrace: float | None = None,
) -> Candidate:
    rng = world.rng
    size = target_m * math.exp(rng.gauss(0.0, size_jitter))
    heading = rng.uniform(0, 2 * math.pi)
    start = (0.0, 0.0)
    spurs = 0
    if archetype in ("loop", "loop_spurs", "road_loop"):
        n = rng.randint(5, 9)
        circ = size / (1.0 + (0.0 if archetype != "loop_spurs" else 0.0))
        radius = circ / (2 * math.pi)
        c = (radius * math.cos(heading), radius * math.sin(heading))
        rs = 0.45 if archetype == "road_loop" else road_share
        nodes, ring_legs = _ring(world, c, radius, n, _kinds_for(world, n, rs))
        # approach: start sits on ring node 0 by construction
        shift = (nodes[0][0], nodes[0][1])
        ring_legs = [world.new_leg((nodes[i][0] - shift[0], nodes[i][1] - shift[1]),
                                   (nodes[(i + 1) % n][0] - shift[0], nodes[(i + 1) % n][1] - shift[1]),
                                   ring_legs[i].kind) for i in range(n)]
        legs = [(l, False) for l in ring_legs]
        if archetype == "loop_spurs":
            for _ in range(rng.randint(1, 3)):
                at = rng.randrange(n)
                end_pt = ring_legs[at].pts_m[0]
                ex = (end_pt[0] + rng.uniform(80, 220) * math.cos(rng.uniform(0, 6.28)),
                      end_pt[1] + rng.uniform(80, 220) * math.sin(rng.uniform(0, 6.28)))
                spur = world.new_leg(end_pt, ex, "singletrack")
                legs[at:at] = [(spur, False), (spur, True)]
                spurs += 1
    elif archetype in ("lollipop", "fake_lollipop"):
        # Engine convention: retrace = distance covered a SECOND time / total, so a pure
        # out-and-back is 0.50 and a lollipop with stem s (out + back) has retrace s / total.
        want = retrace if retrace is not None else (rng.uniform(0.12, 0.32) if archetype == "lollipop" else rng.uniform(0.38, 0.48))
        want = min(want, 0.48)
        stem = size * want
        circuit = size - 2 * stem
        n_stem = max(1, int(stem // 400))
        pts, stem_legs = _chain(world, start, heading, stem, n_stem, _kinds_for(world, n_stem, road_share))
        radius = max(circuit, 200.0) / (2 * math.pi)
        a = heading
        c = (pts[-1][0] + radius * math.cos(a), pts[-1][1] + radius * math.sin(a))
        n = rng.randint(4, 7)
        nodes, ring_legs = _ring(world, c, radius, n, _kinds_for(world, n, road_share))
        shift = (nodes[0][0] - pts[-1][0], nodes[0][1] - pts[-1][1])
        ring_legs = [world.new_leg((nodes[i][0] - shift[0], nodes[i][1] - shift[1]),
                                   (nodes[(i + 1) % n][0] - shift[0], nodes[(i + 1) % n][1] - shift[1]),
                                   ring_legs[i].kind) for i in range(n)]
        legs = [(l, False) for l in stem_legs] + [(l, False) for l in ring_legs] + [(l, True) for l in reversed(stem_legs)]
    elif archetype == "out_and_back":
        n = rng.randint(4, 8)
        pts, ch = _chain(world, start, heading, size / 2.0, n, _kinds_for(world, n, road_share))
        legs = [(l, False) for l in ch] + [(l, True) for l in reversed(ch)]
    elif archetype == "point_to_point":
        n = rng.randint(5, 9)
        pts, ch = _chain(world, start, heading, size, n, _kinds_for(world, n, road_share))
        legs = [(l, False) for l in ch]
    else:
        raise ValueError(archetype)

    path, truth = _assemble(legs, origin)
    truth["spurs"] = spurs
    truth["archetype"] = archetype
    if archetype in ("loop", "road_loop"):
        truth["true_shape"] = "loop"
    elif archetype == "loop_spurs":
        truth["true_shape"] = "loop" if truth["true_retrace"] <= 0.10 else "lollipop"
    elif archetype == "lollipop":
        truth["true_shape"] = "lollipop"
    elif archetype in ("fake_lollipop", "out_and_back"):
        truth["true_shape"] = "out_and_back"
    else:
        truth["true_shape"] = "point_to_point"
    # Shape truth is defined by the retrace share, not by how we built it.
    if archetype != "point_to_point":
        r = truth["true_retrace"]
        truth["true_shape"] = "loop" if r <= 0.10 else ("lollipop" if r <= 0.35 else "out_and_back")
    truth["heat"] = {wid: world.heat.get(wid) for wid in truth["way_ids"] if world.heat.get(wid)}
    truth["ghost_ways"] = [w for w in truth["way_ids"] if w in world.ghost]
    return Candidate(cid, archetype, path, truth)



def build_candidate(world: World, archetype: str, target_m: float, origin, cid: str,
                    size_jitter: float = 0.12, road_share=None, retrace=None) -> Candidate:
    """Build a candidate whose total length lands within 2% of the (jittered) requested length."""
    want = target_m * math.exp(world.rng.gauss(0.0, size_jitter)) if size_jitter else target_m
    base_seed = world.rng.randrange(1 << 30)
    scale = 1.0
    best = None
    for attempt in range(8):
        world.rng = random.Random(base_seed + attempt)
        cand = _build_once(world, archetype, want * scale, origin, cid, 0.0, road_share, retrace)
        got = cand.truth["distance_m"]
        if best is None or abs(got - want) < abs(best.truth["distance_m"] - want):
            best = cand
        if abs(got - want) / want < 0.02:
            break
        scale *= want / max(got, 1.0)
    world.rng = random.Random(base_seed ^ 0x5EED)
    return best

ARCHETYPES = ["loop", "loop_spurs", "lollipop", "fake_lollipop", "out_and_back", "road_loop", "point_to_point"]


def build_pool(scenario: Dict[str, Any], n: int = 36) -> Tuple[List[Candidate], Dict[int, Dict[str, float]]]:
    """Deterministic candidate pool for a scenario (depends only on scenario content)."""
    rng = random.Random(scenario["seed"])
    world = World(rng, scenario.get("road_prevalence", 0.1), scenario.get("area", "Area"), scenario.get("ghost_frac", 0.0))
    origin = (scenario["start"]["lat"], scenario["start"]["lon"])
    target_m = scenario["target_miles"] * 1609.344
    cands: List[Candidate] = []
    explicit = scenario.get("pool_spec")
    if explicit:
        for i, spec in enumerate(explicit):
            tm = spec["miles"] * 1609.344
            cands.append(build_candidate(world, spec["archetype"], tm, origin, f"c{i:02d}",
                                         size_jitter=0.0, road_share=spec.get("road_share"),
                                         retrace=spec.get("retrace")))
    else:
        weights = scenario["archetype_weights"]
        for i in range(n):
            arch = rng.choices(ARCHETYPES, [weights[a] for a in ARCHETYPES])[0]
            cands.append(build_candidate(world, arch, target_m, origin, f"c{i:02d}"))
    return cands, world.heat
