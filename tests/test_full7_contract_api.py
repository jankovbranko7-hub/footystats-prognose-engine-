import unittest

import app as production_entry
import full7_contract_api
import full7_phase7_upload_api
from unittest.mock import patch
from full7_contract_decision import build_decision_engine
from full7_v3_live import predict_v3_live


def _sample_v3():
    gold = {
        "namespaces": {
            "league": {"league": {"data": {"country": "Brazil", "db_english_name": "Serie A"}}}
        }
    }
    gold_features = {
        "features": {
            "league_seasonAVG_home": 1.51,
            "league_seasonAVG_away": 1.15,
            "league_matchesCompleted": 265,
            "prematch_xg_home": 1.69,
            "prematch_xg_away": 1.18,
            "provider_o25_potential": 54,
            "provider_btts_potential": 62,
            "provider_avg_potential": 2.77,
            "prematch_ppg_home": 1.62,
            "prematch_ppg_away": 0.69,
        }
    }
    return predict_v3_live(gold, gold_features)


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

    def test_production_full7_predict_is_backed_by_final_rc_bridge(self):
        matching = [
            route for route in production_entry.app.routes
            if getattr(route, "path", None) == "/api/full7/predict"
        ]
        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0].endpoint.__module__, "full7_phase7_upload_api")
        self.assertEqual(matching[0].endpoint.__name__, "production_predict")

    def test_production_full7_health_is_backed_by_final_rc_bridge(self):
        matching = [
            route for route in production_entry.app.routes
            if getattr(route, "path", None) == "/api/full7/engine-health"
        ]
        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0].endpoint.__module__, "full7_phase7_upload_api")
        self.assertEqual(matching[0].endpoint.__name__, "production_health")

    def test_final_rc_health_declares_frozen_release_semantics(self):
        with patch("full7_phase7_upload_api._load_configured_runtime", return_value=object()):
            out = full7_phase7_upload_api.production_health()
        self.assertTrue(out["ok"])
        self.assertTrue(out["production_mounted"])
        self.assertEqual(out["engine"], "FOOTYSTATS_FULL7_FINAL")
        self.assertEqual(out["engine_version"], "FULL7_FINAL_RC_1.0.0")
        self.assertEqual(out["expected_files"], 7)
        self.assertEqual(out["spielen_allowed_families"], ["HOME", "AWAY", "BTTS_YES"])
        self.assertEqual(out["draw_status"], "AUSLASSEN_ONLY")
        self.assertEqual(out["btts_no_status"], "BEOBACHTEN_ONLY")
        self.assertEqual(out["o25_status"], "HOLD")
        self.assertFalse(out["legacy_v3_1_override_active"])

    def test_v3_health_exposes_live_authorized_decision_source_and_provenance(self):
        out = full7_contract_api.production_health()
        self.assertTrue(out["ok"])
        self.assertTrue(out["production_mounted"])
        self.assertEqual(out["engine"], "FOOTYSTATS_FULL7_CONTRACT")
        self.assertEqual(out["expected_files"], 7)
        self.assertEqual(len(out["markets"]), 7)
        self.assertTrue(out["all_markets_decision_enabled"])
        self.assertTrue(out["probability_mode_no_odds"])
        self.assertEqual(
            out["decision_architecture"],
            "V3_LIVE_META_FAMILY_MODELS_WITH_V2_DIAGNOSTIC_CORE",
        )
        self.assertEqual(out["decision_capable_families"], ["1X2", "BTTS", "TOTALS"])
        self.assertTrue(out["spielen_release_authorized"])
        self.assertEqual(out["release_status"], "LIVE_USER_AUTHORIZED_HISTORICAL_WALK_FORWARD")
        self.assertEqual(out["decision_source"], "FULL7_V3_1_LIVE_META")
        self.assertFalse(out["new_prospective_forward_oos_validated"])

    def test_release_view_uses_v3_for_final_playable_state(self):
        core = build_decision_engine({"features": {}, "feature_owners": {}})
        v3 = _sample_v3()
        released = full7_contract_api._production_release_view(core, v3)
        self.assertTrue(released["release_authorized"])
        self.assertTrue(released["v3_supported"])
        self.assertEqual(released["decision_source"], "FULL7_V3_1_LIVE_META")
        self.assertEqual(set(released["markets"]), set(core["markets"]))
        self.assertEqual(released["playable"], released["candidate_spielen"])
        self.assertIn("v2_reference", released)

    def test_release_view_fails_closed_when_v3_inputs_are_missing(self):
        core = build_decision_engine({"features": {}, "feature_owners": {}})
        released = full7_contract_api._production_release_view(
            core,
            {"supported": False, "missing_inputs": ["prematch_xg_home"]},
        )
        self.assertEqual(released["playable"], [])
        self.assertFalse(released["v3_supported"])
        for row in released["markets"].values():
            self.assertEqual(row["decision"], "AUSLASSEN")


if __name__ == "__main__":
    unittest.main()
