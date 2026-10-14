"""
Loop seeds from riders' own imported, map-matched rides (plan 7.4).

Seeds are stored by app.heat_import as OSM topology only (ordered node ids and way ids) in
`seed_loops`; there are no hand-made seeds. A seed is offered to a rider when its loop passes
within 1.5 mi of their start, and to riders other than its contributors only when at least
HEAT_MIN_UNIQUE_RIDERS distinct riders rode it, or when it is seed-sourced (an imported Garmin
export) and at least 85% of its length is trail-class (heat privacy rule, Round 8). The candidate is the
real network stem from the start to the loop, the loop itself (its gap at the trimmed
start/finish closed along the network) and the stem back, built through the route builder.
"""
import heapq
import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

SEED_RADIUS_M = 2414.0  # 1.5 mi
GAP_BRIDGE_M = 400.0
SEED_PUBLIC_TRAIL_SHARE = 0.85  # a seed loop is offered to everyone when >= 85% of it is trail-class


@dataclass
class SeedLoop:
    id: int
    sport: str
    distance_m: float
    node_path: List[int]
    way_ids: List[int]
    retrace: float
    rides: int


class SeedLoopCatalog:
    def get_matching_seeds(self, lat: float, lon: float, target_miles: float, sport: str = "mtb",
                           user_id: Optional[str] = None, radius_m: float = SEED_RADIUS_M) -> List[SeedLoop]:
        """Seed loops of this heat sport whose geometry passes within 1.5 mi of the start and whose
        length fits the target. Empty until rides are imported."""
        from app.config import settings
        from app.db import get_connection
        from app.decay import TRAIL_CLASS_HIGHWAYS, heat_sport, min_unique_riders

        try:
            with get_connection() as conn, conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT s.id, s.sport, s.distance_m, s.node_path, s.way_ids, s.retrace, s.rides
                    FROM seed_loops s
                    WHERE s.sport = %s
                      AND (cardinality(s.rider_ids) >= %s OR %s = ANY(s.rider_ids)
                           OR (%s AND EXISTS (SELECT 1 FROM activities a
                                              WHERE a.id = s.activity_id AND a.source = 'garmin_export')
                               AND (SELECT COALESCE(SUM(t2.length_m) FILTER (WHERE t2.highway = ANY(%s)), 0)
                                           / NULLIF(SUM(t2.length_m), 0)
                                    FROM trail_segments t2 WHERE t2.segment_id = ANY(s.segment_ids)) >= %s))
                      AND s.distance_m BETWEEN %s AND %s
                      AND EXISTS (
                          SELECT 1 FROM trail_segments t
                          WHERE t.osm_way_id = ANY(s.way_ids)
                            AND ST_DWithin(t.geom::geography, ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography, %s))
                    ORDER BY abs(s.distance_m - %s) LIMIT 20
                    """,
                    (heat_sport(sport), min_unique_riders(), user_id or "",
                     settings.seed_heat_public, list(TRAIL_CLASS_HIGHWAYS), SEED_PUBLIC_TRAIL_SHARE, 0.4 * target_miles * 1609.344,
                     1.3 * target_miles * 1609.344, lon, lat, radius_m, target_miles * 1609.344),
                )
                return [SeedLoop(*row) for row in cur.fetchall()]
        except Exception:
            return []

    def build_candidate(self, seed: SeedLoop, req) -> Optional[Tuple[list, list]]:
        """(coords, pieces) for stem + loop + stem through the current trail graph, or None when
        the loop's segments are no longer all usable (blocked, deleted from OSM)."""
        from app.models import SportProfile
        from app.route_builder import Piece
        from app.trail_graph import graph_for

        bike = req.profile not in (SportProfile.TRAIL_RUN, SportProfile.FOOT)
        graph = graph_for(req.start.lon, req.start.lat, max(seed.distance_m, 8000.0), bike)
        by_pair: Dict[Tuple[int, int], Tuple[int, bool]] = {}
        for sid, s in graph.segments.items():
            by_pair[(s.u, s.v)] = (sid, True)
            by_pair[(s.v, s.u)] = (sid, False)
        loop_steps = []
        for a, b in zip(seed.node_path, seed.node_path[1:]):
            step = by_pair.get((a, b))
            if step is not None:
                loop_steps.append(step)
                continue
            # a short stretch map-matching didn't resolve to segments: bridge it along the network
            bridge = _shortest(graph, a, b, limit_m=GAP_BRIDGE_M)
            if bridge is None:
                return None
            loop_steps += bridge
        # close the trimmed gap at the ride's start/finish along the network
        gap = _shortest(graph, seed.node_path[-1], seed.node_path[0], limit_m=3000.0)
        if gap is None:
            return None
        loop_steps += gap
        start = graph.nearest_node(req.start.lon, req.start.lat)
        if start is None:
            return None
        loop_nodes = {seed.node_path[0]} | set(seed.node_path)
        stem = _shortest(graph, start, None, limit_m=SEED_RADIUS_M * 1.5, targets=loop_nodes)
        if stem is None:
            return None
        stem_steps, join = stem
        # rotate the loop so it starts and ends at the node where the stem joins it
        order = [graph.segments[sid].u if fwd else graph.segments[sid].v for sid, fwd in loop_steps]
        k = order.index(join) if join in order else 0
        loop_steps = loop_steps[k:] + loop_steps[:k]
        steps = stem_steps + loop_steps + [(sid, not fwd) for sid, fwd in reversed(stem_steps)]
        coords = graph.coords_of(steps)
        if coords is None:
            return None
        pieces, idx = [], 0
        for sid, _ in steps:
            seg = graph.segments[sid]
            n = len(seg.coords) - 1
            pieces.append(Piece(start=idx, end=idx + n, way_id=seg.way_id, tags=seg.tags))
            idx += n
        return coords, pieces


def _shortest(graph, src: int, dst: Optional[int], limit_m: float, targets: Optional[set] = None):
    """Dijkstra over graph segments. With dst: steps src->dst. With targets: (steps, reached node)
    to the nearest target node."""
    dist, prev = {src: 0.0}, {}
    pq = [(0.0, src)]
    goal = None
    while pq:
        d, n = heapq.heappop(pq)
        if d > dist.get(n, math.inf) or d > limit_m:
            continue
        if (dst is not None and n == dst) or (targets is not None and n in targets):
            goal = n
            break
        for sid, o in graph.adj.get(n, []):
            nd = d + graph.segments[sid].length
            if nd < dist.get(o, math.inf):
                dist[o] = nd
                prev[o] = (sid, n)
                heapq.heappush(pq, (nd, o))
    if goal is None:
        return None
    steps, node = [], goal
    while node != src:
        sid, parent = prev[node]
        steps.append((sid, graph.segments[sid].u == parent))
        node = parent
    steps.reverse()
    return steps if targets is None else (steps, goal)


seed_catalog = SeedLoopCatalog()
