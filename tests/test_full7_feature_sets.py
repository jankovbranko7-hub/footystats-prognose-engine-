import unittest

from full7_feature_sets import build_feature_sets, classify_feature_set


class FeatureSetTests(unittest.TestCase):
    def test_provider_and_h2h_not_core(self):
        self.assertEqual(classify_feature_set("provider_btts_potential","provider_potentials_research"),"RESEARCH_ONLY")
        self.assertEqual(classify_feature_set("avg_goals","h2h_secondary"),"RESEARCH_ONLY")

    def test_nested_form_windows_reduced(self):
        self.assertEqual(classify_feature_set("home_last10_seasonPPG_overall","form_windows"),"REDUNDANT_NESTED_WINDOW")
        self.assertEqual(classify_feature_set("home_last5_seasonPPG_overall","form_windows"),"CORE_PROBABILITY_CANDIDATE")
        self.assertEqual(classify_feature_set("home_form_delta_seasonPPG_overall","form_deltas"),"CORE_PROBABILITY_CANDIDATE")

    def test_under25_complement_reduced(self):
        self.assertEqual(
            classify_feature_set("home_home_seasonUnder25Percentage","league_team_profiles"),
            "REDUNDANT_COMPLEMENT",
        )

    def test_shots_core_corners_research(self):
        self.assertEqual(classify_feature_set("home_home_shotsAVG","league_team_profiles"),"CORE_PROBABILITY_CANDIDATE")
        self.assertEqual(classify_feature_set("home_home_cornersAVG","league_team_profiles"),"AUXILIARY_RESEARCH")

    def test_quality_separate(self):
        self.assertEqual(classify_feature_set("home_form_last5_sample","form_exposure"),"QUALITY_ONLY")
        self.assertEqual(classify_feature_set("home_secondary_affiliation_count","player_depth_quality_concentration"),"QUALITY_ONLY")

    def test_sets_are_deterministic(self):
        gf={
            "features":{
                "a":1.0,
                "provider_btts_potential":60.0,
                "home_form_last5_sample":5.0,
            },
            "feature_owners":{
                "a":"match_prematch",
                "provider_btts_potential":"provider_potentials_research",
                "home_form_last5_sample":"form_exposure",
            },
        }
        a=build_feature_sets(gf)
        b=build_feature_sets(gf)
        self.assertEqual(a["core_probability"],b["core_probability"])
        self.assertIn("a",a["core_probability"])
        self.assertNotIn("provider_btts_potential",a["core_probability"])


if __name__=="__main__":
    unittest.main()
