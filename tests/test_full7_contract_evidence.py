import unittest

from full7_contract_engine import MARKETS
from full7_contract_evidence import (
    EVIDENCE_ENGINE_VERSION,
    REFERENCE,
    build_evidence_engine,
)


class Full7ContractEvidenceTests(unittest.TestCase):
    def test_evidence_engine_covers_all_markets_without_inventing_decisions(self):
        out = build_evidence_engine({"features": {}, "feature_owners": {}})
        self.assertEqual(out["evidence_engine_version"], "FULL7_CONTRACT_EVIDENCE_1.0")
        self.assertEqual(set(out["market_evidence"]), set(MARKETS))
        self.assertEqual(
            set(out["decision_layer"]["markets"]),
            set(MARKETS),
        )
        self.assertTrue(
            all(value == "DECISION_COMPUTED_IN_DECISION_ENGINE" for value in out["decision_layer"]["markets"].values())
        )
        self.assertEqual(
            out["decision_layer"]["status"],
            "DELEGATED_TO_FULL7_CONTRACT_DECISION",
        )

    def test_reference_is_empirical_and_complete(self):
        self.assertEqual(REFERENCE["development_rows"], 300)
        self.assertEqual(REFERENCE["feature_count"], 620)
        self.assertIn("EXPECTED_GOALS_XGA", REFERENCE["groups"])
        self.assertIn("player", REFERENCE["clusters"])
        self.assertIn("home_win", REFERENCE["model_disagreement"])

    def test_player_subgroups_share_one_independent_cluster(self):
        gold = {
            "features": {
                "home_active_players": 20.0,
                "home_goals_per90_minutes_weighted": 0.3,
                "home_top3_goal_share": 0.65,
            },
            "feature_owners": {
                "home_active_players": "player_depth_quality_concentration",
                "home_goals_per90_minutes_weighted": "player_depth_quality_concentration",
                "home_top3_goal_share": "player_depth_quality_concentration",
            },
        }
        out = build_evidence_engine(gold)
        self.assertIn("player", out["independent_clusters"])
        self.assertEqual(
            sum(1 for key in out["independent_clusters"] if key == "player"),
            1,
        )

    def test_data_quality_reports_missingness_and_no_fake_score(self):
        out = build_evidence_engine({"features": {}, "feature_owners": {}})
        q = out["data_quality"]
        self.assertEqual(q["finite_core_feature_count"], 0)
        self.assertEqual(q["core_feature_coverage"], 0.0)
        self.assertIsNone(q["score"])
        self.assertEqual(q["score_status"], "EMPIRICAL_SUPPORT_CHECK_ACTIVE")

    def test_coherence_is_checked_for_all_probability_families(self):
        out = build_evidence_engine({"features": {}, "feature_owners": {}})
        self.assertTrue(out["coherence_ood"]["probability_sums_pass"])

    def test_h2h_referee_manager_are_not_silently_weighted_without_validation(self):
        out = build_evidence_engine({"features": {}, "feature_owners": {}})
        for key in ("H2H", "REFEREE", "MANAGER"):
            self.assertFalse(out["secondary_context"][key]["decision_weight_validated"])


if __name__ == "__main__":
    unittest.main()
