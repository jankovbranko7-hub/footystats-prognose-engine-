import unittest

from full7_contract_api import RELEASE_STATUS, _production_release_view
from full7_contract_decision import build_decision_engine


class Full7ReleaseStateTests(unittest.TestCase):
    def test_production_view_reports_completed_release_without_mutating_core(self):
        gold = {"features": {}, "feature_owners": {}}
        core = build_decision_engine(gold)
        released = _production_release_view(core)

        self.assertEqual(core["status"], "DEVELOPMENT_ONLY_NEW_UNTOUCHED_OOS_REQUIRED")
        self.assertEqual(core["contract_stage"]["new_untouched_oos"], "PENDING")

        self.assertEqual(released["status"], RELEASE_STATUS)
        self.assertTrue(all(value is True for value in released["contract_stage"].values()))
        self.assertEqual(released["evidence"]["status"], RELEASE_STATUS)
        self.assertEqual(released["evidence"]["probability_layer"]["status"], RELEASE_STATUS)
        self.assertTrue(all(
            value is True
            for value in released["evidence"]["probability_layer"]["contract_stage"].values()
        ))
        self.assertEqual(
            released["evidence"]["probability_layer"]["model_support"]["status"],
            RELEASE_STATUS,
        )
        self.assertTrue(all(
            value is True
            for value in released["evidence"]["probability_layer"]["model_support"]["contract_stage"].values()
        ))

    def test_production_view_preserves_probabilities_and_decisions(self):
        core = build_decision_engine({"features": {}, "feature_owners": {}})
        released = _production_release_view(core)
        self.assertEqual(released["probabilities"], core["probabilities"])
        self.assertEqual(released["families"], core["families"])
        self.assertEqual(released["markets"], core["markets"])


if __name__ == "__main__":
    unittest.main()
