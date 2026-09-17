import unittest

from full7_contract_engine import MARKETS
from full7_contract_ensemble import (
    CALIBRATION_POLICY,
    ENSEMBLE_POLICY,
    ensemble_and_calibrate,
)


class Full7ContractEnsembleTests(unittest.TestCase):
    def test_every_market_has_ensemble_and_calibrated_probability(self):
        out = ensemble_and_calibrate({"features": {}})
        self.assertEqual(set(out["ensemble"]), set(MARKETS))
        self.assertEqual(set(out["calibrated"]), set(MARKETS))
        self.assertEqual(set(out["model_disagreement"]), set(MARKETS))

    def test_ensemble_weights_are_coherent(self):
        for family, policy in ENSEMBLE_POLICY.items():
            self.assertAlmostEqual(
                policy["catboost_weight"] + policy["goal_weight"], 1.0, places=10
            )
            self.assertIn("PROSPECTIVE", policy["selection"])

    def test_learned_strategy_is_not_a_manual_universal_mix(self):
        self.assertEqual(ENSEMBLE_POLICY["1X2"]["strategy"], "CATBOOST_ONLY")
        self.assertEqual(ENSEMBLE_POLICY["BTTS"]["strategy"], "GOAL_ONLY")
        self.assertEqual(ENSEMBLE_POLICY["TOTALS"]["strategy"], "LEARNED_BLEND")
        self.assertAlmostEqual(
            ENSEMBLE_POLICY["TOTALS"]["catboost_weight"],
            0.5317803953799852,
            places=10,
        )

    def test_identity_calibration_is_explicit(self):
        out = ensemble_and_calibrate({"features": {}})
        for family in ("1X2", "BTTS", "TOTALS"):
            self.assertEqual(CALIBRATION_POLICY[family]["method"], "IDENTITY")
        self.assertEqual(out["ensemble"], out["calibrated"])

    def test_calibrated_probabilities_are_coherent(self):
        out = ensemble_and_calibrate({"features": {}})
        self.assertAlmostEqual(out["coherence"]["one_x_two_sum"], 1.0, places=7)
        self.assertAlmostEqual(out["coherence"]["btts_sum"], 1.0, places=7)
        self.assertAlmostEqual(out["coherence"]["totals_sum"], 1.0, places=7)


if __name__ == "__main__":
    unittest.main()
