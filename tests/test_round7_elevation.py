"""Round 7 (GH-34) phase 3: elevation from USGS 3DEP via app.elevation.

Uses tests/fixtures/dem (a generated plane, see make_dem_fixture.py), never real user data.
"""
import os

import pytest

import app.elevation as elevation
from app.config import settings

FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "dem")


def plane(lon, lat):
    return 100.0 + 2000.0 * (lat - 43.10) + 500.0 * (lon + 71.60)


@pytest.fixture
def fixture_dem(monkeypatch):
    monkeypatch.setattr(settings, "dem_dir", FIXTURE_DIR)
    elevation.reset_cache()
    yield
    elevation.reset_cache()


def test_tile_name_is_nw_corner():
    assert elevation.tile_name(-71.5, 43.2) == "n44w072"
    assert elevation.tile_name(-70.9, 42.9) == "n43w071"
    assert elevation.tile_name(-72.1, 45.5) == "n46w073"


def test_bilinear_sample_matches_plane(fixture_dem):
    pts = [[-71.5555, 43.1234], [-71.5201, 43.1777], [-71.5900, 43.1100]]
    for (lon, lat), got in zip(pts, elevation.sample(pts)):
        assert got == pytest.approx(plane(lon, lat), abs=0.01)


def test_missing_coverage_is_none(fixture_dem):
    # outside the fixture's extent, in a tile that isn't on disk, and on the nodata pixel
    assert elevation.sample([[-71.45, 43.15]]) == [None]
    assert elevation.sample([[-70.5, 43.15]]) == [None]
    assert elevation.sample([[-71.5995, 43.1995]]) == [None]
    coords, gain, loss = elevation.route_elevation([[-71.55, 43.15], [-71.45, 43.15]])
    assert coords is None and gain is None and loss is None


def test_densify_spacing_and_vertices():
    coords = [[-71.55, 43.15], [-71.54, 43.15], [-71.54, 43.16]]
    dense, vidx = elevation.densify(coords)
    assert dense[vidx[0]] == coords[0] and dense[vidx[-1]] == coords[-1]
    steps = [elevation._haversine(dense[i], dense[i + 1]) for i in range(len(dense) - 1)]
    assert max(steps) <= 10.0


def test_gain_loss_hysteresis():
    assert elevation.gain_loss([100, 101, 102, 101, 103, 102]) == (3.0, 0.0)  # 1 m jitter ignored
    assert elevation.gain_loss([100, 110, 105, 120, 100]) == (25.0, 25.0)


def test_route_elevation_on_plane(fixture_dem):
    # straight north 0.05 deg: 100 m climb on the plane (2000 m/deg); the hysteresis can leave
    # up to its 3 m threshold uncounted at the end.
    coords, gain, loss = elevation.route_elevation([[-71.55, 43.12], [-71.55, 43.17]])
    assert 97.0 <= gain <= 100.0
    assert loss == 0.0
    assert coords[0][2] == pytest.approx(plane(-71.55, 43.12), abs=0.1)


def test_route_response_uses_dem(fixture_dem):
    from app.models import LatLon, RouteRequest, SportProfile
    from app.routing import process_graphhopper_path

    pts = [[-71.55, 43.12], [-71.55, 43.17], [-71.55, 43.12]]
    path = {"distance": 11120.0, "points": {"coordinates": pts},
            "details": {"surface": [], "road_class": [[0, 2, "path"]], "track_type": [], "osm_way_id": [], "street_name": []}}
    req = RouteRequest(start=LatLon(lat=43.12, lon=-71.55), profile=SportProfile.MTB, route_mode="loop")
    route = process_graphhopper_path(path, req)
    assert 97.0 * 3.2808 <= route.elevation_gain_ft <= 100.0 * 3.2809
    assert 97.0 * 3.2808 <= route.elevation_loss_ft <= 100.0 * 3.2809
    assert all(len(c) == 3 for c in route.coordinates)
