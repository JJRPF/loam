"""
Contracted Trail Graph & Self-Avoiding Loop Search for Loam.
Builds a contracted trail graph (junction nodes, trail edges between them)
and searches self-avoiding walks returning to start with distance-to-start
heuristic pruning. Supports pure loops (retrace <= 10%) and lollipops (short stem).
"""
import math
import heapq
from typing import Dict, Any, List, Tuple, Optional, Set
from dataclasses import dataclass, field

from app.models import RouteRequest, RouteResponse, SurfaceSegment, SportProfile
from app.scoring import (
    calculate_composite_score,
    calculate_repetition_ratio,
    classify_route_geometry,
    generate_minimap,
    get_sector_info,
    haversine_m
)
from app.db import (
    get_connection,
    get_edges_heat,
    check_route_trust_layer,
    log_dnr_override,
    get_user_ridden_edge_ids,
    resolve_osm_trail_name,
    KNOWN_OSM_TRAIL_NAMES
)
from psycopg2.extras import RealDictCursor

METERS_TO_MILES = 0.000621371192
METERS_TO_FEET = 3.280839895


@dataclass
class Junction:
    id: int
    lon: float
    lat: float
    degree: int = 0


@dataclass
class TrailEdge:
    edge_id: str
    u: int  # start junction id
    v: int  # end junction id
    length_m: float
    length_miles: float
    name: str
    highway: str
    surface: str
    osm_way_ids: List[int]
    coordinates: List[List[float]]  # [[lon, lat], ...]


class ContractedTrailGraph:
    def __init__(self):
        self.junctions: Dict[int, Junction] = {}
        self.adjacency: Dict[int, List[Tuple[int, TrailEdge]]] = {}
        self.all_edges: List[TrailEdge] = []

    def add_junction(self, j_id: int, lon: float, lat: float) -> Junction:
        if j_id not in self.junctions:
            self.junctions[j_id] = Junction(id=j_id, lon=lon, lat=lat, degree=0)
            self.adjacency[j_id] = []
        return self.junctions[j_id]

    def add_edge(self, edge: TrailEdge):
        self.all_edges.append(edge)
        self.add_junction(edge.u, edge.coordinates[0][0], edge.coordinates[0][1])
        self.add_junction(edge.v, edge.coordinates[-1][0], edge.coordinates[-1][1])
        self.junctions[edge.u].degree += 1
        self.junctions[edge.v].degree += 1

        self.adjacency[edge.u].append((edge.v, edge))
        # Add reverse traversal
        rev_edge = TrailEdge(
            edge_id=f"{edge.edge_id}_rev",
            u=edge.v,
            v=edge.u,
            length_m=edge.length_m,
            length_miles=edge.length_miles,
            name=edge.name,
            highway=edge.highway,
            surface=edge.surface,
            osm_way_ids=list(edge.osm_way_ids),
            coordinates=list(reversed(edge.coordinates))
        )
        self.adjacency[edge.v].append((edge.u, rev_edge))

    @classmethod
    def from_database(
        cls,
        center_lat: float,
        center_lon: float,
        radius_miles: float = 6.0,
        snap_tolerance_m: float = 35.0
    ) -> "ContractedTrailGraph":
        """
        Builds a contracted trail graph from PostGIS edges within radius of center point.
        Clusters endpoints within snap_tolerance_m to identify junctions.
        """
        graph = cls()
        deg_lat = radius_miles / 69.0
        deg_lon = radius_miles / (69.0 * math.cos(math.radians(center_lat)))
        min_lon = center_lon - deg_lon
        max_lon = center_lon + deg_lon
        min_lat = center_lat - deg_lat
        max_lat = center_lat + deg_lat

        rows = []
        try:
            with get_connection() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute(
                        """
                        SELECT osm_id, name, highway, surface, length_m,
                               ST_AsGeoJSON(geom)::json as geom_json
                        FROM edges
                        WHERE geom IS NOT NULL
                          AND ST_Intersects(geom, ST_MakeEnvelope(%s, %s, %s, %s, 4326))
                          AND length_m > 15.0;
                        """,
                        (min_lon, min_lat, max_lon, max_lat)
                    )
                    rows = cur.fetchall()
        except Exception:
            return graph

        if not rows:
            return graph

        # Cluster endpoints into junctions using O(1) spatial grid
        grid_cell_size = 0.00035  # ~30-38 meters
        grid: Dict[Tuple[int, int], List[int]] = {}
        junction_coords: List[List[float]] = []  # [[lon, lat], ...]

        def get_or_create_junction(coord: List[float]) -> int:
            gx = int(round(coord[0] / grid_cell_size))
            gy = int(round(coord[1] / grid_cell_size))

            # Check this cell and 8 neighboring cells
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    neighbor_key = (gx + dx, gy + dy)
                    for j_idx in grid.get(neighbor_key, []):
                        if haversine_m(coord, junction_coords[j_idx]) <= snap_tolerance_m:
                            return j_idx

            new_idx = len(junction_coords)
            junction_coords.append(coord)
            grid.setdefault((gx, gy), []).append(new_idx)
            return new_idx

        for r in rows:
            gj = r.get("geom_json")
            if not gj or not gj.get("coordinates") or len(gj["coordinates"]) < 2:
                continue
            coords = gj["coordinates"]
            u = get_or_create_junction(coords[0])
            v = get_or_create_junction(coords[-1])
            if u == v:
                continue

            length_m = float(r.get("length_m") or 0.0)
            if length_m <= 0:
                length_m = sum(haversine_m(coords[i], coords[i + 1]) for i in range(len(coords) - 1))

            wid = int(r["osm_id"])
            name = r.get("name") or KNOWN_OSM_TRAIL_NAMES.get(wid) or f"Trail #{wid}"
            hw = r.get("highway") or "path"
            surf = r.get("surface") or ("singletrack" if hw in ("path", "bridleway") else "doubletrack")

            edge = TrailEdge(
                edge_id=str(wid),
                u=u,
                v=v,
                length_m=length_m,
                length_miles=round(length_m * METERS_TO_MILES, 3),
                name=name,
                highway=hw,
                surface=surf,
                osm_way_ids=[wid],
                coordinates=coords
            )
            graph.add_edge(edge)

        return graph

    def find_nearest_junction(self, lat: float, lon: float) -> Tuple[int, float]:
        """Returns (junction_id, distance_m) closest to given (lat, lon)."""
        best_id = -1
        best_dist = float("inf")
        target_pt = [lon, lat]
        for j_id, j in self.junctions.items():
            d = haversine_m(target_pt, [j.lon, j.lat])
            if d < best_dist:
                best_dist = d
                best_id = j_id
        return best_id, best_dist

    def compute_dijkstra_distances(self, start_j: int) -> Dict[int, float]:
        """Computes shortest network distance in meters from start_j to all reachable junctions."""
        distances: Dict[int, float] = {start_j: 0.0}
        pq: List[Tuple[float, int]] = [(0.0, start_j)]

        while pq:
            d, u = heapq.heappop(pq)
            if d > distances.get(u, float("inf")):
                continue
            for v, edge in self.adjacency.get(u, []):
                new_d = d + edge.length_m
                if new_d < distances.get(v, float("inf")):
                    distances[v] = new_d
                    heapq.heappush(pq, (new_d, v))

        return distances

    def search_loops(
        self,
        start_lat: float,
        start_lon: float,
        target_miles: float,
        tolerance: float = 0.35,
        max_stem_ratio: float = 0.20,
        max_results: int = 15
    ) -> List[Dict[str, Any]]:
        """
        Searches self-avoiding walks returning to candidate base junctions near the start.
        Evaluates candidate base junctions (degree >= 2) within 1.5 miles of start point.
        Uses distance-to-start heuristic pruning.
        """
        if not self.junctions:
            return []

        target_m = target_miles / METERS_TO_MILES
        min_target_m = target_m * (1.0 - tolerance)
        max_target_m = target_m * (1.0 + tolerance)
        start_pt = [start_lon, start_lat]

        # Find candidate base junctions near start with degree >= 2
        candidate_junctions = []
        for j_id, j in self.junctions.items():
            if j.degree >= 2:
                d = haversine_m(start_pt, [j.lon, j.lat])
                if d <= 2500.0:  # Within ~1.5 miles
                    candidate_junctions.append((d, j_id))
        candidate_junctions.sort()

        if not candidate_junctions:
            return []

        # Try up to top 5 closest junctions
        found_cycles: List[Dict[str, Any]] = []
        seen_edge_signatures = set()

        for stem_m, base_j in candidate_junctions[:5]:
            two_way_stem_m = 2.0 * stem_m
            dist_to_base = self.compute_dijkstra_distances(base_j)

            def dfs(curr: int, visited_nodes: Set[int], path_edges: List[TrailEdge], accum_m: float):
                if len(found_cycles) >= max_results:
                    return

                for nxt, edge in self.adjacency.get(curr, []):
                    if nxt == base_j and len(path_edges) >= 3:
                        total_loop_m = accum_m + edge.length_m
                        total_route_m = total_loop_m + two_way_stem_m

                        if min_target_m <= total_route_m <= max_target_m:
                            # Edge set signature to avoid near duplicates
                            edge_sig = tuple(sorted(e.edge_id.replace("_rev", "") for e in (path_edges + [edge])))
                            if edge_sig in seen_edge_signatures:
                                continue
                            seen_edge_signatures.add(edge_sig)

                            retrace_ratio = round(two_way_stem_m / max(total_route_m, 1.0), 3)
                            loop_ratio = round(total_loop_m / max(total_route_m, 1.0), 3)

                            if retrace_ratio <= 0.10:
                                shape = "loop"
                            elif (two_way_stem_m / total_route_m) < max_stem_ratio and loop_ratio >= 0.60:
                                shape = "lollipop"
                            else:
                                shape = "out_and_back"

                            found_cycles.append({
                                "edges": path_edges + [edge],
                                "loop_m": total_loop_m,
                                "total_m": total_route_m,
                                "retrace_ratio": retrace_ratio,
                                "shape": shape,
                                "stem_m": stem_m,
                                "base_junction_id": base_j,
                                "start_coord": start_pt
                            })
                            if len(found_cycles) >= max_results:
                                return

                    elif nxt not in visited_nodes:
                        min_return_m = dist_to_base.get(nxt, float("inf"))
                        if min_return_m == float("inf"):
                            continue
                        proj_m = accum_m + edge.length_m + min_return_m + two_way_stem_m
                        if proj_m > max_target_m:
                            continue  # Distance-to-start heuristic pruning

                        dfs(nxt, visited_nodes | {nxt}, path_edges + [edge], accum_m + edge.length_m)

            dfs(base_j, {base_j}, [], 0.0)
            if len(found_cycles) >= max_results:
                break

        found_cycles.sort(key=lambda c: (c["retrace_ratio"], abs(c["total_m"] - target_m)))
        return found_cycles

    def cycle_to_route_response(
        self,
        cycle_spec: Dict[str, Any],
        req: RouteRequest,
        cand_id: str = "graph_loop_1",
        user_id: Optional[str] = None
    ) -> RouteResponse:
        """Converts a topological cycle into a fully evaluated RouteResponse."""
        edges: List[TrailEdge] = cycle_spec["edges"]
        stem_m = cycle_spec["stem_m"]
        total_m = cycle_spec["total_m"]
        dist_miles = round(total_m * METERS_TO_MILES, 2)
        rep_ratio = cycle_spec["retrace_ratio"]
        shape = cycle_spec["shape"]

        # Assemble full route coordinates (Start -> stem -> loop edges -> stem -> Start)
        points: List[List[float]] = []
        start_pt = [req.start.lon, req.start.lat]
        points.append(start_pt)

        # First junction coord
        first_j_coord = edges[0].coordinates[0]
        if haversine_m(start_pt, first_j_coord) > 10.0:
            points.append(first_j_coord)

        # Loop edges coordinates
        osm_way_details: List[List[Any]] = []
        all_way_ids = []
        surface_counts = {"singletrack": 0.0, "doubletrack": 0.0, "gravel": 0.0, "paved": 0.0}

        cur_pt_idx = len(points)
        for e in edges:
            e_coords = e.coordinates
            start_idx = cur_pt_idx
            for pt in e_coords[1:]:
                points.append(pt)
                cur_pt_idx += 1
            end_idx = cur_pt_idx

            for wid in e.osm_way_ids:
                all_way_ids.append(wid)
                osm_way_details.append([start_idx, end_idx, wid, e.name])

            surf = e.surface if e.surface in surface_counts else "singletrack"
            surface_counts[surf] += e.length_m

        # Return stem back to start
        if haversine_m(points[-1], start_pt) > 10.0:
            points.append(start_pt)

        # Surface breakdown percentages
        total_surf_m = sum(surface_counts.values()) or 1.0
        breakdown = {k: round((v / total_surf_m) * 100.0, 1) for k, v in surface_counts.items()}

        surface_strip = [
            SurfaceSegment(
                surface_type="singletrack" if breakdown.get("singletrack", 0) > 50 else "doubletrack",
                length_miles=dist_miles,
                start_index=0,
                end_index=len(points) - 1,
                is_unridden=False
            )
        ]

        est_duration_min = round((dist_miles / 10.0) * 60.0, 1)

        # Find primary trail name
        named_trails = [e.name for e in edges if e.name and not e.name.startswith("Trail #")]
        primary_name = named_trails[0] if named_trails else "Trail Loop"

        # Trust check
        geojson_line = {"type": "LineString", "coordinates": points}
        trust_result = check_route_trust_layer(geojson_line, all_way_ids, user_id=user_id, sport=req.profile.value)
        heat_cache = get_edges_heat(list(set(all_way_ids)), req.profile.value, user_id=user_id)

        # Composite score
        composite_score, score_breakdown, verbal_summary = calculate_composite_score(
            distance_miles=dist_miles,
            target_distance_miles=req.target_distance_miles,
            surface_breakdown=breakdown,
            surface_strip=surface_strip,
            preference=req.terrain_preference,
            sport=req.profile,
            repetition_ratio=rep_ratio,
            warnings=trust_result["all_warnings"],
            edge_osm_ids=list(set(all_way_ids)),
            edge_heat_dict=heat_cache,
            user_id=user_id,
            is_covered_region=True,
            is_lollipop=(shape == "lollipop"),
            route_type=shape
        )

        mini_bbox, mini_svg = generate_minimap(points)

        type_label = "Loop" if shape == "loop" else "Lollipop Loop"
        display_name = f"{primary_name} {type_label}"

        return RouteResponse(
            id=cand_id,
            name=display_name,
            sport=req.profile.value,
            sector="LOOP",
            distance_miles=dist_miles,
            duration_minutes=est_duration_min,
            elevation_gain_ft=None,
            elevation_loss_ft=None,
            surface_breakdown=breakdown,
            surface_strip=surface_strip,
            coordinates=points,
            bbox=[min(p[0] for p in points), min(p[1] for p in points), max(p[0] for p in points), max(p[1] for p in points)],
            minimap_bounds=mini_bbox,
            minimap_svg=mini_svg,
            warnings=trust_result["all_warnings"],
            heat_score=score_breakdown.get("heat"),
            match_score=composite_score,
            score_breakdown=score_breakdown,
            repetition_ratio=rep_ratio,
            route_type=shape,
            primary_trail_name=primary_name,
            verbal_summary=verbal_summary
        )
