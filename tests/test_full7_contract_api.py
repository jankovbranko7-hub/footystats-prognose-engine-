import unittest

import app as production_entry
import full7_contract_api


class Full7ContractPreviewApiTests(unittest.TestCase):
    def test_preview_health_declares_development_only(self):
        out = full7_contract_api.health()
        self.assertTrue(out["ok"])
        self.assertTrue(out["development_only"])
        self.assertFalse(out["production_mounted"])
        self.assertTrue(out["new_untouched_oos_required"])
        self.assertEqual(out["expected_files"], 7)
        self.assertEqual(len(out["markets"]), 7)

    def test_preview_routes_exist_in_standalone_app(self):
        paths = {
            getattr(route, "path", None)
            for route in full7_contract_api.app.routes
        }
        self.assertIn("/api/full7/contract-preview", paths)
        self.assertIn("/api/full7/contract-preview/health", paths)

    def test_preview_routes_are_not_mounted_in_production(self):
        paths = {
            getattr(route, "path", None)
            for route in production_entry.app.routes
        }
        self.assertNotIn("/api/full7/contract-preview", paths)
        self.assertNotIn("/api/full7/contract-preview/health", paths)

    def test_production_full7_predict_is_backed_by_contract_engine(self):
        matching = [
            route
            for route in production_entry.app.routes
            if getattr(route, "path", None) == "/api/full7/predict"
        ]
        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0].endpoint.__module__, "full7_contract_api")
        self.assertEqual(matching[0].endpoint.__name__, "production_predict")

    def test_production_full7_health_is_backed_by_contract_engine(self):
        matching = [
            route
            for route in production_entry.app.routes
            if getattr(route, "path", None) == "/api/full7/engine-health"
        ]
        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0].endpoint.__module__, "full7_contract_api")
        self.assertEqual(matching[0].endpoint.__name__, "production_health")

    def test_production_health_declares_final_contract_release(self):
        out = full7_contract_api.production_health()
        self.assertTrue(out["ok"])
        self.assertTrue(out["production_mounted"])
        self.assertEqual(out["engine"], "FOOTYSTATS_FULL7_CONTRACT")
        self.assertEqual(out["engine_version"], "FULL7_CONTRACT_1.0.0")
        self.assertEqual(out["expected_files"], 7)
        self.assertEqual(len(out["markets"]), 7)
        self.assertTrue(out["all_markets_decision_enabled"])
        self.assertTrue(out["probability_mode_no_odds"])
        self.assertEqual(out["release_status"], "SELECTIVE_PRODUCTION_BTTS_ONLY")
        self.assertEqual(out["family_readiness"]["1X2"], "OBSERVE_ONLY")
        self.assertEqual(out["family_readiness"]["BTTS"], "SELECTIVE")
        self.assertEqual(out["family_readiness"]["TOTALS"], "OBSERVE_ONLY")
        self.assertEqual(out["spielen_allowed_families"], ["BTTS"])


if __name__ == "__main__":
    unittest.main()
