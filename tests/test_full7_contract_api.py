import unittest

import app as production_entry
import full7_contract_api
from full7_contract_decision import build_decision_engine


class Full7ContractPreviewApiTests(unittest.TestCase):
    def test_preview_health_declares_v2_development_only(self):
        out = full7_contract_api.health()
        self.assertTrue(out["ok"])
        self.assertTrue(out["development_only"])
        self.assertFalse(out["production_mounted"])
        self.assertTrue(out["new_untouched_oos_required"])
        self.assertEqual(out["expected_files"], 7)
        self.assertEqual(len(out["markets"]), 7)
        self.assertEqual(out["decision_architecture"], "SEVEN_MARKET_RAW_HEADS_THEN_COHERENCE")

    def test_preview_routes_exist_in_standalone_app(self):
        paths = {getattr(route, "path", None) for route in full7_contract_api.app.routes}
        self.assertIn("/api/full7/contract-preview", paths)
        self.assertIn("/api/full7/contract-preview/health", paths)

    def test_preview_routes_are_not_mounted_in_production(self):
        paths = {getattr(route, "path", None) for route in production_entry.app.routes}
        self.assertNotIn("/api/full7/contract-preview", paths)
        self.assertNotIn("/api/full7/contract-preview/health", paths)

    def test_production_full7_predict_is_backed_by_contract_engine(self):
        matching = [
            route for route in production_entry.app.routes
            if getattr(route, "path", None) == "/api/full7/predict"
        ]
        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0].endpoint.__module__, "full7_contract_api")
        self.assertEqual(matching[0].endpoint.__name__, "production_predict")

    def test_production_full7_health_is_backed_by_contract_engine(self):
        matching = [
            route for route in production_entry.app.routes
            if getattr(route, "path", None) == "/api/full7/engine-health"
        ]
        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0].endpoint.__module__, "full7_contract_api")
        self.assertEqual(matching[0].endpoint.__name__, "production_health")

    def test_v2_health_exposes_seven_decision_capable_markets_but_no_release_authorization(self):
        out = full7_contract_api.production_health()
        self.assertTrue(out["ok"])
        self.assertTrue(out["production_mounted"])
        self.assertEqual(out["engine"], "FOOTYSTATS_FULL7_CONTRACT")
        self.assertEqual(out["expected_files"], 7)
        self.assertEqual(len(out["markets"]), 7)
        self.assertTrue(out["all_markets_decision_enabled"])
        self.assertTrue(out["probability_mode_no_odds"])
        self.assertEqual(out["decision_architecture"], "SEVEN_MARKET_RAW_HEADS_THEN_COHERENCE")
        self.assertEqual(out["decision_capable_families"], ["1X2", "BTTS", "TOTALS"])
        self.assertFalse(out["spielen_release_authorized"])
        self.assertEqual(out["release_status"], "BLOCKED_PENDING_V2_FORWARD_OOS")

    def test_release_view_never_labels_v2_candidates_playable_while_gate_is_blocked(self):
        core = build_decision_engine({"features": {}, "feature_owners": {}})
        released = full7_contract_api._production_release_view(core)
        self.assertFalse(released["release_authorized"])
        self.assertEqual(released["playable"], [])
        self.assertEqual(set(released["markets"]), set(core["markets"]))
        for market, row in released["markets"].items():
            self.assertIn("raw_reliability_score", row, market)
            self.assertIn("raw_decision", row, market)


if __name__ == "__main__":
    unittest.main()
