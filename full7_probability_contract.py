from __future__ import annotations

from typing import Any, Dict, Mapping, Optional


FAMILY_MARKETS = {
    "1X2": ("home_win", "draw", "away_win"),
    "BTTS": ("btts_yes", "btts_no"),
    "TOTALS": ("over_2_5", "under_2_5"),
}

VALID_READINESS = {
    "DEVELOPMENT_CANDIDATE_STRONG",
    "DEVELOPMENT_CANDIDATE_NEEDS_NEW_OOS",
    "HOLD_NO_INCREMENTAL_SIGNAL_YET",
    "PRODUCTION_VALIDATED",
}


def _prob(v: Any) -> float:
    x=float(v)
    if not 0.0 <= x <= 1.0:
        raise ValueError(f"probability outside [0,1]: {x}")
    return x


def validate_family_probabilities(family: str, probabilities: Mapping[str, Any]) -> Dict[str, float]:
    if family not in FAMILY_MARKETS:
        raise ValueError(f"unknown probability family: {family}")
    markets=FAMILY_MARKETS[family]
    values={market:_prob(probabilities[market]) for market in markets}
    total=sum(values.values())
    if abs(total-1.0)>1e-6:
        raise ValueError(f"{family} probabilities are incoherent: sum={total}")
    return values


def build_probability_contract(
    *,
    one_x_two: Mapping[str, Any],
    btts: Mapping[str, Any],
    totals: Optional[Mapping[str, Any]],
    sources: Mapping[str, str],
    readiness: Mapping[str, str],
    model_versions: Mapping[str, str],
) -> Dict[str, Any]:
    probabilities: Dict[str, float] = {}
    probabilities.update(validate_family_probabilities("1X2", one_x_two))
    probabilities.update(validate_family_probabilities("BTTS", btts))

    totals_available=totals is not None
    if totals_available:
        probabilities.update(validate_family_probabilities("TOTALS", totals))

    family_state={}
    for family in FAMILY_MARKETS:
        state=str(readiness.get(family) or "")
        if state not in VALID_READINESS:
            raise ValueError(f"invalid readiness for {family}: {state}")
        source=str(sources.get(family) or "")
        version=str(model_versions.get(family) or "")
        if family!="TOTALS" or totals_available:
            if not source or not version:
                raise ValueError(f"{family} requires model source and version")
        family_state[family]={
            "readiness":state,
            "source":source or None,
            "model_version":version or None,
            "probability_available":family!="TOTALS" or totals_available,
            "recommendation_eligible":state=="PRODUCTION_VALIDATED",
        }

    if not totals_available and family_state["TOTALS"]["readiness"]!="HOLD_NO_INCREMENTAL_SIGNAL_YET":
        raise ValueError("missing totals probabilities require HOLD totals readiness")

    return {
        "probability_contract_version":"FULL7_PROBABILITY_CONTRACT_0.1",
        "probabilities":probabilities,
        "families":family_state,
        "coherence":{
            "one_x_two_sum":sum(probabilities[k] for k in FAMILY_MARKETS["1X2"]),
            "btts_sum":sum(probabilities[k] for k in FAMILY_MARKETS["BTTS"]),
            "totals_sum":(
                sum(probabilities[k] for k in FAMILY_MARKETS["TOTALS"])
                if totals_available else None
            ),
            "pass":True,
        },
        "policy":{
            "probability_is_not_recommendation":True,
            "production_recommendation_requires":"PRODUCTION_VALIDATED family readiness plus later integrity/reliability gate",
            "held_family":"A held family cannot silently borrow another family's readiness.",
        },
    }
