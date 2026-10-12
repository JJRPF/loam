"""Round 7 (GH-34) phase 2: nothing shown to a rider is invented.

No hand-made seeds, no synthetic elevation, no demo tracks or curated fallback trails.
When real data is missing the API says so (None / empty / an error) instead.
"""
import pathlib

import fitparse
import io
import pytest

from app.garmin_seeds import seed_catalog
from app.models import RouteRequest, SportProfile, LatLon
from app.routing import process_graphhopper_path

ROOT = pathlib.Path(__file__).resolve().parents[1]
BOW_TRAILHEAD = (43.130061, -71.482362)  # OSM way/1412556913 (frontend/src/data/trailheads.json)


def _gh_path(points, ascend=None):
    n = len(points)
    path = {
        "distance": 1200.0,
        "points": {"coordinates": points},
        "details": {
            "surface": [[0, n - 1, "ground"]],
            "road_class": [[0, n - 1, "path"]],
            "track_type": [],
            "osm_way_id": [[0, n - 1, 289829681]],
            "street_name": [],
        },
    }
    if ascend is not None:
        path["ascend"] = ascend
        path["descend"] = ascend
    return path


def _req():
    return RouteRequest(start=LatLon(lat=43.13, lon=-71.50), profile=SportProfile.MTB, route_mode="loop",
                        target_distance_miles=1.0)


def test_seed_catalog_empty_without_imported_rides():
    for sport in ("mtb", "trail_run"):
        assert seed_catalog.get_matching_seeds(*BOW_TRAILHEAD, target_miles=10.0, sport=sport) == []
        assert seed_catalog.get_matching_seeds(43.1349, -71.3659, target_miles=14.0, sport=sport) == []


def test_no_ascend_without_a_dem_sample(monkeypatch, tmp_path):
    """GraphHopper's own `ascend` (or none at all) never becomes elevation: without DEM coverage
    the route has no elevation, and with it the value is the DEM's whatever GraphHopper said."""
    import app.elevation as elevation
    from app.config import settings

    pts_2d = [[-71.5000, 43.1300], [-71.5050, 43.1320], [-71.5100, 43.1300]]
    monkeypatch.setattr(settings, "dem_dir", str(tmp_path))  # no tiles at all
    elevation.reset_cache()
    for ascend in (None, 0.0, 150.0):
        route = process_graphhopper_path(_gh_path(pts_2d, ascend=ascend), _req())
        assert route.elevation_gain_ft is None
        assert route.elevation_loss_ft is None
        assert all(len(c) == 2 for c in route.coordinates)

    fixture = pathlib.Path(__file__).parent / "fixtures" / "dem"
    monkeypatch.setattr(settings, "dem_dir", str(fixture))
    elevation.reset_cache()
    pts = [[-71.55, 43.12], [-71.55, 43.17]]
    gains = {process_graphhopper_path(_gh_path(pts, ascend=a), _req()).elevation_gain_ft for a in (None, 0.0, 999.0)}
    assert len(gains) == 1 and None not in gains
    elevation.reset_cache()


def test_elevation_comes_from_sampled_points():
    pts_3d = [[-71.5000, 43.1300, 100.0], [-71.5050, 43.1320, 130.0], [-71.5100, 43.1300, 110.0]]
    route = process_graphhopper_path(_gh_path(pts_3d), _req())
    assert route.elevation_gain_ft == round(30.0 * 3.280839895)
    assert route.elevation_loss_ft == round(20.0 * 3.280839895)


def test_exports_leave_unknown_elevation_unset():
    from app.fit_export import build_fit_course
    from app.gpx_export import build_gpx_track

    coords = [[-71.5000, 43.1300], [-71.5050, 43.1320]]
    gpx = build_gpx_track("t", "mtb", coords, 0.3, 5.0, None, None)
    assert "<ele>" not in gpx and "elevation unavailable" in gpx

    fit = fitparse.FitFile(io.BytesIO(build_fit_course("t", "mtb", coords, 0.3, 5.0, None, None)))
    records = [r for r in fit.get_messages("record")]
    assert records and all(r.get_value("altitude") is None for r in records)


def test_trail_names_are_never_invented():
    from app.db import KNOWN_OSM_TRAIL_NAMES, resolve_osm_trail_name

    assert resolve_osm_trail_name(999202) is None  # a way id that isn't in OSM
    assert "Knox Mountain Trail" not in KNOWN_OSM_TRAIL_NAMES.values()


@pytest.mark.asyncio
async def test_garmin_activity_without_gps_file_is_skipped(monkeypatch):
    """No GPX download -> the activity is skipped, never drawn from its start and end points."""
    from app.connectors import connector_manager
    from app.connectors.encryption import encrypt_token
    from app.db import save_user_connected_service
    from tests.fakes import FakeGarmin

    monkeypatch.setattr(FakeGarmin, "download_activity", lambda self, activity_id, dl_fmt=None: b"")
    save_user_connected_service(user_id="r7_no_gps", provider="garmin",
                                encrypted_token=encrypt_token('{"di_token": "t"}'))
    assert await connector_manager.get_connector("garmin").fetch_activities("r7_no_gps") == []


def test_no_fabrication_left_in_production_code():
    banned = [
        "_init_curated_seeds", "bow-town-forest-kickstart", "ingest_bow_ride_data_and_trails",
        "FALLBACK_OTM_TRAILS", "sample_heat_trails", "_generate_realistic_trackpoints",
        "named_fallbacks", "synth_gain_ft", "* 85.0", "fit_loop_distance", "Bear Brook Explorer",
        "Confirmed open 2 days ago", "Simulate overlapping ride", "NH_TRAILHEAD_PRESETS",
        "NH_TRAILHEAD_GEOCODE_DATA", "synthesized topography",
    ]
    files = list((ROOT / "app").rglob("*.py")) + list((ROOT / "frontend" / "src").rglob("*.ts*"))
    for path in files:
        text = path.read_text()
        for needle in banned:
            assert needle not in text, f"{needle!r} still in {path.relative_to(ROOT)}"
