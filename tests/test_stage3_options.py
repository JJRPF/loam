import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.models import (
    RouteRequest, LatLon, SportProfile, TerrainPreference, SurfaceSegment
)
from app.scoring import (
    calculate_composite_score,
    calculate_repetition_ratio,
    generate_minimap,
    score_input_match,
    score_heat,
    score_mode_value,
    score_quality,
    score_penalties,
    get_sector_info
)
from app.routing import generate_route_options

@pytest.mark.asyncio
async def test_scoring_formula_weights():
    """
    Validates the exact 5-part composite weighting:
    60% input match, 15% heat, 10% mode value, 10% quality, 5% penalties.
    """
    # Case A: Perfect scores across all components
    comp_a, breakdown_a, _ = calculate_composite_score(
        distance_miles=10.0,
        target_distance_miles=10.0,
        surface_breakdown={"singletrack": 100.0},
        surface_strip=[SurfaceSegment(start_index=0, end_index=10, surface_type="singletrack")],
        preference=TerrainPreference(singletrack=1.0, doubletrack=0.0, gravel=0.0, paved=0.0),
        sport=SportProfile.MTB_HARDTAIL,
        repetition_ratio=0.0,
        warnings=[],
        edge_osm_ids=[1001],
        edge_heat_dict={1001: {"weighted_score": 10.0}}
    )
    assert comp_a == 100
    assert breakdown_a["input_match"] == 100.0
    assert breakdown_a["heat"] == 100.0
    assert breakdown_a["mode_value"] == 100.0
    assert breakdown_a["quality"] == 100.0
    assert breakdown_a["penalties"] == 100.0

    # Case B: Verify math weights
    # 0.60 * 50 + 0.15 * 50 + 0.10 * 50 + 0.10 * 50 + 0.05 * 50 = 50.0
    s_in = 50.0
    s_ht = 50.0
    s_mv = 50.0
    s_qu = 50.0
    s_pn = 50.0
    expected = 0.60 * s_in + 0.15 * s_ht + 0.10 * s_mv + 0.10 * s_qu + 0.05 * s_pn
    assert expected == 50.0

def test_out_and_back_repetition_penalty():
    """
    Validates that:
    - repetition < 0.25 has minimal or no penalty (>= 70)
    - repetition >= 0.25 triggers heavy out-and-back penalty (< 70)
    """
    score_clean = score_penalties(repetition_ratio=0.05, warnings=[])
    assert score_clean == 100.0

    score_threshold = score_penalties(repetition_ratio=0.24, warnings=[])
    assert score_threshold >= 70.0

    score_penalized = score_penalties(repetition_ratio=0.45, warnings=[])
    assert score_penalized < 40.0

def test_repetition_calculation_loop_vs_out_and_back():
    """Validates repetition ratio calculation on synthetic loop vs out-and-back."""
    # Synthetic loop: coordinates [A -> B -> C -> D -> A] with separate OSM ways
    loop_coords = [[-71.35, 43.13], [-71.35, 43.14], [-71.34, 43.14], [-71.34, 43.13], [-71.35, 43.13]]
    loop_ways = [[0, 1, 101], [1, 2, 102], [2, 3, 103], [3, 4, 104]]
    loop_rep = calculate_repetition_ratio(loop_coords, loop_ways)
    assert loop_rep == 0.0

    # Synthetic out-and-back: [A -> B -> C -> B -> A] traversing ways 201, 202 out and 202, 201 back
    oab_coords = [[-71.35, 43.13], [-71.35, 43.14], [-71.35, 43.15], [-71.35, 43.14], [-71.35, 43.13]]
    oab_ways = [[0, 1, 201], [1, 2, 202], [2, 3, 202], [3, 4, 201]]
    oab_rep = calculate_repetition_ratio(oab_coords, oab_ways)
    assert oab_rep == 0.5 # 50% repeated

def test_heat_scoring():
    """Validates neutral coverage-aware heat vs high recorded activity."""
    # Cold start / no heat in rural area: neutral 70.0
    neutral_score = score_heat([101, 102], "mtb", {})
    assert neutral_score == 70.0

    # High heat recorded
    heat_cache = {
        101: {"weighted_score": 10.0},
        102: {"weighted_score": 10.0}
    }
    hot_score = score_heat([101, 102], "mtb", heat_cache)
    assert hot_score == 100.0
    assert hot_score > neutral_score

def test_quality_surface_continuity():
    """Validates that continuous surface segments score higher than choppy transitions."""
    # Smooth: 2 transitions over 10 miles
    smooth_strip = [
        SurfaceSegment(start_index=0, end_index=40, surface_type="singletrack"),
        SurfaceSegment(start_index=40, end_index=50, surface_type="gravel"),
        SurfaceSegment(start_index=50, end_index=100, surface_type="singletrack")
    ]
    smooth_score = score_quality(smooth_strip, 10.0)
    assert smooth_score >= 95.0

    # Choppy: 25 transitions over 10 miles
    choppy_strip = []
    for i in range(25):
        st = "singletrack" if i % 2 == 0 else "paved"
        choppy_strip.append(SurfaceSegment(start_index=i*4, end_index=(i+1)*4, surface_type=st))
    choppy_score = score_quality(choppy_strip, 10.0)
    assert choppy_score < 75.0
    assert smooth_score > choppy_score

def test_minimap_generation():
    """Validates that generate_minimap produces valid bbox and SVG path."""
    coords = [
        [-71.3524, 43.1305],
        [-71.3600, 43.1400],
        [-71.3400, 43.1450],
        [-71.3524, 43.1305]
    ]
    bbox, svg_path = generate_minimap(coords, width=120, height=80)
    assert len(bbox) == 4
    assert bbox[0] < bbox[2] # min_lon < max_lon
    assert bbox[1] < bbox[3] # min_lat < max_lat
    assert svg_path.startswith("M")
    assert "L" in svg_path

def test_sector_info():
    """Validates sector naming across azimuth angles."""
    name_0, code_0, q_0 = get_sector_info(0.0)
    assert "North" in name_0
    assert code_0 == "N"
    assert "Q1" in q_0

    name_90, code_90, q_90 = get_sector_info(90.0)
    assert "East" in name_90
    assert code_90 == "E"
    assert "Q2" in q_90

    name_180, code_180, q_180 = get_sector_info(180.0)
    assert "South" in name_180
    assert code_180 == "S"
    assert "Q3" in q_180

    name_270, code_270, q_270 = get_sector_info(270.0)
    assert "West" in name_270
    assert code_270 == "W"
    assert "Q4" in q_270

@pytest.mark.asyncio
async def test_route_options_endpoint_bear_brook():
    """
    Acceptance Check:
    Validates POST /api/route/options generates 10 valid, distinct options for Bear Brook.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {
            "start": {"lat": 43.1305, "lon": -71.3524, "name": "Bear Brook Trailhead"},
            "profile": "mtb_hardtail",
            "route_mode": "loop",
            "target_distance_miles": 10.0,
            "candidate_count": 10
        }
        res = await client.post("/api/route/options", json=payload)
        assert res.status_code == 200
        data = res.json()
        options = data["options"]
        # Round 5: honest shape labels + strict road cap mean fewer (but real) options; never padded
        assert 1 <= len(options) <= 10

        # Verify each option has miles, climbing, minimap bounds & svg, and composite score
        sectors_seen = set()
        for opt in options:
            assert opt["distance_miles"] > 0.0
            assert "elevation_gain_ft" in opt
            assert opt["minimap_bounds"] is not None
            assert len(opt["minimap_bounds"]) == 4
            assert opt["minimap_svg"] is not None
            assert opt["minimap_svg"].startswith("M")
            assert 1 <= opt["match_score"] <= 100
            assert opt["score_breakdown"] is not None
            assert "composite" in opt["score_breakdown"]
            assert "input_match" in opt["score_breakdown"]
            assert "heat" in opt["score_breakdown"]
            assert "mode_value" in opt["score_breakdown"]
            assert "quality" in opt["score_breakdown"]
            assert "penalties" in opt["score_breakdown"]
            assert "repetition_ratio" in opt["score_breakdown"]
            if opt.get("sector"):
                sectors_seen.add(opt["sector"])

        # Multi-quadrant / sector diversity: at least 3 distinct compass directions
        assert len(sectors_seen) >= 3

@pytest.mark.asyncio
async def test_route_options_streaming_endpoint():
    """Validates SSE streaming endpoint POST /api/route/options/stream."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {
            "start": {"lat": 43.1305, "lon": -71.3524, "name": "Bear Brook Trailhead"},
            "profile": "mtb_hardtail",
            "route_mode": "loop",
            "target_distance_miles": 10.0,
            "candidate_count": 10
        }
        res = await client.post("/api/route/options/stream", json=payload)
        assert res.status_code == 200
        assert "text/event-stream" in res.headers.get("content-type", "")

        body_text = res.text
        assert "event: candidate" in body_text
        assert "event: complete" in body_text
        candidate_count = body_text.count("event: candidate")
        assert 1 <= candidate_count <= 10

@pytest.mark.asyncio
async def test_route_options_highland_mountain():
    """Options from a public OSM trailhead (Oak Hill City Forest parking, way/848156793).

    Was Highland Mountain Bike Park at hand-typed coordinates; Highland's ways are tagged
    private in OSM, so the trust layer now (correctly) blocks routes there. Option-count
    acceptance lives in tests/test_round7_routing.py.
    """
    import json, pathlib
    th = next(t for t in json.loads((pathlib.Path(__file__).parents[1] / "frontend/src/data/trailheads.json").read_text())["trailheads"]
              if t["parking_osm"] == "way/848156793")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {
            "start": {"lat": th["lat"], "lon": th["lon"], "name": th["name"]},
            "profile": "mtb_fullsus",
            "route_mode": "loop",
            "target_distance_miles": 8.0,
            "candidate_count": 10
        }
        res = await client.post("/api/route/options", json=payload)
        assert res.status_code == 200
        data = res.json()
        assert len(data["options"]) >= 1
        for opt in data["options"]:
            assert opt["distance_miles"] > 0
            assert opt["match_score"] >= 1
