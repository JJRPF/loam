import pytest
from app.routing import classify_surface
from app.db import (
    get_unridden_high_heat_trails,
)


def test_classify_surface_residential_roads():
    """Residential and paved roads are never singletrack (classification is by OSM tags)."""
    assert classify_surface("residential", "asphalt") == "paved"
    assert classify_surface("residential", None) == "paved"
    assert classify_surface("unclassified", None) == "paved"
    assert classify_surface("service", None) == "paved"
    assert classify_surface("tertiary", None) == "paved"


def test_classify_surface_singletrack_and_doubletrack():
    assert classify_surface("path", None) == "singletrack"
    assert classify_surface("path", "dirt") == "singletrack"
    assert classify_surface("path", "ground") == "singletrack"
    assert classify_surface("track", None) == "doubletrack"
    assert classify_surface("track", "gravel") == "gravel"


def test_unridden_trails_excludes_roads():
    """Verify unridden high heat trails do not contain residential roads."""
    trails = get_unridden_high_heat_trails(
        user_id="test_user_sample",
        lat=43.1343,
        lon=-71.4972,
        radius_miles=15.0,
        sport="mtb"
    )
    trail_names = [t["name"] for t in trails]

    # Must NOT contain residential roads
    assert "Grandview Road" not in trail_names
    assert "Ridgewood Drive" not in trail_names
    assert "Bettys Lane" not in trail_names

    # Must have surface not equal to 'paved'
    for t in trails:
        assert t.get("surface") != "paved", f"Trail {t['name']} has paved surface in MTB unridden trails"

