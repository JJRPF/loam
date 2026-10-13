"""Route elevation from USGS 3DEP 1/3 arc-second (~10 m) DEM tiles (docs/round7-plan.md 5.2).

Tiles live in `settings.dem_dir` as `USGS_13_<n44w072>.tif` (named by the NW corner), fetched by
scripts/fetch_3dep.py. Every route is densified to <= 10 m spacing and sampled bilinearly;
gain and loss use a 3 m hysteresis. If any sample has no DEM coverage (missing tile, nodata),
the route's elevation is None: the UI says "Elevation unavailable" rather than guessing.
"""
import atexit
import math
import os
import threading
from collections import OrderedDict
from typing import List, Optional, Sequence, Tuple

from app.config import settings

MAX_SPACING_M = 10.0
HYSTERESIS_M = 3.0
EARTH_R = 6371008.8
_MAX_OPEN_TILES = 6

_lock = threading.Lock()
_open: "OrderedDict[str, object]" = OrderedDict()


def tile_name(lon: float, lat: float) -> str:
    """3DEP tile covering a point: NW corner, e.g. (-71.5, 43.2) -> n44w072."""
    return f"n{math.floor(lat) + 1:02d}w{math.floor(-lon) + 1:03d}"


def _dataset(name: str):
    """An open rasterio dataset for a tile, or None if the tile isn't on disk. Call under _lock."""
    if name in _open:
        _open.move_to_end(name)
        return _open[name]
    path = os.path.join(settings.dem_dir, f"USGS_13_{name}.tif")
    if not os.path.exists(path):
        _open[name] = None
    else:
        import rasterio
        _open[name] = rasterio.open(path)
    while len(_open) > _MAX_OPEN_TILES:
        _, old = _open.popitem(last=False)
        if old is not None:
            old.close()
    return _open[name]


def tile_count() -> int:
    """How many 3DEP tiles are on disk (for /health)."""
    try:
        return sum(1 for f in os.listdir(settings.dem_dir) if f.startswith("USGS_13_") and f.endswith(".tif"))
    except OSError:
        return 0


def reset_cache() -> None:
    with _lock:
        while _open:
            _, ds = _open.popitem()
            if ds is not None:
                ds.close()


atexit.register(reset_cache)


def _haversine(a: Sequence[float], b: Sequence[float]) -> float:
    p1, p2 = math.radians(a[1]), math.radians(b[1])
    dp, dl = p2 - p1, math.radians(b[0] - a[0])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_R * math.asin(math.sqrt(h))


def densify(coords: Sequence[Sequence[float]], max_spacing_m: float = MAX_SPACING_M) -> Tuple[List[List[float]], List[int]]:
    """Inserts points so no step exceeds max_spacing_m. Returns (points, index of each original vertex)."""
    out: List[List[float]] = []
    vertex_index: List[int] = []
    for i, c in enumerate(coords):
        if i > 0:
            prev = coords[i - 1]
            d = _haversine(prev, c)
            n = int(math.ceil(d / max_spacing_m)) if d > max_spacing_m else 1
            for k in range(1, n):
                t = k / n
                out.append([prev[0] + (c[0] - prev[0]) * t, prev[1] + (c[1] - prev[1]) * t])
        vertex_index.append(len(out))
        out.append([c[0], c[1]])
    return out, vertex_index


def sample(coords: Sequence[Sequence[float]]) -> List[Optional[float]]:
    """Bilinear DEM elevation (meters) per [lon, lat]; None where no tile or nodata covers it."""
    import numpy as np
    from rasterio.windows import Window

    result: List[Optional[float]] = [None] * len(coords)
    by_tile = {}
    for i, c in enumerate(coords):
        by_tile.setdefault(tile_name(c[0], c[1]), []).append(i)

    with _lock:
        for name, idxs in by_tile.items():
            ds = _dataset(name)
            if ds is None:
                continue
            inv = ~ds.transform
            # fractional pixel coordinates of pixel centers
            cols, rows = [], []
            for i in idxs:
                col, row = inv * (coords[i][0], coords[i][1])
                cols.append(col - 0.5)
                rows.append(row - 0.5)
            c0 = max(int(math.floor(min(cols))), 0)
            r0 = max(int(math.floor(min(rows))), 0)
            c1 = min(int(math.floor(max(cols))) + 2, ds.width)
            r1 = min(int(math.floor(max(rows))) + 2, ds.height)
            if c1 <= c0 or r1 <= r0:
                continue
            block = ds.read(1, window=Window(c0, r0, c1 - c0, r1 - r0), masked=True)
            data = np.ma.filled(block.astype("float64"), np.nan)
            for i, col, row in zip(idxs, cols, rows):
                x, y = col - c0, row - r0
                xi, yi = int(math.floor(x)), int(math.floor(y))
                if xi < 0 or yi < 0 or xi + 1 >= data.shape[1] or yi + 1 >= data.shape[0]:
                    continue
                fx, fy = x - xi, y - yi
                q = data[yi:yi + 2, xi:xi + 2]
                if np.isnan(q).any():
                    continue
                v = (q[0, 0] * (1 - fx) * (1 - fy) + q[0, 1] * fx * (1 - fy)
                     + q[1, 0] * (1 - fx) * fy + q[1, 1] * fx * fy)
                result[i] = float(v)
    return result


def gain_loss(elevations: Sequence[float], threshold_m: float = HYSTERESIS_M) -> Tuple[float, float]:
    """Total climb and descent with hysteresis: a change counts once it exceeds threshold_m."""
    if not elevations:
        return 0.0, 0.0
    gain = loss = 0.0
    anchor = elevations[0]
    for e in elevations[1:]:
        if e - anchor >= threshold_m:
            gain += e - anchor
            anchor = e
        elif anchor - e >= threshold_m:
            loss += anchor - e
            anchor = e
    return gain, loss


def route_elevation(coords: Sequence[Sequence[float]]) -> Tuple[Optional[List[List[float]]], Optional[float], Optional[float]]:
    """(coords with elevation in meters as a 3rd value, gain_m, loss_m), or (None, None, None)
    when any part of the route has no DEM coverage."""
    if len(coords) < 2:
        return None, None, None
    dense, vertex_index = densify(coords)
    elevs = sample(dense)
    if any(e is None for e in elevs):
        return None, None, None
    gain, loss = gain_loss(elevs)
    coords3d = [[c[0], c[1], round(elevs[vi], 1)] for c, vi in zip(coords, vertex_index)]
    return coords3d, gain, loss
