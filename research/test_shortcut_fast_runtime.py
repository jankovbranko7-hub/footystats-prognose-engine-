from __future__ import annotations

import time

import v050_shortcut_fast_patch as fast


def run() -> None:
    kickoff = int(time.time()) + 3600

    def fake_api_get(endpoint: str, api_key: str, **params):
        assert api_key == "TEST-SECRET-KEY"
        if endpoint == "/match":
            return {
                "success": True,
                "data": {
                    "id": 12345,
                    "homeID": 10,
                    "awayID": 20,
                    "competition_id": 777,
                    "date_unix": kickoff,
                    "pre_match_home_ppg": 1.5,
                    "pre_match_away_ppg": 1.2,
                    "btts_potential": 66,
                    "odds_ft_1": 1.9,
                    "odds_comparison": {"FT Result": {"Home": {"book": "1.9"}}},
                },
            }
        if endpoint == "/league-season":
            return {"success": True, "data": {"seasonAVG_overall": 2.8}}
        if endpoint == "/league-teams":
            return {
                "success": True,
                "pager": {"current_page": 1, "max_page": 1},
                "data": [
                    {"id": 10, "stats": {"seasonMatchesPlayed_home": 10, "xg_for_avg_home": 1.5}},
                    {"id": 20, "stats": {"seasonMatchesPlayed_away": 10, "xg_for_avg_away": 1.2}},
                ],
            }
        if endpoint == "/lastx":
            return {"success": True, "data": [{"id": params["team_id"], "last_x_match_num": 5, "stats": {"seasonPPG_overall": 1.1}}]}
        if endpoint == "/league-tables":
            return {"success": True, "data": {"league_table": []}}
        if endpoint == "/league-players":
            return {
                "success": True,
                "pager": {"current_page": 1, "max_page": 1},
                "data": [
                    {"id": 1, "club_team_id": 10, "goals_overall": 2},
                    {"id": 2, "club_team_id": 20, "goals_overall": 3},
                    {"id": 3, "club_team_id": 99, "goals_overall": 99},
                ],
            }
        raise AssertionError(endpoint)

    original = fast._api_get
    fast._api_get = fake_api_get
    try:
        parsed, diagnostics = fast._virtual_files("TEST-SECRET-KEY", 12345)
    finally:
        fast._api_get = original

    assert len(parsed) == 5
    assert [item["name"] for item in parsed] == [
        "12345_MatchDaten.json",
        "777_LeagueDaten.json",
        "12345_FormDaten.json",
        "12345_TableDaten.json",
        "12345_PlayerDaten.json",
    ]
    assert diagnostics["virtual_file_count"] == 5
    assert diagnostics["player_rows_before_filter"] == 3
    assert diagnostics["player_rows_after_filter"] == 2
    assert diagnostics["api_key_persisted"] is False
    assert diagnostics["max_time"] == kickoff - 1

    match_payload = parsed[0]["data"]["payload"]
    assert "odds_comparison" not in match_payload["data"]
    assert "odds_ft_1" not in match_payload["data"]

    player_rows = parsed[4]["data"]["payload"]["pages"][0]["data"]
    assert {row["club_team_id"] for row in player_rows} == {10, 20}

    print("FAST shortcut server-side collection smoke passed")


if __name__ == "__main__":
    run()
