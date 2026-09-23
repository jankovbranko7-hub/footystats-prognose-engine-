import json

from full7_phase7_features import extract_phase4_features
from research.full7_phase4_model_research import _extract_features as research_extract


def sample_row():
    sources = {
        "match": {
            "prematch_optional": {
                "team_a_xg_prematch": 1.7,
                "team_b_xg_prematch": 1.1,
                "pre_match_home_ppg": 1.8,
                "pre_match_away_ppg": 1.0,
                "btts_potential": 58,
            },
            "identity": {"game_week": 8, "homeID": 10, "awayID": 20},
        },
        "league": {
            "season_safe_identity": {"matchesCompleted": 88, "seasonAVG_home": 1.55},
            "league_aggregates_derived": {"league_source_count": 88, "goals_avg": 2.7},
            "teams_full_home_away": [
                {
                    "id": 10,
                    "stats": {
                        "seasonBTTSPercentageHT_home": 44,
                        "seasonMatchesPlayed_home": 8,
                        "seasonPPG_home": 2.0,
                    },
                },
                {
                    "id": 20,
                    "stats": {
                        "seasonBTTSPercentageHT_away": 38,
                        "seasonMatchesPlayed_away": 8,
                        "seasonPPG_away": 1.1,
                    },
                },
            ],
        },
        "form": {
            "home": {"last5": {"n": 5, "goals_for_avg": 1.8, "btts_rate": 0.6}},
            "away": {"last5": {"n": 5, "goals_for_avg": 1.0, "btts_rate": 0.4}},
        },
        "table": {
            "home_row": {"id": 10, "matchesPlayed": 8, "ppg": 2.0, "position": 2},
            "away_row": {"id": 20, "matchesPlayed": 8, "ppg": 1.1, "position": 11},
        },
        "player": {
            "players": [
                {"club_team_id": 10, "goals_overall": 5, "assists_overall": 2, "minutes_played_overall": 720},
                {"club_team_id": 10, "goals_overall": 3, "assists_overall": 1, "minutes_played_overall": 600},
                {"club_team_id": 20, "goals_overall": 2, "assists_overall": 2, "minutes_played_overall": 650},
            ]
        },
    }
    return {"home_id": 10, "away_id": 20, "feature_sources_json": json.dumps(sources)}


def test_phase7_feature_extractor_is_semantically_identical_to_frozen_phase4():
    row = sample_row()
    expected_features, expected_groups = research_extract(row)
    actual_features, actual_groups = extract_phase4_features(
        json.loads(row["feature_sources_json"]), home_id=10, away_id=20
    )
    assert actual_features == expected_features
    assert actual_groups == expected_groups


def test_phase7_feature_extractor_does_not_invent_missing_form_values():
    row = sample_row()
    sources = json.loads(row["feature_sources_json"])
    sources["form"] = {}
    features, _ = extract_phase4_features(sources, home_id=10, away_id=20)
    assert not any(name.startswith("form.") for name in features)
