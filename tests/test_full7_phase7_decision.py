import math

from full7_phase7_decision import (
    PHASE6_DECISION_LOCK_SHA256,
    evaluate_phase7_decision,
)


PASS_GATES = {
    "train_forward_support": True,
    "development_support": True,
    "chronological_segment_support": True,
    "calibration_gap": True,
    "calibration_slope_intercept": True,
    "wilson_uncertainty": True,
    "probability_bin_support": True,
    "input_integrity": True,
    "model_integrity": True,
}


def evaluate(home=0.55, draw=0.25, away=0.20, btts_yes=0.60, **kwargs):
    return evaluate_phase7_decision(
        probabilities={
            "home": home,
            "draw": draw,
            "away": away,
            "btts_yes": btts_yes,
        },
        feature_coverage={"1X2": 0.99, "BTTS": 0.99},
        integrity_gates=PASS_GATES,
        **kwargs,
    )


def decision(result, direction):
    return result["directions"][direction]["decision"]


def test_home_spielen_uses_phase6_threshold_not_legacy_71_percent():
    result = evaluate(home=0.55, draw=0.25, away=0.20)
    assert decision(result, "HOME") == "SPIELEN"
    assert result["final_decision_source"] == (
        f"PHASE6_DECISION_LOCK_SHA256:{PHASE6_DECISION_LOCK_SHA256}"
    )
    assert result["manual_performance_gates"] is False


def test_home_beobachten():
    result = evaluate(home=0.45, draw=0.30, away=0.25)
    assert decision(result, "HOME") == "BEOBACHTEN"


def test_home_auslassen_below_watch_zone():
    result = evaluate(home=0.39, draw=0.31, away=0.30)
    assert decision(result, "HOME") == "AUSLASSEN"


def test_draw_is_always_auslassen_even_when_top_class():
    result = evaluate(home=0.25, draw=0.50, away=0.25)
    assert decision(result, "DRAW") == "AUSLASSEN"
    assert result["directions"]["DRAW"]["reason"] == "DRAW_FAIL_CLOSED_DISABLED"


def test_away_spielen():
    result = evaluate(home=0.20, draw=0.24, away=0.56)
    assert decision(result, "AWAY") == "SPIELEN"


def test_away_beobachten_above_play_ceiling():
    result = evaluate(home=0.17, draw=0.15, away=0.68)
    assert decision(result, "AWAY") == "BEOBACHTEN"


def test_btts_yes_spielen_uses_phase6_threshold_not_legacy_605_percent():
    result = evaluate(btts_yes=0.56)
    assert decision(result, "BTTS_YES") == "SPIELEN"


def test_btts_yes_beobachten():
    result = evaluate(btts_yes=0.52)
    assert decision(result, "BTTS_YES") == "BEOBACHTEN"


def test_btts_no_is_watch_only():
    result = evaluate(btts_yes=0.45)
    assert decision(result, "BTTS_NO") == "BEOBACHTEN"
    assert result["directions"]["BTTS_NO"]["play_enabled"] is False


def test_o25_and_u25_are_always_hold():
    result = evaluate()
    assert decision(result, "O25") == "HOLD"
    assert decision(result, "U25") == "HOLD"
    assert result["o25_status"] == "HOLD"


def test_missing_core_inputs_fail_closed():
    result = evaluate_phase7_decision(
        probabilities={"home": 0.55, "draw": 0.25, "away": 0.20},
        feature_coverage={"1X2": 0.99},
        integrity_gates=PASS_GATES,
    )
    assert all(
        decision(result, name) == "AUSLASSEN"
        for name in ("HOME", "DRAW", "AWAY", "BTTS_YES", "BTTS_NO")
    )
    assert "MALFORMED_INPUT" in result["fail_closed_reasons"]


def test_low_1x2_feature_coverage_blocks_home_play():
    result = evaluate_phase7_decision(
        probabilities={"home": 0.55, "draw": 0.25, "away": 0.20, "btts_yes": 0.60},
        feature_coverage={"1X2": 0.97, "BTTS": 0.99},
        integrity_gates=PASS_GATES,
    )
    assert decision(result, "HOME") == "AUSLASSEN"
    assert result["directions"]["HOME"]["reason"] == "FEATURE_COVERAGE_FAIL"


def test_probability_above_empirical_ceiling_is_not_extrapolated():
    result = evaluate(home=0.86, draw=0.08, away=0.06, btts_yes=0.71)
    assert decision(result, "HOME") == "AUSLASSEN"
    assert decision(result, "BTTS_YES") == "AUSLASSEN"


def test_1x2_coherence_failure_fails_closed():
    result = evaluate(home=0.55, draw=0.30, away=0.20)
    assert result["coherence"]["1X2"] is False
    assert decision(result, "HOME") == "AUSLASSEN"


def test_malformed_input_fails_closed_without_throwing():
    result = evaluate_phase7_decision(
        probabilities="not-a-mapping",
        feature_coverage="not-a-mapping",
        integrity_gates="not-a-mapping",
    )
    assert "MALFORMED_INPUT" in result["fail_closed_reasons"]
    assert decision(result, "HOME") == "AUSLASSEN"


def test_nan_and_inf_fail_closed():
    for bad in (math.nan, math.inf, -math.inf):
        result = evaluate(home=bad, draw=0.25, away=0.20)
        assert decision(result, "HOME") == "AUSLASSEN"
        assert "NON_FINITE_PROBABILITY" in result["fail_closed_reasons"]


def test_feature_schema_mismatch_fails_closed():
    gates = {**PASS_GATES, "feature_schema": False}
    result = evaluate_phase7_decision(
        probabilities={"home": 0.55, "draw": 0.25, "away": 0.20, "btts_yes": 0.60},
        feature_coverage={"1X2": 0.99, "BTTS": 0.99},
        integrity_gates=gates,
    )
    assert decision(result, "HOME") == "AUSLASSEN"
    assert "INTEGRITY_GATE_FAIL:feature_schema" in result["fail_closed_reasons"]


def test_non_preferred_1x2_direction_cannot_watch_or_play():
    result = evaluate(home=0.45, draw=0.10, away=0.45)
    assert decision(result, "AWAY") == "AUSLASSEN"
