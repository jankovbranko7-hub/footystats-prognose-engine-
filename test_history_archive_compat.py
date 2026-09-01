import unittest
from unittest.mock import patch

import app


def parsed_bundle(include_history=True, history_name="123456_HistoryDaten.json"):
    match = {
        "data": {
            "id": 123456,
            "homeID": 10,
            "awayID": 20,
            "competition_id": 30,
            "home_name": "Heim",
            "away_name": "Auswärts",
        }
    }
    league = {
        "data": [
            {"id": 10, "name": "Heim", "stats": {}},
            {"id": 20, "name": "Auswärts", "stats": {}},
        ]
    }
    files = [
        {"name": "123456_MatchDaten.json", "data": match},
        {"name": "30_LeagueDaten.json", "data": league},
        {"name": "123456_FormDaten.json", "data": {"teams": []}},
        {"name": "123456_TableDaten.json", "data": {"data": {}}},
        {"name": "123456_PlayerDaten.json", "data": {"pages": []}},
    ]
    if include_history:
        files.append({
            "name": history_name,
            "data": {
                "pages": [
                    {
                        "pager": {"current_page": 1, "max_page": 1},
                        "data": [{"id": 99, "homeID": 7, "awayID": 8, "date": "2026-08-01"}],
                    }
                ]
            },
        })
    return files


class HistoryArchiveCompatibilityTests(unittest.TestCase):
    def test_sixth_file_is_recognized_but_not_model_input(self):
        pair = app.select_pair(parsed_bundle())
        self.assertTrue(pair["ok"])
        self.assertIn("history", pair["source_files"])
        self.assertNotIn("history", pair["supplemental_data"])
        self.assertEqual(pair["history_archive"]["status"], "OK")
        self.assertFalse(pair["history_archive"]["model_use"])

    def test_five_file_bundle_still_works(self):
        pair = app.select_pair(parsed_bundle(include_history=False))
        self.assertTrue(pair["ok"])
        self.assertEqual(pair["history_archive"]["status"], "NICHT GELIEFERT")

    def test_wrong_history_match_id_is_blocked(self):
        pair = app.select_pair(parsed_bundle(history_name="999999_HistoryDaten.json"))
        self.assertFalse(pair["ok"])
        self.assertEqual(pair["phase"], "PAIRING_FAILED")
        self.assertEqual(pair["history_archive"]["status"], "MAPPING FEHLER")

    def test_incomplete_history_pagination_is_reported_without_model_use(self):
        files = parsed_bundle()
        files[-1]["data"]["pages"][0]["pager"]["max_page"] = 3
        pair = app.select_pair(files)
        self.assertTrue(pair["ok"])
        self.assertEqual(pair["history_archive"]["status"], "PAGINATION UNVOLLSTÄNDIG")
        self.assertFalse(pair["history_archive"]["pagination"]["complete"])
        self.assertFalse(pair["history_archive"]["model_use"])

    def test_history_is_archived_and_sanitized(self):
        files = parsed_bundle()
        files[-1]["data"]["api_key"] = "must-not-leave"
        pair = app.select_pair(files)
        result = {"ok": True, "model_version": "0.4.0", "audit": {"match": app.mf(files[0]["data"])}}
        package = app._archive_package(files, pair, result)
        self.assertIn("history", package["sources"])
        self.assertNotIn("api_key", package["sources"]["history"]["content"])
        self.assertEqual(package["archive_version"], "1.1.0")

    def test_analysis_core_output_is_identical_with_or_without_history(self):
        fixed_prediction = {
            "ok": True,
            "model_version": "0.4.0",
            "probabilities": {"btts_yes": 0.61},
            "markets": [{"key": "btts_yes", "probability_pct": 61.0}],
            "strongest_market": {"key": "btts_yes", "probability_pct": 61.0},
            "decision": "BEOBACHTEN",
            "diagnostics": {},
            "audit": {"match": {"match_id": 123456}},
        }

        def attach(result, report, sources):
            copied = dict(result)
            copied["input_sources"] = dict(sources)
            return copied

        with patch.object(app, "predict", return_value=fixed_prediction), \
             patch.object(app, "supplemental_report", return_value={}), \
             patch.object(app, "_attach_supplemental", side_effect=attach):
            five = app._analyze_bundle(parsed_bundle(include_history=False))
            six = app._analyze_bundle(parsed_bundle(include_history=True))

        for key in ("probabilities", "markets", "strongest_market", "decision", "model_version"):
            self.assertEqual(five[key], six[key])
        self.assertFalse(six["history_archive"]["model_use"])


if __name__ == "__main__":
    unittest.main()
