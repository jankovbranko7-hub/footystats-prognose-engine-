"""Result-supervised reliability policy for V0.5.0 CONTEXT-AWARE.

The frozen V0.4.3 FULL-5 probability vector is unchanged. This module only
maps the existing six-market probability state to a learned reliability score
and one of three action groups. Model coefficients and reliability-group
centers were learned from genuine chronological OOF predictions with verified
results. No human betting threshold or hand-written predictive weight is used.
"""
from __future__ import annotations

import copy
import math
from typing import Any, Dict, Tuple

POLICY_VERSION = "2.0.0"
POLICY_NAME = "FULL5_RESULT_SUPERVISED_RELIABILITY_POLICY"
POLICY_SOURCE = "RESULT_SUPERVISED_OOF_RELIABILITY_POLICY"

MARKETS: Tuple[Tuple[str, str], ...] = (
    ("HOME", "home_win"),
    ("AWAY", "away_win"),
    ("BTTS YES", "btts_yes"),
    ("BTTS NO", "btts_no"),
    ("OVER 2.5", "over_2_5"),
    ("UNDER 2.5", "under_2_5"),
)
SELECTED_MARKET_LABELS = tuple(label for label, _ in MARKETS)

FEATURE_NAMES = (
    "baseline_home_win",
    "baseline_draw",
    "baseline_away_win",
    "baseline_btts_yes",
    "baseline_over_2_5",
    "sel_HOME",
    "sel_AWAY",
    "sel_BTTS_YES",
    "sel_BTTS_NO",
    "sel_OVER_2_5",
    "sel_UNDER_2_5",
)
SCALER_MEAN = (
    0.3972676097234817,
    0.2736968194142279,
    0.32903557086229,
    0.6496057837288587,
    0.6250487129121429,
    0.0,
    0.0,
    0.7003610108303249,
    0.0,
    0.22743682310469315,
    0.07220216606498195,
)
SCALER_SCALE = (
    0.12018084266417756,
    0.042186395598672016,
    0.11525895274756821,
    0.07622427738262914,
    0.11192629300339134,
    1.0,
    1.0,
    0.4580998421076467,
    1.0,
    0.41917694903314784,
    0.2588223585405771,
)
LOGISTIC_COEFFICIENTS = (
    -0.10944317201112005,
    -0.4035814332297539,
    0.2618331844532771,
    0.11714577081090767,
    0.2816327202080124,
    0.0,
    0.0,
    -0.044109189391905355,
    0.0,
    -0.13433121701007145,
    0.29562732846406664,
)
LOGISTIC_INTERCEPT = 0.6144297193439443
REGULARIZATION_C = 0.3

RELIABILITY_CENTERS = (
    0.4792998524589671,
    0.6421979695630394,
    0.8175575956624413,
)
RELIABILITY_GROUPS = ("NIEDRIG", "MITTEL", "HOCH")
ACTIONS = ("AUSLASSEN / KEIN BET", "BEOBACHTEN", "SPIELEN")
# Backward-compatible audit alias used by the existing release smoke.
LEARNED_CENTROIDS = RELIABILITY_CENTERS
# Obsolete probability-only centers retained solely so historical diagnostic
# callers/tests can be interpreted. apply_learned_policy() never uses them.
LEGACY_DIAGNOSTIC_PROBABILITY_CENTROIDS = (
    0.5939096343988497,
    0.6848009383779808,
    0.7950201361084736,
)

TRAINING_OOF_ROWS = 277
PRIMARY_META_OOS_MATCHES = 195
PRIMARY_META_OOS_PLAY_N = 58
PRIMARY_META_OOS_PLAY_CORRECT = 44
PRIMARY_META_OOS_PLAY_HIT_RATE = 0.7586206896551724
PRIMARY_META_OOS_PLAY_WILSON95 = (0.6347001974698658, 0.8504112564333051)

SELECTED_MARKET_SUPPORT = {
    "HOME": 0,
    "AWAY": 0,
    "BTTS YES": 194,
    "BTTS NO": 0,
    "OVER 2.5": 63,
    "UNDER 2.5": 20,
}


def _num(value: Any) -> float | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        out = float(value)
        return out if math.isfinite(out) and 0.0 <= out <= 1.0 else None
    except Exception:
        return None


def _probabilities(result: Dict[str, Any]) -> Dict[str, float]:
    raw = result.get("probabilities") or {}
    values: Dict[str, float] = {}
    for _, key in MARKETS:
        value = _num(raw.get(key))
        if value is not None:
            values[key] = value
    if len(values) == len(MARKETS):
        return values

    # Compatibility fallback for report variants exposing the ranked market list.
    # No missing value is inferred here.
    label_map = {label.upper(): key for label, key in MARKETS}
    for item in result.get("markets") or []:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or item.get("market") or "").strip().upper()
        key = label_map.get(label)
        if not key:
            continue
        value = _num(item.get("probability"))
        if value is None:
            try:
                pct = float(item.get("probability_pct"))
                value = pct / 100.0 if 0.0 <= pct <= 100.0 else None
            except Exception:
                value = None
        if value is not None:
            values[key] = value

    if len(values) != len(MARKETS):
        missing = [key for _, key in MARKETS if key not in values]
        raise ValueError(
            "Result-supervised policy missing six-market probabilities: "
            + ", ".join(missing)
        )
    return values


def _draw_probability(result: Dict[str, Any], actionable: Dict[str, float]) -> float:
    raw = result.get("probabilities") or {}
    for key in ("draw", "draw_probability", "draw_prob"):
        value = _num(raw.get(key))
        if value is not None:
            return value

    # 1X2 is a normalized probability family in V0.4.3. When a report variant
    # omits the explicit draw field, derive it exactly as the remaining mass.
    home = actionable.get("home_win")
    away = actionable.get("away_win")
    if home is not None and away is not None:
        value = 1.0 - home - away
        if -1e-9 <= value <= 1.0 + 1e-9:
            return min(1.0, max(0.0, value))
    raise ValueError("Result-supervised policy missing 1X2 draw probability.")


def select_strongest_market(result: Dict[str, Any]) -> Dict[str, Any]:
    probabilities = _probabilities(result)
    label, key = max(MARKETS, key=lambda item: probabilities[item[1]])
    probability = float(probabilities[key])
    return {
        "label": label,
        "key": key,
        "probability": probability,
        "probability_pct": round(probability * 100.0, 2),
    }


def _feature_vector(result: Dict[str, Any], strongest: Dict[str, Any]) -> Tuple[float, ...]:
    p = _probabilities(result)
    draw = _draw_probability(result, p)
    selected = str(strongest["label"])
    one_hot = tuple(1.0 if selected == label else 0.0 for label in SELECTED_MARKET_LABELS)
    return (
        p["home_win"],
        draw,
        p["away_win"],
        p["btts_yes"],
        p["over_2_5"],
        *one_hot,
    )


def _sigmoid(value: float) -> float:
    if value >= 0:
        z = math.exp(-value)
        return 1.0 / (1.0 + z)
    z = math.exp(value)
    return z / (1.0 + z)


def reliability_score(result: Dict[str, Any], strongest: Dict[str, Any] | None = None) -> Dict[str, Any]:
    strongest = strongest or select_strongest_market(result)
    x = _feature_vector(result, strongest)
    linear = LOGISTIC_INTERCEPT
    for value, mean, scale, coef in zip(x, SCALER_MEAN, SCALER_SCALE, LOGISTIC_COEFFICIENTS):
        if not math.isfinite(scale) or scale <= 0:
            raise RuntimeError("Frozen reliability scaler contains an invalid scale.")
        linear += coef * ((value - mean) / scale)
    score = _sigmoid(linear)

    distances = tuple(abs(score - center) for center in RELIABILITY_CENTERS)
    index = min(range(len(distances)), key=distances.__getitem__)
    selected_label = str(strongest["label"])
    support_n = int(SELECTED_MARKET_SUPPORT.get(selected_label, 0))
    return {
        "score": score,
        "group_index": index,
        "reliability_group": RELIABILITY_GROUPS[index],
        "decision": ACTIONS[index],
        "assigned_reliability_center": RELIABILITY_CENTERS[index],
        "distance_to_reliability_center": distances[index],
        "selected_market_training_support_n": support_n,
        "selected_market_direct_support": support_n > 0,
        "linear_predictor": linear,
    }


def learned_action(result: Any) -> Dict[str, Any]:
    """Compatibility entry point.

    Dict input uses the current result-supervised v2 policy. Numeric input is
    retained only for historical diagnostics/tests and never drives production.
    """
    if isinstance(result, dict):
        strongest = select_strongest_market(result)
        return reliability_score(result, strongest)
    value = _num(result)
    if value is None:
        raise TypeError("learned_action expects a result dict or a diagnostic probability in [0,1].")
    distances = tuple(abs(value - c) for c in LEGACY_DIAGNOSTIC_PROBABILITY_CENTROIDS)
    index = min(range(len(distances)), key=distances.__getitem__)
    return {
        "decision": ACTIONS[index],
        "diagnostic_only": True,
        "legacy_probability_only": True,
    }


def apply_learned_policy(result: Dict[str, Any]) -> Dict[str, Any]:
    """Apply frozen result-supervised reliability model without changing probabilities."""
    out = copy.deepcopy(result)
    original_probabilities = copy.deepcopy(out.get("probabilities"))
    strongest = select_strongest_market(out)
    reliability = reliability_score(out, strongest)
    legacy_decision = out.get("decision")

    out["legacy_v043_decision_diagnostic"] = legacy_decision
    out["strongest_market"] = strongest
    out["decision"] = reliability["decision"]
    out["final_decision_source"] = POLICY_SOURCE
    out["manual_performance_gates"] = "NONE"
    out["learned_decision_policy"] = {
        "name": POLICY_NAME,
        "version": POLICY_VERSION,
        "source": POLICY_SOURCE,
        "algorithm": "STANDARDIZED_L2_LOGISTIC_PLUS_KMEANS_3_RELIABILITY_GROUPS",
        "training_uses_results": True,
        "training_target": "strongest_selectable_market_correct",
        "trained_on_oof_rows": TRAINING_OOF_ROWS,
        "regularization_C": REGULARIZATION_C,
        "primary_meta_oos_matches": PRIMARY_META_OOS_MATCHES,
        "primary_meta_oos_play": {
            "n": PRIMARY_META_OOS_PLAY_N,
            "correct": PRIMARY_META_OOS_PLAY_CORRECT,
            "hit_rate": PRIMARY_META_OOS_PLAY_HIT_RATE,
            "wilson95": list(PRIMARY_META_OOS_PLAY_WILSON95),
        },
        "reliability_score": reliability["score"],
        "reliability_group": reliability["reliability_group"],
        "reliability_group_index": reliability["group_index"],
        # Centers are retained for audit/reproducibility only; the normal UI does
        # not expose them as if they were betting thresholds.
        "reliability_cluster_centers_audit_only": list(RELIABILITY_CENTERS),
        "assigned_reliability_center_audit_only": reliability["assigned_reliability_center"],
        "distance_to_reliability_center_audit_only": reliability["distance_to_reliability_center"],
        "assignment": "nearest learned reliability-group center",
        "selected_market": strongest,
        "selected_market_training_support_n": reliability["selected_market_training_support_n"],
        "selected_market_direct_support": reliability["selected_market_direct_support"],
        "human_performance_thresholds": False,
        "human_feature_mix_weights": False,
        "legacy_v043_gate_output_used_for_final_action": False,
        "probabilities_modified": False,
        "profitability_claim": False,
    }

    if original_probabilities != out.get("probabilities"):
        raise RuntimeError("Reliability policy must not modify V0.4.3 probabilities.")

    diagnostics = dict(out.get("diagnostics") or {})
    protocol = dict(diagnostics.get("elite_protocol") or {})
    if protocol:
        protocol["legacy_v043_final_decision_diagnostic"] = protocol.get("final_decision")
        protocol["final_decision"] = reliability["decision"]
        protocol["final_decision_source"] = POLICY_SOURCE
        protocol["manual_performance_gates"] = "NONE"
        protocol["legacy_gate_system_role"] = "DIAGNOSTIC_ONLY"
        diagnostics["elite_protocol"] = protocol
        out["diagnostics"] = diagnostics
    return out
