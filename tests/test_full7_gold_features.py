import unittest
from full7_gold_features import manager_block, match_block, player_block, referee_block, team_metric


class GoldFeatureTests(unittest.TestCase):
    def test_team_metric_requires_sample(self):
        t={"stats":{"seasonMatchesPlayed_home":0,"xg_for_avg_home":1.9}}
        self.assertIsNone(team_metric(t,"xg_for_avg","home"))

    def test_referee_uses_assigned_id_and_median(self):
        r={"data":[
            {"id":5,"appearances_overall":20,"btts_percentage":60,"goals_per_match_overall":2.8},
            {"id":6,"appearances_overall":20,"btts_percentage":40,"goals_per_match_overall":2.2},
        ]}
        b=referee_block(r,5)
        self.assertEqual(b["features"]["referee_btts_percentage"],60)
        self.assertEqual(b["features"]["referee_btts_percentage_vs_league_median"],10)

    def test_manager_requires_team_and_competition(self):
        m={
            "home":{"data":[{"id":1,"competition_id":9,"club_team_id":101,"appearances_overall":5,"wins_per_overall":60}]},
            "away":{"data":[{"id":2,"competition_id":9,"club_team_id":202,"appearances_overall":5,"wins_per_overall":20}]},
        }
        b=manager_block(m,101,202,9)
        self.assertEqual(b["features"]["manager_wins_per_overall_home_minus_away"],40)

    def test_player_no_lineup_inference(self):
        p={"pages":[{"data":[
            {"id":1,"club_team_id":101,"position":"Forward","minutes_played_overall":90,"goals_per_90_overall":1,"assists_per_90_overall":0,"goals_involved_per_90_overall":1,"goals_overall":1,"assists_overall":0},
            {"id":2,"club_team_id":202,"position":"Forward","minutes_played_overall":90,"goals_per_90_overall":0,"assists_per_90_overall":0,"goals_involved_per_90_overall":0,"goals_overall":0,"assists_overall":0},
        ]}]}
        b=player_block(p,101,202)
        self.assertIn("no injury or lineup inference"," ".join(b["notes"]).lower())

    def test_match_block_no_odds_or_actual(self):
        m={"team_a_xg_prematch":1.2,"team_b_xg_prematch":1.0,"team_a_xg":4.0,"odds_ft_1":1.3}
        b=match_block(m)
        self.assertEqual(b["features"]["prematch_xg_home"],1.2)
        self.assertFalse(any("odds" in k or k=="team_a_xg" for k in b["features"]))


if __name__=="__main__":
    unittest.main()
