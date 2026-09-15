from __future__ import annotations

from typing import Any, Dict, Mapping

from full7_contract_engine import MARKETS, contract_model_support

ENSEMBLE_VERSION = "FULL7_CONTRACT_OOS_ENSEMBLE_1.0"
CALIBRATION_VERSION = "FULL7_CONTRACT_CALIBRATION_1.0"

MARKET_FAMILY = {
    "home_win": "1X2",
    "draw": "1X2",
    "away_win": "1X2",
    "btts_yes": "BTTS",
    "btts_no": "BTTS",
    "over_2_5": "TOTALS",
    "under_2_5": "TOTALS",
}

# Strategy class was selected by prospective temporal development evaluation
# on the later four OOF date blocks (126 rows). No manual 40/60 or 50/50 mix.
#
# 1X2: CATBOOST_ONLY beat GOAL_ONLY and temporally learned blend.
# BTTS: GOAL_ONLY beat CATBOOST_ONLY and temporally learned blend.
# TOTALS: LEARNED_BLEND beat both single-source candidates.
#
# The final TOTALS blend coefficient is refit on all 180 development OOF rows
# only after LEARNED_BLEND was selected prospectively.
ENSEMBLE_POLICY: Dict[str, Dict[str, Any]] = {
    "1X2": {
        "strategy": "CATBOOST_ONLY",
        "catboost_weight": 1.0,
        "goal_weight": 0.0,
        "selection": "PROSPECTIVE_TEMPORAL_DEVELOPMENT",
    },
    "BTTS": {
        "strategy": "GOAL_ONLY",
        "catboost_weight": 0.0,
        "goal_weight": 1.0,
        "selection": "PROSPECTIVE_TEMPORAL_DEVELOPMENT",
    },
    "TOTALS": {
        "strategy": "LEARNED_BLEND",
        "catboost_weight": 0.5317803953799852,
        "goal_weight": 0.4682196046200148,
        "selection": "PROSPECTIVE_TEMPORAL_DEVELOPMENT_THEN_REFIT_180_OOF",
    },
}

# Calibration is a mandatory architecture layer. Prospective temporal testing
# showed that Temperature / Platt / Isotonic calibration increased aggregate
# LogLoss versus the unmodified ensemble probabilities. Therefore the correct
# learned calibration method is explicitly IDENTITY / NO_ADJUSTMENT.
CALIBRATION_POLICY: Dict[str, Dict[str, Any]] = {
    "1X2": {
        "method": "IDENTITY",
        "reason": "Temporal calibration selector worsened prospective LogLoss: 1.071168 vs 1.046733 ensemble.",
    },
    "BTTS": {
        "method": "IDENTITY",
        "reason": "Temporal calibration selector worsened prospective LogLoss: 0.685036 vs 0.682648 ensemble.",
    },
    "TOTALS": {
        "method": "IDENTITY",
        "reason": "Temporal calibration selector worsened prospective LogLoss: 0.687136 vs 0.681950 ensemble.",
    },
}


def _renormalize(probabilities: Dict[str, float]) -> Dict[str, float]:
    one = probabilities["home_win"] + probabilities["draw"] + probabilities["away_win"]
    if one <= 0:
        raise RuntimeError("invalid 1X2 ensemble mass")
    probabilities["home_win"] /= one
    probabilities["draw"] /= one
    probabilities["away_win"] /= one

    btts = probabilities["btts_yes"] + probabilities["btts_no"]
    if btts <= 0:
        raise RuntimeError("invalid BTTS ensemble mass")
    probabilities["btts_yes"] /= btts
    probabilities["btts_no"] /= btts

    totals = probabilities["over_2_5"] + probabilities["under_2_5"]
    if totals <= 0:
        raise RuntimeError("invalid totals ensemble mass")
    probabilities["over_2_5"] /= totals
    probabilities["under_2_5"] /= totals
    return probabilities


def ensemble_and_calibrate(gold_features: Mapping[str, Any]) -> Dict[str, Any]:
    support = contract_model_support(gold_features)
    cat = support["catboost"]
    goal = support["goal_model"]

    ensemble: Dict[str, float] = {}
    disagreement: Dict[str, float] = {}

    for market in MARKETS:
        family = MARKET_FAMILY[market]
        policy = ENSEMBLE_POLICY[family]
        wc = float(policy["catboost_weight"])
        wg = float(policy["goal_weight"])
        ensemble[market] = wc * float(cat[market]) + wg * float(goal[market])
        disagreement[market] = abs(float(cat[market]) - float(goal[market]))

    ensemble = _renormalize(ensemble)

    # Identity is a real, empirically selected calibration result.
    calibrated = dict(ensemble)

    return {
        "ensemble_version": ENSEMBLE_VERSION,
        "calibration_version": CALIBRATION_VERSION,
        "status": "DEVELOPMENT_ONLY",
        "model_support": support,
        "ensemble_policy": ENSEMBLE_POLICY,
        "calibration_policy": CALIBRATION_POLICY,
        "ensemble": ensemble,
        "calibrated": calibrated,
        "model_disagreement": disagreement,
        "coherence": {
            "one_x_two_sum": calibrated["home_win"] + calibrated["draw"] + calibrated["away_win"],
            "btts_sum": calibrated["btts_yes"] + calibrated["btts_no"],
            "totals_sum": calibrated["over_2_5"] + calibrated["under_2_5"],
        },
        "contract_stage": {
            "goal_model_all_7": True,
            "catboost_all_7": True,
            "oos_ensemble": True,
            "calibration": True,
            "evidence_engine_all_7": "PENDING",
            "decision_all_7": "PENDING",
            "new_untouched_oos": "PENDING",
        },
    }
