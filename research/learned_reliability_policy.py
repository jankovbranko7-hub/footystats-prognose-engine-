"""Learned three-state decision policy for the context-aware release.

The six-market probability vector remains the frozen V0.4.3 FULL-5 output.
No hand-written betting threshold is used here.  The three centroids below are
an artifact learned by KMeans(k=3) from the strongest-market probabilities of
all 300 canonical Strict-Pre-Match rows.  KMeans fitting used probabilities
only (no result labels).  The primary policy validation was chronological:
each date block was assigned using centroids fit only on earlier OOF blocks.
"""
from __future__ import annotations

import copy
from typing import Any, Dict, Iterable, Tuple

POLICY_VERSION = "1.0.0"
POLICY_NAME = "FULL5_CONTEXT_RELIABILITY_POLICY"
POLICY_SOURCE = "LEARNED_RELIABILITY_CLUSTER_POLICY"

# Frozen model artifact: FINAL_RELIABILITY_POLICY_MODEL_1_0.json
LEARNED_CENTROIDS: Tuple[float, float, float] = (
    0.5939096343988497,
    0.6848009383779808,
    0.7950201361084736,
)
ACTIONS: Tuple[str, str, str] = (
    "AUSLASSEN / KEIN BET",
    "BEOBACHTEN",
    "SPIELEN",
)

# Exactly the six selectable markets from the project contract.  Draw remains
# part of the 1X2 probability model but is not one of these six actions.
MARKETS: Tuple[Tuple[str, str], ...] = (
    ("HOME", "home_win"),
    ("AWAY", "away_win"),
    ("BTTS YES", "btts_yes"),
    ("BTTS NO", "btts_no"),
    ("OVER 2.5", "over_2_5"),
    ("UNDER 2.5", "under_2_5"),
)


def _num(value: Any) -> float | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        out = float(value)
        return out if 0.0 <= out <= 1.0 else None
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

    # Compatibility fallback for report variants exposing only the ranked
    # market list.  This does not infer or fabricate probabilities.
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
        raise ValueError("Learned policy missing six-market probabilities: " + ", ".join(missing))
    return values


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


def learned_action(probability: float) -> Dict[str, Any]:
    value = float(probability)
    distances = [abs(value - center) for center in LEARNED_CENTROIDS]
    index = min(range(len(distances)), key=distances.__getitem__)
    return {
        "decision": ACTIONS[index],
        "centroid_index": index,
        "assigned_centroid": LEARNED_CENTROIDS[index],
        "distance_to_centroid": distances[index],
    }


def apply_learned_policy(result: Dict[str, Any]) -> Dict[str, Any]:
    """Replace legacy manual action gates with the frozen learned cluster policy.

    Probability values are not changed.  Old V0.4.3 gate outputs are retained as
    diagnostics only so the release remains auditable.
    """
    out = copy.deepcopy(result)
    strongest = select_strongest_market(out)
    action = learned_action(strongest["probability"])
    legacy_decision = out.get("decision")

    out["legacy_v043_decision_diagnostic"] = legacy_decision
    out["strongest_market"] = strongest
    out["decision"] = action["decision"]
    out["final_decision_source"] = POLICY_SOURCE
    out["manual_performance_gates"] = "NONE"
    out["learned_decision_policy"] = {
        "name": POLICY_NAME,
        "version": POLICY_VERSION,
        "source": POLICY_SOURCE,
        "algorithm": "KMEANS_NEAREST_LEARNED_CENTROID",
        "centroids": list(LEARNED_CENTROIDS),
        "centroids_learned_from": "300 Strict-Pre-Match strongest-market probabilities; results not used for centroid fitting",
        "assignment": "nearest centroid by absolute distance",
        "centroid_index": action["centroid_index"],
        "assigned_centroid": action["assigned_centroid"],
        "distance_to_centroid": action["distance_to_centroid"],
        "selected_market": strongest,
        "human_performance_thresholds": False,
        "human_feature_mix_weights": False,
        "legacy_v043_gate_output_used_for_final_action": False,
    }

    diagnostics = dict(out.get("diagnostics") or {})
    protocol = dict(diagnostics.get("elite_protocol") or {})
    if protocol:
        protocol["legacy_v043_final_decision_diagnostic"] = protocol.get("final_decision")
        protocol["final_decision"] = action["decision"]
        protocol["final_decision_source"] = POLICY_SOURCE
        protocol["manual_performance_gates"] = "NONE"
        protocol["legacy_gate_system_role"] = "DIAGNOSTIC_ONLY"
        diagnostics["elite_protocol"] = protocol
        out["diagnostics"] = diagnostics
    return out
