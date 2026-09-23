"""Frozen FULL-7 Phase-6 decision policy used by the Phase-7 RC.

This module deliberately contains no V3.1 imports and no totals decision path.
It consumes calibrated, coherent probabilities from the locked model runtime and
applies only the rules frozen before Phase-6 OOS evaluation.
"""
from __future__ import annotations

import math
from typing import Any, Mapping


PHASE5_CALIBRATION_DECISION_LOCK_SHA256 = (
    "cb48662360cd66b4e7daaf84ff47294c04d8bb7983e3da9cceecc30207984a99"
)
FINAL_PHASE5_MANIFEST_SHA256 = (
    "189057b6bc81c0e86b1eb1eb7d131e9592c320dd01f7a4ccaaf9b46ae885ab1a"
)
PHASE6_DECISION_LOCK_SHA256 = (
    "627f581e0e3a11c099166abdc792566a7a8fb5e8d252e748fc8e43457813829e"
)
PHASE6_MANIFEST_SHA256 = (
    "dff0689bfa2c81bb7c7c9f0b1ce9beeb4dd3bcbd6de4779ee205d86dbe15cca4"
)

FINAL_DECISION_SOURCE = f"PHASE6_DECISION_LOCK_SHA256:{PHASE6_DECISION_LOCK_SHA256}"
MANUAL_PERFORMANCE_GATES = False

FEATURE_COVERAGE_FLOORS = {"1X2": 0.97775, "BTTS": 0.98086}
PLAY_ZONES = {
    "HOME": (0.50, 0.80),
    "AWAY": (0.50, 0.65),
    "BTTS_YES": (0.55, 0.70),
}
WATCH_ZONES = {
    "HOME": (0.40, 0.85),
    "AWAY": (0.40, 0.70),
    "BTTS_YES": (0.50, 0.70),
    "BTTS_NO": (0.50, 0.60),
}

REQUIRED_INTEGRITY_GATES = (
    "train_forward_support",
    "development_support",
    "chronological_segment_support",
    "calibration_gap",
    "calibration_slope_intercept",
    "wilson_uncertainty",
    "probability_bin_support",
    "input_integrity",
    "model_integrity",
)


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _card(direction: str, probability: float | None, decision: str, reason: str, *, play: bool) -> dict[str, Any]:
    return {
        "direction": direction,
        "probability": probability,
        "decision": decision,
        "reason": reason,
        "play_enabled": play,
        "decision_source": FINAL_DECISION_SOURCE,
    }


def _fail_closed_cards(reason: str, probabilities: Mapping[str, float] | None = None) -> dict[str, dict[str, Any]]:
    p = probabilities or {}
    return {
        "HOME": _card("HOME", p.get("home"), "AUSLASSEN", reason, play=True),
        "DRAW": _card("DRAW", p.get("draw"), "AUSLASSEN", "DRAW_FAIL_CLOSED_DISABLED", play=False),
        "AWAY": _card("AWAY", p.get("away"), "AUSLASSEN", reason, play=True),
        "BTTS_YES": _card("BTTS_YES", p.get("btts_yes"), "AUSLASSEN", reason, play=True),
        "BTTS_NO": _card("BTTS_NO", p.get("btts_no"), "AUSLASSEN", reason, play=False),
        "O25": _card("O25", None, "HOLD", "O25_NOT_RELEASED", play=False),
        "U25": _card("U25", None, "HOLD", "O25_NOT_RELEASED", play=False),
    }


def _result(
    directions: Mapping[str, Any],
    probabilities: Mapping[str, float] | None,
    coherence: Mapping[str, bool],
    gates: Mapping[str, bool],
    reasons: list[str],
) -> dict[str, Any]:
    return {
        "engine": "FOOTYSTATS_FULL7_FINAL_RC",
        "final_decision_source": FINAL_DECISION_SOURCE,
        "manual_performance_gates": MANUAL_PERFORMANCE_GATES,
        "probabilities": dict(probabilities or {}),
        "directions": dict(directions),
        "coherence": dict(coherence),
        "integrity_gates": {**dict(gates), "all_pass": bool(gates) and all(gates.values())},
        "fail_closed_reasons": sorted(set(reasons)),
        "o25_status": "HOLD",
        "o25_decision_rules_active": False,
        "legacy_v3_1_override_active": False,
        "final_decision_dependency_audit": {
            "active_source": FINAL_DECISION_SOURCE,
            "legacy_v3_1_active": False,
            "legacy_thresholds_active": False,
            "o25_runtime_active": False,
        },
    }


def _zone_decision(direction: str, probability: float) -> tuple[str, str]:
    play = PLAY_ZONES.get(direction)
    if play is not None and play[0] <= probability <= play[1]:
        return "SPIELEN", "PHASE6_PLAY_GATES_PASS"
    watch = WATCH_ZONES.get(direction)
    if watch is not None and watch[0] <= probability <= watch[1]:
        return "BEOBACHTEN", "PHASE6_WATCH_GATES_PASS"
    return "AUSLASSEN", "PROBABILITY_OUTSIDE_SUPPORTED_PREOOS_RANGE"


def evaluate_phase7_decision(
    *,
    probabilities: Any,
    feature_coverage: Any,
    integrity_gates: Any,
) -> dict[str, Any]:
    """Apply the frozen direction rules and fail closed on every invalid input."""
    if not isinstance(probabilities, Mapping) or not isinstance(feature_coverage, Mapping) or not isinstance(integrity_gates, Mapping):
        reason = "MALFORMED_INPUT"
        return _result(
            _fail_closed_cards(reason), {}, {"1X2": False, "BTTS": False}, {}, [reason]
        )

    required = ("home", "draw", "away", "btts_yes")
    if any(key not in probabilities for key in required):
        reason = "MALFORMED_INPUT"
        return _result(
            _fail_closed_cards(reason), {}, {"1X2": False, "BTTS": False}, {}, [reason]
        )

    parsed = {key: _number(probabilities.get(key)) for key in required}
    if any(value is None for value in parsed.values()):
        reason = "NON_FINITE_PROBABILITY"
        return _result(
            _fail_closed_cards(reason, parsed), parsed, {"1X2": False, "BTTS": False}, {}, [reason]
        )
    p = {key: float(value) for key, value in parsed.items()}
    p["btts_no"] = 1.0 - p["btts_yes"]

    in_range = all(0.0 <= value <= 1.0 for value in p.values())
    coherence = {
        "1X2": in_range and abs(p["home"] + p["draw"] + p["away"] - 1.0) <= 1e-10,
        "BTTS": in_range and abs(p["btts_no"] - (1.0 - p["btts_yes"])) <= 1e-12,
    }
    gate_state = {key: integrity_gates.get(key) is True for key in REQUIRED_INTEGRITY_GATES}
    if "feature_schema" in integrity_gates:
        gate_state["feature_schema"] = integrity_gates.get("feature_schema") is True
    failed_gates = [f"INTEGRITY_GATE_FAIL:{key}" for key, passed in gate_state.items() if not passed]
    reasons = list(failed_gates)
    if not coherence["1X2"] or not coherence["BTTS"]:
        reasons.append("PREDICTION_COHERENCE_FAIL")
    if not in_range:
        reasons.append("PROBABILITY_OUT_OF_RANGE")
    if reasons:
        reason = reasons[0]
        return _result(_fail_closed_cards(reason, p), p, coherence, gate_state, reasons)

    coverage = {family: _number(feature_coverage.get(family)) for family in ("1X2", "BTTS")}
    if any(value is None or not 0.0 <= value <= 1.0 for value in coverage.values()):
        reason = "MALFORMED_INPUT"
        return _result(_fail_closed_cards(reason, p), p, coherence, gate_state, [reason])

    ordered = ("HOME", "DRAW", "AWAY")
    values = (p["home"], p["draw"], p["away"])
    preferred_1x2 = ordered[max(range(3), key=lambda index: values[index])]
    directions: dict[str, dict[str, Any]] = {
        "DRAW": _card("DRAW", p["draw"], "AUSLASSEN", "DRAW_FAIL_CLOSED_DISABLED", play=False),
        "O25": _card("O25", None, "HOLD", "O25_NOT_RELEASED", play=False),
        "U25": _card("U25", None, "HOLD", "O25_NOT_RELEASED", play=False),
    }

    for direction, key in (("HOME", "home"), ("AWAY", "away")):
        probability = p[key]
        if coverage["1X2"] < FEATURE_COVERAGE_FLOORS["1X2"]:
            state, reason = "AUSLASSEN", "FEATURE_COVERAGE_FAIL"
        elif direction != preferred_1x2:
            state, reason = "AUSLASSEN", "NOT_MODEL_PREFERRED_DIRECTION"
        else:
            state, reason = _zone_decision(direction, probability)
        directions[direction] = _card(direction, probability, state, reason, play=True)

    preferred_btts = "BTTS_YES" if p["btts_yes"] >= 0.5 else "BTTS_NO"
    for direction, key in (("BTTS_YES", "btts_yes"), ("BTTS_NO", "btts_no")):
        probability = p[key]
        if coverage["BTTS"] < FEATURE_COVERAGE_FLOORS["BTTS"]:
            state, reason = "AUSLASSEN", "FEATURE_COVERAGE_FAIL"
        elif direction != preferred_btts:
            state, reason = "AUSLASSEN", "NOT_MODEL_PREFERRED_DIRECTION"
        else:
            state, reason = _zone_decision(direction, probability)
        directions[direction] = _card(
            direction, probability, state, reason, play=direction == "BTTS_YES"
        )

    return _result(directions, p, coherence, gate_state, [])
