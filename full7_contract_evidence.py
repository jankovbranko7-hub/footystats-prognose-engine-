from __future__ import annotations

import gzip
import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple

from full7_contract_engine import CORE_FEATURES, MARKETS
from full7_contract_ensemble import MARKET_FAMILY, ensemble_and_calibrate
from full7_signal_groups import audit_signal_groups

EVIDENCE_ENGINE_VERSION = "FULL7_CONTRACT_EVIDENCE_1.0"
_REFERENCE_SHA256 = "1c5bc5de261d9ddf267d22d98fd8df8d1ce71279f838d90a4c3581a5802f1b91"
_REFERENCE_PATH = Path(__file__).resolve().parent / "models" / "full7_evidence_reference.json.gz"

PLAYER_DEPTH_TOKENS = (
    "players_found", "active_players", "active_player_share", "player_minutes",
    "active_minutes", "goalkeeper_count", "defender_count", "midfielder_count",
    "forward_count", "goalkeeper_minutes", "defender_minutes",
    "midfielder_minutes", "forward_minutes",
)

_GROUP_REFERENCE_KEY = {
    "VENUE_STRENGTH": "VENUE",
}

_GROUP_CLUSTER = {
    "PLAYER_DEPTH": "player",
    "PLAYER_QUALITY": "player",
    "PLAYER_CONCENTRATION": "player",
}

_SAMPLE_KEYS = {
    "EXPECTED_GOALS_XGA": (
        "home_overall_matches", "away_overall_matches",
        "home_home_matches", "away_away_matches",
    ),
    "GOALS_DEFENCE": (
        "home_overall_matches", "away_overall_matches",
        "home_home_matches", "away_away_matches",
    ),
    "VENUE_STRENGTH": ("home_home_matches", "away_away_matches"),
    "CURRENT_FORM": ("home_last5_home_matches", "away_last5_away_matches"),
    "TABLE_STRENGTH": ("home_table_overall_matches", "away_table_overall_matches"),
    "SHOTS_CHANCE_CREATION": (
        "home_overall_matches", "away_overall_matches",
        "home_home_matches", "away_away_matches",
    ),
    "FIRST_SECOND_HALF": (
        "home_overall_matches", "away_overall_matches",
        "home_home_matches", "away_away_matches",
    ),
    "BTTS_OU_PROFILE": (
        "home_overall_matches", "away_overall_matches",
        "home_home_matches", "away_away_matches",
    ),
    "PLAYER_DEPTH": (
        "home_players_found", "away_players_found",
        "home_active_player_share", "away_active_player_share",
    ),
    "PLAYER_QUALITY": (
        "home_players_found", "away_players_found",
        "home_active_player_share", "away_active_player_share",
    ),
    "PLAYER_CONCENTRATION": (
        "home_players_found", "away_players_found",
        "home_active_player_share", "away_active_player_share",
    ),
    "H2H_SECONDARY": ("h2h_matches",),
}


def _load_reference() -> Dict[str, Any]:
    raw = _REFERENCE_PATH.read_bytes()
    if hashlib.sha256(raw).hexdigest() != _REFERENCE_SHA256:
        raise RuntimeError("FULL-7 evidence reference SHA-256 mismatch")
    return json.loads(gzip.decompress(raw).decode("utf-8"))


REFERENCE = _load_reference()


def _finite(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def contract_evidence_group(name: str) -> str:
    """Deterministic feature-to-evidence mapping used by the reference and runtime."""
    low = name.lower()
    if low.startswith("h2h_"):
        return "H2H_SECONDARY"
    if low.startswith("referee_"):
        return "REFEREE"
    if "manager_" in low:
        return "MANAGER"
    if any(token in low for token in (
        "bttspercentageht", "cspercentageht", "ftspercentageht",
        "scoredavght", "concededavght", "avght",
        "2hg", "_ht", "first_half", "second_half",
    )):
        return "FIRST_SECOND_HALF"
    if "xg" in low:
        return "EXPECTED_GOALS_XGA"
    if "shot" in low or "conversion" in low:
        return "SHOTS_CHANCE_CREATION"
    if any(token in low for token in (
        "btts", "over25", "under25", "seasoncs", "seasonfts",
        "clean_sheet", "failed_to_score",
    )):
        return "BTTS_OU_PROFILE"
    if any(token in low for token in ("scoredavg", "concededavg", "goal_difference")):
        return "GOALS_DEFENCE"
    if low.startswith("table_") or "_table_" in low:
        return "TABLE_STRENGTH"
    if "form_" in low or "last5_" in low or "last6_" in low or "last10_" in low:
        return "CURRENT_FORM"
    if any(token in low for token in PLAYER_DEPTH_TOKENS):
        return "PLAYER_DEPTH"
    if any(token in low for token in ("top1_", "top2_", "top3_")) and "share" in low:
        return "PLAYER_CONCENTRATION"
    if any(token in low for token in ("goals_per90", "assists_per90", "involvement_per90")):
        return "PLAYER_QUALITY"
    if (
        low.startswith("home_") or low.startswith("away_") or low.startswith("player_")
    ) and any(token in low for token in (
        "player", "goalkeeper", "defender", "midfielder", "forward",
    )):
        return "PLAYER_QUALITY"
    if low.startswith("league_derived_") or low.startswith("league_"):
        return "LEAGUE_CONTEXT"
    if "ppg" in low:
        return "VENUE_STRENGTH"
    return "MATCH_CONTEXT"


CORE_GROUP_FEATURES: Dict[str, Tuple[str, ...]] = {}
_tmp: Dict[str, List[str]] = defaultdict(list)
for _name in CORE_FEATURES:
    _tmp[contract_evidence_group(_name)].append(_name)
CORE_GROUP_FEATURES = {key: tuple(value) for key, value in sorted(_tmp.items())}

CORE_CLUSTER_FEATURES: Dict[str, Tuple[str, ...]] = {}
_cluster_tmp: Dict[str, List[str]] = defaultdict(list)
for _group, _names in CORE_GROUP_FEATURES.items():
    _cluster = _GROUP_CLUSTER.get(_group, _group.lower())
    _cluster_tmp[_cluster].extend(_names)
CORE_CLUSTER_FEATURES = {key: tuple(value) for key, value in sorted(_cluster_tmp.items())}


def _reference_group(group: str) -> Dict[str, Any] | None:
    key = _GROUP_REFERENCE_KEY.get(group, group)
    return (REFERENCE.get("groups") or {}).get(key)


def _strength_label(group: str, market: str, delta: float) -> str:
    ref = _reference_group(group)
    if ref is None:
        return "UNVALIDATED"
    market_ref = (ref.get("markets") or {}).get(market)
    if not market_ref:
        return "UNVALIDATED"
    magnitude = abs(delta)
    q25 = float(market_ref["abs_delta_q25"])
    q50 = float(market_ref["abs_delta_q50"])
    q75 = float(market_ref["abs_delta_q75"])

    if magnitude == 0.0 or magnitude < q25:
        return "NEUTRAL"
    if magnitude < q50:
        strength = "WEAK"
    elif magnitude < q75:
        strength = "MODERATE"
    else:
        strength = "STRONG"
    return f"{strength}_{'CONFIRM' if delta > 0 else 'COUNTER'}"


def _cluster_strength_label(cluster: str, market: str, delta: float) -> str:
    ref = (REFERENCE.get("clusters") or {}).get(cluster)
    if ref is None:
        return "UNVALIDATED"
    market_ref = (ref.get("markets") or {}).get(market)
    if not market_ref:
        return "UNVALIDATED"
    magnitude = abs(delta)
    q25 = float(market_ref["abs_delta_q25"])
    q50 = float(market_ref["abs_delta_q50"])
    q75 = float(market_ref["abs_delta_q75"])
    if magnitude == 0.0 or magnitude < q25:
        return "NEUTRAL"
    if magnitude < q50:
        strength = "WEAK"
    elif magnitude < q75:
        strength = "MODERATE"
    else:
        strength = "STRONG"
    return f"{strength}_{'CONFIRM' if delta > 0 else 'COUNTER'}"


def _removed_gold(gold_features: Mapping[str, Any], names: Iterable[str]) -> Dict[str, Any]:
    cloned = dict(gold_features)
    features = dict(gold_features.get("features") or {})
    for name in names:
        features[name] = None
    cloned["features"] = features
    return cloned


def _preferred_market(probabilities: Mapping[str, float], family: str) -> str:
    if family == "1X2":
        return max(("home_win", "draw", "away_win"), key=lambda key: probabilities[key])
    if family == "BTTS":
        return "btts_yes" if probabilities["btts_yes"] >= probabilities["btts_no"] else "btts_no"
    if family == "TOTALS":
        return "over_2_5" if probabilities["over_2_5"] >= probabilities["under_2_5"] else "under_2_5"
    raise ValueError(family)


def _sample_band(key: str, value: float | None) -> Dict[str, Any]:
    ref = (REFERENCE.get("sample_exposure") or {}).get(key)
    if value is None:
        return {"key": key, "value": None, "band": "UNAVAILABLE"}
    if ref is None:
        return {"key": key, "value": value, "band": "UNVALIDATED"}
    q25 = float(ref["q25"])
    q75 = float(ref["q75"])
    if value < q25:
        band = "LOW"
    elif value < q75:
        band = "MEDIUM"
    else:
        band = "HIGH"
    return {
        "key": key,
        "value": value,
        "band": band,
        "reference_q25": q25,
        "reference_q75": q75,
    }


def _group_sample_security(group: str, features: Mapping[str, Any]) -> Dict[str, Any]:
    if group in {"REFEREE", "MANAGER"}:
        return {
            "status": "UNVALIDATED_HISTORICAL_SAMPLE",
            "metrics": [],
            "decision_weight_validated": False,
        }
    keys = _SAMPLE_KEYS.get(group)
    if not keys:
        return {"status": "NOT_SAMPLE_LIMITED", "metrics": []}

    metrics = [_sample_band(key, _finite(features.get(key))) for key in keys]
    rank = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
    known = [item["band"] for item in metrics if item["band"] in rank]
    status = min(known, key=lambda value: rank[value]) if known else "UNKNOWN"
    return {"status": status, "metrics": metrics}


def _observational_h2h(gold_features: Mapping[str, Any]) -> Dict[str, Any]:
    features = gold_features.get("features") or {}
    sample = _finite(features.get("h2h_matches"))
    if sample is None or sample <= 0:
        return {
            "available": False,
            "status": "UNAVAILABLE",
            "decision_weight_validated": False,
            "markets": {},
        }

    home = _finite(features.get("h2h_home_team_win_pct"))
    away = _finite(features.get("h2h_away_team_win_pct"))
    btts = _finite(features.get("h2h_bttsPercentage"))
    over = _finite(features.get("h2h_over25Percentage"))
    draw = None
    if home is not None and away is not None:
        draw = max(0.0, 100.0 - home - away)

    market_scores = {
        "home_win": home,
        "draw": draw,
        "away_win": away,
        "btts_yes": btts,
        "btts_no": None if btts is None else 100.0 - btts,
        "over_2_5": over,
        "under_2_5": None if over is None else 100.0 - over,
    }
    directions: Dict[str, str] = {}

    result_values = {k: v for k, v in market_scores.items() if k in {"home_win","draw","away_win"} and v is not None}
    if len(result_values) == 3:
        high = max(result_values, key=result_values.get)
        low = min(result_values, key=result_values.get)
        for market in ("home_win", "draw", "away_win"):
            directions[market] = (
                "DIRECTIONAL_CONFIRM_UNVALIDATED" if market == high
                else "DIRECTIONAL_COUNTER_UNVALIDATED" if market == low
                else "DIRECTIONAL_NEUTRAL_UNVALIDATED"
            )
    for yes, no in (("btts_yes", "btts_no"), ("over_2_5", "under_2_5")):
        yv = market_scores[yes]
        nv = market_scores[no]
        if yv is None or nv is None:
            continue
        if abs(yv - nv) < 1e-12:
            directions[yes] = directions[no] = "DIRECTIONAL_NEUTRAL_UNVALIDATED"
        elif yv > nv:
            directions[yes] = "DIRECTIONAL_CONFIRM_UNVALIDATED"
            directions[no] = "DIRECTIONAL_COUNTER_UNVALIDATED"
        else:
            directions[yes] = "DIRECTIONAL_COUNTER_UNVALIDATED"
            directions[no] = "DIRECTIONAL_CONFIRM_UNVALIDATED"

    return {
        "available": True,
        "status": "SECONDARY_EVIDENCE_AVAILABLE_NOT_INCREMENTALLY_VALIDATED",
        "decision_weight_validated": False,
        "sample_security": _group_sample_security("H2H_SECONDARY", features),
        "latest_match_age_days": _finite(features.get("h2h_latest_match_age_days")),
        "market_scores_pct": market_scores,
        "markets": directions,
    }


def _observational_referee_manager(
    group: str,
    audit: Mapping[str, Any],
    gold_features: Mapping[str, Any],
) -> Dict[str, Any]:
    row = next((item for item in audit.get("groups", []) if item.get("group") == group), None)
    available = bool(row and row.get("available"))
    return {
        "available": available,
        "status": (
            "VALID_INPUT_EVIDENCE_AVAILABLE_WITH_SAMPLE_CAUTION"
            if available else "UNAVAILABLE"
        ),
        "feature_count": int((row or {}).get("feature_count") or 0),
        "decision_weight_validated": False,
        "sample_security": _group_sample_security(group, gold_features.get("features") or {}),
        "reason": (
            "Strict historical FULL-7 outcome evidence is not yet sufficient to assign a learned decision weight."
            if available else "No valid pre-match block available for this match."
        ),
    }


def build_evidence_engine(
    gold_features: Mapping[str, Any],
    *,
    validation_quality: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    base = ensemble_and_calibrate(gold_features)
    calibrated = base["calibrated"]
    features = gold_features.get("features") or {}
    audit = audit_signal_groups(dict(gold_features))

    group_results: Dict[str, Dict[str, Any]] = {}
    group_removed_probabilities: Dict[str, Dict[str, float]] = {}

    for group, names in CORE_GROUP_FEATURES.items():
        available = [name for name in names if _finite(features.get(name)) is not None]
        if not available:
            group_results[group] = {
                "available": False,
                "core_feature_count": len(names),
                "available_feature_count": 0,
                "sample_security": _group_sample_security(group, features),
                "markets": {market: {"status": "UNAVAILABLE"} for market in MARKETS},
            }
            continue

        removed = ensemble_and_calibrate(_removed_gold(gold_features, names))["calibrated"]
        group_removed_probabilities[group] = removed
        market_rows: Dict[str, Any] = {}
        for market in MARKETS:
            delta = float(calibrated[market]) - float(removed[market])
            market_rows[market] = {
                "status": _strength_label(group, market, delta),
                "probability": float(calibrated[market]),
                "probability_without_group": float(removed[market]),
                "delta": delta,
                "absolute_delta": abs(delta),
            }
        group_results[group] = {
            "available": True,
            "core_feature_count": len(names),
            "available_feature_count": len(available),
            "feature_coverage": len(available) / len(names),
            "cluster": _GROUP_CLUSTER.get(group, group.lower()),
            "sample_security": _group_sample_security(group, features),
            "markets": market_rows,
        }

    cluster_results: Dict[str, Dict[str, Any]] = {}
    for cluster, names in CORE_CLUSTER_FEATURES.items():
        available = [name for name in names if _finite(features.get(name)) is not None]
        if not available:
            continue
        removed = ensemble_and_calibrate(_removed_gold(gold_features, names))["calibrated"]
        base_pref = {
            family: _preferred_market(calibrated, family)
            for family in ("1X2", "BTTS", "TOTALS")
        }
        removed_pref = {
            family: _preferred_market(removed, family)
            for family in ("1X2", "BTTS", "TOTALS")
        }
        market_rows: Dict[str, Any] = {}
        for market in MARKETS:
            delta = float(calibrated[market]) - float(removed[market])
            family = MARKET_FAMILY[market]
            market_rows[market] = {
                "status": _cluster_strength_label(cluster, market, delta),
                "delta": delta,
                "absolute_delta": abs(delta),
                "family_preference_before": base_pref[family],
                "family_preference_after_removal": removed_pref[family],
                "family_preference_flip": base_pref[family] != removed_pref[family],
            }
        cluster_results[cluster] = {
            "available": True,
            "core_feature_count": len(names),
            "available_feature_count": len(available),
            "feature_coverage": len(available) / len(names),
            "markets": market_rows,
        }

    independent_by_market: Dict[str, Any] = {}
    severity_rank = {"WEAK": 1, "MODERATE": 2, "STRONG": 3}
    for market in MARKETS:
        confirm = []
        counter = []
        neutral = []
        flips = []
        moves = []
        for cluster, row in cluster_results.items():
            evidence = row["markets"][market]
            status = evidence["status"]
            moves.append(evidence["absolute_delta"])
            if evidence["family_preference_flip"]:
                flips.append(cluster)
            if status == "NEUTRAL" or status == "UNVALIDATED":
                neutral.append(cluster)
            elif status.endswith("_CONFIRM"):
                confirm.append({"cluster": cluster, "status": status})
            elif status.endswith("_COUNTER"):
                counter.append({"cluster": cluster, "status": status})

        strongest_counter = None
        if counter:
            strongest_counter = max(
                counter,
                key=lambda item: severity_rank.get(item["status"].split("_", 1)[0], 0),
            )

        independent_by_market[market] = {
            "confirm_count": len(confirm),
            "counter_count": len(counter),
            "neutral_count": len(neutral),
            "confirmations": confirm,
            "counters": counter,
            "strongest_counter": strongest_counter,
            "counterargument_test": {
                "status": "MEASURED_EMPIRICAL_GATE_ACTIVE",
                "counter_count": len(counter),
                "strongest_counter": strongest_counter,
            },
            "robustness": {
                "status": "MEASURED_EMPIRICAL_GATE_ACTIVE",
                "family_preference_flip_count": len(flips),
                "flip_clusters": flips,
                "max_cluster_probability_move": max(moves) if moves else 0.0,
            },
        }

    core_values = [_finite(features.get(name)) for name in CORE_FEATURES]
    finite_count = sum(value is not None for value in core_values)
    core_coverage = finite_count / len(CORE_FEATURES)

    outside_q01_q99 = []
    outside_min_max = []
    ranges = REFERENCE.get("feature_ranges") or {}
    for name, value in zip(CORE_FEATURES, core_values):
        if value is None:
            continue
        ref = ranges.get(name)
        if not ref:
            continue
        if value < float(ref["q01"]) or value > float(ref["q99"]):
            outside_q01_q99.append(name)
        if value < float(ref["min"]) or value > float(ref["max"]):
            outside_min_max.append(name)

    disagreement = base["model_disagreement"]
    disagreement_flags: Dict[str, Any] = {}
    for market in MARKETS:
        ref = (REFERENCE.get("model_disagreement") or {}).get(market) or {}
        q95 = _finite(ref.get("q95"))
        value = float(disagreement[market])
        disagreement_flags[market] = {
            "absolute_difference": value,
            "reference_q95": q95,
            "above_development_q95": bool(q95 is not None and value > q95),
        }

    coverage_ref = REFERENCE.get("coverage") or {}
    if core_coverage < float(coverage_ref.get("min", 0.0)):
        coverage_status = "BELOW_DEVELOPMENT_MIN"
    elif core_coverage < float(coverage_ref.get("q05", 0.0)):
        coverage_status = "BELOW_DEVELOPMENT_Q05"
    elif core_coverage < float(coverage_ref.get("q25", 0.0)):
        coverage_status = "BELOW_DEVELOPMENT_Q25"
    else:
        coverage_status = "WITHIN_DEVELOPMENT_CORE_RANGE"

    h2h = _observational_h2h(gold_features)
    referee = _observational_referee_manager("REFEREE", audit, gold_features)
    manager = _observational_referee_manager("MANAGER", audit, gold_features)

    return {
        "evidence_engine_version": EVIDENCE_ENGINE_VERSION,
        "status": "DEVELOPMENT_ONLY",
        "probability_layer": base,
        "signal_groups": group_results,
        "independent_clusters": cluster_results,
        "market_evidence": independent_by_market,
        "secondary_context": {
            "H2H": h2h,
            "REFEREE": referee,
            "MANAGER": manager,
        },
        "sample_security": {
            "groups": {
                group: row.get("sample_security")
                for group, row in group_results.items()
            },
            "H2H": h2h.get("sample_security"),
            "REFEREE": referee.get("sample_security"),
            "MANAGER": manager.get("sample_security"),
        },
        "data_quality": {
            "core_feature_count": len(CORE_FEATURES),
            "finite_core_feature_count": finite_count,
            "core_feature_coverage": core_coverage,
            "coverage_status": coverage_status,
            "outside_development_q01_q99_count": len(outside_q01_q99),
            "outside_development_q01_q99_features": outside_q01_q99,
            "outside_development_min_max_count": len(outside_min_max),
            "outside_development_min_max_features": outside_min_max,
            "available_signal_group_count": audit.get("available_group_count"),
            "available_evidence_cluster_count": audit.get("available_evidence_cluster_count"),
            "forbidden_odds_feature_count": audit.get("forbidden_odds_feature_count"),
            "validation_quality": dict(validation_quality or {}),
            "score": None,
            "score_status": "EMPIRICAL_SUPPORT_CHECK_ACTIVE",
        },
        "coherence_ood": {
            "probability_sums": base.get("coherence"),
            "probability_sums_pass": all(
                abs(float(value) - 1.0) <= 1e-7
                for value in (base.get("coherence") or {}).values()
            ),
            "model_disagreement": disagreement_flags,
            "high_disagreement_market_count": sum(
                1 for row in disagreement_flags.values()
                if row["above_development_q95"]
            ),
            "ood_feature_fraction_q01_q99": (
                len(outside_q01_q99) / finite_count if finite_count else 1.0
            ),
            "ood_feature_fraction_min_max": (
                len(outside_min_max) / finite_count if finite_count else 1.0
            ),
            "status": "MEASURED_EMPIRICAL_GATE_ACTIVE",
        },
        "decision_layer": {
            "status": "DELEGATED_TO_FULL7_CONTRACT_DECISION",
            "markets": {
                market: "DECISION_COMPUTED_IN_DECISION_ENGINE"
                for market in MARKETS
            },
            "reason": "Evidence measurements feed the temporally learned FULL7_CONTRACT_DECISION_GATE_1.0; final market states are emitted by full7_contract_decision.",
        },
    }
