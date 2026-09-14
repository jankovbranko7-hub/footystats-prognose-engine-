import unittest
from full7_feature_registry import classify


class RegistryTests(unittest.TestCase):
    def test_outcome_target(self):
        x=classify("match","data.winningTeam",-1)
        self.assertEqual(x.status,"TARGET_ONLY")
        self.assertIn("-1_IS_DRAW_TARGET",x.sentinel_policy)

    def test_odds_blocked(self):
        self.assertEqual(classify("match","data.odds_ft_1",1.8).status,"ODDS_BLOCKED")
        self.assertEqual(classify("match","data.odds_comparison.FT.Home.Pinnacle","1.8").status,"ODDS_BLOCKED")

    def test_actual_blocked(self):
        self.assertEqual(classify("match","data.team_a_xg",0).status,"POST_MATCH_BLOCKED")

    def test_prematch_xg_candidate(self):
        x=classify("match","data.team_a_xg_prematch",1.2)
        self.assertEqual(x.status,"CANDIDATE_DIRECT")
        self.assertEqual(x.family,"expected_goals_xga")

    def test_league_exposure(self):
        x=classify("league","team_pages.data[].stats.seasonBTTSPercentage_home",55)
        self.assertEqual(x.exposure_path,"team_pages.data[].stats.seasonMatchesPlayed_home")
        self.assertEqual(x.status,"CANDIDATE_DERIVED")

    def test_zero_requires_exposure(self):
        x=classify("league","team_pages.data[].stats.seasonFTSPercentage_home",0)
        self.assertIn("positive exposure",x.zero_policy)

    def test_table_overlap_not_independent(self):
        x=classify("table","data.league_table[].seasonWins_home",5)
        self.assertEqual(x.status,"REDUNDANCY_CHECK_REQUIRED")

    def test_player_rank_minus_one_not_best(self):
        x=classify("player","pages[].data[].rank_in_league_top_attackers",-1)
        self.assertIn("UNRANKED",x.sentinel_policy)

    def test_player_bio_blocked_by_default(self):
        self.assertEqual(classify("player","pages[].data[].age",25).status,"REVIEW_REQUIRED")

    def test_referee_exposure(self):
        x=classify("referee","data[].goals_per_match_overall",2.7)
        self.assertEqual(x.family,"referee")
        self.assertEqual(x.exposure_path,"data[].appearances_overall")

    def test_manager_exposure(self):
        x=classify("manager","data[].wins_per_home",60)
        self.assertEqual(x.family,"manager")
        self.assertEqual(x.exposure_path,"data[].appearances_home")

    def test_metadata_never_predictive(self):
        self.assertEqual(classify("player","_footystats_meta.max_time","123").status,"METADATA_ONLY")

    def test_provider_potential_requires_ablation(self):
        self.assertEqual(classify("match","data.btts_potential",62).status,"PROVIDER_DERIVED")

    def test_form_family(self):
        x=classify("form","home.data[].stats.seasonPPG_overall",2.0)
        self.assertEqual(x.family,"form")
        self.assertEqual(x.status,"CANDIDATE_DERIVED")

    def test_redundancy_group(self):
        a=classify("league","team_pages.data[].stats.seasonBTTS_home",5)
        b=classify("league","team_pages.data[].stats.seasonBTTSPercentage_home",55)
        self.assertEqual(a.redundancy_group,b.redundancy_group)


if __name__=="__main__":
    unittest.main()
