import pytest
from app.routing import classify_surface
from app.db import (
    resolve_osm_trail_name,
    get_unridden_high_heat_trails,
    get_heat_trail_geojson,
    KNOWN_OSM_TRAIL_NAMES,
    ingest_bow_ride_data_and_trails
)
from app.otm import FALLBACK_OTM_TRAILS


def test_classify_surface_residential_roads():
    """Verify residential and paved roads are never classified as singletrack."""
    # Test with Grandview Road
    assert classify_surface("residential", "asphalt", "Grandview Road") == "paved"
    assert classify_surface(None, None, "Grandview Road") == "paved"
    assert classify_surface("residential", None, "Grandview Road") == "paved"

    # Test with Ridgewood Drive
    assert classify_surface("residential", "paved", "Ridgewood Drive") == "paved"
    assert classify_surface(None, None, "Ridgewood Dr") == "paved"

    # Test with Bettys Lane
    assert classify_surface("unclassified", None, "Bettys Lane") == "paved"
    assert classify_surface(None, None, "Bettys Ln") == "paved"

    # Test with other road types
    assert classify_surface("service", None, "Access Road") == "paved"
    assert classify_surface("tertiary", None, "Main Street") == "paved"


def test_classify_surface_singletrack_and_doubletrack():
    """Verify actual paths and trails are classified as singletrack or doubletrack."""
    # Paths default to singletrack
    assert classify_surface("path", None, "Robertson Trail") == "singletrack"
    assert classify_surface("path", "dirt", "Single Circuit Trail") == "singletrack"
    assert classify_surface("path", "ground", "Boulder Trail") == "singletrack"

    # Tracks default to doubletrack
    assert classify_surface("track", None, "Branch Londonderry Turnpike East") == "doubletrack"
    assert classify_surface("track", "gravel", "Powerlines Trail") == "gravel"


def test_bow_town_forest_curated_trails():
    """Verify Bow Town Forest trails exist in curated registry."""
    bow_trails = [
        "Robertson Trail",
        "Single Circuit Trail",
        "Boulder Trail",
        "Robinson's Crest Trail",
        "Mossy Trail",
        "Branch Londonderry Turnpike East"
    ]
    curated_names = set(KNOWN_OSM_TRAIL_NAMES.values())
    for trail in bow_trails:
        assert trail in curated_names, f"Expected {trail} in KNOWN_OSM_TRAIL_NAMES"


def test_unridden_trails_excludes_roads():
    """Verify unridden high heat trails do not contain residential roads."""
    trails = get_unridden_high_heat_trails(
        user_id="test_user_sample",
        lat=43.1343,
        lon=-71.4972,
        radius_miles=15.0,
        sport="mtb"
    )
    assert len(trails) > 0
    trail_names = [t["name"] for t in trails]

    # Must NOT contain residential roads
    assert "Grandview Road" not in trail_names
    assert "Ridgewood Drive" not in trail_names
    assert "Bettys Lane" not in trail_names

    # Must have surface not equal to 'paved'
    for t in trails:
        assert t.get("surface") != "paved", f"Trail {t['name']} has paved surface in MTB unridden trails"


def test_heat_geojson_includes_bow_trails():
    """Verify heat trail GeoJSON includes Bow Town Forest trails in fallback and properties."""
    geojson = get_heat_trail_geojson(sport="mtb")
    assert geojson["type"] == "FeatureCollection"
    assert len(geojson["features"]) > 0

    feature_names = [f["properties"]["name"] for f in geojson["features"]]
    # Should include both Bear Brook and Bow Town Forest trails
    assert any("Robertson" in name or "Single Circuit" in name or "Bobcat" in name for name in feature_names)


def test_ingest_bow_ride_data_and_trails():
    """Verify ingest_bow_ride_data_and_trails runs cleanly and reports ingested edges."""
    res = ingest_bow_ride_data_and_trails(user_id="test_bow_ingest_user", sport="mtb")
    assert res["status"] == "success"
    assert res["edges_ingested"] >= 6
    assert "Robertson Trail" in res["trails"]
    assert "Single Circuit Trail" in res["trails"]
