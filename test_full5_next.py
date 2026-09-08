from __future__ import annotations

import copy
import unittest

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
                "confirming_blocks": [f"B{i}" for i in range(confirming)],
                "counter_blocks": [f"C{i}" for i in range(counters)],
                "gates": {"pre_match_integrity": {"strict_pre_match": strict}},
            },
        },
    }


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
                output = apply_full5_next(result_template(key=market, probability=.60), five_files())
                self.assertEqual(output["full5_next"]["selected_market"], market)

    def test_04_all_five_sources_recognized(self):
        self.assertEqual(source_types(five_files()), set(SOURCE_TYPES))

    def test_05_sample_quality_high(self):
        self.assertEqual(sample_quality(result_template()), 1.0)

    def test_06_sample_quality_low(self):
        self.assertLess(sample_quality(result_template(home_n=1, away_n=1, home_depth=5, away_depth=5)), .40)

    def test_07_play_gate(self):
        output = apply_full5_next(result_template(), five_files())
        self.assertEqual(output["decision"], "SPIELEN")

    def test_08_two_confirmations_observe(self):
        output = apply_full5_next(result_template(confirming=2), five_files())
        self.assertEqual(output["decision"], "BEOBACHTEN")

    def test_09_counter_blocks_play(self):
        output = apply_full5_next(result_template(counters=1), five_files())
        self.assertEqual(output["decision"], "BEOBACHTEN")

    def test_10_robustness_blocks_play(self):
        output = apply_full5_next(result_template(robust=False), five_files())
        self.assertEqual(output["decision"], "BEOBACHTEN")

    def test_11_low_sample_blocks_play(self):
        result = result_template(home_n=1, away_n=1, home_depth=5, away_depth=5)
        output = apply_full5_next(result, five_files())
        self.assertEqual(output["decision"], "BEOBACHTEN")

    def test_12_non_strict_is_no_bet(self):
        output = apply_full5_next(result_template(strict=False), five_files())
        self.assertEqual(output["decision"], "AUSLASSEN / KEIN BET")

    def test_13_missing_source_is_no_bet(self):
        output = apply_full5_next(result_template(), five_files()[:-1])
        self.assertEqual(output["decision"], "AUSLASSEN / KEIN BET")
        invalid = result_template()
        invalid["audit"]["valid"] = False
        output = apply_full5_next(invalid, five_files())
        self.assertEqual(output["decision"], "AUSLASSEN / KEIN BET")

    def test_14_below_observe_is_no_bet(self):
        output = apply_full5_next(result_template(probability=.49), five_files())
        self.assertEqual(output["decision"], "AUSLASSEN / KEIN BET")

    def test_15_fallback_is_reported(self):
        output = apply_full5_next(result_template(full5=False), five_files())
        self.assertEqual(output["full5_next"]["full5_status"], "FALLBACK AUF V0.4.2")

    def test_16_explainability_complete(self):
        next_result = apply_full5_next(result_template(), five_files())["full5_next"]
        self.assertTrue(next_result["positive_reasons"])
        self.assertTrue(next_result["why_this_market"])
        self.assertEqual(next_result["signal_conflict"], 0)

    def test_17_higher_probability_market_explained(self):
        output = apply_full5_next(result_template(key="home_win", probability=.40), five_files())
        self.assertIn("höhere Rohwahrscheinlichkeit", output["full5_next"]["why_not_higher_probability_market"])

    def test_18_core_probabilities_unchanged(self):
        result = result_template()
        before = copy.deepcopy(result["probabilities"])
        output = apply_full5_next(result, five_files())
        self.assertEqual(output["probabilities"], before)
        files = five_files()
        files[0]["data"] = {"data": {"team_a_xg": 2.0, "team_a_xg_prematch": 1.4}}
        self.assertEqual(blocked_target_fields(files), ["team_a_xg"])
        clean = sanitize_parsed_files(files)
        self.assertNotIn("team_a_xg", clean[0]["data"]["data"])
        self.assertEqual(clean[0]["data"]["data"]["team_a_xg_prematch"], 1.4)


if __name__ == "__main__":
    unittest.main()
