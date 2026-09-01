import unittest
from unittest.mock import patch

import app


TARGET_UNIX = 1_788_000_000


def league_team(team_id, xg_home, xga_home, xg_away, xga_away):
    return {
        "id": team_id,
        "name": f"Team {team_id}",
        "stats": {
            "seasonMatchesPlayed_overall": 24,
            "seasonMatchesPlayed_home": 12,
            "seasonMatchesPlayed_away": 12,
            "xg_for_avg_overall": (xg_home + xg_away) / 2,
            "xg_against_avg_overall": (xga_home + xga_away) / 2,
            "xg_for_avg_home": xg_home,
            "xg_against_avg_home": xga_home,
            "xg_for_avg_away": xg_away,
            "xg_against_avg_away": xga_away,
            "seasonBTTSPercentage_home": 55,
            "seasonBTTSPercentage_away": 52,
            "seasonOver25Percentage_home": 51,
            "seasonOver25Percentage_away": 49,
            "seasonUnder25Percentage_home": 49,
            "seasonUnder25Percentage_away": 51,
            "winPercentage_home": 50,
            "winPercentage_away": 35,
        },
    }


def history_payload(max_page=1):
    rows = []
    team_ids = [10, 20, 30, 40, 50, 60]
    for index in range(36):
        rows.append({
            "id": 900_000 + index,
            "homeID": team_ids[index % len(team_ids)],
            "awayID": team_ids[(index + 1) % len(team_ids)],
            "competition_id": 30,
            "status": "complete",
            "date_unix": TARGET_UNIX - (index + 1) * 86_400,
            "homeGoalCount": 0,
            "awayGoalCount": 0,
        })
    return {"pages": [{"pager": {"current_page": 1, "max_page": max_page}, "data": rows}]}


def parsed_bundle(include_history=True, history_name="123456_HistoryDaten.json", max_page=1):
    match = {"data": {
        "id": 123456,
        "homeID": 10,
        "awayID": 20,
        "competition_id": 30,
        "home_name": "Heim",
        "away_name": "Auswärts",
        "date_unix": TARGET_UNIX,
    }}
    league = {"data": [
        league_team(10, 1.65, 1.05, 1.25, 1.35),
        league_team(20, 1.45, 1.20, 1.35, 1.45),
        league_team(30, 1.55, 1.15, 1.30, 1.30),
        league_team(40, 1.40, 1.25, 1.20, 1.50),
        league_team(50, 1.70, 1.00, 1.40, 1.25),
        league_team(60, 1.30, 1.40, 1.10, 1.55),
    ]}
    files = [
        {"name": "123456_MatchDaten.json", "data": match},
        {"name": "30_LeagueDaten.json", "data": league},
        {"name": "123456_FormDaten.json", "data": {"teams": []}},
        {"name": "123456_TableDaten.json", "data": {"data": {}}},
        {"name": "123456_PlayerDaten.json", "data": {"pages": []}},
    ]
    if include_history:
        files.append({"name": history_name, "data": history_payload(max_page=max_page)})
    return files


class HistoryModelTests(unittest.TestCase):
    def test_bundle_fits_history_only_once(self):
        original = app._fit_history_rho
        with patch.object(app, "_fit_history_rho", wraps=original) as fitted:
            result = app._analyze_bundle(parsed_bundle())
        self.assertTrue(result["ok"])
        self.assertEqual(fitted.call_count, 1)

    def test_sixth_file_is_a_real_model_input(self):
        result = app._analyze_bundle(parsed_bundle())
        self.assertTrue(result["ok"])
        self.assertEqual(result["model_version"], "0.5.0")
        self.assertTrue(result["diagnostics"]["history"]["active"])
        self.assertEqual(result["diagnostics"]["history"]["records_used"], 36)
        self.assertTrue(result["method"]["history_dixon_coles"])
        self.assertTrue(result["history_archive"]["model_use"])

    def test_history_changes_the_shared_scoregrid(self):
        without = app._analyze_bundle(parsed_bundle(include_history=False))
        with_history = app._analyze_bundle(parsed_bundle())
        self.assertTrue(without["ok"] and with_history["ok"])
        self.assertFalse(without["diagnostics"]["history"]["active"])
        self.assertNotEqual(without["diagnostics"]["history"]["rho"], with_history["diagnostics"]["history"]["rho"])
        differences = [
            abs(without["probabilities"][key] - with_history["probabilities"][key])
            for key in ("home_win", "away_win", "btts_yes", "over_2_5")
        ]
        self.assertGreater(max(differences), 0.001)

    def test_five_file_fallback_remains_safe(self):
        result = app._analyze_bundle(parsed_bundle(include_history=False))
        self.assertTrue(result["ok"])
        self.assertFalse(result["method"]["history_dixon_coles"])
        self.assertEqual(result["history_archive"]["status"], "NICHT GELIEFERT")

    def test_wrong_history_match_id_is_blocked(self):
        pair = app.select_pair(parsed_bundle(history_name="999999_HistoryDaten.json"))
        self.assertFalse(pair["ok"])
        self.assertEqual(pair["phase"], "PAIRING_FAILED")
        self.assertEqual(pair["history_archive"]["status"], "MAPPING FEHLER")

    def test_incomplete_history_pagination_disables_model_use(self):
        result = app._analyze_bundle(parsed_bundle(max_page=3))
        self.assertTrue(result["ok"])
        self.assertFalse(result["diagnostics"]["history"]["active"])
        self.assertEqual(result["history_archive"]["status"], "PAGINATION UNVOLLSTÄNDIG")
        self.assertIn("unvollständig", result["diagnostics"]["history"]["reason"])

    def test_future_target_wrong_competition_and_live_rows_are_excluded(self):
        match = app.mf(parsed_bundle()[0]["data"])
        history = history_payload()
        history["pages"][0]["data"].extend([
            {"id": 123456, "homeID": 10, "awayID": 20, "competition_id": 30, "status": "complete", "date_unix": TARGET_UNIX - 100, "homeGoalCount": 1, "awayGoalCount": 1},
            {"id": 777001, "homeID": 10, "awayID": 20, "competition_id": 30, "status": "complete", "date_unix": TARGET_UNIX + 100, "homeGoalCount": 1, "awayGoalCount": 1},
            {"id": 777002, "homeID": 10, "awayID": 20, "competition_id": 99, "status": "complete", "date_unix": TARGET_UNIX - 100, "homeGoalCount": 1, "awayGoalCount": 1},
            {"id": 777003, "homeID": 10, "awayID": 20, "competition_id": 30, "status": "live", "date_unix": TARGET_UNIX - 100, "homeGoalCount": 1, "awayGoalCount": 1},
        ])
        fit = app._fit_history_rho(history, match, parsed_bundle()[1]["data"])
        self.assertEqual(fit["records_eligible"], 36)
        self.assertEqual(fit["excluded"]["target_match"], 1)
        self.assertEqual(fit["excluded"]["not_before_kickoff"], 1)
        self.assertEqual(fit["excluded"]["wrong_competition"], 1)
        self.assertEqual(fit["excluded"]["not_completed"], 1)

    def test_history_is_archived_and_sanitized(self):
        files = parsed_bundle()
        files[-1]["data"]["api_key"] = "must-not-leave"
        pair = app.select_pair(files)
        result = app._analyze_bundle(files)
        result.pop("_archive_pair", None)
        package = app._archive_package(files, pair, result)
        self.assertIn("history", package["sources"])
        self.assertNotIn("api_key", package["sources"]["history"]["content"])
        self.assertEqual(package["archive_version"], "1.1.0")


if __name__ == "__main__":
    unittest.main()
