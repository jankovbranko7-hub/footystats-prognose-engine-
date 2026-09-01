#!/usr/bin/env python3
import copy
import unittest

from v041_decision_gate import direct_counter_edge, evaluate_v041


def analysis_fixture():
    return {
        "decision": "BEOBACHTEN",
        "method": {"empirical_bayes_shrinkage": True},
        "strongest_market": {"key": "btts_yes", "probability_pct": 66.0},
        "probabilities": {
            "home_win": 0.42,
            "draw": 0.25,
            "away_win": 0.33,
            "btts_yes": 0.66,
            "btts_no": 0.34,
            "over_2_5": 0.65,
            "under_2_5": 0.35,
        },
        "samples": {"security": "NIEDRIG"},
        "diagnostics": {
            "data_quality": "HOCH",
            "result_vs_underlying": "KONSISTENT",
            "single_point_of_failure": False,
            "elite_protocol": {
                "gates": {
                    "multi_block_confirmation": "BESTANDEN",
                    "counterargument": {"status": "KEIN RELEVANTES"},
                    "influence_removal": {"status": "BESTANDEN"},
                    "fragility_removal": {"status": "BESTANDEN"},
                    "data_quality": "HOCH",
                    "coherence": {"passed": True},
                }
            },
        },
    }


class V041GateTests(unittest.TestCase):
    def test_edge_uses_direct_counter_not_correlated_second_market(self):
        edge = direct_counter_edge(analysis_fixture())
        self.assertEqual(edge["counter_market"], "btts_no")
        self.assertEqual(edge["difference_pp"], 32.0)
        self.assertEqual(edge["status"], "KLAR")

    def test_low_sample_can_be_compensated_only_with_all_stress_guards(self):
        result = evaluate_v041(analysis_fixture())
        self.assertEqual(result["decision"], "SPIELEN")
        self.assertEqual(result["sample_gate"]["status"], "KOMPENSIERT_DURCH_SHRINKAGE_UND_STRESSTESTS")

    def test_failed_removal_keeps_observe(self):
        analysis = analysis_fixture()
        analysis["diagnostics"]["elite_protocol"]["gates"]["influence_removal"]["status"] = "EINGESCHRÄNKT"
        result = evaluate_v041(analysis)
        self.assertEqual(result["decision"], "BEOBACHTEN")
        self.assertFalse(result["play_checks"]["sample_reliability"])

    def test_strong_underlying_contradiction_forces_skip(self):
        analysis = analysis_fixture()
        analysis["diagnostics"]["result_vs_underlying"] = "STARK WIDERSPRÜCHLICH"
        analysis["decision"] = "AUSLASSEN"
        self.assertEqual(evaluate_v041(analysis)["decision"], "AUSLASSEN")

    def test_probability_below_65_stays_observe(self):
        analysis = analysis_fixture()
        analysis["strongest_market"]["probability_pct"] = 64.9
        analysis["probabilities"]["btts_yes"] = 0.649
        analysis["probabilities"]["btts_no"] = 0.351
        self.assertEqual(evaluate_v041(analysis)["decision"], "BEOBACHTEN")

    def test_outcomes_cannot_change_gate_result(self):
        analysis = analysis_fixture()
        polluted = copy.deepcopy(analysis)
        polluted["actual_score"] = "0:0"
        polluted["strongest_market_hit"] = False
        self.assertEqual(evaluate_v041(analysis), evaluate_v041(polluted))

    def test_non_promoted_reports_keep_v040_decision(self):
        analysis = analysis_fixture()
        analysis["strongest_market"]["probability_pct"] = 61.0
        analysis["decision"] = "AUSLASSEN"
        self.assertEqual(evaluate_v041(analysis)["decision"], "AUSLASSEN")


if __name__ == "__main__":
    unittest.main()
