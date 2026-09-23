import unittest

from full7_phase7_features import extract_phase4_features
from full7_phase7_upload_api import _compat_view, _normalize_sources, _pack_lastx


class Full7Phase7UploadBridgeTests(unittest.TestCase):
    def test_pack_lastx_matches_frozen_form_semantics(self):
        row = {
            "last_x_match_num": 5,
            "stats": {
                "seasonMatchesPlayed_home": 3,
                "seasonScoredAVG_overall": 1.4,
                "seasonConcededAVG_overall": 1.0,
                "seasonBTTSPercentage_overall": 60,
                "seasonOver25Percentage_overall": 40,
                "seasonCSPercentage_overall": 20,
                "seasonFTSPercentage_overall": 20,
                "xg_for_avg_overall": 1.55,
                "xg_against_avg_overall": 1.10,
                "seasonScoredAVG_home": 1.7,
                "seasonConcededAVG_home": 0.7,
                "seasonBTTSPercentage_home": 67,
                "seasonOver25Percentage_home": 33,
                "seasonCSPercentage_home": 33,
                "seasonFTSPercentage_home": 0,
                "xg_for_avg_home": 1.8,
                "xg_against_avg_home": 0.9,
            },
        }
        overall = _pack_lastx(row, "overall")
        self.assertEqual(overall["n"], 5)
        self.assertEqual(overall["goals_for_avg"], 1.4)
        self.assertEqual(overall["btts_rate"], 0.6)
        self.assertEqual(overall["xga_avg"], 1.1)
        home = _pack_lastx(row, "home")
        self.assertEqual(home["n"], 3)
        self.assertEqual(home["goals_for_avg"], 1.7)
        self.assertEqual(home["btts_rate"], 0.67)

    def test_compat_view_preserves_final_decisions(self):
        result = {
            "directions": {
                "HOME": {"probability": 0.61, "decision": "SPIELEN", "reason": "PASS"},
                "DRAW": {"probability": 0.22, "decision": "AUSLASSEN", "reason": "DRAW_FAIL_CLOSED_DISABLED"},
                "AWAY": {"probability": 0.17, "decision": "AUSLASSEN", "reason": "NOT_MODEL_PREFERRED_DIRECTION"},
                "BTTS_YES": {"probability": 0.58, "decision": "SPIELEN", "reason": "PASS"},
                "BTTS_NO": {"probability": 0.42, "decision": "AUSLASSEN", "reason": "NOT_MODEL_PREFERRED_DIRECTION"},
                "O25": {"probability": None, "decision": "HOLD", "reason": "O25_NOT_RELEASED"},
                "U25": {"probability": None, "decision": "HOLD", "reason": "O25_NOT_RELEASED"},
            }
        }
        view = _compat_view(result)
        self.assertEqual(view["markets"]["home_win"]["decision"], "SPIELEN")
        self.assertEqual(view["markets"]["over_2_5"]["decision"], "HOLD")
        self.assertEqual(len(view["playable"]), 2)
        self.assertEqual(view["families"]["TOTALS"]["decision"], "HOLD")

    def test_seven_file_gold_normalizes_to_phase4_feature_names(self):
        stats = {
            "seasonScoredAVG_overall": 1.5,
            "seasonConcededAVG_overall": 1.0,
            "seasonBTTSPercentage_overall": 60,
            "seasonOver25Percentage_overall": 40,
            "seasonCSPercentage_overall": 20,
            "seasonFTSPercentage_overall": 20,
            "xg_for_avg_overall": 1.6,
            "xg_against_avg_overall": 1.1,
            "seasonMatchesPlayed_home": 3,
            "seasonMatchesPlayed_away": 2,
            "seasonScoredAVG_home": 1.8,
            "seasonConcededAVG_home": 0.8,
            "seasonBTTSPercentage_home": 67,
            "seasonOver25Percentage_home": 33,
            "seasonCSPercentage_home": 33,
            "seasonFTSPercentage_home": 0,
            "xg_for_avg_home": 1.9,
            "xg_against_avg_home": 0.9,
            "seasonScoredAVG_away": 1.0,
            "seasonConcededAVG_away": 1.3,
            "seasonBTTSPercentage_away": 50,
            "seasonOver25Percentage_away": 50,
            "seasonCSPercentage_away": 0,
            "seasonFTSPercentage_away": 50,
            "xg_for_avg_away": 1.2,
            "xg_against_avg_away": 1.4,
        }
        def form_rows(team):
            return [
                {"id": team, "last_x_match_num": n, "stats": dict(stats)}
                for n in (5, 6, 10)
            ]
        gold = {
            "identity": {
                "match_id": 99,
                "home_id": 1,
                "away_id": 2,
                "season_id": 7,
                "kickoff_unix": 2000,
            },
            "namespaces": {
                "match": {"data": {"id": 99, "homeID": 1, "awayID": 2, "date_unix": 2000}},
                "league": {
                    "league": {"data": {
                        "id": 7, "matchesCompleted": 20, "seasonAVG_overall": 2.5,
                        "seasonAVG_home": 1.4, "seasonAVG_away": 1.1,
                        "seasonBTTSPercentage": 55, "seasonOver25Percentage_overall": 50,
                        "cornersAVG_overall": 9.5, "cornersRecorded_matches": 20,
                    }},
                    "team_pages": {"data": [
                        {"id": 1, "stats": {"seasonBTTSPercentageHT_home": 25}},
                        {"id": 2, "stats": {"seasonBTTSPercentageHT_away": 30}},
                    ]},
                },
                "form": {
                    "home": {"data": form_rows(1)},
                    "away": {"data": form_rows(2)},
                },
                "table": {"data": {
                    "league_table": [
                        {"id": 1, "position": 1, "points": 10, "matchesPlayed": 5},
                        {"id": 2, "position": 2, "points": 8, "matchesPlayed": 5},
                    ]
                }},
                "player": {"pages": [
                    {"data": [
                        {"id": 10, "club_team_id": 1, "minutes_played_overall": 450, "goals_overall": 2, "assists_overall": 1},
                        {"id": 20, "club_team_id": 2, "minutes_played_overall": 450, "goals_overall": 1, "assists_overall": 1},
                    ]}
                ]},
            },
        }
        sources = _normalize_sources(gold)
        features, _groups = extract_phase4_features(sources, home_id=1, away_id=2)
        self.assertEqual(features["form.home.last5.goals_for_avg"], 1.5)
        self.assertEqual(features["league_derived.goals_avg"], 2.5)
        self.assertEqual(features["A2.players_found_home"], 1)
        self.assertIn("A1.fh_btts_venue_home", features)


if __name__ == "__main__":
    unittest.main()
