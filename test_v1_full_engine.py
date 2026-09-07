import unittest

import v042_engine
import v043_engine
import v043_release
import v1_full_engine


class DummyLegacy:
    @staticmethod
    def num(value):
        if value is None or isinstance(value, bool):
            return None
        try:
            return float(value)
        except Exception:
            return None

    @staticmethod
    def match_obj(data):
        return data


class V1FullUnitTests(unittest.TestCase):
    def test_all_six_markets_are_explicit(self):
        self.assertEqual(
            v1_full_engine.MARKETS,
            (
                "home_win", "away_win", "btts_yes", "btts_no",
                "over_2_5", "under_2_5",
            ),
        )

    def test_probability_core_lock_is_unchanged(self):
        self.assertEqual(v043_engine.FEATURE_COUNT, 40)
        self.assertEqual(v043_release.FULL5_ALPHA, 3.0)
        self.assertEqual(v042_engine.RHO, -0.25)
        self.assertFalse(hasattr(v1_full_engine, "_predict_lambda"))

    def test_consensus_requires_unopposed_multi_signal_agreement(self):
        yes = v1_full_engine._consensus_direction(
            ["BTTS_YES", "BTTS_YES"], "BTTS_YES", "BTTS_NO"
        )
        mixed = v1_full_engine._consensus_direction(
            ["BTTS_YES", "BTTS_NO", "BTTS_YES"], "BTTS_YES", "BTTS_NO"
        )
        single = v1_full_engine._consensus_direction(
            ["BTTS_YES"], "BTTS_YES", "BTTS_NO"
        )
        self.assertEqual(yes["direction"], "BTTS_YES")
        self.assertEqual(mixed["direction"], "GEMISCHT")
        self.assertEqual(single["direction"], "GEMISCHT")

    def test_leakage_guard_blocks_target_live_and_gpt_fields(self):
        payload = {
            "homeGoalCount": 2,
            "team_a_xg": 1.8,
            "gpt_en": "prediction text",
            "team_a_xg_prematch": 1.2,
        }
        guard = v1_full_engine._leakage_guard(DummyLegacy(), payload)
        blocked = set(guard["blocked_fields_present_and_ignored"])
        self.assertIn("homeGoalCount", blocked)
        self.assertIn("team_a_xg", blocked)
        self.assertIn("gpt_en", blocked)
        self.assertNotIn("team_a_xg_prematch", blocked)
        self.assertFalse(guard["target_live_fields_used"])
        self.assertFalse(guard["gpt_en_used"])

    def test_double_counting_guard_preserves_classic_structural_blocks(self):
        guard = v1_full_engine._double_counting_guard()
        self.assertEqual(guard["INDEPENDENT_CONFIRMATION"]["BTTS"], ["UNDERLYING", "MATCH", "FORM"])
        self.assertEqual(guard["INDEPENDENT_CONFIRMATION"]["1X2"], ["UNDERLYING", "MATCH", "FORM", "TABLE"])
        self.assertEqual(guard["INDEPENDENT_CONFIRMATION"]["OU_2_5"], ["UNDERLYING", "MATCH", "FORM", "PLAYER"])
        self.assertFalse(guard["specialists_added_to_confirmation_count"])
        self.assertFalse(guard["last5_last6_last10_counted_separately"])

    def test_robust_selection_prefers_playable_market_over_higher_observe(self):
        assessments = [
            {"key": "btts_yes", "decision": "BEOBACHTEN", "probability_pct": 70.0, "family_strength_pct": 40.0},
            {"key": "over_2_5", "decision": "SPIELEN", "probability_pct": 66.0, "family_strength_pct": 32.0},
        ]
        chosen = v1_full_engine._select_robust_market(assessments)
        self.assertEqual(chosen["key"], "over_2_5")

    def test_specialist_alignment_never_adds_confirmation_count(self):
        full = {"btts": {"direction": "BTTS_NO", "balance": -3, "applicable_signal_count": 3}}
        alignment = v1_full_engine._specialist_alignment(full, "btts_yes")
        self.assertTrue(alignment["clear_contradiction"])
        self.assertEqual(alignment["confirmation_count_added"], 0)


class V1FullRuntimeTests(unittest.TestCase):
    def test_health_and_ui_expose_full_v1(self):
        import app  # noqa: F401
        import app_v040 as legacy

        route = next(r for r in legacy.app.router.routes if getattr(r, "path", None) == "/api/health")
        health = route.endpoint()
        self.assertEqual(health["version"], "1.0.0")
        self.assertTrue(health["v043_probability_core_locked"])
        self.assertEqual(health["alpha"], 3.0)
        self.assertEqual(health["rho"], -0.25)
        self.assertFalse(health["probabilities_modified_by_v1"])
        self.assertFalse(health["new_lambda_core"])
        self.assertEqual(len(health["all_six_markets"]), 6)
        self.assertTrue(all(health["specialists"].values()))

        html = legacy.INDEX_HTML
        self.assertIn("Spielpaarung", html)
        self.assertIn("Warum BEOBACHTEN?", html)
        self.assertIn("V1 Multi-Market & Specialists", html)
        self.assertIn("Alle sechs Märkte", html)
        self.assertIn("Core-Topmarkt", html)


if __name__ == "__main__":
    unittest.main(verbosity=2)
