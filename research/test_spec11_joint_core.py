import math
import unittest

from spec11_joint_core_patch import (
    MARKETS, average_markets, conservative_market_ranking,
    empirical_bayes_rate, score_probabilities, uncertainty_action,
)


class JointCoreTest(unittest.TestCase):
    def test_score_matrix_is_coherent(self):
        p = score_probabilities(1.72, 1.09)
        self.assertAlmostEqual(p["home_win"] + p["draw"] + p["away_win"], 1.0, places=10)
        self.assertAlmostEqual(p["btts_yes"] + p["btts_no"], 1.0, places=10)
        self.assertAlmostEqual(p["over_2_5"] + p["under_2_5"], 1.0, places=10)
        self.assertEqual(set(p), set(MARKETS))
        self.assertTrue(all(math.isfinite(value) and 0 <= value <= 1 for value in p.values()))

    def test_variant_average_remains_coherent(self):
        p = average_markets({
            "a": score_probabilities(1.2, 0.8),
            "b": score_probabilities(1.5, 1.1),
            "c": score_probabilities(1.8, 1.3),
            "d": score_probabilities(1.4, 0.9),
        })
        self.assertAlmostEqual(p["home_win"] + p["draw"] + p["away_win"], 1.0, places=10)
        self.assertAlmostEqual(p["btts_yes"] + p["btts_no"], 1.0, places=10)
        self.assertAlmostEqual(p["over_2_5"] + p["under_2_5"], 1.0, places=10)

    def test_empirical_bayes_shrinks_toward_league(self):
        rows = [(1.0, 10), (1.5, 10), (2.0, 10), (1.4, 10)]
        low = empirical_bayes_rate(3.0, 2, rows)
        high = empirical_bayes_rate(3.0, 30, rows)
        self.assertLess(low["shrunk"], high["shrunk"])
        self.assertLess(low["reliability"], high["reliability"])
        self.assertGreater(low["shrunk"], low["league_mean"])

    def test_uncertainty_action_has_no_probability_cutoff(self):
        ranking = conservative_market_ranking()
        self.assertEqual(ranking[0]["market"], "over_2_5")
        self.assertEqual(uncertainty_action("over_2_5")[0], "SPIELEN")
        self.assertEqual(uncertainty_action("btts_yes")[0], "BEOBACHTEN")
        self.assertEqual(uncertainty_action("under_2_5")[0], "BEOBACHTEN")
        self.assertEqual(uncertainty_action("home_win")[0], "AUSLASSEN")

    def test_ui_identifies_joint_outcome_engine(self):
        import app

        html = app.legacy.INDEX_HTML
        self.assertIn("Build 1.1.6-joint-outcome", html)
        self.assertIn("Joint-Outcome Engine", html)
        self.assertIn("Joint-Outcome V1.1.6 auswerten", html)
        self.assertNotIn("Build 1.1.6-cross-market-normalized", html)
        self.assertNotIn("keine Decision Engine", html)

    def test_full_five_file_bundle_uses_joint_core(self):
        import app
        from research.test_spec11_native_engine import build_bundle

        result = app.legacy._analyze_bundle(build_bundle(8, 8))
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["engine_version"], "1.1.6-joint-outcome")
        self.assertEqual(result["method"]["probability_core"], "JOINT_POISSON_SCORE_MATRIX_EMPIRICAL_BAYES")
        self.assertEqual(result["method"]["legacy_signal_ranking_role"], "DIAGNOSTIC_ONLY")
        self.assertFalse(result["method"]["research_only"])
        self.assertEqual(len(result["joint_outcome"]["probabilities"]), 7)
        p = result["joint_outcome"]["probabilities"]
        self.assertAlmostEqual(p["home_win"] + p["draw"] + p["away_win"], 1.0, places=6)
        self.assertAlmostEqual(p["btts_yes"] + p["btts_no"], 1.0, places=6)
        self.assertAlmostEqual(p["over_2_5"] + p["under_2_5"], 1.0, places=6)
        self.assertIn(result["decision"], {"SPIELEN", "BEOBACHTEN", "AUSLASSEN"})
        self.assertIn("strongest_market", result["evidence_diagnostic"])


if __name__ == "__main__":
    unittest.main()
