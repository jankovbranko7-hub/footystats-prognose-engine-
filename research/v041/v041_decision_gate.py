#!/usr/bin/env python3
"""FootyStats v0.4.1 offline decision gate.

This module does not change the v0.4.0 probability core. It only repairs two
structural decision problems found before looking at individual final scores:

1. Relative edge is measured against a mutually exclusive counter-outcome,
   never against a correlated market such as BTTS Yes versus Over 2.5.
2. A low early-season venue sample is not an automatic veto when the existing
   empirical-Bayes shrinkage and every independent stress/quality guard pass.

The function accepts only a pre-match analysis object. Final scores or outcome
labels are intentionally not part of its interface.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


VERSION = "0.4.1-offline-gate-test"

DIRECT_COUNTERS = {
    "btts_yes": ("btts_no",),
    "btts_no": ("btts_yes",),
    "over_2_5": ("under_2_5",),
    "under_2_5": ("over_2_5",),
    "home_win": ("draw", "away_win"),
    "away_win": ("draw", "home_win"),
}

ALLOWED_UNDERLYING = {"KONSISTENT", "TEILWEISE KONSISTENT"}
ALLOWED_QUALITY = {"HOCH", "MITTEL"}


def _number(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _percent(value: Any) -> Optional[float]:
    number = _number(value)
    if number is None:
        return None
    return number * 100 if 0 <= number <= 1 else number


def _strongest(analysis: Dict[str, Any]) -> tuple[Optional[str], Optional[float]]:
    strongest = analysis.get("strongest_market") or {}
    if isinstance(strongest, dict):
        market = strongest.get("key")
        probability = _percent(strongest.get("probability_pct"))
    else:
        market = strongest
        probability = None
    probabilities = analysis.get("probabilities") or {}
    if probability is None and market:
        probability = _percent(probabilities.get(market))
    return market, probability


def direct_counter_edge(analysis: Dict[str, Any]) -> Dict[str, Any]:
    market, top_probability = _strongest(analysis)
    probabilities = analysis.get("probabilities") or {}
    counters = DIRECT_COUNTERS.get(market or "", ())
    counter_values = [
        (counter, _percent(probabilities.get(counter)))
        for counter in counters
        if _percent(probabilities.get(counter)) is not None
    ]
    if top_probability is None or not counter_values:
        return {
            "status": "NICHT PRÜFBAR",
            "market": market,
            "top_probability_pct": top_probability,
            "counter_market": None,
            "counter_probability_pct": None,
            "difference_pp": None,
        }
    counter_market, counter_probability = max(counter_values, key=lambda item: item[1])
    difference = top_probability - counter_probability
    status = "KLAR" if difference >= 5 else ("KNAPP" if difference >= 2 else "NICHT VORHANDEN")
    return {
        "status": status,
        "market": market,
        "top_probability_pct": round(top_probability, 3),
        "counter_market": counter_market,
        "counter_probability_pct": round(counter_probability, 3),
        "difference_pp": round(difference, 3),
    }


def _gate_status(protocol: Dict[str, Any], key: str) -> Any:
    return (protocol.get("gates") or {}).get(key)


def evaluate_v041(analysis: Dict[str, Any]) -> Dict[str, Any]:
    """Return an outcome-blind offline decision and complete gate audit."""
    market, top_probability = _strongest(analysis)
    base_decision = analysis.get("decision")
    diagnostics = analysis.get("diagnostics") or {}
    protocol = diagnostics.get("elite_protocol") or {}
    method = analysis.get("method") or {}
    samples = analysis.get("samples") or {}

    multi_block = _gate_status(protocol, "multi_block_confirmation")
    counter_gate = _gate_status(protocol, "counterargument") or {}
    counter_status = counter_gate.get("status") if isinstance(counter_gate, dict) else counter_gate
    influence = _gate_status(protocol, "influence_removal") or {}
    fragility = _gate_status(protocol, "fragility_removal") or {}
    influence_status = influence.get("status") if isinstance(influence, dict) else influence
    fragility_status = fragility.get("status") if isinstance(fragility, dict) else fragility
    coherence = _gate_status(protocol, "coherence") or {}
    coherence_passed = bool(coherence.get("passed")) if isinstance(coherence, dict) else coherence == "BESTANDEN"

    quality = _gate_status(protocol, "data_quality") or diagnostics.get("data_quality")
    underlying = diagnostics.get("result_vs_underlying")
    sample_security = samples.get("security") or diagnostics.get("sample_security")
    single_point = bool(diagnostics.get("single_point_of_failure"))
    empirical_bayes = bool(method.get("empirical_bayes_shrinkage"))
    edge = direct_counter_edge(analysis)

    candidate = top_probability is not None and top_probability >= 65
    multi_passed = multi_block == "BESTANDEN"
    counter_passed = counter_status not in {"STARK", "RELEVANT", "DOMINANT"}
    removal_passed = influence_status == "BESTANDEN" and fragility_status == "BESTANDEN"
    quality_passed = quality in ALLOWED_QUALITY
    underlying_passed = underlying in ALLOWED_UNDERLYING
    edge_passed = edge["status"] == "KLAR"

    low_sample_compensated = (
        sample_security == "NIEDRIG"
        and empirical_bayes
        and multi_passed
        and counter_passed
        and removal_passed
        and quality_passed
        and underlying_passed
        and coherence_passed
        and not single_point
    )
    sample_passed = sample_security in {"HOCH", "MITTEL"} or low_sample_compensated
    sample_status = (
        "BESTANDEN"
        if sample_security in {"HOCH", "MITTEL"}
        else "KOMPENSIERT_DURCH_SHRINKAGE_UND_STRESSTESTS"
        if low_sample_compensated
        else "NICHT BESTANDEN"
    )

    play_checks = {
        "probability_65": candidate,
        "direct_counter_edge": edge_passed,
        "multi_block": multi_passed,
        "counterargument": counter_passed,
        "influence_and_fragility_removal": removal_passed,
        "sample_reliability": sample_passed,
        "data_quality": quality_passed,
        "result_vs_underlying": underlying_passed,
        "coherence": coherence_passed,
        "no_single_point_of_failure": not single_point,
    }

    if candidate and all(play_checks.values()):
        decision = "SPIELEN"
    else:
        # Minimal-delta rule: only the proven SPIELEN blockade is repaired.
        # Every report not promoted by the new rule keeps its v0.4.0 outcome.
        decision = base_decision if base_decision in {"AUSLASSEN", "BEOBACHTEN"} else "BEOBACHTEN"

    failed_checks = [key for key, passed in play_checks.items() if not passed]
    return {
        "version": VERSION,
        "base_v040_decision": base_decision,
        "decision": decision,
        "market": market,
        "probability_pct": round(top_probability, 3) if top_probability is not None else None,
        "direct_counter_edge": edge,
        "sample_gate": {
            "raw_security": sample_security,
            "status": sample_status,
            "empirical_bayes_shrinkage": empirical_bayes,
        },
        "play_checks": play_checks,
        "failed_play_checks": failed_checks,
        "outcome_data_used": False,
    }


__all__ = ["VERSION", "direct_counter_edge", "evaluate_v041"]
