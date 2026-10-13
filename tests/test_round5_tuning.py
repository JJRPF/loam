import pytest
from app.engine_config import EngineConfig, get_config, use_config
from app.scoring import classify_route_geometry, calculate_composite_score
from app.models import SportProfile, TerrainPreference, RouteResponse
from app.routing import classify_surface, select_options
from loam_eval.evaluator import layer0, evaluate_scenario


def test_engine_config_defaults_and_override():
    """Verify default engine configuration matches tuned parameters and can be overridden."""
    cfg = get_config()
    assert cfg.loop_max_retrace <= 0.15
    assert cfg.lollipop_max_retrace <= 0.35
    assert cfg.mult_loop >= 1.0
    assert cfg.mult_out_and_back < 1.0

    # Custom instance
    custom = EngineConfig(loop_max_retrace=0.08, lollipop_max_retrace=0.30)
    assert custom.loop_max_retrace == 0.08
    assert custom.to_dict()["lollipop_max_retrace"] == 0.30


def test_route_classification_rejects_fake_lollipops():
    """Verify routes with stem retrace > lollipop_max_retrace are classified as out_and_back."""
    cfg = EngineConfig(loop_max_retrace=0.10, lollipop_max_retrace=0.35)
    with use_config(cfg):
        # 4% retrace is a true loop
        shape, _ = classify_route_geometry(coordinates=[[0, 0], [1, 1], [0, 0]], repetition_ratio=0.04)
        assert shape == "loop"

        # 36% retrace exceeds 35% cap -> must be out_and_back, NOT lollipop
        shape_36, _ = classify_route_geometry(coordinates=[[0, 0], [1, 1], [0, 0]], repetition_ratio=0.36)
        assert shape_36 == "out_and_back"

        # Round 4 defect: 57% retrace route was mislabeled as lollipop
        shape_57, _ = classify_route_geometry(coordinates=[[0, 0], [1, 1], [0, 0]], repetition_ratio=0.57)
        assert shape_57 == "out_and_back"


def test_true_loop_outranks_retraced_out_and_back():
    """Verify a true loop outranks a retraced route when loop mode is requested."""
    cfg = EngineConfig(
        w_input=0.35,
        w_heat=0.30,
        w_mode=0.25,
        w_quality=0.10,
        w_penalty=0.50,
        mult_loop=1.15,
        mult_out_and_back=0.30,
        road_cap_pct=15.0
    )

    with use_config(cfg):
        # True loop (14.1 mi, 4% retrace, 8% road)
        loop_score, loop_bd, _ = calculate_composite_score(
            distance_miles=14.1,
            target_distance_miles=14.0,
            surface_breakdown={"singletrack": 92.0, "paved": 8.0},
            surface_strip=[],
            preference=TerrainPreference(singletrack=0.8, paved=0.1),
            sport=SportProfile.MTB,
            repetition_ratio=0.04,
            warnings=[],
            edge_osm_ids=[],
            route_type="loop"
        )

        # Retraced route (14.1 mi, 52% retrace, 8% road)
        retraced_score, retraced_bd, _ = calculate_composite_score(
            distance_miles=14.1,
            target_distance_miles=14.0,
            surface_breakdown={"singletrack": 92.0, "paved": 8.0},
            surface_strip=[],
            preference=TerrainPreference(singletrack=0.8, paved=0.1),
            sport=SportProfile.MTB,
            repetition_ratio=0.52,
            warnings=[],
            edge_osm_ids=[],
            route_type="out_and_back"
        )

        assert loop_score > retraced_score + 25.0, (
            f"True loop ({loop_score}) should strongly outrank retraced route ({retraced_score})"
        )


def test_road_cap_enforcement_and_penalties():
    """Verify routes exceeding user road cap receive penalties."""
    cfg = EngineConfig(
        road_cap_pct=15.0,
        road_score_weight=1.5
    )

    with use_config(cfg):
        # Route conforming to 15% road cap (10% road)
        score_ok, _, _ = calculate_composite_score(
            distance_miles=10.0,
            target_distance_miles=10.0,
            surface_breakdown={"singletrack": 90.0, "paved": 10.0},
            surface_strip=[],
            preference=TerrainPreference(singletrack=0.85, paved=0.15),
            sport=SportProfile.MTB,
            repetition_ratio=0.05,
            warnings=[],
            edge_osm_ids=[],
            route_type="loop"
        )

        # Route severely exceeding road cap (40% road)
        score_excess, _, _ = calculate_composite_score(
            distance_miles=10.0,
            target_distance_miles=10.0,
            surface_breakdown={"singletrack": 60.0, "paved": 40.0},
            surface_strip=[],
            preference=TerrainPreference(singletrack=0.85, paved=0.15),
            sport=SportProfile.MTB,
            repetition_ratio=0.05,
            warnings=[],
            edge_osm_ids=[],
            route_type="loop"
        )

        assert score_ok > score_excess + 20.0


def test_evaluator_layer_0_hard_gates():
    """Verify loam_eval Layer 0 hard gates catch road cap, fake lollipop, and distance violations."""
    sc = {
        "id": "test_scen",
        "shape": "loop",
        "sport_profile": "mtb",
        "target_miles": 10.0,
        "road_cap_pct": 15.0,
        "terrain": {"singletrack": 0.8, "doubletrack": 0.1, "gravel": 0.05, "paved": 0.05},
        "covered": True,
    }

    # Case 1: Exceeds 15% road cap (40% road)
    bad_road_truth = {
        "road_pct": 40.0,
        "true_shape": "loop",
        "true_retrace": 0.04,
        "distance_m": 16093.44,  # exactly 10.0 mi
        "ghost_ways": [],
        "dnr_ways": []
    }
    fails_road = layer0(sc, bad_road_truth)
    assert "road_cap" in fails_road

    # Case 2: Fake lollipop / high retrace (55% retrace on requested loop)
    fake_lollipop_truth = {
        "road_pct": 5.0,
        "true_shape": "out_and_back",
        "true_retrace": 0.55,
        "distance_m": 16093.44,
        "ghost_ways": [],
        "dnr_ways": []
    }
    fails_fake = layer0(sc, fake_lollipop_truth)
    assert "shape_mismatch" in fails_fake

    # Case 3: Distance error > 15%
    bad_distance_truth = {
        "road_pct": 5.0,
        "true_shape": "loop",
        "true_retrace": 0.04,
        "distance_m": 25000.0,  # ~15.5 mi on 10 mi target
        "ghost_ways": [],
        "dnr_ways": []
    }
    fails_dist = layer0(sc, bad_distance_truth)
    assert "distance" in fails_dist

    # Case 4: Clean route passes all Layer 0 gates
    clean_truth = {
        "road_pct": 8.0,
        "true_shape": "loop",
        "true_retrace": 0.04,
        "distance_m": 16093.44,
        "ghost_ways": [],
        "dnr_ways": []
    }
    fails_clean = layer0(sc, clean_truth)
    assert fails_clean == []
