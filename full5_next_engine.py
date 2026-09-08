"""Validated FULL-5 NEXT decision layer for the V0.4.3 FULL-5 core.

The probability core is intentionally unchanged: 40 features, alpha=3.0,
Dixon-Coles rho=-0.25 and the established V0.4.2 fallback.  This module only
applies the chronologically locked six-market evidence gate.
"""
from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Set


VERSION = "FULL-5-NEXT-1.0.0"
CORE_VERSION = "0.4.3"
MARKET_KEYS = (
    "home_win", "away_win", "btts_yes", "btts_no", "over_2_5", "under_2_5"
)
SOURCE_TYPES = ("match", "league", "form", "table", "player")
PLAY_PROBABILITY = 0.60
OBSERVE_PROBABILITY = 0.50
MIN_CONFIRMING_BLOCKS = 3
MAX_COUNTER_BLOCKS = 0
MIN_SAMPLE_QUALITY = 0.40
TARGET_MATCH_BLOCKLIST = {
    "homeGoalCount", "awayGoalCount", "totalGoalCount", "overallGoalCount",
    "HTGoalCount", "GoalCount_2hg", "homeGoals", "awayGoals",
    "homeGoals_timings", "awayGoals_timings", "ht_goals_team_a", "ht_goals_team_b",
    "goals_2hg_team_a", "goals_2hg_team_b", "team_a_goal_details", "team_b_goal_details",
    "team_a_penalty_goals", "team_b_penalty_goals", "team_a_0_10_min_goals",
    "team_b_0_10_min_goals", "team_a_shots", "team_b_shots",
    "team_a_shotsOffTarget", "team_b_shotsOffTarget", "team_a_shotsOnTarget",
    "team_b_shotsOnTarget", "team_a_corners", "team_b_corners", "team_a_fh_corners",
    "team_b_fh_corners", "team_a_2h_corners", "team_b_2h_corners", "corner_fh_count",
    "corner_2h_count", "totalCornerCount", "team_a_possession", "team_b_possession",
    "team_a_cards_num", "team_b_cards_num", "team_a_fh_cards", "team_b_fh_cards",
    "team_a_2h_cards", "team_b_2h_cards", "team_a_yellow_cards", "team_b_yellow_cards",
    "team_a_red_cards", "team_b_red_cards", "team_a_xg", "team_b_xg", "total_xg",
    "winningTeam", "result", "gpt_en", "gpt_int",
}


def _number(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
        return out if math.isfinite(out) else default
    except (TypeError, ValueError):
        return default


def probability_sums_valid(probabilities: Mapping[str, Any], tolerance: float = 1e-6) -> bool:
    """Validate all V0.4.3 probability families without modifying them."""
    required = ("home_win", "draw", "away_win", "btts_yes", "btts_no", "over_2_5", "under_2_5")
    try:
        values = {key: float(probabilities[key]) for key in required}
    except (KeyError, TypeError, ValueError):
        return False
    if any(not math.isfinite(value) or not 0 <= value <= 1 for value in values.values()):
        return False
    return all((
        abs(values["home_win"] + values["draw"] + values["away_win"] - 1) <= tolerance,
        abs(values["btts_yes"] + values["btts_no"] - 1) <= tolerance,
        abs(values["over_2_5"] + values["under_2_5"] - 1) <= tolerance,
    ))


def source_types(parsed_files: Sequence[Mapping[str, Any]]) -> Set[str]:
    """Identify the five required files from their production filenames."""
    found: Set[str] = set()
    for item in parsed_files:
        name = str(item.get("name") or item.get("filename") or "").lower()
        for source in SOURCE_TYPES:
            if f"{source}daten" in name or name.endswith(f"{source}.json"):
                found.add(source)
    return found


def _sanitize_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _sanitize_value(item) for key, item in value.items()
                if key not in TARGET_MATCH_BLOCKLIST}
    if isinstance(value, list):
        return [_sanitize_value(item) for item in value]
    return value


def sanitize_parsed_files(parsed_files: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """Remove target-match live/post fields before the V0.4.3 core sees them."""
    clean: List[Dict[str, Any]] = []
    for item in parsed_files:
        copied = dict(item)
        name = str(item.get("name") or item.get("filename") or "").lower()
        copied["data"] = _sanitize_value(item.get("data")) if "matchdaten" in name else item.get("data")
        clean.append(copied)
    return clean


def blocked_target_fields(parsed_files: Sequence[Mapping[str, Any]]) -> List[str]:
    found: Set[str] = set()
    def visit(value: Any) -> None:
        if isinstance(value, Mapping):
            for key, item in value.items():
                if key in TARGET_MATCH_BLOCKLIST:
                    found.add(key)
                else:
                    visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)
    for item in parsed_files:
        name = str(item.get("name") or item.get("filename") or "").lower()
        if "matchdaten" in name:
            visit(item.get("data"))
    return sorted(found)


def sample_quality(result: Mapping[str, Any]) -> float:
    """Locked 0..1 sample score used in the validated decision gate."""
    samples = result.get("samples") or {}
    venue_n = min(_number(samples.get("home_venue")), _number(samples.get("away_venue")))
    supplemental = ((result.get("diagnostics") or {}).get("supplemental_inputs") or {})
    player = ((supplemental.get("coverage") or {}).get("player") or {})
    home_depth = _number((player.get("home") or {}).get("players_found"))
    away_depth = _number((player.get("away") or {}).get("players_found"))
    player_depth = min(home_depth, away_depth)
    return 0.6 * min(1.0, venue_n / 10.0) + 0.4 * min(1.0, player_depth / 22.0)


def _higher_probability_reason(result: Mapping[str, Any], selected_key: str, selected_p: float) -> str:
    alternatives = []
    for market in result.get("markets") or []:
        key = str(market.get("key") or "")
        if key in MARKET_KEYS:
            alternatives.append((key, str(market.get("label") or key), _number(market.get("probability_pct")) / 100.0))
    higher = sorted((item for item in alternatives if item[2] > selected_p + 1e-12), key=lambda item: item[2], reverse=True)
    if not higher:
        return "Kein anderer spielbarer Markt besitzt eine höhere Rohwahrscheinlichkeit."
    key, label, probability = higher[0]
    return (
        f"{label} ({probability:.1%}) besitzt die höhere Rohwahrscheinlichkeit, "
        "verlor aber den normalisierten Markt-Family-/Evidenzvergleich."
    )


def apply_full5_next(result: Dict[str, Any], parsed_files: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """Attach the locked final decision while preserving every core probability."""
    if not isinstance(result, dict) or not result.get("ok"):
        return result
    probabilities = result.get("probabilities") or {}
    if not probability_sums_valid(probabilities):
        raise ValueError("V0.4.3 probability sums are invalid")

    strongest = result.get("strongest_market") or {}
    market_key = str(strongest.get("key") or "")
    if market_key not in MARKET_KEYS:
        raise ValueError("V0.4.3 returned no valid strongest playable market")
    probability = float(probabilities[market_key])

    diagnostics = result.get("diagnostics") or {}
    protocol = diagnostics.get("elite_protocol") or {}
    gates = protocol.get("gates") or {}
    confirming = list(protocol.get("confirming_blocks") or [])
    counters = list(protocol.get("counter_blocks") or [])
    strict = ((gates.get("pre_match_integrity") or {}).get("strict_pre_match") is True)
    robust = diagnostics.get("robustness_status") == "BESTANDEN"
    found_sources = source_types(parsed_files)
    all_five = found_sources == set(SOURCE_TYPES)
    audit_valid = ((result.get("audit") or {}).get("valid") is True)
    data_quality_gate = all_five and audit_valid
    quality = sample_quality(result)
    data_quality = str(diagnostics.get("data_quality") or "UNBEKANNT")
    sample_security = str(diagnostics.get("sample_security") or "UNBEKANNT")

    play = all((
        strict,
        data_quality_gate,
        probability >= PLAY_PROBABILITY,
        len(confirming) >= MIN_CONFIRMING_BLOCKS,
        len(counters) <= MAX_COUNTER_BLOCKS,
        robust,
        quality >= MIN_SAMPLE_QUALITY,
    ))
    observe = all((
        strict,
        data_quality_gate,
        probability >= OBSERVE_PROBABILITY,
        len(confirming) >= 2,
        len(counters) <= 1,
    ))
    decision = "SPIELEN" if play else "BEOBACHTEN" if observe else "AUSLASSEN / KEIN BET"

    positive_reasons: List[str] = [
        "Der Markt gewann den normalisierten Vergleich aller sechs spielbaren Märkte.",
        f"V0.4.3-Core-Wahrscheinlichkeit: {probability:.1%}.",
    ]
    if confirming:
        positive_reasons.append(f"Bestätigende Signalblöcke ({len(confirming)}): {', '.join(confirming)}.")
    if robust:
        positive_reasons.append("Robustheitsprüfung bestanden.")
    if all_five:
        positive_reasons.append("Alle fünf FootyStats-Dateien wurden erkannt.")

    counterarguments = list(counters)
    if not strict:
        counterarguments.append("Snapshot liegt nicht strikt vor Kickoff.")
    if not all_five:
        missing = [name for name in SOURCE_TYPES if name not in found_sources]
        counterarguments.append("Fehlende Datenquelle(n): " + ", ".join(missing) + ".")
    if not audit_valid:
        counterarguments.append("Datenqualitäts-Audit nicht bestanden.")
    if probability < PLAY_PROBABILITY:
        counterarguments.append(f"Probability Gate für SPIELEN nicht erreicht ({probability:.1%} < {PLAY_PROBABILITY:.0%}).")
    if len(confirming) < MIN_CONFIRMING_BLOCKS:
        counterarguments.append(
            f"Nur {len(confirming)} bestätigende Blöcke; für SPIELEN sind {MIN_CONFIRMING_BLOCKS} erforderlich."
        )
    if not robust:
        counterarguments.append("Robustheitsprüfung nicht bestanden.")
    if quality < MIN_SAMPLE_QUALITY:
        counterarguments.append(f"Sample Quality zu niedrig ({quality:.2f} < {MIN_SAMPLE_QUALITY:.2f}).")

    full5 = ((((result.get("expected_goals") or {}).get("hybrid_model") or {}).get("full5")) or {})
    next_result = {
        "version": VERSION,
        "validation_reference": "247 strict+verified matches; development=160; chronological OOS=87",
        "oos_play_result": {"hits": 23, "plays": 33, "hit_rate": 0.696969696969697},
        "probability_core": "V0.4.3 FULL-5",
        "probability_core_changed": False,
        "feature_count": 40,
        "alpha": 3.0,
        "dixon_coles_rho": -0.25,
        "elite_lambda": False,
        "new_feature_blocks": [],
        "selected_market": market_key,
        "selected_market_label": strongest.get("label") or market_key,
        "probability": probability,
        "probability_pct": round(probability * 100, 1),
        "decision": decision,
        "positive_reasons": positive_reasons,
        "counterarguments": counterarguments,
        "signal_agreement": len(confirming),
        "signal_conflict": len(counters),
        "confirming_blocks": confirming,
        "counter_blocks": counters,
        "strict_pre_match": strict,
        "all_five_sources": all_five,
        "data_quality_gate": data_quality_gate,
        "audit_valid": audit_valid,
        "sources_found": sorted(found_sources),
        "data_quality": data_quality,
        "robustness": "BESTANDEN" if robust else "NICHT BESTANDEN",
        "sample_quality": round(quality, 6),
        "sample_security": sample_security,
        "full5_status": "AKTIV" if full5.get("applied") is True else "FALLBACK AUF V0.4.2",
        "why_this_market": (
            "Der Markt gewann den normalisierten Vergleich aller sechs Märkte und besitzt "
            "die stärkste bestätigte Evidenzfamilie."
        ),
        "why_not_higher_probability_market": _higher_probability_reason(result, market_key, probability),
        "locked_parameters": {
            "play_probability": PLAY_PROBABILITY,
            "observe_probability": OBSERVE_PROBABILITY,
            "minimum_confirming_blocks": MIN_CONFIRMING_BLOCKS,
            "maximum_counter_blocks": MAX_COUNTER_BLOCKS,
            "robustness_required": True,
            "all_five_sources_required": True,
            "minimum_sample_quality": MIN_SAMPLE_QUALITY,
        },
    }
    result["full5_next"] = next_result
    result["decision"] = decision
    protocol["final_decision"] = decision
    protocol["decision_reasons"] = positive_reasons + counterarguments
    protocol["full5_next"] = next_result
    diagnostics["elite_protocol"] = protocol
    diagnostics["full5_next"] = next_result
    result["diagnostics"] = diagnostics
    result["model_version"] = VERSION
    method = dict(result.get("method") or {})
    method.update({
        "release_status": "production",
        "probability_core": "V0.4.3 FULL-5 unchanged",
        "decision_engine": VERSION,
        "oos_reoptimized": False,
        "file_6": False,
        "file_7": False,
    })
    result["method"] = method
    return result
