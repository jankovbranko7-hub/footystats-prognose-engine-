import unittest

from full7_contract_api import RELEASE_STATUS, _production_release_view
from full7_contract_decision import build_decision_engine


class Full7ReleaseStateTests(unittest.TestCase):
    def test_production_view_reports_release_without_mutating_fit_provenance(self):
        gold = {"features": {}, "feature_owners": {}}
        core = build_decision_engine(gold)
        released = _production_release_view(core)

        self.assertEqual(core["status"], "DEVELOPMENT_ONLY_NEW_UNTOUCHED_OOS_REQUIRED")
        self.assertEqual(core["contract_stage"]["new_untouched_oos"], "PENDING")

        self.assertEqual(released["status"], RELEASE_STATUS)
        self.assertEqual(released["contract_stage"], core["contract_stage"])
        self.assertEqual(released["evidence"]["status"], core["evidence"]["status"])
        self.assertEqual(
            released["evidence"]["probability_layer"]["status"],
            core["evidence"]["probability_layer"]["status"],
        )
        self.assertEqual(
            released["evidence"]["probability_layer"]["contract_stage"],
            core["evidence"]["probability_layer"]["contract_stage"],
        )
        self.assertEqual(
            released["evidence"]["probability_layer"]["model_support"]["status"],
            core["evidence"]["probability_layer"]["model_support"]["status"],
        )
        self.assertEqual(
            released["evidence"]["probability_layer"]["model_support"]["contract_stage"],
            core["evidence"]["probability_layer"]["model_support"]["contract_stage"],
        )

    def test_production_view_preserves_probabilities_and_decisions(self):
        core = build_decision_engine({"features": {}, "feature_owners": {}})
        released = _production_release_view(core)
        self.assertEqual(released["probabilities"], core["probabilities"])
        self.assertEqual(released["families"], core["families"])
        self.assertEqual(released["markets"], core["markets"])


if __name__ == "__main__":
    unittest.main()
