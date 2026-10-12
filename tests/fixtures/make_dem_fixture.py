"""Generates tests/fixtures/dem/USGS_13_n44w072.tif: a synthetic test DEM (not real terrain).

A 100x100 float32 plane over 43.10-43.20 N, 71.60-71.50 W with elevation
    e(lon, lat) = 100 + 2000 * (lat - 43.10) + 500 * (lon + 71.60)  meters,
so bilinear samples are exactly predictable. Pixel (0, 0) is nodata to test gaps.
"""
import os

import numpy as np
import rasterio
from rasterio.transform import from_origin

WEST, NORTH, RES, N = -71.60, 43.20, 0.001, 100


def plane(lon, lat):
    return 100.0 + 2000.0 * (lat - 43.10) + 500.0 * (lon + 71.60)


def main():
    rows, cols = np.mgrid[0:N, 0:N]
    lon = WEST + (cols + 0.5) * RES
    lat = NORTH - (rows + 0.5) * RES
    data = plane(lon, lat).astype("float32")
    data[0, 0] = -999999.0
    path = os.path.join(os.path.dirname(__file__), "dem", "USGS_13_n44w072.tif")
    with rasterio.open(path, "w", driver="GTiff", width=N, height=N, count=1, dtype="float32",
                       crs="EPSG:4269", transform=from_origin(WEST, NORTH, RES, RES), nodata=-999999.0,
                       compress="deflate") as ds:
        ds.write(data, 1)
    print(path, os.path.getsize(path))


if __name__ == "__main__":
    main()
