"""Trail graph loop search on real OSM topology (docs/round7-plan.md 6.2).

Built from `trail_segments` (scripts/import_osm_graph.py): junctions are OSM node ids, never
snapped by distance. Degree-2 nodes are contracted into chains that keep their ordered
segments, so a chain walked v -> u is emitted with reversed coordinates and every route is
continuous. Blocked segments (access, bicycle/foot = no, steps for bikes, informal paths, hard
restrictions, the user's DNR) never enter a search. Roads are connectors whose length counts
against the road budget.

Loop search: a self-avoiding DFS from a base junction with distance-to-base pruning, run as
many short randomized restarts (seeded RNG) within a time and node-visit budget, de-duplicated
by >= 70% shared length. A stem from the start to the base junction is the real network path
(Dijkstra over segments).
"""
import heapq
import json
import math
import random
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Set, Tuple

EARTH_R = 6371008.8
BIKE_ALLOWED = {"yes", "designated", "permissive", "destination"}
FOOT_ALLOWED = {"yes", "designated", "permissive", "destination"}
CONTINUITY_M = 1.0


def _hav(a: Sequence[float], b: Sequence[float]) -> float:
    p1, p2 = math.radians(a[1]), math.radians(b[1])
    dp, dl = p2 - p1, math.radians(b[0] - a[0])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_R * math.asin(math.sqrt(min(1.0, h)))


@dataclass
class Segment:
    id: int
    way_id: int
    u: int
    v: int
    coords: List[List[float]]
    length: float
    category: str
    tags: Dict[str, Optional[str]]


@dataclass
class Chain:
    id: int
    u: int
    v: int
    segs: List[Tuple[int, bool]]  # (segment id, walked forward u->v)
    length: float
    road_length: float


@dataclass
class Loop:
    """A candidate: ordered (segment id, forward) steps from the start node and back."""
    steps: List[Tuple[int, bool]]
    length: float
    stem_length: float
    base_node: int
    chain_ids: Set[int] = field(default_factory=set)


def is_blocked(seg_tags: Dict[str, Optional[str]], bike: bool) -> bool:
    """Hard access rules from OSM tags for this sport."""
    access = (seg_tags.get("access") or "").lower()
    if bike:
        mode = (seg_tags.get("bicycle") or "").lower()
        if mode == "no" or seg_tags.get("highway") == "steps":
            return True
        if access in ("private", "no") and mode not in BIKE_ALLOWED:
            return True
    else:
        mode = (seg_tags.get("foot") or "").lower()
        if mode == "no":
            return True
        if access in ("private", "no") and mode not in FOOT_ALLOWED:
            return True
    if (seg_tags.get("informal") or "").lower() == "yes":
        return True
    return False


class TrailGraph:
    def __init__(self, segments: Dict[int, Segment]):
        self.segments = segments
        self.adj: Dict[int, List[Tuple[int, int]]] = {}  # node -> [(segment id, other node)]
        self.node_xy: Dict[int, List[float]] = {}
        for s in segments.values():
            self.adj.setdefault(s.u, []).append((s.id, s.v))
            self.adj.setdefault(s.v, []).append((s.id, s.u))
            self.node_xy[s.u] = s.coords[0]
            self.node_xy[s.v] = s.coords[-1]
        self.chains: Dict[int, Chain] = {}
        self.core_adj: Dict[int, List[Tuple[int, int]]] = {}  # node -> [(chain id, other node)]
        self._contract()

    # ---- loading -----------------------------------------------------------------------
    @classmethod
    def load(cls, min_lon: float, min_lat: float, max_lon: float, max_lat: float, bike: bool,
             blocked_ways: Optional[Set[int]] = None) -> "TrailGraph":
        from app.db import get_connection

        blocked_ways = blocked_ways or set()
        segments: Dict[int, Segment] = {}
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT segment_id, osm_way_id, from_node, to_node, ST_AsGeoJSON(geom), length_m, category,
                           name, highway, surface, tracktype, access, bicycle, foot, informal
                    FROM trail_segments
                    WHERE geom && ST_MakeEnvelope(%s, %s, %s, %s, 4326)
                    """,
                    (min_lon, min_lat, max_lon, max_lat),
                )
                rows = cur.fetchall()
                hard_blocked = _hard_restricted_segments(cur, min_lon, min_lat, max_lon, max_lat)
        for (sid, way, u, v, gj, length, cat, name, hw, surf, tt, acc, bic, foot, informal) in rows:
            tags = {"name": name, "highway": hw, "surface": surf, "tracktype": tt, "access": acc,
                    "bicycle": bic, "foot": foot, "informal": informal}
            if way in blocked_ways or sid in hard_blocked or is_blocked(tags, bike):
                continue
            segments[sid] = Segment(sid, way, u, v, json.loads(gj)["coordinates"], float(length), cat, tags)
        return cls(segments)

    # ---- contraction ---------------------------------------------------------------------
    def _contract(self) -> None:
        # 2-core: loops can't use dead ends, so strip degree-1 nodes repeatedly.
        degree = {n: len(e) for n, e in self.adj.items()}
        removed_segs: Set[int] = set()
        stack = [n for n, d in degree.items() if d == 1]
        while stack:
            n = stack.pop()
            if degree.get(n, 0) != 1:
                continue
            for sid, other in self.adj[n]:
                if sid in removed_segs:
                    continue
                removed_segs.add(sid)
                degree[n] -= 1
                degree[other] -= 1
                if degree[other] == 1:
                    stack.append(other)
        core_segs = {sid for sid in self.segments if sid not in removed_segs}
        cadj: Dict[int, List[Tuple[int, int]]] = {}
        for sid in core_segs:
            s = self.segments[sid]
            cadj.setdefault(s.u, []).append((sid, s.v))
            cadj.setdefault(s.v, []).append((sid, s.u))
        junction = {n for n, e in cadj.items() if len(e) != 2}
        used: Set[int] = set()
        cid = 0

        def walk(start: int, sid: int, other: int) -> Optional[Chain]:
            nonlocal cid
            steps, length, road = [], 0.0, 0.0
            node, seg_id, nxt = start, sid, other
            while True:
                used.add(seg_id)
                s = self.segments[seg_id]
                steps.append((seg_id, s.u == node))
                length += s.length
                if s.category == "paved":
                    road += s.length
                node = nxt
                if node in junction or node == start:
                    break
                cont = [(i, o) for i, o in cadj[node] if i not in used]
                if not cont:
                    break
                seg_id, nxt = cont[0]
            cid += 1
            return Chain(cid, start, node, steps, length, road)

        for n in junction:
            for sid, other in cadj[n]:
                if sid not in used:
                    ch = walk(n, sid, other)
                    self.chains[ch.id] = ch
        # isolated cycles with no junction: treat one node as a junction
        for sid in core_segs:
            if sid not in used:
                s = self.segments[sid]
                ch = walk(s.u, sid, s.v)
                self.chains[ch.id] = ch
        for ch in self.chains.values():
            self.core_adj.setdefault(ch.u, []).append((ch.id, ch.v))
            if ch.v != ch.u:
                self.core_adj.setdefault(ch.v, []).append((ch.id, ch.u))

    # ---- geometry helpers ----------------------------------------------------------------
    def nearest_node(self, lon: float, lat: float, max_m: float = 500.0) -> Optional[int]:
        best, best_d = None, max_m
        for n, xy in self.node_xy.items():
            if abs(xy[0] - lon) > 0.01 or abs(xy[1] - lat) > 0.008:
                continue
            d = _hav(xy, (lon, lat))
            if d < best_d:
                best, best_d = n, d
        return best

    def _dijkstra_segments(self, src: int, limit_m: float):
        dist = {src: 0.0}
        prev: Dict[int, Tuple[int, int]] = {}
        pq = [(0.0, src)]
        while pq:
            d, n = heapq.heappop(pq)
            if d > dist.get(n, math.inf) or d > limit_m:
                continue
            for sid, o in self.adj.get(n, []):
                if sid in getattr(self, "_excluded_segs", ()):
                    continue
                nd = d + self.segments[sid].length
                if nd < dist.get(o, math.inf) and nd <= limit_m:
                    dist[o] = nd
                    prev[o] = (sid, n)
                    heapq.heappush(pq, (nd, o))
        return dist, prev

    def _dijkstra_core(self, src: int, limit_m: float) -> Dict[int, float]:
        dist = {src: 0.0}
        pq = [(0.0, src)]
        while pq:
            d, n = heapq.heappop(pq)
            if d > dist.get(n, math.inf) or d > limit_m:
                continue
            for cid, o in self.core_adj.get(n, []):
                nd = d + self.chains[cid].length
                if nd < dist.get(o, math.inf) and nd <= limit_m:
                    dist[o] = nd
                    heapq.heappush(pq, (nd, o))
        return dist

    def _chain_steps(self, cid: int, from_node: int) -> List[Tuple[int, bool]]:
        ch = self.chains[cid]
        if from_node == ch.u:
            return list(ch.segs)
        return [(sid, not fwd) for sid, fwd in reversed(ch.segs)]

    def coords_of(self, steps: List[Tuple[int, bool]]) -> Optional[List[List[float]]]:
        """Concatenated coordinates; None if any step doesn't start where the last one ended."""
        out: List[List[float]] = []
        for sid, fwd in steps:
            c = self.segments[sid].coords
            c = c if fwd else list(reversed(c))
            if out:
                if _hav(out[-1], c[0]) > CONTINUITY_M:
                    return None
                out.extend(c[1:])
            else:
                out.extend(c)
        return out

    # ---- loop search ---------------------------------------------------------------------
    def search_loops(self, start_lon: float, start_lat: float, target_m: float, tolerance: float,
                     road_budget_m: float, seed: int, time_budget_s: float = 2.0,
                     visit_cap: int = 3_000_000, max_loops: int = 40,
                     excluded_ways: Optional[Set[int]] = None) -> List[Loop]:
        """Loops from the start, `excluded_ways` (e.g. the rider's DNR) never used."""
        t_end = time.monotonic() + time_budget_s
        self._excluded_segs = {sid for sid, s in self.segments.items() if s.way_id in (excluded_ways or ())}
        self._excluded_chains = {cid for cid, ch in self.chains.items()
                                 if any(sid in self._excluded_segs for sid, _ in ch.segs)}
        start = self.nearest_node(start_lon, start_lat)
        if start is None or not self.core_adj:
            return []
        max_stem = 0.20 * target_m  # a lollipop's stem is < 20% of the route
        stem_dist, stem_prev = self._dijkstra_segments(start, max_stem)
        def touches_trail(n: int) -> bool:
            return any(self.chains[c].road_length < self.chains[c].length for c, _ in self.core_adj[n])

        # bases: loop-graph junctions on a trail, reachable by the stem
        bases = sorted((d, n) for n, d in stem_dist.items() if n in self.core_adj and touches_trail(n))
        # spread the bases out: the nearest first, then others >= 300 m from those chosen
        chosen: List[Tuple[float, int]] = []
        for d, n in bases:
            if all(_hav(self.node_xy[n], self.node_xy[m]) >= 300.0 for _, m in chosen):
                chosen.append((d, n))
            if len(chosen) >= 10:
                break
        rng = random.Random(seed)
        found: List[Loop] = []
        states = []
        for stem_len, base in chosen:
            loop_target = target_m - 2.0 * stem_len
            if loop_target < 0.5 * target_m:
                continue
            lo, hi = loop_target * (1 - tolerance), loop_target * (1 + tolerance)
            states.append((stem_len, base, lo, hi, self._dijkstra_core(base, hi),
                           self._stem_steps(start, base, stem_prev)))
        visits, i = 0, 0
        # round-robin randomized restarts over the bases until the time or visit budget is spent
        while states and time.monotonic() < t_end and visits < visit_cap and len(found) < max_loops:
            stem_len, base, lo, hi, to_base, stem_steps = states[i % len(states)]
            i += 1
            v, loop_chains = self._dfs_once(base, lo, hi, road_budget_m, to_base, rng, 20000)
            visits += v
            if loop_chains is None:
                continue
            loop_steps: List[Tuple[int, bool]] = []
            node = base
            for cid in loop_chains:
                loop_steps.extend(self._chain_steps(cid, node))
                ch = self.chains[cid]
                node = ch.v if node == ch.u else ch.u
            steps = stem_steps + loop_steps + [(sid, not fwd) for sid, fwd in reversed(stem_steps)]
            length = sum(self.segments[sid].length for sid, _ in steps)
            cand = Loop(steps, length, stem_len, base, set(loop_chains))
            if not self._is_duplicate(cand, found):
                found.append(cand)
        return found

    def _stem_steps(self, start: int, base: int, prev) -> List[Tuple[int, bool]]:
        steps = []
        node = base
        while node != start:
            sid, parent = prev[node]
            s = self.segments[sid]
            steps.append((sid, s.u == parent))
            node = parent
        steps.reverse()
        return steps

    def _dfs_once(self, base: int, lo: float, hi: float, road_budget: float, to_base: Dict[int, float],
                  rng: random.Random, cap: int):
        """One randomized self-avoiding DFS from base; returns (visits, chain ids of a loop or None)."""
        visits = 0
        first = self._ordered(list(self.core_adj.get(base, [])), rng)
        # stack frames: (node, chain path, length, road length, visited nodes, remaining neighbours)
        stack = [(base, [], 0.0, 0.0, {base}, first)]
        while stack:
            node, path, acc, road, seen, nbrs = stack[-1]
            if not nbrs:
                stack.pop()
                continue
            cid, other = nbrs.pop()
            visits += 1
            if visits > cap:
                return visits, None
            ch = self.chains[cid]
            if cid in path or cid in self._excluded_chains:
                continue
            nacc, nroad = acc + ch.length, road + ch.road_length
            if nacc > hi or nroad > road_budget:
                continue
            if other == base:
                if nacc >= lo and (len(path) >= 1 or ch.u == ch.v):
                    return visits, path + [cid]
                continue
            if other in seen or nacc + to_base.get(other, math.inf) > hi:
                continue
            nxt = self._ordered([x for x in self.core_adj.get(other, []) if x[0] != cid], rng)
            # near the target length, try the neighbours that lead back first
            if nacc > lo * 0.6:
                nxt.sort(key=lambda x: to_base.get(x[1], math.inf), reverse=True)
            stack.append((other, path + [cid], nacc, nroad, seen | {other}, nxt))
        return visits, None

    def _ordered(self, nbrs: List[Tuple[int, int]], rng: random.Random) -> List[Tuple[int, int]]:
        """Random order with trail chains first (popped from the end): roads are connectors."""
        keyed = [(rng.random() - 1.5 * (self.chains[c].road_length / max(self.chains[c].length, 1.0)), (c, o))
                 for c, o in nbrs]
        keyed.sort()
        return [x for _, x in keyed]

    def _is_duplicate(self, cand: Loop, found: List[Loop], threshold: float = 0.70) -> bool:
        clen = {cid: self.chains[cid].length for cid in cand.chain_ids}
        total = sum(clen.values()) or 1.0
        for f in found:
            shared = sum(clen[c] for c in cand.chain_ids & f.chain_ids)
            other_total = sum(self.chains[c].length for c in f.chain_ids) or 1.0
            if shared / min(total, other_total) >= threshold:
                return True
        return False


def _hard_restricted_segments(cur, min_lon, min_lat, max_lon, max_lat) -> Set[int]:
    """Segments under an active hard restriction (by way id or geometry) in the bbox."""
    import datetime
    month = datetime.date.today().month
    cur.execute(
        """
        SELECT s.segment_id, r.seasonal_start_month, r.seasonal_end_month
        FROM trail_segments s
        JOIN restrictions r ON r.is_hard AND (
            r.edge_osm_id = s.osm_way_id OR (r.geom IS NOT NULL AND ST_Intersects(r.geom, s.geom)))
        WHERE s.geom && ST_MakeEnvelope(%s, %s, %s, %s, 4326)
        """,
        (min_lon, min_lat, max_lon, max_lat),
    )
    out = set()
    for sid, s0, s1 in cur.fetchall():
        if s0 and s1:
            active = (s0 <= month <= s1) if s0 <= s1 else (month >= s0 or month <= s1)
            if not active:
                continue
        out.add(sid)
    return out


# ---- cache: one graph per region tile, rebuilt when the OSM import changes --------------------
_cache: "OrderedDict[tuple, TrailGraph]" = OrderedDict()
_cache_lock = threading.Lock()
_CACHE_SIZE = 6
TILE_DEG = 0.05


def graph_for(lon: float, lat: float, radius_m: float, bike: bool) -> TrailGraph:
    """The trail graph around a start, cached per (tile, radius bucket, sport class, import)."""
    from app.db import latest_osm_import_id

    bucket = int(math.ceil(radius_m / 5000.0))
    tile = (round(lat / TILE_DEG), round(lon / TILE_DEG))
    key = (tile, bucket, bike, latest_osm_import_id())
    with _cache_lock:
        if key in _cache:
            _cache.move_to_end(key)
            return _cache[key]
    r = bucket * 5000.0 + TILE_DEG * 111_000.0
    clat, clon = tile[0] * TILE_DEG, tile[1] * TILE_DEG
    dlat = r / 111_132.0
    dlon = r / (111_132.0 * math.cos(math.radians(clat)))
    graph = TrailGraph.load(clon - dlon, clat - dlat, clon + dlon, clat + dlat, bike)
    with _cache_lock:
        _cache[key] = graph
        while len(_cache) > _CACHE_SIZE:
            _cache.popitem(last=False)
    return graph


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()
