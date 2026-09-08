"""Trained FULL-5 NEXT market-ranking and abstention layer.

The probability core is intentionally unchanged: 40 features, alpha=3.0,
Dixon-Coles rho=-0.25 and the established V0.4.2 fallback.  This module only
applies the chronologically trained six-market ranker and reliability policy.
Only data-integrity checks may override the trained final decision.
"""
from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Set

import full5_next_ai as learned_ai


VERSION = "FULL-5-NEXT-AI-2.1.0"
CORE_VERSION = "0.4.3"
MARKET_KEYS = (
    "home_win", "away_win", "btts_yes", "btts_no", "over_2_5", "under_2_5"
)
SOURCE_TYPES = ("match", "league", "form", "table", "player")
APPLICABLE_EVIDENCE_BLOCKS = {
    "home_win": ("UNDERLYING", "MATCH", "FORM", "TABLE"),
    "away_win": ("UNDERLYING", "MATCH", "FORM", "TABLE"),
    "btts_yes": ("UNDERLYING", "MATCH", "FORM"),
    "btts_no": ("UNDERLYING", "MATCH", "FORM"),
    "over_2_5": ("UNDERLYING", "MATCH", "FORM", "PLAYER"),
    "under_2_5": ("UNDERLYING", "MATCH", "FORM", "PLAYER"),
}
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
    """Legacy diagnostic score; it never gates the final AI policy."""
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
        "verlor aber den trainierten Fünf-Dateien-Correctness-Vergleich."
    )


def _confirmation_diagnostic(market_key: str, confirming: Sequence[str]) -> Dict[str, Any]:
    """Describe confirmations against blocks applicable to the selected family.

    This is export/presentation metadata only and never affects the decision.
    """
    applicable_names = list(APPLICABLE_EVIDENCE_BLOCKS[market_key])
    confirmed_names = [name for name in confirming if name in applicable_names]
    required = len(applicable_names)
    if len(confirmed_names) == required:
        status = "BESTANDEN"
    elif confirmed_names:
        status = "TEILWEISE"
    else:
        status = "NICHT BESTANDEN"
    return {
        "confirmations": len(confirmed_names),
        "applicable_blocks": len(applicable_names),
        "applicable_block_names": applicable_names,
        "required": required,
        "status": status,
        "diagnostic_only": True,
        "affects_final_decision": False,
    }


def apply_full5_next(result: Dict[str, Any], parsed_files: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """Attach the trained final decision while preserving every core probability.

    The only hard overrides are data-integrity conditions. Confirmations,
    counters, rank stability, robustness and sample quality remain diagnostics
    or continuous model inputs; no fixed performance threshold is applied here.
    """
    if not isinstance(result, dict) or not result.get("ok"):
        return result
    probabilities = result.get("probabilities") or {}
    if not probability_sums_valid(probabilities):
        raise ValueError("V0.4.3 probability sums are invalid")

    diagnostics = result.get("diagnostics") or {}
    protocol = diagnostics.get("elite_protocol") or {}
    gates = protocol.get("gates") or {}
    strict = ((gates.get("pre_match_integrity") or {}).get("strict_pre_match") is True)
    robust = diagnostics.get("robustness_status") == "BESTANDEN"
    found_sources = source_types(parsed_files)
    all_five = found_sources == set(SOURCE_TYPES)
    audit_valid = ((result.get("audit") or {}).get("valid") is True)
    leakage_guard_passed = not blocked_target_fields(parsed_files)
    quality = sample_quality(result)
    data_quality = str(diagnostics.get("data_quality") or "UNBEKANNT")
    sample_security = str(diagnostics.get("sample_security") or "UNBEKANNT")

    ai_error = None
    try:
        ranking = learned_ai.rank_markets(result, parsed_files)
        selected = ranking["selected"]
        market_key = str(selected["market"])
        probability = float(probabilities[market_key])
        learned_score = float(selected["learned_score"])
        score_gap = float(selected["score_gap"])
        rank_stability = float(selected["rank_stability"])
        confirming = list(selected["confirming_blocks"])
        counters = list(selected["counter_blocks"])
        confirmation_gate = _confirmation_diagnostic(market_key, confirming)
        policy = learned_ai.apply_abstention_policy(result, ranking)
    except (KeyError, TypeError, ValueError, RuntimeError) as exc:
        ai_error = str(exc)
        strongest = result.get("strongest_market") or {}
        market_key = str(strongest.get("key") or "")
        if market_key not in MARKET_KEYS:
            raise ValueError("V0.4.3 returned no valid playable market") from exc
        probability = float(probabilities[market_key])
        learned_score = score_gap = rank_stability = 0.0
        confirming = []
        counters = ["AI_INPUT"]
        confirmation_gate = _confirmation_diagnostic(market_key, confirming)
        ranking = {"selected": {}, "second": {}, "candidates": [], "model": {}}
        policy = {
            "decision": "AUSLASSEN / KEIN BET", "reliability": 0.0,
            "reliability_bootstrap_mean": 0.0, "reliability_uncertainty": 0.0,
            "reliability_q10": 0.0, "reliability_q90": 0.0,
            "learned_observe_boundary": None, "learned_play_boundary": None,
            "boundary_provenance": None, "final_decision_source": "TRAINED_AI_POLICY",
            "manual_performance_gates": "NONE",
            "integrity_gates": ["STRICT_PREMATCH", "FIVE_FILES", "AUDIT", "LEAKAGE", "REQUIRED_INPUTS"],
        }

    integrity_checks = {
        "STRICT_PREMATCH": strict,
        "FIVE_FILES": all_five,
        "AUDIT": audit_valid,
        "LEAKAGE": leakage_guard_passed,
        "REQUIRED_INPUTS": ai_error is None,
    }
    integrity_passed = all(integrity_checks.values())
    policy_decision = str(policy["decision"])
    decision = policy_decision if integrity_passed else "AUSLASSEN / KEIN BET"

    positive_reasons: List[str] = [
        "Das trainierte FULL-5-NEXT-Modell wählte diesen Markt im Vergleich aller sechs Kandidaten.",
        f"V0.4.3-Core-Wahrscheinlichkeit: {probability:.1%}.",
        f"Gelernter Correctness-Score: {learned_score:.1%}; Rangstabilität: {rank_stability:.1%}.",
        f"Gelernte finale AI-Reliability: {float(policy['reliability']):.1%}.",
    ]
    if confirming:
        positive_reasons.append(
            f"{confirmation_gate['confirmations']}/{confirmation_gate['applicable_blocks']} "
            "anwendbare Signalblöcke bestätigt (nur Diagnose): " + ", ".join(confirming) + "."
        )
    if robust:
        positive_reasons.append("Robustheitsdiagnose bestanden; kontinuierliche Stresswerte fließen in die AI ein.")
    if all_five:
        positive_reasons.append("Alle fünf FootyStats-Dateien wurden erkannt.")

    counterarguments = [f"Gegenargument im Signalblock {name}." for name in counters]
    if not strict:
        counterarguments.append("Snapshot liegt nicht strikt vor Kickoff.")
    if not all_five:
        missing = [name for name in SOURCE_TYPES if name not in found_sources]
        counterarguments.append("Fehlende Datenquelle(n): " + ", ".join(missing) + ".")
    if not audit_valid:
        counterarguments.append("Datenqualitäts-Audit nicht bestanden.")
    if not leakage_guard_passed:
        counterarguments.append("Leakage-Schutz nicht bestanden.")
    if ai_error:
        counterarguments.append("Trainierte Decision Engine nicht anwendbar: " + ai_error)
    if counters:
        counterarguments.append("Diese Konflikte sind diagnostisch und kein manuelles Decision-Gate.")

    full5 = ((((result.get("expected_goals") or {}).get("hybrid_model") or {}).get("full5")) or {})
    next_result = {
        "version": VERSION,
        "validation_reference": "Development-only chronological grouped rolling OOF; former 87-match OOS excluded",
        "rolling_oof_result": learned_ai.load_model().get("abstention_validation") or {},
        "probability_core": "V0.4.3 FULL-5",
        "probability_core_changed": False,
        "feature_count": 40,
        "alpha": 3.0,
        "dixon_coles_rho": -0.25,
        "elite_lambda": False,
        "new_feature_blocks": [],
        "selected_market": market_key,
        "selected_market_label": learned_ai.LABELS.get(market_key, market_key),
        "probability": probability,
        "probability_pct": round(probability * 100, 1),
        "learned_correctness_score": round(learned_score, 6),
        "learned_correctness_score_pct": round(learned_score * 100, 1),
        "learned_score_gap": round(score_gap, 6),
        "rank_stability": round(rank_stability, 6),
        "rank_stability_pct": round(rank_stability * 100, 1),
        "ranking_uncertainty": round(float((ranking.get("selected") or {}).get("rank_score_std") or 0.0), 6),
        "ranking_uncertainty_iqr": round(float((ranking.get("selected") or {}).get("rank_score_iqr") or 0.0), 6),
        "market_ranking": [
            {
                "market": item["market"], "label": item["label"],
                "core_probability": round(float(item["core_probability"]), 6),
                "learned_score": round(float(item["learned_score"]), 6),
            }
            for item in sorted(ranking["candidates"], key=lambda entry: entry["learned_score"], reverse=True)
        ],
        "decision": decision,
        "policy_decision": policy_decision,
        "integrity_override": not integrity_passed,
        "final_ai_reliability": round(float(policy["reliability"]), 6),
        "final_ai_reliability_pct": round(float(policy["reliability"]) * 100, 1),
        "final_ai_uncertainty": round(float(policy["reliability_uncertainty"]), 6),
        "final_ai_reliability_q10": round(float(policy["reliability_q10"]), 6),
        "final_ai_reliability_q90": round(float(policy["reliability_q90"]), 6),
        "learned_observe_boundary": policy["learned_observe_boundary"],
        "learned_play_boundary": policy["learned_play_boundary"],
        "decision_boundary_provenance": policy["boundary_provenance"],
        "FINAL_DECISION_SOURCE": "TRAINED_AI_POLICY",
        "MANUAL_PERFORMANCE_GATES": "NONE",
        "INTEGRITY_GATES": "STRICT_PREMATCH, FIVE_FILES, AUDIT, LEAKAGE, REQUIRED_INPUTS",
        "positive_reasons": positive_reasons,
        "counterarguments": counterarguments,
        "signal_agreement": len(confirming),
        "signal_conflict": len(counters),
        "confirming_blocks": confirming,
        "counter_blocks": counters,
        "confirmations": confirmation_gate["confirmations"],
        "applicable_blocks": confirmation_gate["applicable_blocks"],
        "applicable_block_names": confirmation_gate["applicable_block_names"],
        "required": confirmation_gate["required"],
        "confirmation_status": confirmation_gate["status"],
        "confirmation_gate": confirmation_gate,
        "strict_pre_match": strict,
        "all_five_sources": all_five,
        "data_quality_gate": all_five and audit_valid,
        "audit_valid": audit_valid,
        "leakage_guard_passed": leakage_guard_passed,
        "required_ai_inputs_valid": ai_error is None,
        "integrity_checks": integrity_checks,
        "integrity_passed": integrity_passed,
        "sources_found": sorted(found_sources),
        "data_quality": data_quality,
        "robustness": "BESTANDEN" if robust else "NICHT BESTANDEN",
        "sample_quality": round(quality, 6),
        "sample_security": sample_security,
        "full5_status": "AKTIV" if full5.get("applied") is True else "FALLBACK AUF V0.4.2",
        "why_this_market": (
            "Der Markt besitzt nach gelernter, stark regularisierter Fünf-Dateien-Gewichtung den höchsten "
            "Correctness-Score aller sechs Kandidaten."
        ),
        "why_not_higher_probability_market": _higher_probability_reason(result, market_key, probability),
        "decision_policy": {
            "source": "TRAINED_AI_POLICY",
            "manual_performance_gates": "NONE",
            "learned_observe_boundary": policy["learned_observe_boundary"],
            "learned_play_boundary": policy["learned_play_boundary"],
            "boundary_provenance": policy["boundary_provenance"],
            "integrity_gates": list(integrity_checks),
        },
    }
    result["full5_next"] = next_result
    result["decision"] = decision
    protocol["final_decision"] = decision
    protocol["decision_reasons"] = positive_reasons + counterarguments
    protocol_gates = dict(protocol.get("gates") or {})
    protocol_gates["multi_block_confirmation"] = dict(confirmation_gate)
    protocol["gates"] = protocol_gates
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
        "validation": "Development-only rolling chronological grouped OOF; former 87-match OOS excluded",
        "final_decision_source": "TRAINED_AI_POLICY",
        "manual_performance_gates": "NONE",
        "file_6": False,
        "file_7": False,
    })
    result["method"] = method
    return result
