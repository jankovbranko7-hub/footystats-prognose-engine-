import unittest

from full7_signal_groups import audit_signal_groups, classify_gold_feature


class SignalGroupTests(unittest.TestCase):
    def test_form_windows_share_one_group(self):
        self.assertEqual(
            classify_gold_feature("home_last5_seasonPPG_overall", "form_windows"),
            "CURRENT_FORM",
        )
        self.assertEqual(
            classify_gold_feature("home_form_delta_seasonPPG_overall", "form_deltas"),
            "CURRENT_FORM",
        )

    def test_player_subgroups_share_cluster(self):
        gf={
            "features":{
                "home_active_players":20.0,
                "home_goals_per90_minutes_weighted":0.2,
                "home_top3_goal_share":0.7,
            },
            "feature_owners":{
                "home_active_players":"player_depth_quality_concentration",
                "home_goals_per90_minutes_weighted":"player_depth_quality_concentration",
                "home_top3_goal_share":"player_depth_quality_concentration",
            },
        }
        audit=audit_signal_groups(gf)
        rows={r["group"]:r for r in audit["groups"]}
        self.assertEqual(rows["PLAYER_DEPTH"]["cluster"],"player")
        self.assertEqual(rows["PLAYER_QUALITY"]["cluster"],"player")
        self.assertEqual(rows["PLAYER_CONCENTRATION"]["cluster"],"player")
        self.assertIn("player",audit["available_evidence_clusters"])
        self.assertEqual(audit["available_evidence_clusters"].count("player"),1)

    def test_half_time_btts_not_full_match_btts_group(self):
        self.assertEqual(
            classify_gold_feature(
                "home_home_seasonBTTSPercentageHT",
                "league_team_profiles",
            ),
            "FIRST_SECOND_HALF",
        )

    def test_provider_potential_not_evidence_eligible(self):
        gf={
            "features":{"provider_btts_potential":70.0},
            "feature_owners":{"provider_btts_potential":"provider_potentials_research"},
        }
        audit=audit_signal_groups(gf)
        row=next(r for r in audit["groups"] if r["group"]=="PROVIDER_POTENTIALS_RESEARCH")
        self.assertFalse(row["evidence_eligible"])

    def test_odds_feature_is_guarded(self):
        gf={
            "features":{"odds_ft_1":1.8},
            "feature_owners":{"odds_ft_1":"match_prematch"},
        }
        audit=audit_signal_groups(gf)
        self.assertEqual(audit["forbidden_odds_feature_count"],1)

    def test_every_owned_feature_assigned_once(self):
        gf={
            "features":{
                "prematch_xg_home":1.3,
                "prematch_ppg_home":1.5,
                "league_xg_avg":2.7,
                "table_matchvenue_ppg_diff":0.5,
            },
            "feature_owners":{
                "prematch_xg_home":"match_prematch",
                "prematch_ppg_home":"match_prematch",
                "league_xg_avg":"league_context",
                "table_matchvenue_ppg_diff":"table_relative_strength",
            },
        }
        audit=audit_signal_groups(gf)
        self.assertEqual(audit["unassigned_feature_count"],0)
        self.assertEqual(audit["assigned_feature_count"],4)


if __name__=="__main__":
    unittest.main()
