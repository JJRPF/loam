"""The one way a RouteResponse is built (docs/round7-plan.md 6.1).

GraphHopper paths, trail-graph loops and seed loops all arrive as a coordinate list plus
"pieces" (index ranges along one OSM way, with that way's tags). From those alone this module
computes distance, the surface strip and breakdown (app.surface), real elevation
(app.elevation), retrace from undirected step reuse, the shape label, road % excluding the
access stretch, the geometry-fidelity measure, trust layer, heat, new-to-me and the score.
"""
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from app.elevation import gain_loss, route_elevation
from app.engine_config import get_config
from app.models import Cue, RouteRequest, RouteResponse, SportProfile, SurfaceSegment
from app.scoring import SPUR_LABEL_M, Spur, calculate_composite_score, find_spurs, generate_minimap
from app.surface import surface_category

METERS_TO_MILES = 0.000621371192
METERS_TO_FEET = 3.280839895
EARTH_R = 6371008.8
ACCESS_CAP_M = 3218.688  # at most 2 mi at each end counts as "road to trail"
ACCESS_MAX_SHARE = 0.40  # and never more than 40% of the route
GEOMETRY_MAX_OFFSET_M = 15.0

PROFILE_SPEED_MPH = {
    SportProfile.MTB: 10.0, SportProfile.MTB_HARDTAIL: 10.5, SportProfile.MTB_FULLSUS: 10.0,
    SportProfile.MTB_GRAVEL: 13.0, SportProfile.MTB_FAT: 8.0, SportProfile.MTB_EMTB: 15.5,
    SportProfile.TRAIL_RUN: 6.0, SportProfile.BIKE: 12.0, SportProfile.FOOT: 3.5,
}


@dataclass
class Piece:
    """coords[start..end] (inclusive) runs along OSM way `way_id`, which carries `tags`."""
    start: int
    end: int
    way_id: Optional[int]
    tags: Dict[str, Optional[str]] = field(default_factory=dict)


@dataclass
class BuiltRoute:
    route: RouteResponse
    way_lengths: Dict[int, float]  # meters along each OSM way (dedup by shared length)
    way_ids: List[int]


def _bearing(a: Sequence[float], b: Sequence[float]) -> float:
    p1, p2 = math.radians(a[1]), math.radians(b[1])
    dl = math.radians(b[0] - a[0])
    return math.degrees(math.atan2(math.sin(dl) * math.cos(p2),
                                   math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl))) % 360.0


def _point_at(pts: Sequence[Sequence[float]], cum: Sequence[float], i: int, back: bool, span_m: float = 30.0):
    """A vertex about span_m before (back) or after vertex i along the line."""
    j = i
    if back:
        while j > 0 and cum[i] - cum[j] < span_m:
            j -= 1
    else:
        while j < len(pts) - 1 and cum[j] - cum[i] < span_m:
            j += 1
    return pts[j]


def _trail_label(tags: Dict[str, Optional[str]], cat: str) -> str:
    name = (tags.get("name") or "").strip()
    if name:
        return name
    return {"singletrack": "unnamed singletrack", "doubletrack": "unnamed doubletrack",
            "gravel": "unnamed gravel road", "paved": "unnamed road"}.get(cat, "unnamed trail")


def build_cues(pts: Sequence[Sequence[float]], step_len: Sequence[float], step_cat: Sequence[str],
               step_tags: Sequence[Dict[str, Optional[str]]], limit: int = 200) -> List[Cue]:
    """A cue sheet: where the route changes trail (or doubles back sharply) and which way to turn.
    Names come from OSM tags only; unnamed ways are described by their surface."""
    n = len(pts)
    if n < 2:
        return []
    cum = [0.0]
    for L in step_len:
        cum.append(cum[-1] + L)
    labels = [_trail_label(step_tags[i], step_cat[i]) for i in range(n - 1)]

    def cue(i: int, kind: str, text: str) -> Cue:
        return Cue(distance_miles=round(cum[i] * METERS_TO_MILES, 2), text=text, lat=pts[i][1], lon=pts[i][0], kind=kind)

    cues = [cue(0, "start", f"Start on {labels[0]}")]
    for i in range(1, n - 1):
        changed = labels[i] != labels[i - 1]
        before = _bearing(_point_at(pts, cum, i, True), pts[i])
        after = _bearing(pts[i], _point_at(pts, cum, i, False))
        delta = (after - before + 540.0) % 360.0 - 180.0  # -180..180, positive = right
        sharp = abs(delta) >= 70.0
        if not (changed or sharp) or (cum[i] - (cues[-1].distance_miles / METERS_TO_MILES)) < 40.0:
            continue
        side = "right" if delta > 0 else "left"
        if abs(delta) >= 25.0:
            how = "Sharp " + side if abs(delta) >= 120.0 else "Turn " + side
            cues.append(cue(i, "turn", f"{how} onto {labels[i]}" if changed else f"{how} (stay on {labels[i]})"))
        elif changed:
            cues.append(cue(i, "continue", f"Continue onto {labels[i]}"))
        if len(cues) >= limit - 1:
            break
    cues.append(cue(n - 1, "arrive", "Arrive"))
    return cues


def haversine_m(a: Sequence[float], b: Sequence[float]) -> float:
    p1, p2 = math.radians(a[1]), math.radians(b[1])
    dp, dl = p2 - p1, math.radians(b[0] - a[0])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_R * math.asin(math.sqrt(min(1.0, h)))


def _step_key(a: Sequence[float], b: Sequence[float]) -> Tuple:
    """Undirected key of a step between two vertices (OSM node coordinates repeat exactly)."""
    ka = (round(a[0], 6), round(a[1], 6))
    kb = (round(b[0], 6), round(b[1], 6))
    return (ka, kb) if ka <= kb else (kb, ka)


def pieces_from_graphhopper(details: Dict[str, Any], n_points: int) -> List[Piece]:
    """Pieces from GraphHopper path details (osm_way_id, road_class, surface, track_type, street_name)."""
    keys = {"osm_way_id": "way_id", "road_class": "highway", "surface": "surface",
            "track_type": "tracktype", "street_name": "name"}
    cuts = {0, max(n_points - 1, 0)}
    for k in keys:
        for item in details.get(k, []) or []:
            if len(item) >= 3:
                cuts.add(int(item[0]))
                cuts.add(int(item[1]))
    bounds = sorted(c for c in cuts if 0 <= c <= n_points - 1)

    def value_at(k: str, idx: int):
        for item in details.get(k, []) or []:
            if len(item) >= 3 and item[0] <= idx < item[1]:
                return item[2]
        return None

    pieces = []
    for s, e in zip(bounds, bounds[1:]):
        if e <= s:
            continue
        tags = {keys[k]: value_at(k, s) for k in keys if k != "osm_way_id"}
        way = value_at("osm_way_id", s)
        pieces.append(Piece(start=s, end=e, way_id=int(way) if way is not None else None, tags=tags))
    return pieces


def _shape(total_m: float, retraced_m: float, endpoint_gap_m: float) -> str:
    """Round 6 thresholds: loop <= 10% retrace; lollipop with stem < 20% and loop >= 60%."""
    cfg = get_config()
    if total_m <= 1.0:
        return "loop"
    if endpoint_gap_m > 600.0 and endpoint_gap_m / total_m > 0.20:
        return "point_to_point"
    retrace = retraced_m / total_m
    if retrace <= cfg.loop_max_retrace:
        return "loop"
    stem_frac = retrace  # the stem is ridden twice, so its one-way length equals the retraced length
    loop_frac = 1.0 - 2.0 * retrace
    if retrace <= cfg.lollipop_max_retrace and stem_frac < 0.20 and loop_frac >= 0.60:
        return "lollipop"
    return "out_and_back"


def geometry_offset_m(coords: Sequence[Sequence[float]], way_ids: Sequence[int]) -> Optional[float]:
    """Max distance (m) from the route, densified to <= 10 m, to the OSM geometry of the ways it
    claims. None when a claimed way has no OSM geometry (the route can't be checked -> fails)."""
    import numpy as np
    import shapely
    from app.db import get_way_geometries
    from app.elevation import densify

    ids = sorted({w for w in way_ids if w is not None})
    if len(coords) < 2 or not ids:
        return None
    geoms = get_way_geometries(ids)
    if any(w not in geoms for w in ids):
        return None
    lat0 = math.radians(sum(c[1] for c in coords) / len(coords))
    scale = np.array([EARTH_R * math.cos(lat0) * math.pi / 180.0, EARTH_R * math.pi / 180.0])
    lines = shapely.multilinestrings(
        [shapely.linestrings(np.asarray(geoms[w])[:, :2] * scale) for w in ids if len(geoms[w]) >= 2])
    dense, _ = densify(coords)
    pts = shapely.points(np.asarray(dense)[:, :2] * scale)
    return round(float(shapely.distance(pts, lines).max()), 1)


REQUIRED_NEAR_M = 30.0  # a rider midpoint this close to a spur means the spur is wanted


def _spur_required(spur: Spur, coords: Sequence[Sequence[float]], required: Sequence[Sequence[float]]) -> bool:
    return any(haversine_m(coords[i], r) <= REQUIRED_NEAR_M
               for r in required for i in range(spur.start_idx + 1, spur.end_idx))


def trim_spurs(coords: Sequence[Sequence[float]], pieces: List[Piece],
               required_points: Sequence[Sequence[float]] = ()) -> Tuple[List[Sequence[float]], List[Piece], List[Spur]]:
    """Cut every spur that is not wanted: not through a required point ([lon, lat]) and not the whole
    route (a pure out-and-back is the route, not a spur of it). The route is at the same node before and after a spur, so dropping
    the out-and-back keeps the line continuous. Returns (coords, pieces, spurs cut)."""
    coords = list(coords)
    cut: List[Spur] = []
    while True:
        n = len(coords)
        spurs = find_spurs([list(c) for c in coords])
        victim = next((s for s in spurs
                       if not (s.start_idx == 0 and s.end_idx == n - 1) and not _spur_required(s, coords, required_points)), None)
        if victim is None:
            return coords, pieces, cut
        # Steps start_idx..end_idx-1 go; the piece owning each remaining step is kept.
        owner = [None] * (n - 1)
        for pi, pc in enumerate(pieces):
            for i in range(max(pc.start, 0), min(pc.end, n - 1)):
                owner[i] = pi
        keep_steps = [i for i in range(n - 1) if not victim.start_idx <= i < victim.end_idx]
        coords = coords[:victim.start_idx + 1] + coords[victim.end_idx + 1:]
        new_pieces: List[Piece] = []
        src: List[int] = []
        for new_i, old_i in enumerate(keep_steps):
            pi = owner[old_i]
            if pi is None:
                continue
            if new_pieces and src[-1] == pi and new_pieces[-1].end == new_i:
                new_pieces[-1].end = new_i + 1
            else:
                new_pieces.append(Piece(new_i, new_i + 1, pieces[pi].way_id, pieces[pi].tags))
                src.append(pi)
        pieces = new_pieces
        cut.append(victim)


def build_route_response(
    coords: Sequence[Sequence[float]],
    pieces: List[Piece],
    req: RouteRequest,
    source: str,
    user_id: Optional[str] = None,
    *,
    cand_id: Optional[str] = None,
    label: Optional[str] = None,
    heat_cache: Optional[Dict[int, Dict[str, Any]]] = None,
    user_ridden: Optional[Set[int]] = None,
    covered: Optional[bool] = None,
    trust_result: Optional[Dict[str, Any]] = None,
    extra_warnings: Optional[List[str]] = None,
    check_geometry: bool = True,
    required_points: Optional[Sequence[Sequence[float]]] = None,
) -> BuiltRoute:
    from app.db import check_route_trust_layer, get_edges_heat, is_region_covered

    # Spurs: out-and-back stubs the rider did not ask for are cut before anything is measured.
    # required_points are [lon, lat]; default is the request's midpoints (empty for a plain loop).
    if required_points is None:
        required_points = [[w.lon, w.lat] for w in (req.waypoints or [])]
    coords, pieces, _cut_spurs = trim_spurs(coords, pieces, required_points)
    pts = [[float(c[0]), float(c[1])] for c in coords]
    n = len(pts)
    kept_spurs = find_spurs(pts)
    # Wanted spurs (through a midpoint) and a whole-route out-and-back are not penalised as spurs.
    unwanted = [sp for sp in kept_spurs if not _spur_required(sp, pts, required_points)
                and not (sp.start_idx == 0 and sp.end_idx == n - 1)]
    spur_max_m = max((sp.length_m for sp in unwanted), default=0.0)
    step_len = [haversine_m(pts[i], pts[i + 1]) for i in range(n - 1)]
    total_m = sum(step_len)

    # Per-step category and way from the pieces (a step belongs to the piece that contains it).
    step_cat: List[str] = ["paved"] * max(n - 1, 0)
    step_way: List[Optional[int]] = [None] * max(n - 1, 0)
    step_tags: List[Dict[str, Optional[str]]] = [{}] * max(n - 1, 0)
    for pc in pieces:
        cat = surface_category(pc.tags)
        for i in range(max(pc.start, 0), min(pc.end, n - 1)):
            step_cat[i], step_way[i], step_tags[i] = cat, pc.way_id, pc.tags

    # Surface strip: consecutive steps of one category; breakdown by length.
    strip: List[SurfaceSegment] = []
    cat_len: Dict[str, float] = {"singletrack": 0.0, "doubletrack": 0.0, "gravel": 0.0, "paved": 0.0}
    for i, cat in enumerate(step_cat):
        cat_len[cat] = cat_len.get(cat, 0.0) + step_len[i]
        if strip and strip[-1].surface_type == cat and strip[-1].end_index == i:
            strip[-1].end_index = i + 1
        else:
            strip.append(SurfaceSegment(start_index=i, end_index=i + 1, surface_type=cat,
                                        raw_surface=step_tags[i].get("surface"),
                                        raw_road_class=step_tags[i].get("highway")))
    breakdown = {k: round(v / total_m * 100.0, 1) for k, v in cat_len.items() if total_m > 0 and v > 0}

    # Retrace: steps whose undirected key was ridden earlier in the route.
    seen: Set[Tuple] = set()
    retraced_m = 0.0
    retraced_lines: List[List[List[float]]] = []
    for i in range(n - 1):
        k = _step_key(pts[i], pts[i + 1])
        if k in seen:
            retraced_m += step_len[i]
            retraced_lines.append([pts[i], pts[i + 1]])
        else:
            seen.add(k)
    retrace = retraced_m / total_m if total_m > 0 else 0.0
    endpoint_gap = haversine_m(pts[0], pts[-1]) if n >= 2 else 0.0
    shape = _shape(total_m, retraced_m, endpoint_gap)

    # Access: road from the start to the first trail (and the same at the end), capped at 1 mi each.
    def run_length(indices) -> float:
        acc = 0.0
        for i in indices:
            if step_cat[i] != "paved" or acc >= ACCESS_CAP_M:
                break
            acc += step_len[i]
        return min(acc, ACCESS_CAP_M)

    has_trail = any(c != "paved" for c in step_cat)
    lead = run_length(range(n - 1)) if has_trail else 0.0
    tail = run_length(range(n - 2, -1, -1)) if has_trail else 0.0
    access_m = min(lead + tail, cat_len["paved"], ACCESS_MAX_SHARE * total_m)
    road_pct = round(max(0.0, cat_len["paved"] - access_m) / max(total_m - access_m, 1.0) * 100.0, 1)

    # Elevation from the DEM only.
    ascend_m = descend_m = None
    out_coords: List[List[float]] = pts
    if coords and all(len(c) > 2 and c[2] is not None for c in coords):
        out_coords = [[float(c[0]), float(c[1]), float(c[2])] for c in coords]
        ascend_m, descend_m = gain_loss([c[2] for c in out_coords])
    else:
        coords3d, ascend_m, descend_m = route_elevation(pts)
        if coords3d is not None:
            out_coords = coords3d

    # Ways ridden once (not the stem ridden out and back): two options that share an approach
    # but ride different loops are different options.
    key_count: Dict[Tuple, int] = {}
    for i in range(n - 1):
        k = _step_key(pts[i], pts[i + 1])
        key_count[k] = key_count.get(k, 0) + 1
    way_lengths: Dict[int, float] = {}
    all_ways: Dict[int, None] = {}
    for i, w in enumerate(step_way):
        if w is None:
            continue
        all_ways[w] = None
        if key_count[_step_key(pts[i], pts[i + 1])] == 1:
            way_lengths[w] = way_lengths.get(w, 0.0) + step_len[i]
    way_ids = list(all_ways)

    # Trust layer, heat, coverage, new-to-me.
    if trust_result is None:
        trust_result = check_route_trust_layer({"type": "LineString", "coordinates": pts}, way_ids,
                                               user_id=user_id, sport=req.profile.value)
    if covered is None:
        covered = is_region_covered(req.start.lat, req.start.lon)
    if heat_cache is None:
        heat_cache = get_edges_heat(way_ids, req.profile.value, user_id=user_id)
    warnings: List[str] = list(extra_warnings or []) + list(trust_result.get("all_warnings", []))
    if covered:
        ghosts = {w for i, w in enumerate(step_way) if w is not None and step_cat[i] != "paved" and w not in heat_cache}
        if ghosts:
            warnings.append(f"Ghost trail warning: traverses {len(ghosts)} trail edge(s) with no logged activity heat.")

    unridden_m = 0.0
    if user_ridden is not None:
        for i, w in enumerate(step_way):
            if w is not None and w not in user_ridden and step_cat[i] != "paved":
                unridden_m += step_len[i]
        for seg in strip:
            seg_m = sum(step_len[i] for i in range(seg.start_index, seg.end_index))
            new_m = sum(step_len[i] for i in range(seg.start_index, seg.end_index)
                        if step_way[i] is not None and step_way[i] not in user_ridden)
            seg.is_unridden = seg_m > 0 and new_m / seg_m >= 0.35
    dist_mi = round(total_m * METERS_TO_MILES, 2)
    unridden_mi = round(unridden_m * METERS_TO_MILES, 2)
    unridden_pct = round(min(100.0, unridden_m / total_m * 100.0), 1) if total_m > 0 else 0.0

    score, score_breakdown, verbal = calculate_composite_score(
        distance_miles=dist_mi, target_distance_miles=req.target_distance_miles,
        surface_breakdown=breakdown, surface_strip=strip, preference=req.terrain_preference,
        sport=req.profile, repetition_ratio=retrace, warnings=warnings, edge_osm_ids=way_ids,
        edge_heat_dict=heat_cache, user_id=user_id, is_covered_region=covered,
        find_new_trails_mode=req.find_new_trails_mode, unridden_percent=unridden_pct,
        target_new_percent=req.min_new_trail_percent, unridden_miles=unridden_mi,
        target_new_miles=req.min_new_trail_miles, is_lollipop=(shape == "lollipop"), route_type=shape,
        spur_count=len(unwanted), spur_max_m=spur_max_m,
    )

    # Name: the longest named trail (not road) + the honest shape label.
    named: Dict[str, float] = {}
    for i, t in enumerate(step_tags):
        nm = (t.get("name") or "").strip()
        if nm and step_cat[i] != "paved":
            named[nm] = named.get(nm, 0.0) + step_len[i]
    primary = max(named, key=named.get) if named else None
    shape_label = {"loop": "Loop", "lollipop": "Lollipop Loop", "out_and_back": "Out-and-Back",
                   "point_to_point": "Route"}[shape]
    start_prefix = req.start.name.split("(")[0].strip() if req.start.name else "Start"
    if primary:
        trail = primary[: -len(" Loop")] if primary.endswith(" Loop") and shape_label.endswith("Loop") else primary
        name = f"{start_prefix} — {trail} {shape_label}"
    elif label:
        name = f"{start_prefix} — {label}"
    else:
        name = f"{start_prefix} — {shape_label}"

    speed = PROFILE_SPEED_MPH.get(req.profile, 10.0)
    mini_bbox, mini_svg = generate_minimap(pts)
    lons, lats = [p[0] for p in pts], [p[1] for p in pts]

    route = RouteResponse(
        id=cand_id,
        name=name,
        sport=req.profile.value,
        sector=label,
        distance_miles=dist_mi,
        duration_minutes=round(dist_mi / speed * 60.0, 1),
        elevation_gain_ft=round(ascend_m * METERS_TO_FEET) if ascend_m is not None else None,
        elevation_loss_ft=round(descend_m * METERS_TO_FEET) if descend_m is not None else None,
        surface_breakdown=breakdown,
        surface_strip=strip,
        coordinates=out_coords,
        bbox=[min(lons), min(lats), max(lons), max(lats)] if pts else [],
        minimap_bounds=mini_bbox,
        minimap_svg=mini_svg,
        warnings=warnings,
        dnr_warnings=[f"DNR Warning: Traverses '{d['name']}' ({d.get('reason', 'User DNR')})"
                      for d in trust_result.get("soft_dnr", [])],
        snowmobile_warnings=trust_result.get("snowmobile_warnings", []),
        community_flag_warnings=trust_result.get("community_flag_warnings", []),
        hard_block_waived=bool(trust_result.get("waived_hard_blocks_count", 0) > 0),
        heat_score=score_breakdown.get("heat"),
        match_score=score,
        score_breakdown=score_breakdown,
        repetition_ratio=round(retrace, 3),
        retraced_miles=round(retraced_m * METERS_TO_MILES, 2),
        retraced_coordinates=retraced_lines,
        verbal_summary=verbal,
        route_type=shape,
        primary_trail_name=primary,
        is_find_new_trails=req.find_new_trails_mode,
        unridden_miles=unridden_mi,
        unridden_percent=unridden_pct,
        unridden_segments_count=sum(1 for s in strip if s.is_unridden),
        source=source,
        road_pct=road_pct,
        access_miles=round(access_m * METERS_TO_MILES, 2),
        geometry_max_offset_m=geometry_offset_m(pts, way_ids) if check_geometry else None,
        cues=build_cues(pts, step_len, step_cat, step_tags),
    )
    if route.access_miles >= 0.1:
        route.verbal_summary = f"{route.verbal_summary} {route.access_miles:.1f} mi road to trail."
    return BuiltRoute(route=route, way_lengths=way_lengths, way_ids=way_ids)
