"""Versioned routing-engine configuration (Round 5 tuning).

Every tunable parameter of ranking/classification/selection lives here so a
variant is just a JSON file. The engine is a pure function of
(config, candidates), which keeps benchmark runs deterministic.

Parameters marked [live] only affect live GraphHopper candidate generation
(cost model / waypoint snapping); the offline benchmark cannot exercise them.
"""
from __future__ import annotations

import contextlib
import contextvars
import json
from dataclasses import dataclass, field, asdict, fields
from typing import Any, Dict, Iterator, Optional

CONFIG_VERSION = 1


@dataclass
class EngineConfig:
    version: int = CONFIG_VERSION

    # --- Shape thresholds (repetition = share of route distance that retraces) ---
    loop_max_retrace: float = 0.10        # <= this is a clean loop
    lollipop_max_retrace: float = 0.35    # <= this (with a real circuit) is a lollipop; above = out-and-back
    min_lollipop_circuit_frac: float = 0.15

    # --- Composite weights (current production 60/15/10/10/5) ---
    w_input: float = 0.60
    w_heat: float = 0.15
    w_mode: float = 0.10
    w_quality: float = 0.10
    w_penalty: float = 0.05

    # --- Shape multipliers applied to the composite (honest shape ranking) ---
    mult_loop: float = 1.00
    mult_lollipop: float = 0.97
    mult_out_and_back: float = 0.60

    # --- Road handling ---
    road_cap_pct: float = 15.0            # hard cap on paved/road % of route distance
    road_cap_slack_pct: float = 0.0       # extra tolerance before the hard gate trips
    road_score_weight: float = 0.5        # extra composite penalty per % road above preference

    # --- Distance ---
    distance_tolerance: float = 0.15      # Layer-0 style gate: |d - target| / target
    distance_gate_enforced: bool = True
    distance_slope: float = 1.5           # distance-score loss per unit relative error

    # --- Selection / diversity ---
    dup_overlap_strict: float = 0.70
    dup_overlap_relaxed: float = 0.82
    candidate_count: int = 10

    # --- [live] generation / cost model ---
    paved_cost_multiplier: float = 8.0
    doubletrack_cost_multiplier: float = 1.0
    waypoint_snap_radius_m: float = 60.0
    loop_waypoint_radius_scale: float = 1.0
    spur_trim: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EngineConfig":
        known = {f.name for f in fields(cls)}
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"Unknown config keys: {sorted(unknown)}")
        return cls(**data)

    @classmethod
    def load(cls, path: str) -> "EngineConfig":
        with open(path, "r", encoding="utf-8") as fh:
            return cls.from_dict(json.load(fh))

    def dump(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, indent=2, sort_keys=True)
            fh.write("\n")


_ACTIVE: contextvars.ContextVar[Optional[EngineConfig]] = contextvars.ContextVar(
    "loam_engine_config", default=None
)
_DEFAULT = EngineConfig()


def get_config() -> EngineConfig:
    return _ACTIVE.get() or _DEFAULT


@contextlib.contextmanager
def use_config(cfg: EngineConfig) -> Iterator[EngineConfig]:
    token = _ACTIVE.set(cfg)
    try:
        yield cfg
    finally:
        _ACTIVE.reset(token)


# Ranges the search loop may explore: name -> (low, high) floats, or list of choices.
SEARCH_SPACE: Dict[str, Any] = {
    "loop_max_retrace": (0.05, 0.15),
    "lollipop_max_retrace": (0.25, 0.40),
    "w_input": (0.35, 0.70),
    "w_heat": (0.05, 0.25),
    "w_mode": (0.02, 0.15),
    "w_quality": (0.05, 0.20),
    "w_penalty": (0.02, 0.20),
    "mult_lollipop": (0.85, 1.0),
    "mult_out_and_back": (0.30, 0.80),
    "road_score_weight": (0.0, 2.0),
    "distance_slope": (0.8, 2.0),
    "dup_overlap_strict": (0.55, 0.85),
}
