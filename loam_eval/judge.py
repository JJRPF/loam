"""Layer 3: multimodal LLM judge (calibrated, cost-controlled, advisory by default).

No paid provider is wired in: spend needs Justin's written approval (issue #30).
``Judge`` is a protocol; a provider adapter just implements ``score_pair``. This
module supplies the safeguards around any adapter:

* order bias:  every pair is judged twice with sides swapped; disagreement => tie
* temperature 0 and reasons logged (adapter responsibility, recorded here)
* cache:       identical (config-independent) pair payloads are never re-billed
* call cap:    hard budget, raises ``BudgetExceeded`` instead of silently spending
* calibration: the judge may influence selection only if it agrees with human
               labels on >= 75% of calibration pairs; otherwise advisory only
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, Tuple

CALIBRATION_THRESHOLD = 0.75
RUBRIC = ["loop_quality", "flow_naturalness", "road_avoidance", "variety", "plausibility"]


class BudgetExceeded(RuntimeError):
    pass


class Judge(Protocol):
    name: str

    def score_pair(self, first: Dict[str, Any], second: Dict[str, Any]) -> Dict[str, Any]:
        """Return {"winner": "first"|"second"|"tie", "reason": str, "rubric": {...}}.

        ``first``/``second`` hold the map image path + structured JSON (miles, climbing,
        surface split, retrace %, road %, shape, warnings). Must run at temperature 0.
        """


class NotApproved(RuntimeError):
    pass


def require_approval() -> int:
    """Paid judge calls need an explicit, written call budget via env (set by Justin)."""
    raw = os.environ.get("LOAM_JUDGE_APPROVED_CALLS", "")
    if not raw.isdigit() or int(raw) <= 0:
        raise NotApproved("No approved LLM-judge budget. Set LOAM_JUDGE_APPROVED_CALLS after written approval.")
    return int(raw)


@dataclass
class JudgeSession:
    judge: Judge
    max_calls: int
    cache_path: Optional[str] = None
    calls: int = 0
    cache: Dict[str, Any] = field(default_factory=dict)
    log: List[Dict[str, Any]] = field(default_factory=list)

    def __post_init__(self):
        if self.cache_path and os.path.exists(self.cache_path):
            with open(self.cache_path, "r", encoding="utf-8") as fh:
                self.cache = json.load(fh)

    def _key(self, a: Dict[str, Any], b: Dict[str, Any]) -> str:
        blob = json.dumps([self.judge.name, a, b], sort_keys=True, default=str)
        return hashlib.sha256(blob.encode()).hexdigest()

    def _call(self, a, b) -> Dict[str, Any]:
        k = self._key(a, b)
        if k in self.cache:
            return self.cache[k]
        if self.calls >= self.max_calls:
            raise BudgetExceeded(f"judge call cap {self.max_calls} reached")
        self.calls += 1
        res = self.judge.score_pair(a, b)
        self.cache[k] = res
        self.log.append({"pair": k[:12], "result": res})
        return res

    def compare(self, a: Dict[str, Any], b: Dict[str, Any]) -> str:
        """Winner ('a'|'b'|'tie') after judging both orderings."""
        r1 = self._call(a, b)["winner"]
        r2 = self._call(b, a)["winner"]
        v1 = {"first": "a", "second": "b"}.get(r1, "tie")
        v2 = {"first": "b", "second": "a"}.get(r2, "tie")
        return v1 if v1 == v2 else "tie"

    def save(self):
        if self.cache_path:
            os.makedirs(os.path.dirname(self.cache_path) or ".", exist_ok=True)
            with open(self.cache_path, "w", encoding="utf-8") as fh:
                json.dump(self.cache, fh, sort_keys=True)


def calibrate(session: JudgeSession, labeled: List[Tuple[Dict[str, Any], Dict[str, Any], str]]) -> Dict[str, Any]:
    """labeled: (payload_a, payload_b, human_winner 'a'|'b'). Ties count as misses."""
    if not labeled:
        return {"n": 0, "agreement": None, "influences_selection": False,
                "reason": "no human labels yet: judge stays advisory"}
    hits = sum(1 for a, b, h in labeled if session.compare(a, b) == h)
    agreement = hits / len(labeled)
    ok = agreement >= CALIBRATION_THRESHOLD
    return {"n": len(labeled), "agreement": round(agreement, 4), "influences_selection": ok,
            "reason": "calibrated" if ok else f"agreement {agreement:.0%} < {CALIBRATION_THRESHOLD:.0%}: advisory only"}


class MockJudge:
    """Deterministic stand-in for tests only (prefers lower retrace and road, closer miles)."""
    name = "mock-v1"

    def score_pair(self, first: Dict[str, Any], second: Dict[str, Any]) -> Dict[str, Any]:
        def s(p):
            return -p["retrace_pct"] - p["road_pct"] - abs(p["miles"] - p["target_miles"])
        a, b = s(first), s(second)
        w = "first" if a > b else ("second" if b > a else "tie")
        return {"winner": w, "reason": "mock rubric", "rubric": {k: 3 for k in RUBRIC}}
