import unittest

from full7_contract_engine import (
    MARKETS,
    MODEL_FOUNDATION_VERSION,
    contract_model_support,
)
from full7_market_feature_sets import build_market_feature_sets
from full7_signal_groups import ALL_MARKETS, GROUP_META


class Full7ContractModelFoundationTests(unittest.TestCase):
    def test_all_seven_markets_have_both_model_sources(self):
        out = contract_model_support({"features": {}})
        self.assertEqual(out["model_foundation_version"], "FULL7_CONTRACT_MODEL_FOUNDATION_1.0")
        self.assertEqual(tuple(out["markets"]), MARKETS)
        self.assertEqual(set(out["catboost"]), set(MARKETS))
        self.assertEqual(set(out["goal_model"]), set(MARKETS))
        self.assertEqual(out["feature_count"], 620)
        self.assertTrue(out["same_broad_core_all_target_families"])

    def test_probability_families_are_coherent(self):
        out = contract_model_support({"features": {}})
        c = out["coherence"]
        for key, value in c.items():
            self.assertAlmostEqual(value, 1.0, places=7, msg=key)

    def test_missing_features_do_not_invent_coverage(self):
        out = contract_model_support({"features": {}})
        self.assertEqual(out["feature_coverage"], 0.0)
        self.assertEqual(out["status"], "DEVELOPMENT_ONLY")
        self.assertEqual(out["contract_stage"]["oos_ensemble"], "PENDING")
        self.assertEqual(out["contract_stage"]["decision_all_7"], "PENDING")

    def test_same_broad_core_is_offered_to_all_target_families(self):
        sample = [
            "prematch_xg_home",
            "table_overall_ppg_diff",
            "home_last5_shotsAVG_overall",
            "home_top3_goal_share",
            "home_overall_seasonBTTSPercentageHT",
        ]
        out = build_market_feature_sets(sample)
        self.assertEqual(out["markets"]["1X2"], out["markets"]["BTTS"])
        self.assertEqual(out["markets"]["BTTS"], out["markets"]["TOTALS"])
        self.assertFalse(out["policy"]["hard_market_domain_exclusions"])

    def test_evidence_architecture_covers_all_markets(self):
        for group in (
            "EXPECTED_GOALS_XGA", "GOALS_DEFENCE", "VENUE_STRENGTH",
            "CURRENT_FORM", "LEAGUE_CONTEXT", "TABLE_STRENGTH",
            "SHOTS_CHANCE_CREATION", "FIRST_SECOND_HALF", "BTTS_OU_PROFILE",
            "PLAYER_DEPTH", "PLAYER_QUALITY", "PLAYER_CONCENTRATION",
            "H2H_SECONDARY", "REFEREE", "MANAGER", "MATCH_CONTEXT",
        ):
            self.assertEqual(tuple(GROUP_META[group]["markets"]), ALL_MARKETS)
        self.assertTrue(GROUP_META["H2H_SECONDARY"]["evidence_eligible"])


if __name__ == "__main__":
    unittest.main()
