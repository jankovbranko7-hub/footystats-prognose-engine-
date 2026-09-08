from __future__ import annotations

import copy
import unittest
from unittest.mock import patch

from full5_next_engine import (
    MARKET_KEYS,
    SOURCE_TYPES,
    apply_full5_next,
    blocked_target_fields,
    probability_sums_valid,
    sample_quality,
    sanitize_parsed_files,
    source_types,
)


def five_files():
    return [{"name": f"123_{name.title()}Daten.json", "data": {}} for name in SOURCE_TYPES]


def result_template(*, key="over_2_5", probability=.70, confirming=3, counters=0,
                    strict=True, robust=True, home_n=10, away_n=10,
                    home_depth=24, away_depth=24, full5=True):
    probabilities = {
        "home_win": .40, "draw": .25, "away_win": .35,
        "btts_yes": .60, "btts_no": .40,
        "over_2_5": .70, "under_2_5": .30,
    }
    probabilities[key] = probability
    complement = {
        "btts_yes": "btts_no", "btts_no": "btts_yes",
        "over_2_5": "under_2_5", "under_2_5": "over_2_5",
    }
    if key in complement:
        probabilities[complement[key]] = 1 - probability
    if key in {"home_win", "away_win"}:
        other = "away_win" if key == "home_win" else "home_win"
        probabilities[other] = 1 - probability - probabilities["draw"]
    labels = {
        "home_win": "Sieg Heim", "away_win": "Sieg Auswärts",
        "btts_yes": "BTTS Ja", "btts_no": "BTTS Nein",
        "over_2_5": "Über 2,5", "under_2_5": "Unter 2,5",
    }
    markets = [
        {"key": market, "label": labels[market],
         "probability_pct": probabilities[market] * 100}
        for market in MARKET_KEYS
    ]
    applicable = {
        "home_win": ["UNDERLYING", "MATCH", "FORM", "TABLE"],
        "away_win": ["UNDERLYING", "MATCH", "FORM", "TABLE"],
        "btts_yes": ["UNDERLYING", "MATCH", "FORM"],
        "btts_no": ["UNDERLYING", "MATCH", "FORM"],
        "over_2_5": ["UNDERLYING", "MATCH", "FORM", "PLAYER"],
        "under_2_5": ["UNDERLYING", "MATCH", "FORM", "PLAYER"],
    }[key]
    return {
        "ok": True,
        "probabilities": probabilities,
        "markets": markets,
        "strongest_market": {"key": key, "label": labels[key],
                             "probability_pct": probability * 100},
        "decision": "BEOBACHTEN",
        "audit": {"valid": True},
        "expected_goals": {"hybrid_model": {"full5": {"applied": full5}}},
        "samples": {"home_venue": home_n, "away_venue": away_n},
        "diagnostics": {
            "data_quality": "HOCH",
            "sample_security": "HOCH",
            "robustness_status": "BESTANDEN" if robust else "NICHT BESTANDEN",
            "supplemental_inputs": {"coverage": {"player": {
                "home": {"players_found": home_depth},
                "away": {"players_found": away_depth},
            }}},
            "elite_protocol": {
                "confirming_blocks": applicable[:confirming],
                "counter_blocks": [f"C{i}" for i in range(counters)],
                "gates": {
                    "pre_match_integrity": {"strict_pre_match": strict},
                    "multi_block_confirmation": {
                        "confirmations": confirming,
                        "required": 4,
                        "status": "EINGESCHRÄNKT",
                    },
                },
            },
        },
    }


def ai_ranking(result, *, rank_stability=.90, learned_score=.72):
    key = result["strongest_market"]["key"]
    protocol = result["diagnostics"]["elite_protocol"]
    confirming = list(protocol.get("confirming_blocks") or [])
    counters = list(protocol.get("counter_blocks") or [])
    applicable = {
        "home_win": ["UNDERLYING", "MATCH", "FORM", "TABLE"],
        "away_win": ["UNDERLYING", "MATCH", "FORM", "TABLE"],
        "btts_yes": ["UNDERLYING", "MATCH", "FORM"],
        "btts_no": ["UNDERLYING", "MATCH", "FORM"],
        "over_2_5": ["UNDERLYING", "MATCH", "FORM", "PLAYER"],
        "under_2_5": ["UNDERLYING", "MATCH", "FORM", "PLAYER"],
    }[key]
    selected = {
        "market": key, "label": result["strongest_market"]["label"],
        "core_probability": result["probabilities"][key], "learned_score": learned_score,
        "score_gap": .08, "rank_stability": rank_stability,
        "confirming_blocks": confirming, "counter_blocks": counters,
        "confirmations": len(confirming), "counters": len(counters),
        "applicable_blocks": len(applicable), "applicable_block_names": applicable,
        "confirmation_ratio": len(confirming) / len(applicable), "sample_quality": .80,
    }
    candidates = []
    for index, market in enumerate(MARKET_KEYS):
        candidates.append({
            "market": market, "label": market, "core_probability": result["probabilities"][market],
            "learned_score": learned_score if market == key else .60 - index * .01,
        })
    return {"selected": selected, "second": candidates[0], "candidates": candidates, "model": {}}


def ai_policy(*, decision="SPIELEN", reliability=.70):
    return {
        "decision": decision, "reliability": reliability,
        "reliability_bootstrap_mean": reliability, "reliability_uncertainty": .02,
        "reliability_q10": reliability - .03, "reliability_q90": reliability + .03,
        "learned_observe_boundary": .6422845219898217,
        "learned_play_boundary": .6788983142117558,
        "boundary_provenance": "trained-test-policy",
        "final_decision_source": "TRAINED_AI_POLICY",
        "manual_performance_gates": "NONE",
        "integrity_gates": ["STRICT_PREMATCH", "FIVE_FILES", "AUDIT", "LEAKAGE", "REQUIRED_INPUTS"],
    }


def apply_ai(result, files=None, *, rank_stability=.90, learned_score=.72,
             policy_decision="SPIELEN", reliability=.70):
    with patch(
        "full5_next_engine.learned_ai.rank_markets",
        side_effect=lambda current, parsed: ai_ranking(
            current, rank_stability=rank_stability, learned_score=learned_score
        ),
    ), patch(
        "full5_next_engine.learned_ai.apply_abstention_policy",
        return_value=ai_policy(decision=policy_decision, reliability=reliability),
    ), patch(
        "full5_next_engine.learned_ai.load_model",
        return_value={"abstention_validation": {"matches": 60, "plays": 29, "hits": 18}},
    ):
        return apply_full5_next(result, files or five_files())


class Full5NextTests(unittest.TestCase):
    def test_01_probability_sums_valid(self):
        self.assertTrue(probability_sums_valid(result_template()["probabilities"]))

    def test_02_invalid_probability_sum_rejected(self):
        probabilities = result_template()["probabilities"]
        probabilities["draw"] += .1
        self.assertFalse(probability_sums_valid(probabilities))

    def test_03_all_six_markets_supported(self):
        for market in MARKET_KEYS:
            with self.subTest(market=market):
                output = apply_ai(result_template(key=market, probability=.60))
                self.assertEqual(output["full5_next"]["selected_market"], market)

    def test_04_all_five_sources_recognized(self):
        self.assertEqual(source_types(five_files()), set(SOURCE_TYPES))

    def test_05_sample_quality_high(self):
        self.assertEqual(sample_quality(result_template()), 1.0)

    def test_06_sample_quality_low(self):
        self.assertLess(sample_quality(result_template(home_n=1, away_n=1, home_depth=5, away_depth=5)), .40)

    def test_07_trained_policy_selects_play(self):
        output = apply_ai(result_template())
        self.assertEqual(output["decision"], "SPIELEN")

    def test_08_confirmations_do_not_gate_play(self):
        output = apply_ai(result_template(confirming=2))
        self.assertEqual(output["decision"], "SPIELEN")
        self.assertTrue(output["full5_next"]["confirmation_gate"]["diagnostic_only"])

    def test_09_counter_blocks_do_not_gate_play(self):
        output = apply_ai(result_template(counters=1))
        self.assertEqual(output["decision"], "SPIELEN")

    def test_10_robustness_boolean_does_not_gate_play(self):
        output = apply_ai(result_template(robust=False))
        self.assertEqual(output["decision"], "SPIELEN")

    def test_11_sample_quality_is_continuous_not_hard_cutoff(self):
        result = result_template(home_n=1, away_n=1, home_depth=5, away_depth=5)
        output = apply_ai(result)
        self.assertEqual(output["decision"], "SPIELEN")
        self.assertEqual(output["full5_next"]["MANUAL_PERFORMANCE_GATES"], "NONE")

    def test_12_non_strict_is_no_bet(self):
        output = apply_ai(result_template(strict=False))
        self.assertEqual(output["decision"], "AUSLASSEN / KEIN BET")

    def test_13_missing_source_is_no_bet(self):
        output = apply_ai(result_template(), five_files()[:-1])
        self.assertEqual(output["decision"], "AUSLASSEN / KEIN BET")
        invalid = result_template()
        invalid["audit"]["valid"] = False
        output = apply_ai(invalid)
        self.assertEqual(output["decision"], "AUSLASSEN / KEIN BET")

    def test_14_no_probability_cutoff(self):
        output = apply_ai(result_template(probability=.49))
        self.assertEqual(output["decision"], "SPIELEN")
        self.assertEqual(output["full5_next"]["FINAL_DECISION_SOURCE"], "TRAINED_AI_POLICY")

    def test_15_fallback_is_reported(self):
        output = apply_ai(result_template(full5=False))
        self.assertEqual(output["full5_next"]["full5_status"], "FALLBACK AUF V0.4.2")

    def test_16_explainability_complete(self):
        next_result = apply_ai(result_template())["full5_next"]
        self.assertTrue(next_result["positive_reasons"])
        self.assertTrue(next_result["why_this_market"])
        self.assertEqual(next_result["signal_conflict"], 0)

    def test_17_higher_probability_market_explained(self):
        output = apply_ai(result_template(key="home_win", probability=.40))
        self.assertIn("höhere Rohwahrscheinlichkeit", output["full5_next"]["why_not_higher_probability_market"])

    def test_18_core_probabilities_unchanged(self):
        result = result_template()
        before = copy.deepcopy(result["probabilities"])
        output = apply_ai(result)
        self.assertEqual(output["probabilities"], before)
        files = five_files()
        files[0]["data"] = {"data": {"team_a_xg": 2.0, "team_a_xg_prematch": 1.4}}
        self.assertEqual(blocked_target_fields(files), ["team_a_xg"])
        clean = sanitize_parsed_files(files)
        self.assertNotIn("team_a_xg", clean[0]["data"]["data"])
        self.assertEqual(clean[0]["data"]["data"]["team_a_xg_prematch"], 1.4)

    def test_19_btts_confirmation_export_is_three_of_three(self):
        result = result_template(key="btts_yes", probability=.70, confirming=3)
        before_probabilities = copy.deepcopy(result["probabilities"])
        output = apply_ai(result)
        gate = output["full5_next"]["confirmation_gate"]
        legacy_gate = output["diagnostics"]["elite_protocol"]["gates"]["multi_block_confirmation"]
        self.assertEqual(output["decision"], "SPIELEN")
        self.assertEqual(output["probabilities"], before_probabilities)
        self.assertEqual(gate["confirmations"], 3)
        self.assertEqual(gate["applicable_blocks"], 3)
        self.assertEqual(gate["required"], 3)
        self.assertEqual(gate["status"], "BESTANDEN")
        self.assertEqual(gate["applicable_block_names"], ["UNDERLYING", "MATCH", "FORM"])
        self.assertEqual(legacy_gate, gate)

    def test_20_unstable_ai_rank_is_continuous_not_gate(self):
        output = apply_ai(result_template(), rank_stability=.49)
        self.assertEqual(output["decision"], "SPIELEN")
        self.assertEqual(output["full5_next"]["rank_stability"], .49)

    def test_21_ai_failure_is_no_bet_without_core_change(self):
        result = result_template()
        before = copy.deepcopy(result["probabilities"])
        with patch("full5_next_engine.learned_ai.rank_markets", side_effect=ValueError("missing input")):
            output = apply_full5_next(result, five_files())
        self.assertEqual(output["decision"], "AUSLASSEN / KEIN BET")
        self.assertEqual(output["probabilities"], before)

    def test_22_all_six_ai_scores_exported(self):
        output = apply_ai(result_template())
        ranking = output["full5_next"]["market_ranking"]
        self.assertEqual(len(ranking), 6)
        self.assertTrue(all("learned_score" in item for item in ranking))

    def test_23_ai_score_does_not_replace_core_probability(self):
        output = apply_ai(result_template(probability=.61), learned_score=.83)
        self.assertEqual(output["full5_next"]["probability"], .61)
        self.assertEqual(output["full5_next"]["learned_correctness_score"], .83)

    def test_24_all_action_states_come_from_trained_policy(self):
        for decision in ("SPIELEN", "BEOBACHTEN", "AUSLASSEN / KEIN BET"):
            with self.subTest(decision=decision):
                output = apply_ai(result_template(), policy_decision=decision)
                self.assertEqual(output["decision"], decision)
                self.assertEqual(output["full5_next"]["policy_decision"], decision)
                self.assertFalse(output["full5_next"]["integrity_override"])

    def test_25_only_integrity_may_override_trained_policy(self):
        output = apply_ai(result_template(strict=False), policy_decision="SPIELEN")
        self.assertEqual(output["decision"], "AUSLASSEN / KEIN BET")
        self.assertTrue(output["full5_next"]["integrity_override"])
        self.assertFalse(output["full5_next"]["integrity_checks"]["STRICT_PREMATCH"])

    def test_26_leakage_integrity_gate_overrides_play(self):
        files = five_files()
        files[0]["data"] = {"team_a_xg": 2.4}
        output = apply_ai(result_template(), files, policy_decision="SPIELEN")
        self.assertEqual(output["decision"], "AUSLASSEN / KEIN BET")
        self.assertFalse(output["full5_next"]["integrity_checks"]["LEAKAGE"])


if __name__ == "__main__":
    unittest.main()
