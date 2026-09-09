"""Deterministic smoke for result-supervised reliability policy v2."""
import copy

from research.learned_reliability_policy import (
    POLICY_SOURCE,
    POLICY_VERSION,
    RELIABILITY_CENTERS,
    apply_learned_policy,
)

CASES = [
    (
        "AUSLASSEN / KEIN BET",
        {
            "home_win": 0.4701369649087472,
            "draw": 0.2915352026243412,
            "away_win": 0.2383278324669115,
            "btts_yes": 0.6053254290809583,
            "btts_no": 0.3946745709190417,
            "over_2_5": 0.5642929945515532,
            "under_2_5": 0.4357070054484467,
        },
    ),
    (
        "BEOBACHTEN",
        {
            "home_win": 0.3164033140496531,
            "draw": 0.3415619804037565,
            "away_win": 0.3420347055465895,
            "btts_yes": 0.5213444104052143,
            "btts_no": 0.4786555895947857,
            "over_2_5": 0.4310335503688371,
            "under_2_5": 0.5689664496311628,
        },
    ),
    (
        "SPIELEN",
        {
            "home_win": 0.2921339681575944,
            "draw": 0.2530469411503557,
            "away_win": 0.4548190906920499,
            "btts_yes": 0.7261765591282086,
            "btts_no": 0.2738234408717914,
            "over_2_5": 0.7167852292954222,
            "under_2_5": 0.2832147707045778,
        },
    ),
]

assert POLICY_VERSION == "2.0.0"
assert POLICY_SOURCE == "RESULT_SUPERVISED_OOF_RELIABILITY_POLICY"
assert len(RELIABILITY_CENTERS) == 3
assert tuple(sorted(RELIABILITY_CENTERS)) == RELIABILITY_CENTERS

for expected, probabilities in CASES:
    source = {
        "ok": True,
        "probabilities": copy.deepcopy(probabilities),
        "decision": "LEGACY",
        "diagnostics": {
            "elite_protocol": {
                "final_decision": "LEGACY",
            }
        },
    }
    frozen = copy.deepcopy(source["probabilities"])
    out = apply_learned_policy(source)
    policy = out["learned_decision_policy"]

    assert out["probabilities"] == frozen
    assert out["decision"] == expected
    assert out["final_decision_source"] == POLICY_SOURCE
    assert out["manual_performance_gates"] == "NONE"
    assert policy["training_uses_results"] is True
    assert policy["trained_on_oof_rows"] == 277
    assert policy["primary_meta_oos_matches"] == 195
    assert policy["primary_meta_oos_play"]["n"] == 58
    assert policy["primary_meta_oos_play"]["correct"] == 44
    assert policy["human_performance_thresholds"] is False
    assert policy["human_feature_mix_weights"] is False
    assert policy["legacy_v043_gate_output_used_for_final_action"] is False
    assert policy["probabilities_modified"] is False
    assert policy["reliability_group"] in {"NIEDRIG", "MITTEL", "HOCH"}

# Draw compatibility: derive exact normalized residual when the report omits draw.
without_draw = copy.deepcopy(CASES[1][1])
without_draw.pop("draw")
out = apply_learned_policy({"probabilities": without_draw, "decision": "LEGACY"})
assert out["decision"] == "BEOBACHTEN"

print("result-supervised reliability policy v2 smoke passed")
