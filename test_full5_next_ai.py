from __future__ import annotations

import copy
import unittest
from unittest.mock import patch

from full5_next_ai import (
    FEATURE_NAMES, MARKETS, POLICY_FEATURE_NAMES, _predict, candidate_features,
    load_model, rank_markets,
)


def flat_inputs():
    return {
        "baseline_home_win": .42, "baseline_draw": .28, "baseline_away_win": .30,
        "baseline_btts_yes": .61, "baseline_btts_no": .39,
        "baseline_over_2_5": .64, "baseline_under_2_5": .36,
        "match_prematch_xg_home": 1.45, "match_prematch_xg_away": 1.20,
        "match_prematch_xg_total": 2.65, "match_ppg_diff": .40,
        "league_ppg_diff": .35, "league_btts_mean": 58.0, "league_over25_mean": 62.0,
        "league_first_half_btts_mean": 24.0, "league_first_half_goals_avg_mean": 1.15,
        "league_second_half_goals_avg_mean": 1.50, "btts_zero_goal_support": 70.0,
        "form5_ppg_diff": .20, "form10_ppg_diff": .30,
        "form10_btts_mean": 65.0, "form10_over25_mean": 60.0,
        "table_ppg_diff": .45,
        "player_contribution_per90_home": .31, "player_contribution_per90_away": .27,
        "player_depth_min": 24.0, "league_matches_mean": 10.0,
    }


class Full5NextAiTests(unittest.TestCase):
    def test_01_six_candidates_and_feature_contract(self):
        candidates = candidate_features(flat_inputs())
        self.assertEqual([candidate["market"] for candidate in candidates], list(MARKETS))
        self.assertTrue(all(tuple(candidate["features"]) == FEATURE_NAMES for candidate in candidates))

    def test_02_btts_uses_three_applicable_blocks(self):
        btts = next(candidate for candidate in candidate_features(flat_inputs()) if candidate["market"] == "btts_yes")
        self.assertEqual(btts["applicable_blocks"], 3)
        self.assertEqual(btts["applicable_block_names"], ["UNDERLYING", "MATCH", "FORM"])

    def test_03_missing_value_is_not_imputed(self):
        inputs = flat_inputs()
        inputs["form10_btts_mean"] = None
        with self.assertRaisesRegex(ValueError, "form10_btts_mean"):
            candidate_features(inputs)

    def test_04_model_artifact_is_complete(self):
        model = load_model()
        self.assertEqual(model["training_matches"], 247)
        self.assertEqual(model["training_candidates"], 1482)
        self.assertEqual(len(model["bootstrap_models"]), 80)
        self.assertEqual(len(model["central_model"]["coefficient"]), len(FEATURE_NAMES))
        self.assertEqual(model["decision_policy"]["final_decision_source"], "TRAINED_AI_POLICY")
        self.assertEqual(model["decision_policy"]["manual_performance_gates"], [])
        self.assertEqual(len(model["abstention_policy"]["feature_names"]), len(POLICY_FEATURE_NAMES))
        self.assertEqual(len(model["abstention_policy"]["bootstrap_models"]), 80)
        self.assertEqual(model["abstention_validation"]["former_87_match_oos_rows_used"], 0)

    def test_05_scores_are_deterministic_and_bounded(self):
        model = load_model()["central_model"]
        features = candidate_features(flat_inputs())[0]["features"]
        first = _predict(model, features)
        second = _predict(model, copy.deepcopy(features))
        self.assertEqual(first, second)
        self.assertGreater(first, 0)
        self.assertLess(first, 1)

    def test_06_real_ranker_exports_stability(self):
        with patch("full5_next_ai._live_inputs", return_value=flat_inputs()):
            ranked = rank_markets({}, [])
        self.assertIn(ranked["selected"]["market"], MARKETS)
        self.assertGreaterEqual(ranked["selected"]["rank_stability"], 0)
        self.assertLessEqual(ranked["selected"]["rank_stability"], 1)
        self.assertEqual(len(ranked["candidates"]), 6)


if __name__ == "__main__":
    unittest.main()
