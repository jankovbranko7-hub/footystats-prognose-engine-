from __future__ import annotations

PRODUCTION_FAMILY_POLICY = {
    "1X2": {
        "max_decision": "BEOBACHTEN",
        "spielen_allowed": False,
        "cap_reason": "FAMILY_OOS_OBSERVE_ONLY",
    },
    "BTTS": {
        "max_decision": "SPIELEN",
        "spielen_allowed": True,
        "cap_reason": None,
        "min_family_margin": 0.08,
    },
    "TOTALS": {
        "max_decision": "BEOBACHTEN",
        "spielen_allowed": False,
        "cap_reason": "FAMILY_OOS_OBSERVE_ONLY",
    },
}
DECISION_RANK = {"AUSLASSEN": 0, "BEOBACHTEN": 1, "SPIELEN": 2}


def apply_precision_policy(
    family: str,
    state: str,
    reason: str,
    *,
    sample_status: str,
    family_margin: float,
    catboost_prefers_market: float,
    goal_prefers_market: float,
) -> tuple[str, str]:
    policy = PRODUCTION_FAMILY_POLICY[family]
    if DECISION_RANK[state] > DECISION_RANK[policy["max_decision"]]:
        state = policy["max_decision"]
        reason = str(policy["cap_reason"])
    if state == "SPIELEN" and sample_status == "LOW":
        state = "BEOBACHTEN"
        reason = "SAMPLE_SECURITY_LOW"
    if family == "BTTS" and state == "SPIELEN":
        min_margin = float(policy["min_family_margin"])
        if family_margin < min_margin:
            state = "BEOBACHTEN"
            reason = "FAMILY_MARGIN_BELOW_MIN"
        elif not (catboost_prefers_market and goal_prefers_market):
            state = "BEOBACHTEN"
            reason = "MODEL_DISAGREEMENT"
    return state, reason
