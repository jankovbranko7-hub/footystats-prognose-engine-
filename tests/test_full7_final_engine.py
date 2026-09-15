import math
import unittest

import app as production_entry
from full7_final_engine import (
    BTTS_PLAY_CONFIDENCE,
    ENGINE_VERSION,
    READINESS,
    predict_gold_features,
)


class Full7FinalEngineTests(unittest.TestCase):
    def test_engine_version_and_readiness(self):
        self.assertEqual(ENGINE_VERSION, "FULL7_GATED_1.0.0")
        self.assertEqual(READINESS["BTTS"], "OOS_VALIDATED_SELECTIVE")
        self.assertEqual(READINESS["1X2"], "OOS_OBSERVE_ONLY")
        self.assertEqual(READINESS["TOTALS"], "OOS_OBSERVE_ONLY")
        self.assertAlmostEqual(BTTS_PLAY_CONFIDENCE, 0.632489, places=6)

    def test_model_bundle_loads_and_fail_closed_on_missing_features(self):
        out = predict_gold_features({"features": {}})
        p = out["probabilities"]
        self.assertAlmostEqual(p["home_win"] + p["draw"] + p["away_win"], 1.0, places=7)
        self.assertAlmostEqual(p["btts_yes"] + p["btts_no"], 1.0, places=7)
        self.assertAlmostEqual(p["over_2_5"] + p["under_2_5"], 1.0, places=7)
        self.assertEqual(out["decision"]["decision"], "AUSLASSEN")
        self.assertFalse(out["decision"]["integrity_ok"])

    def test_model_feature_counts_are_frozen(self):
        out = predict_gold_features({"features": {}})
        self.assertEqual(out["model_integrity"]["feature_counts"]["core"], 620)
        self.assertEqual(out["model_integrity"]["feature_counts"]["btts"], 594)
        self.assertEqual(out["model_integrity"]["feature_counts"]["totals"], 556)

    def test_production_routes_mounted(self):
        paths = {getattr(route, "path", None) for route in production_entry.app.routes}
        self.assertIn("/api/full7/predict", paths)
        self.assertIn("/api/full7/engine-health", paths)
        self.assertIn("/api/full7/validate", paths)


if __name__ == "__main__":
    unittest.main()
