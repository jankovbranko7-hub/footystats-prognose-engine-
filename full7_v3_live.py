from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence

ENGINE_VERSION = "FULL7_V3_1_LIVE_COMPAT_1.0"
MODEL_VERSION = "FULL7_V3_LIVE_LOGIT_MODEL_1.0"
DECISION_SOURCE = "FULL7_V3_1_LIVE_META"
HISTORICAL_TRAINING_ROWS = 17685
HISTORICAL_WALK_FORWARD_OOS_ROWS = 12379
NEW_PROSPECTIVE_FORWARD_OOS_VALIDATED = False

FAMILY_MARKETS = {
    "1X2": ("home_win", "draw", "away_win"),
    "TOTALS": ("over_2_5", "under_2_5"),
    "BTTS": ("btts_yes", "btts_no"),
}

# PLAY thresholds were selected only on OOS folds 1-3 and then evaluated on
# untouched later folds 4-7. OBSERVE thresholds are conservative operational
# cutoffs and are not represented as separately optimized hit-rate thresholds.
PLAY_THRESHOLDS = {"1X2": 0.71, "TOTALS": 0.70, "BTTS": 0.605}
OBSERVE_THRESHOLDS = {"1X2": 0.60, "TOTALS": 0.60, "BTTS": 0.56}
LATE_OOS_PLAY_EVIDENCE = {
    "1X2": {"n": 489, "correct": 326, "hit_rate": 326 / 489, "wilson_95_low": 0.6237278322353581},
    "TOTALS": {"n": 450, "correct": 306, "hit_rate": 306 / 450, "wilson_95_low": 0.6355319336963334},
    "BTTS": {"n": 1668, "correct": 1031, "hit_rate": 1031 / 1668, "wilson_95_low": 0.5945429764640386},
}

_BASE = Path(__file__).resolve().parent
_MODEL_DIR = _BASE / "models"
_MODEL_PATHS = {
    "1X2": _MODEL_DIR / "full7_v3_live_1x2.json",
    "TOTALS": _MODEL_DIR / "full7_v3_live_ou.json",
    "BTTS": _MODEL_DIR / "full7_v3_live_btts.json",
}

def _load_model(path: Path) -> Dict[str, Any]:
    raw = path.read_bytes()
    model = json.loads(raw.decode("utf-8"))
    if model.get("schema") != MODEL_VERSION:
        raise RuntimeError(f"V3 live model schema mismatch: {path.name}")
    model["_sha256"] = hashlib.sha256(raw).hexdigest()
    return model

_MODELS = {family: _load_model(path) for family, path in _MODEL_PATHS.items()}
MODEL_SHA256 = {family: model["_sha256"] for family, model in _MODELS.items()}
NUMERIC_FEATURES: Sequence[str] = tuple(_MODELS["1X2"]["numeric_features"])


def _finite(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _unwrap_data(value: Any) -> Any:
    if isinstance(value, dict) and "data" in value:
        return value.get("data")
    return value


def _league_name(gold: Mapping[str, Any]) -> str | None:
    namespaces = gold.get("namespaces") or {}
    league_ns = namespaces.get("league") or {}
    wrapper = league_ns.get("league") if isinstance(league_ns, dict) else None
    row = _unwrap_data(wrapper)
    if not isinstance(row, dict):
        return None
    country = str(row.get("country") or "").strip()
    name = str(row.get("db_english_name") or row.get("name") or "").strip()
    if country and name:
        return f"{country} {name}"
    return name or country or None


def _engineered(base: Mapping[str, float]) -> Dict[str, float]:
    lh = base["liga_avg_heim_vor_spiel"]
    la = base["liga_avg_aus_vor_spiel"]
    xh = base["fs_xg_prematch_heim"]
    xa = base["fs_xg_prematch_aus"]
    ph = base["fs_pre_ppg_heim"]
    pa = base["fs_pre_ppg_aus"]
    o = base["fs_o25_potential"] / 100.0
    b = base["fs_btts_potential"] / 100.0
    a = base["fs_avg_potential"]
    return {
        "league_goal_total": lh + la,
        "league_goal_diff": lh - la,
        "league_goal_absdiff": abs(lh - la),
        "fs_xg_total": xh + xa,
        "fs_xg_diff": xh - xa,
        "fs_xg_absdiff": abs(xh - xa),
        "fs_xg_min": min(xh, xa),
        "fs_xg_product": xh * xa,
        "ppg_diff": ph - pa,
        "ppg_absdiff": abs(ph - pa),
        "ppg_total": ph + pa,
        "o25_potential_frac": o,
        "btts_potential_frac": b,
        "avg_potential_copy": a,
        "potential_diff": o - b,
        "potential_absdiff": abs(o - b),
        "avg_minus_fsxg": a - (xh + xa),
        "fsxg_minus_league": (xh + xa) - (lh + la),
        "potential_product": o * b,
        "ppg_product": ph * pa,
    }


def build_live_record(gold: Mapping[str, Any], gold_features: Mapping[str, Any]) -> Dict[str, Any]:
    """Map only semantically aligned pre-match fields from the seven-file Gold layer.

    No odds, result fields, historical decisions or non-reconstructible rolling
    eight-match aggregates are accepted by this adapter.
    """
    features = gold_features.get("features") or {}
    mapping = {
        "liga_avg_heim_vor_spiel": "league_seasonAVG_home",
        "liga_avg_aus_vor_spiel": "league_seasonAVG_away",
        "liga_spiele_bisher": "league_matchesCompleted",
        "fs_xg_prematch_heim": "prematch_xg_home",
        "fs_xg_prematch_aus": "prematch_xg_away",
        "fs_o25_potential": "provider_o25_potential",
        "fs_btts_potential": "provider_btts_potential",
        "fs_avg_potential": "provider_avg_potential",
        "fs_pre_ppg_heim": "prematch_ppg_home",
        "fs_pre_ppg_aus": "prematch_ppg_away",
    }
    base: Dict[str, float] = {}
    missing = []
    for target, source in mapping.items():
        value = _finite(features.get(source))
        if value is None:
            missing.append(source)
        else:
            base[target] = value
    league = _league_name(gold)
    if not league:
        missing.append("league.country+league.name")
    if missing:
        return {"supported": False, "missing": missing, "record": None, "league": league}
    record = {**base, **_engineered(base), "liga": league}
    return {"supported": True, "missing": [], "record": record, "league": league}


def _sigmoid(value: float) -> float:
    x = max(-40.0, min(40.0, float(value)))
    return 1.0 / (1.0 + math.exp(-x))


def _score(model: Mapping[str, Any], record: Mapping[str, Any]) -> list[float]:
    numeric = []
    for name, mean, scale in zip(model["numeric_features"], model["mean"], model["scale"]):
        value = float(record[name])
        denom = float(scale) if abs(float(scale)) > 1e-12 else 1.0
        numeric.append((value - float(mean)) / denom)
    categories = list(model["league_categories"])
    league = str(record.get("liga") or "")
    one_hot = [1.0 if league == category else 0.0 for category in categories]
    vector = numeric + one_hot
    scores = []
    for coef, intercept in zip(model["coef"], model["intercept"]):
        scores.append(float(intercept) + sum(float(a) * float(b) for a, b in zip(coef, vector)))
    return scores


def _predict_family(family: str, record: Mapping[str, Any]) -> Dict[str, float]:
    model = _MODELS[family]
    scores = _score(model, record)
    classes = list(model["classes"])
    if len(classes) == 2:
        p1 = _sigmoid(scores[0])
        return {str(classes[0]): 1.0 - p1, str(classes[1]): p1}
    # SGDClassifier(log_loss) multiclass predict_proba uses one-vs-rest logistic
    # probabilities normalized across classes, not a softmax over raw scores.
    raw = [_sigmoid(value) for value in scores]
    den = sum(raw) or 1.0
    return {str(cls): value / den for cls, value in zip(classes, raw)}


def _state(confidence: float, family: str, *, league_known: bool) -> tuple[str, str]:
    if confidence >= PLAY_THRESHOLDS[family] and league_known:
        return "SPIELEN", "V3_HISTORICAL_WALK_FORWARD_PLAY_GATE"
    if confidence >= OBSERVE_THRESHOLDS[family]:
        reason = "V3_OBSERVE_BAND" if league_known else "V3_UNSEEN_LEAGUE_PLAY_CAP"
        return "BEOBACHTEN", reason
    return "AUSLASSEN", "V3_BELOW_OBSERVE_BAND"


def predict_v3_live(gold: Mapping[str, Any], gold_features: Mapping[str, Any]) -> Dict[str, Any]:
    adapter = build_live_record(gold, gold_features)
    if not adapter["supported"]:
        return {
            "ok": False,
            "supported": False,
            "engine_version": ENGINE_VERSION,
            "decision_source": DECISION_SOURCE,
            "missing_inputs": adapter["missing"],
            "markets": {},
            "families": {},
            "probabilities": {},
            "playable": [],
        }
    record = adapter["record"]
    league = str(adapter["league"])
    league_known = league in set(_MODELS["1X2"]["league_categories"])

    p1 = _predict_family("1X2", record)
    pou = _predict_family("TOTALS", record)
    pbt = _predict_family("BTTS", record)
    probabilities = {
        "home_win": p1["0"], "draw": p1["1"], "away_win": p1["2"],
        "over_2_5": pou["1"], "under_2_5": pou["0"],
        "btts_yes": pbt["1"], "btts_no": pbt["0"],
    }

    markets: Dict[str, Dict[str, Any]] = {}
    families: Dict[str, Dict[str, Any]] = {}
    playable = []
    for family, names in FAMILY_MARKETS.items():
        selected = max(names, key=lambda name: probabilities[name])
        confidence = float(probabilities[selected])
        state, reason = _state(confidence, family, league_known=league_known)
        families[family] = {
            "selected_market": selected,
            "probability": confidence,
            "decision": state,
            "decision_reason": reason,
            "play_threshold": PLAY_THRESHOLDS[family],
            "observe_threshold": OBSERVE_THRESHOLDS[family],
            "late_oos_play_evidence": dict(LATE_OOS_PLAY_EVIDENCE[family]),
        }
        for name in names:
            selected_here = name == selected
            final_state = state if selected_here else "AUSLASSEN"
            final_reason = reason if selected_here else "COHERENCE_NOT_SELECTED"
            card = {
                "market": name,
                "family": family,
                "selected_in_family": selected_here,
                "probability": float(probabilities[name]),
                "raw_reliability_score": float(probabilities[name]),
                "raw_decision": final_state,
                "raw_decision_reason": final_reason,
                "reliability_score": float(probabilities[name]),
                "decision": final_state,
                "decision_reason": final_reason,
                "sample_security": "HISTORICAL_WALK_FORWARD",
                "data_quality_support": True,
            }
            markets[name] = card
            if selected_here and state == "SPIELEN":
                playable.append({
                    "market": name,
                    "family": family,
                    "probability": float(probabilities[name]),
                    "decision": state,
                    "reason": reason,
                })

    return {
        "ok": True,
        "supported": True,
        "engine_version": ENGINE_VERSION,
        "decision_source": DECISION_SOURCE,
        "league": league,
        "league_known_in_training": league_known,
        "probabilities": probabilities,
        "families": families,
        "markets": markets,
        "playable": playable,
        "model_sha256": dict(MODEL_SHA256),
        "validation_provenance": {
            "training_rows": HISTORICAL_TRAINING_ROWS,
            "historical_walk_forward_oos_rows": HISTORICAL_WALK_FORWARD_OOS_ROWS,
            "new_prospective_forward_oos_validated": NEW_PROSPECTIVE_FORWARD_OOS_VALIDATED,
            "play_threshold_selection": "OOS_FOLDS_1_TO_3_ONLY",
            "play_threshold_evaluation": "LATER_OOS_FOLDS_4_TO_7",
        },
        "feature_policy": {
            "odds_used": False,
            "postmatch_fields_used": False,
            "historical_8_game_aggregates_used": False,
            "source": "SEVEN_FILE_GOLD_PREMATCH_ONLY",
        },
    }
