"""Round 7 (GH-34) phase 3: one surface classification from OSM tags; OSM topology import."""
import pytest

from app.surface import classify_surface, surface_category
from scripts.import_osm_graph import split_points


def cat(**tags):
    return surface_category(tags)


# Round 4 regression roads, with the tags these ways carry in the NH extract
# (Grandview Road 42743790 unclassified/asphalt, 18842487 residential/untagged;
#  Ridgewood Drive 5596213 residential/untagged, 18842104 residential/unpaved;
#  Bettys Lane 523822588 residential/untagged, 18859432 residential/asphalt).
@pytest.mark.parametrize("tags", [
    {"highway": "unclassified", "surface": "asphalt", "name": "Grandview Road"},
    {"highway": "residential", "name": "Grandview Road"},
    {"highway": "unclassified", "name": "Grandview Road"},
    {"highway": "residential", "name": "Ridgewood Drive"},
    {"highway": "residential", "surface": "unpaved", "name": "Ridgewood Drive"},
    {"highway": "residential", "name": "Bettys Lane"},
    {"highway": "residential", "surface": "asphalt", "name": "Bettys Lane"},
])
def test_round4_regression_roads_are_paved(tags):
    assert surface_category(tags) == "paved"


def test_paved_branches():
    for hw in ("residential", "service", "tertiary", "secondary", "primary", "living_street", "pedestrian"):
        assert cat(highway=hw) == "paved"
        assert cat(highway=hw, surface="dirt") == "paved"  # any road class is road
    assert cat(highway="unclassified") == "paved"  # unknown surface on a road -> paved
    for s in ("asphalt", "paved", "concrete", "chipseal", "paving_stones"):
        assert cat(highway="path", surface=s) == "paved"
        assert cat(highway="track", surface=s) == "paved"


def test_singletrack_branches():
    for hw in ("path", "bridleway", "footway"):
        assert cat(highway=hw) == "singletrack"  # unknown surface on a path -> singletrack
        assert cat(highway=hw, surface="ground") == "singletrack"
        assert cat(highway=hw, surface="dirt") == "singletrack"
    assert classify_surface({"highway": "steps"}).steps is True


def test_doubletrack_branches():
    assert cat(highway="track") == "doubletrack"  # unknown surface on a track -> doubletrack
    for grade in ("grade2", "grade3", "grade4", "grade5"):
        assert cat(highway="track", tracktype=grade) == "doubletrack"
    assert cat(highway="track", surface="ground") == "doubletrack"


def test_gravel_branches():
    assert cat(highway="track", tracktype="grade1") == "gravel"
    for s in ("gravel", "fine_gravel", "compacted"):
        assert cat(highway="path", surface=s) == "gravel"
        assert cat(highway="track", surface=s) == "gravel"
    assert cat(highway="unclassified", surface="unpaved") == "gravel"
    assert cat(highway="unclassified", surface="dirt") == "gravel"


def test_graphhopper_unknown_values_and_flags():
    # GraphHopper reports untagged values as MISSING/OTHER
    assert cat(road_class="path", surface="missing", track_type="missing") == "singletrack"
    assert cat(road_class="track", surface="other") == "doubletrack"
    assert classify_surface({"highway": "track", "snowmobile": "yes"}).snowmobile is True
    assert classify_surface({"route": "snowmobile"}).category == "doubletrack"
    assert classify_surface({"highway": "path", "informal": "yes"}).informal is True


def test_routing_wrapper_ignores_names():
    from app.routing import classify_surface as gh_classify
    assert gh_classify("path", None, None, "Something Road") == "singletrack"
    assert gh_classify(None, None, None, "Grandview Road") == "paved"  # untagged -> conservative road
    assert gh_classify("residential", None, None, "Single Circuit Trail") == "paved"


def test_split_points_at_junctions_and_endpoints():
    # way 1-2-3-4-5 where node 3 is shared with another way
    assert split_points([1, 2, 3, 4, 5], {3}) == [0, 2, 4]
    # endpoints only
    assert split_points([1, 2, 3], set()) == [0, 2]
    # a junction at an endpoint doesn't add an empty segment
    assert split_points([1, 2, 3], {1, 3}) == [0, 2]
    # a closed way (1 repeats) is cut where the shared node appears inside
    assert split_points([1, 2, 3, 4, 1], {1, 3}) == [0, 2, 4]


def test_imported_topology_is_consistent():
    """The local import: segments chain by OSM node ids and roads are classified by tags."""
    from app.db import get_connection
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM trail_segments")
            if cur.fetchone()[0] == 0:
                pytest.skip("OSM graph not imported (python -m scripts.import_osm_graph)")
            # consecutive segments of a way share their junction node
            cur.execute("""
                SELECT count(*) FROM trail_segments a JOIN trail_segments b
                  ON a.osm_way_id = b.osm_way_id AND b.seq = a.seq + 1
                WHERE a.to_node <> b.from_node
            """)
            assert cur.fetchone()[0] == 0
            # Grandview Road (way 42743790, unclassified/asphalt) is paved in the graph
            cur.execute("SELECT DISTINCT category FROM trail_segments WHERE osm_way_id = 42743790")
            assert [r[0] for r in cur.fetchall()] == ["paved"]
            # edges geometry and tags come from OSM
            cur.execute("SELECT osm_source, name, highway FROM edges WHERE osm_id = 220551352")
            assert cur.fetchone() == (True, "Bobcat Trail", "path")
