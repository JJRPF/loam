"""Round 7 (GH-34): PAD-US wilderness polygons block bikes, not feet."""
import pytest

from app.db import check_route_trust_layer, get_connection


def _wilderness_point():
    with get_connection() as conn, conn.cursor() as cur:
        # the wilderness with the most imported trail segments inside it (one in NH, not Maine)
        cur.execute("""SELECT r.name, ST_X(ST_PointOnSurface(r.geom)), ST_Y(ST_PointOnSurface(r.geom))
                       FROM restrictions r JOIN trail_segments s ON ST_Intersects(r.geom, s.geom)
                       WHERE r.source LIKE 'PAD-US%' AND r.restriction_type = 'wilderness'
                       GROUP BY r.id, r.name, r.geom ORDER BY count(*) DESC LIMIT 1""")
        return cur.fetchone()


def test_wilderness_is_a_bike_only_hard_block():
    row = _wilderness_point()
    if row is None:
        pytest.skip("run `python -m scripts.import_padus` first")
    name, lon, lat = row
    line = {"type": "LineString", "coordinates": [[lon, lat], [lon + 0.0003, lat + 0.0003]]}
    bike = check_route_trust_layer(line, [], sport="mtb_hardtail")
    foot = check_route_trust_layer(line, [], sport="trail_run")
    assert bike["has_unwaived_hard_blocks"], bike
    assert any(name in str(b) for b in bike["hard_blocks"])
    assert not foot["has_unwaived_hard_blocks"], foot


def test_wilderness_segments_are_removed_from_the_bike_graph_only():
    from app.trail_graph import _hard_restricted_segments
    row = _wilderness_point()
    if row is None:
        pytest.skip("run `python -m scripts.import_padus` first")
    _, lon, lat = row
    with get_connection() as conn, conn.cursor() as cur:
        bbox = (lon - 0.05, lat - 0.05, lon + 0.05, lat + 0.05)
        bike = _hard_restricted_segments(cur, *bbox, bike=True)
        foot = _hard_restricted_segments(cur, *bbox, bike=False)
    assert len(bike) > 0 and not foot
