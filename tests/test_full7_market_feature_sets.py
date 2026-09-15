import unittest

from full7_market_feature_sets import build_market_feature_sets, domain_family, structural_status


class MarketFeatureSetTests(unittest.TestCase):
    def test_odds_blocked(self):
        self.assertEqual(structural_status("odds_ft_1"),"BLOCKED")

    def test_provider_and_h2h_research_only(self):
        self.assertEqual(structural_status("provider_btts_potential"),"RESEARCH_ONLY")
        self.assertEqual(structural_status("h2h_avg_goals"),"RESEARCH_ONLY")

    def test_nested_form_window_removed_but_delta_allowed(self):
        self.assertEqual(structural_status("home_last10_seasonPPG_overall"),"REDUNDANT_NESTED_WINDOW")
        self.assertEqual(structural_status("home_form_delta_seasonPPG_overall"),"ELIGIBLE")

    def test_market_domains(self):
        self.assertEqual(domain_family("prematch_xg_home"),"XG")
        self.assertEqual(domain_family("home_home_shotsOnTargetAVG"),"SHOTS")
        self.assertEqual(domain_family("home_active_players"),"PLAYER")

    def test_totals_excludes_table_strength(self):
        core=[
            "prematch_xg_home",
            "home_home_shotsAVG",
            "table_matchvenue_ppg_diff",
            "home_active_players",
        ]
        sets=build_market_feature_sets(core)
        self.assertIn("prematch_xg_home",sets["markets"]["TOTALS"])
        self.assertNotIn("table_matchvenue_ppg_diff",sets["markets"]["TOTALS"])
        self.assertIn("table_matchvenue_ppg_diff",sets["markets"]["1X2"])

    def test_deterministic(self):
        core=["home_active_players","prematch_xg_home","home_home_seasonBTTSPercentage"]
        self.assertEqual(build_market_feature_sets(core),build_market_feature_sets(reversed(core)))


if __name__=="__main__":
    unittest.main()
