import unittest
from full7_gold_features import (
    form_match_venue_blocks,
    h2h_block,
    league_context_block,
    manager_block,
    match_block,
    player_block,
    provider_potential_block,
    referee_block,
    table_block,
    team_metric,
)


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

    def test_player_secondary_club_is_not_primary_membership(self):
        p={"pages":[{"data":[
            {"id":1,"club_team_id":999,"club_team_2_id":101,"position":"Forward","minutes_played_overall":90,"goals_per_90_overall":1,"assists_per_90_overall":0,"goals_involved_per_90_overall":1,"goals_overall":1,"assists_overall":0},
            {"id":2,"club_team_id":101,"club_team_2_id":-1,"position":"Forward","minutes_played_overall":45,"goals_per_90_overall":0,"assists_per_90_overall":0,"goals_involved_per_90_overall":0,"goals_overall":0,"assists_overall":0},
            {"id":3,"club_team_id":202,"club_team_2_id":-1,"position":"Forward","minutes_played_overall":45,"goals_per_90_overall":0,"assists_per_90_overall":0,"goals_involved_per_90_overall":0,"goals_overall":0,"assists_overall":0},
        ]}]}
        b=player_block(p,101,202)
        self.assertEqual(b["features"]["home_players_found"],1)
        self.assertEqual(b["features"]["home_secondary_affiliation_count"],1)

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

    def test_provider_potentials_are_isolated(self):
        b=provider_potential_block({"btts_potential":70,"o25_potential":65,"odds_ft_1":1.8})
        self.assertEqual(b["features"]["provider_btts_potential"],70)
        self.assertEqual(b["features"]["provider_o25_potential"],65)
        self.assertFalse(any("odds" in k for k in b["features"]))

    def test_league_context(self):
        b=league_context_block({"league":{"data":{"xg_avg":3.1,"seasonAVG_overall":2.7,"seasonBTTSPercentage":54,"totalMatches":100}}})
        self.assertEqual(b["features"]["league_xg_avg"],3.1)
        self.assertEqual(b["features"]["league_seasonBTTSPercentage"],54)
        self.assertEqual(b["features"]["league_totalMatches"],100)

    def test_form_match_venue_uses_home_and_away_splits(self):
        form={
            "home":{"data":[{"id":101,"last_x_match_num":5,"stats":{"seasonMatchesPlayed_home":3,"seasonPPG_home":2.0,"xg_for_avg_home":1.5}},
                            {"id":101,"last_x_match_num":10,"stats":{"seasonMatchesPlayed_home":5,"seasonPPG_home":1.4,"xg_for_avg_home":1.2}}]},
            "away":{"data":[{"id":202,"last_x_match_num":5,"stats":{"seasonMatchesPlayed_away":2,"seasonPPG_away":1.0,"xg_for_avg_away":1.1}},
                            {"id":202,"last_x_match_num":10,"stats":{"seasonMatchesPlayed_away":5,"seasonPPG_away":1.2,"xg_for_avg_away":1.0}}]},
        }
        blocks=form_match_venue_blocks(form,101,202)
        features={k:v for b in blocks for k,v in b["features"].items()}
        self.assertEqual(features["home_last5_home_seasonPPG"],2.0)
        self.assertEqual(features["away_last5_away_seasonPPG"],1.0)
        self.assertEqual(features["form_last5_matchvenue_seasonPPG_home_minus_away"],1.0)

    def test_table_matchvenue_diff(self):
        table={"data":{
            "all_matches_table_overall":[{"id":101,"position":5,"points":10,"matchesPlayed":5},{"id":202,"position":2,"points":12,"matchesPlayed":5}],
            "all_matches_table_home":[{"id":101,"position":3,"points":9,"matchesPlayed":3},{"id":202,"position":2,"points":6,"matchesPlayed":3}],
            "all_matches_table_away":[{"id":101,"position":6,"points":1,"matchesPlayed":2},{"id":202,"position":1,"points":6,"matchesPlayed":2}],
        }}
        b=table_block(table,101,202)
        self.assertEqual(b["features"]["table_matchvenue_ppg_diff"],0.0)

    def test_player_active_depth(self):
        p={"pages":[{"data":[
            {"id":1,"club_team_id":101,"position":"Forward","minutes_played_overall":90,"goals_per_90_overall":1,"assists_per_90_overall":0,"goals_involved_per_90_overall":1,"goals_overall":1,"assists_overall":0},
            {"id":2,"club_team_id":101,"position":"Defender","minutes_played_overall":0,"goals_per_90_overall":0,"assists_per_90_overall":0,"goals_involved_per_90_overall":0,"goals_overall":0,"assists_overall":0},
            {"id":3,"club_team_id":202,"position":"Forward","minutes_played_overall":45,"goals_per_90_overall":0,"assists_per_90_overall":0,"goals_involved_per_90_overall":0,"goals_overall":0,"assists_overall":0},
        ]}]}
        b=player_block(p,101,202)
        self.assertEqual(b["features"]["home_active_players"],1)
        self.assertEqual(b["features"]["home_active_player_share"],0.5)
        self.assertEqual(b["features"]["away_active_minutes_median"],45)

    def test_h2h_age_and_same_venue(self):
        match={"homeID":101,"awayID":202,"date_unix":2000000000,"h2h":{
            "previous_matches_results":{"totalMatches":2,"team_a_win_percent":50,"team_b_win_percent":0},
            "betting_stats":{"avg_goals":2.5,"bttsPercentage":50,"over25Percentage":50},
            "previous_matches_ids":[
                {"team_a_id":101,"team_b_id":202,"team_a_goals":2,"team_b_goals":1,"date_unix":1990000000},
                {"team_a_id":202,"team_b_id":101,"team_a_goals":1,"team_b_goals":1,"date_unix":1980000000},
            ],
        }}
        b=h2h_block(match)
        self.assertEqual(b["features"]["same_venue_orientation_count"],1)
        self.assertEqual(b["features"]["same_venue_btts_pct"],100)
        self.assertGreater(b["features"]["latest_match_age_days"],0)


if __name__=="__main__":
    unittest.main()
