from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence

from full7_contract_engine import MARKETS
from full7_contract_evidence import build_evidence_engine
from full7_precision_policy import (
    PRODUCTION_FAMILY_POLICY,
    apply_precision_policy,
)

DECISION_GATE_VERSION = "FULL7_CONTRACT_DECISION_GATE_1.0"
_ARTIFACT_PATH = Path(__file__).resolve().parent / "models" / "full7_contract_decision_gate.json"

FAMILY_MARKETS = {
    "1X2": ("home_win", "draw", "away_win"),
    "BTTS": ("btts_yes", "btts_no"),
    "TOTALS": ("over_2_5", "under_2_5"),
}

ARTIFACT = json.loads(_ARTIFACT_PATH.read_text(encoding="utf-8"))
if ARTIFACT.get("version") != DECISION_GATE_VERSION:
    raise RuntimeError("FULL-7 decision artifact version mismatch")

FEATURE_NAMES: Sequence[str] = tuple(ARTIFACT["feature_names"])
CLUSTERS: Sequence[str] = tuple(ARTIFACT["clusters"])


def _finite(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _logit(probability: float) -> float:
    p = min(1.0 - 1e-6, max(1e-6, float(probability)))
    return math.log(p / (1.0 - p))


def _sigmoid(value: float) -> float:
    x = max(-40.0, min(40.0, float(value)))
    return 1.0 / (1.0 + math.exp(-x))


def _sample_low_fraction(gold_features: Mapping[str, Any]) -> Dict[str, Any]:
    features = gold_features.get("features") or {}
    low = 0
    compared = 0
    details: List[Dict[str, Any]] = []
    for name, q25 in ARTIFACT.get("sample_q25_reference", {}).items():
        value = _finite(features.get(name))
        if value is None:
            continue
        compared += 1
        is_low = value < float(q25)
        low += int(is_low)
        details.append({
            "feature": name,
            "value": value,
            "development_q25": float(q25),
            "below_q25": is_low,
        })
    fraction = (low / compared) if compared else 1.0
    ref = ARTIFACT["development_reference"]["low_sample_fraction_q25"]
    if fraction <= float(ref["q25"]):
        status = "HIGH"
    elif fraction <= float(ref["q75"]):
        status = "MEDIUM"
    else:
        status = "LOW"
    return {
        "status": status,
        "low_feature_count": low,
        "compared_feature_count": compared,
        "low_fraction_q25": fraction,
        "development_q25": float(ref["q25"]),
        "development_q75": float(ref["q75"]),
        "details": details,
    }


def _decision_features(
    evidence: Mapping[str, Any],
    gold_features: Mapping[str, Any],
    family: str,
    market: str,
) -> Dict[str, float]:
    probability_layer = evidence["probability_layer"]
    calibrated = probability_layer["calibrated"]
    model_support = probability_layer["model_support"]
    catboost = model_support["catboost"]
    goal = model_support["goal_model"]

    cluster_rows = evidence["independent_clusters"]
    deltas: Dict[str, float] = {}
    confirm_count = 0
    counter_count = 0
    sum_confirm = 0.0
    sum_counter = 0.0
    flip_count = 0
    max_move = 0.0

    for cluster in CLUSTERS:
        row = cluster_rows.get(cluster)
        market_row = (row or {}).get("markets", {}).get(market, {})
        delta = float(market_row.get("delta") or 0.0)
        deltas[cluster] = delta
        max_move = max(max_move, abs(delta))
        if delta > 0:
            confirm_count += 1
            sum_confirm += delta
        elif delta < 0:
            counter_count += 1
            sum_counter += -delta
        if market_row.get("family_preference_flip"):
            flip_count += 1

    family_probabilities = {
        candidate: float(calibrated[candidate])
        for candidate in FAMILY_MARKETS[family]
    }
    others = [
        value
        for candidate, value in family_probabilities.items()
        if candidate != market
    ]
    family_margin = float(calibrated[market]) - max(others)

    cat_family = {
        candidate: float(catboost[candidate])
        for candidate in FAMILY_MARKETS[family]
    }
    goal_family = {
        candidate: float(goal[candidate])
        for candidate in FAMILY_MARKETS[family]
    }

    sample = _sample_low_fraction(gold_features)

    values: Dict[str, float] = {
        "model_disagreement": abs(float(catboost[market]) - float(goal[market])),
        "confirm_count": float(confirm_count),
        "counter_count": float(counter_count),
        "sum_confirm_delta": sum_confirm,
        "sum_counter_delta": sum_counter,
        "net_evidence_delta": sum_confirm - sum_counter,
        "max_cluster_move": max_move,
        "preference_flip_count": float(flip_count),
        "coverage": float(evidence["data_quality"]["core_feature_coverage"]),
        "ood_fraction_q01_q99": float(
            evidence["coherence_ood"]["ood_feature_fraction_q01_q99"]
        ),
        "low_sample_fraction_q25": float(sample["low_fraction_q25"]),
        "family_margin": family_margin,
        "catboost_prefers_market": float(max(cat_family, key=cat_family.get) == market),
        "goal_prefers_market": float(max(goal_family, key=goal_family.get) == market),
    }
    for cluster in CLUSTERS:
        values[f"delta__{cluster}"] = deltas[cluster]

    missing = [name for name in FEATURE_NAMES if name not in values]
    if missing:
        raise RuntimeError(f"FULL-7 decision features missing: {missing}")
    return values


def _adjusted_score(base_probability: float, values: Mapping[str, float], family: str) -> float:
    cfg = ARTIFACT["families"][family]
    mean = cfg["scaler_mean"]
    scale = cfg["scaler_scale"]
    beta = cfg["beta"]
    if not (len(mean) == len(scale) == len(beta) == len(FEATURE_NAMES)):
        raise RuntimeError("FULL-7 decision artifact vector length mismatch")

    eta = _logit(base_probability)
    for index, name in enumerate(FEATURE_NAMES):
        denom = float(scale[index])
        if abs(denom) < 1e-12:
            denom = 1.0
        z = (float(values[name]) - float(mean[index])) / denom
        eta += float(beta[index]) * z
    return _sigmoid(eta)


def _state_from_score(score: float, family: str) -> str:
    cfg = ARTIFACT["families"][family]
    low = float(cfg["threshold_low_to_observe"])
    high = float(cfg["threshold_observe_to_play"])
    if score < low:
        return "AUSLASSEN"
    if score < high:
        return "BEOBACHTEN"
    return "SPIELEN"


def _development_support(evidence: Mapping[str, Any]) -> Dict[str, Any]:
    coverage = float(evidence["data_quality"]["core_feature_coverage"])
    ood = float(evidence["coherence_ood"]["ood_feature_fraction_q01_q99"])
    coverage_ref = ARTIFACT["development_reference"]["coverage"]
    ood_ref = ARTIFACT["development_reference"]["ood_fraction_q01_q99"]

    failures: List[str] = []
    if coverage < float(coverage_ref["min"]):
        failures.append("COVERAGE_BELOW_DEVELOPMENT_MIN")
    if ood > float(ood_ref["max"]):
        failures.append("OOD_ABOVE_DEVELOPMENT_MAX")
    if not evidence["coherence_ood"]["probability_sums_pass"]:
        failures.append("PROBABILITY_COHERENCE_FAIL")
    if int(evidence["data_quality"]["forbidden_odds_feature_count"] or 0) > 0:
        failures.append("ODDS_FEATURE_LEAKAGE")

    return {
        "pass": not failures,
        "failures": failures,
        "coverage": coverage,
        "development_coverage_min": float(coverage_ref["min"]),
        "ood_fraction_q01_q99": ood,
        "development_ood_max": float(ood_ref["max"]),
    }


def _raw_market_head(
    evidence: Mapping[str, Any],
    gold_features: Mapping[str, Any],
    support: Mapping[str, Any],
    sample_security: Mapping[str, Any],
    family: str,
    market: str,
) -> Dict[str, Any]:
    calibrated = evidence["probability_layer"]["calibrated"]
    base_probability = float(calibrated[market])
    values = _decision_features(evidence, gold_features, family, market)
    adjusted = _adjusted_score(base_probability, values, family)

    strategy = ARTIFACT["families"][family]["strategy"]
    if strategy == "EVIDENCE_ADJUSTED":
        reliability_score = adjusted
    elif strategy == "EVIDENCE_DOWNGRADE":
        reliability_score = min(base_probability, adjusted)
    else:
        raise RuntimeError(f"unknown FULL-7 decision strategy: {strategy}")

    state = _state_from_score(reliability_score, family)
    reason = "EMPIRICAL_GATE"
    if not support["pass"]:
        state = "AUSLASSEN"
        reason = "OUTSIDE_DEVELOPMENT_SUPPORT"

    state, reason = apply_precision_policy(
        family,
        state,
        reason,
        sample_status=str(sample_security["status"]),
        family_margin=float(values["family_margin"]),
        catboost_prefers_market=float(values["catboost_prefers_market"]),
        goal_prefers_market=float(values["goal_prefers_market"]),
    )

    return {
        "base_probability": base_probability,
        "evidence_adjusted_probability": adjusted,
        "raw_reliability_score": reliability_score,
        "raw_decision": state,
        "raw_decision_reason": reason,
        "decision_features": values,
        "strategy": strategy,
    }


def build_decision_engine(
    gold_features: Mapping[str, Any],
    *,
    validation_quality: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    evidence = build_evidence_engine(
        gold_features,
        validation_quality=validation_quality,
    )
    calibrated = evidence["probability_layer"]["calibrated"]
    support = _development_support(evidence)
    sample_security = _sample_low_fraction(gold_features)

    family_results: Dict[str, Any] = {}
    market_results: Dict[str, Any] = {}
    raw_heads: Dict[str, Dict[str, Any]] = {}

    for family, markets in FAMILY_MARKETS.items():
        for market in markets:
            raw_heads[market] = _raw_market_head(
                evidence,
                gold_features,
                support,
                sample_security,
                family,
                market,
            )

    selected_markets: Dict[str, str] = {}
    for family, markets in FAMILY_MARKETS.items():
        selected = max(
            markets,
            key=lambda market: (
                float(raw_heads[market]["raw_reliability_score"]),
                float(calibrated[market]),
            ),
        )
        selected_markets[family] = selected
        selected_head = raw_heads[selected]

        family_results[family] = {
            "selected_market": selected,
            "arbitration_basis": "RAW_RELIABILITY_THEN_CALIBRATED_PROBABILITY",
            "base_probability": selected_head["base_probability"],
            "evidence_adjusted_probability": selected_head["evidence_adjusted_probability"],
            "reliability_score": selected_head["raw_reliability_score"],
            "strategy": selected_head["strategy"],
            "decision": selected_head["raw_decision"],
            "decision_reason": selected_head["raw_decision_reason"],
            "thresholds": {
                "auslassen_to_beobachten": float(
                    ARTIFACT["families"][family]["threshold_low_to_observe"]
                ),
                "beobachten_to_spielen": float(
                    ARTIFACT["families"][family]["threshold_observe_to_play"]
                ),
            },
            "prospective_development_validation": ARTIFACT["families"][family][
                "prospective_last3"
            ],
            "production_policy": {
                "max_decision": PRODUCTION_FAMILY_POLICY[family]["max_decision"],
                "spielen_allowed": PRODUCTION_FAMILY_POLICY[family]["spielen_allowed"],
                "validation_maturity": PRODUCTION_FAMILY_POLICY[family].get(
                    "validation_maturity"
                ),
            },
        }

        for market in markets:
            raw = raw_heads[market]
            if market == selected:
                final_state = raw["raw_decision"]
                final_reason = raw["raw_decision_reason"]
            else:
                final_state = "AUSLASSEN"
                final_reason = "COHERENCE_NOT_SELECTED"

            market_evidence = evidence["market_evidence"][market]
            market_results[market] = {
                "market": market,
                "family": family,
                "selected_in_family": market == selected,
                "probability": float(calibrated[market]),
                "raw_reliability_score": raw["raw_reliability_score"],
                "raw_decision": raw["raw_decision"],
                "raw_decision_reason": raw["raw_decision_reason"],
                "reliability_score": raw["raw_reliability_score"],
                "decision": final_state,
                "decision_reason": final_reason,
                "counterargument_test": market_evidence["counterargument_test"],
                "robustness": market_evidence["robustness"],
                "sample_security": sample_security["status"],
                "data_quality_support": support["pass"],
            }

    return {
        "decision_gate_version": DECISION_GATE_VERSION,
        "status": "DEVELOPMENT_ONLY_NEW_UNTOUCHED_OOS_REQUIRED",
        "probabilities": dict(calibrated),
        "families": family_results,
        "markets": market_results,
        "evidence": evidence,
        "sample_security": sample_security,
        "data_quality_support": support,
        "coherence": {
            "arbitration_stage": "AFTER_SEVEN_RAW_HEADS",
            "all_seven_raw_heads_scored": len(raw_heads) == len(MARKETS),
            "one_active_candidate_per_family": True,
            "arbitration_basis": "RAW_RELIABILITY_THEN_CALIBRATED_PROBABILITY",
            "selected_markets": selected_markets,
            "nonselected_markets_fail_closed": True,
        },
        "contract_stage": {
            "goal_model_all_7": True,
            "catboost_all_7": True,
            "oos_ensemble": True,
            "calibration": True,
            "evidence_engine_all_7": True,
            "counterarguments": True,
            "robustness": True,
            "sample_security": True,
            "data_quality": True,
            "coherence_ood": True,
            "decision_all_7": True,
            "new_untouched_oos": "PENDING",
        },
    }
