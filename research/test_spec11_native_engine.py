"""Smoke tests for standalone SPEC v1.1 native engine."""
from spec11_native_engine import analyze_bundle


def _page(rows, current=1, maximum=1):
    return {"data": rows, "pager": {"current_page": current, "max_page": maximum, "total_results": len(rows)}}


def _team(tid, matches, venue_matches, home=True):
    split = "home" if home else "away"
    stats = {
        "seasonMatchesPlayed_overall": matches,
        f"seasonMatchesPlayed_{split}": venue_matches,
        f"seasonPPG_{split}": 2.0 if tid == 1 else 1.0,
        f"seasonBTTSPercentage_{split}": 60,
        f"seasonBTTSPercentageHT_{split}": 25,
        f"seasonOver25Percentage_{split}": 60,
        f"seasonUnder25Percentage_{split}": 40,
        f"seasonFTSPercentage_{split}": 20,
        f"seasonCSPercentage_{split}": 20,
        f"xg_for_avg_{split}": 1.6 if tid == 1 else 1.2,
        f"xg_against_avg_{split}": 1.1 if tid == 1 else 1.5,
    }
    if matches == 0:
        for key in list(stats):
            stats[key] = 0
    return {"id": tid, "name": f"T{tid}", "stats": stats}


def _form_team(tid, sample, ppg, btts=60, o25=60):
    return {"id": tid, "last_x_match_num": sample, "stats": {"last_x": sample, "seasonPPG_overall": ppg, "seasonBTTSPercentage_overall": btts, "seasonOver25Percentage_overall": o25, "seasonUnder25Percentage_overall": 100-o25}}


def build_bundle(home_matches=0, away_matches=1):
    kickoff = 2000000000; capture = kickoff - 1000; max_time = kickoff - 1
    match = {"_footystats_meta": {"endpoint": "/match", "captured_at_unix": capture, "kickoff_unix": kickoff}, "payload": {"data": {"id": 99, "homeID": 1, "awayID": 2, "competition_id": 77, "date_unix": kickoff, "home_name": "Home", "away_name": "Away", "season": "2026/27", "pre_match_home_ppg": 0, "pre_match_away_ppg": 1.0, "team_a_xg_prematch": 0, "team_b_xg_prematch": 1.3, "btts_potential": 62, "o25_potential": 58, "u25_potential": 42}}}
    teams = [_team(1, home_matches, home_matches, True), _team(2, away_matches, away_matches, False), {"id": 3, "stats": {"seasonMatchesPlayed_overall": 5, "seasonMatchesPlayed_home": 3, "seasonMatchesPlayed_away": 2, "seasonPPG_home": 1.5, "seasonPPG_away": 1.2, "seasonBTTSPercentage_home": 50, "seasonBTTSPercentage_away": 50, "seasonBTTSPercentageHT_home": 20, "seasonBTTSPercentageHT_away": 20, "seasonOver25Percentage_home": 50, "seasonOver25Percentage_away": 50, "seasonUnder25Percentage_home": 50, "seasonUnder25Percentage_away": 50, "seasonFTSPercentage_home": 30, "seasonFTSPercentage_away": 30, "seasonCSPercentage_home": 30, "seasonCSPercentage_away": 30, "xg_for_avg_home": 1.4, "xg_for_avg_away": 1.2, "xg_against_avg_home": 1.2, "xg_against_avg_away": 1.4}}]
    league = {"_footystats_meta": {"endpoint": "/league-season", "team_endpoint": "/league-teams", "captured_at_unix": capture, "kickoff_unix": kickoff, "max_time": max_time, "team_pagination_complete": "true"}, "payload": {"team_pages": _page(teams), "league": {"data": {"seasonBTTSPercentage": 55}}}}
    form = {"_footystats_meta": {"endpoint": "/lastx", "captured_at_unix": capture, "kickoff_unix": kickoff}, "payload": {"home": {"data": [_form_team(1, 5, 2.4), _form_team(1, 10, 2.0)]}, "away": {"data": [_form_team(2, 5, 1.4), _form_team(2, 10, 1.2)]}}}
    table = {"_footystats_meta": {"endpoint": "/league-tables", "captured_at_unix": capture, "kickoff_unix": kickoff, "max_time": max_time}, "payload": {"data": {"all_matches_table_overall": [{"id": 1, "matchesPlayed": home_matches, "points": 0, "position": 20}, {"id": 2, "matchesPlayed": away_matches, "points": away_matches, "position": 10}], "all_matches_table_home": [], "all_matches_table_away": []}}}
    players = [{"id": 101, "club_team_id": 1, "minutes_played_overall": 400, "goals_involved_per_90_overall": .5}, {"id": 201, "club_team_id": 2, "minutes_played_overall": 350, "goals_involved_per_90_overall": .4}, {"id": 301, "club_team_id": 3, "minutes_played_overall": 450, "goals_involved_per_90_overall": .3}]
    player = {"_footystats_meta": {"endpoint": "/league-players", "captured_at_unix": capture, "kickoff_unix": kickoff, "max_time": max_time, "pagination_complete": True, "max_page": "1"}, "payload": {"pages": [_page(players)]}}
    return [{"name": "99_MatchDaten.json", "data": match}, {"name": "77_LeagueDaten.json", "data": league}, {"name": "99_FormDaten.json", "data": form}, {"name": "99_TableDaten.json", "data": table}, {"name": "99_PlayerDaten.json", "data": player}]


def main():
    result = analyze_bundle(build_bundle(0, 1))
    assert result["ok"] is True, result
    assert result["sample_state"]["home"]["class"] == "COLD START"
    assert result["sample_state"]["away"]["class"] == "LOW SAMPLE"
    assert result["method"]["probability_core"] == "NONE"
    assert result["method"]["v043_used"] is False
    assert result["method"]["v042_used"] is False
    assert result["method"]["fallback"] == "NONE"
    assert len(result["markets"]) == 7
    assert all(m["action"] in {"SPIELEN", "BEOBACHTEN", "AUSLASSEN"} for m in result["markets"])
    bad = build_bundle(0, 1)[:-1]
    result_bad = analyze_bundle(bad)
    assert result_bad["ok"] is False and result_bad["phase"] == "SPEC11_FILE_PAIRING_FAILED"
    print("SPEC v1.1 native smoke OK", result["decision"], result["recommended_market"])


if __name__ == "__main__":
    main()
