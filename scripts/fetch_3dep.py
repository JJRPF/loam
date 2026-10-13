#!/usr/bin/env python3
"""Download USGS 3DEP 1/3 arc-second (~10 m) DEM tiles covering New Hampshire.

Tiles are 1°x1° GeoTIFFs named by their NW corner: n43..n46 x w071..w073. A tile that 404s
(open ocean) is skipped. Each downloaded file is checked by opening it with rasterio.

    python -I scripts/fetch_3dep.py [--dest DIR]   (default: $DATA_DIR/elevation/3dep13)
"""
import argparse
import os
import sys
import urllib.error
import urllib.request

BASE = "https://prd-tnm.s3.amazonaws.com/StagedProducts/Elevation/13/TIFF/current"
LATS = ["n43", "n44", "n45", "n46"]
LONS = ["w071", "w072", "w073"]


def tile_names():
    return [f"{la}{lo}" for la in LATS for lo in LONS]


def check(path):
    import rasterio
    with rasterio.open(path) as ds:
        return ds.width > 0 and ds.height > 0 and ds.crs is not None


def fetch(tile, dest):
    path = os.path.join(dest, f"USGS_13_{tile}.tif")
    if os.path.exists(path):
        try:
            if check(path):
                return "present", path
        except Exception:
            os.remove(path)
    url = f"{BASE}/{tile}/USGS_13_{tile}.tif"
    tmp = path + ".part"
    try:
        with urllib.request.urlopen(url, timeout=60) as resp, open(tmp, "wb") as out:
            while True:
                chunk = resp.read(1 << 20)
                if not chunk:
                    break
                out.write(chunk)
    except urllib.error.HTTPError as e:
        if os.path.exists(tmp):
            os.remove(tmp)
        if e.code in (403, 404):
            return "missing", None
        raise
    os.replace(tmp, path)
    if not check(path):
        raise RuntimeError(f"{path} does not open as a GeoTIFF")
    return "downloaded", path


def main():
    default = os.path.join(os.environ.get("DATA_DIR", os.path.expanduser("~/dev/loam/main/data")), "elevation", "3dep13")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dest", default=default)
    args = ap.parse_args()
    os.makedirs(args.dest, exist_ok=True)
    for tile in tile_names():
        status, path = fetch(tile, args.dest)
        size = f"{os.path.getsize(path) / 1e6:.0f} MB" if path else "-"
        print(f"{tile}: {status} {size}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
