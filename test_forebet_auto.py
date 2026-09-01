from __future__ import annotations

import unittest

import forebet_auto as fa


SAMPLE = [
    {
        "matchDate": "2026-09-02",
        "matchTime": "18:30",
        "leagueName": "Test League",
        "home": "Royal Antwerp FC",
        "away": "Sint-Truiden",
        "probability_1_percent": "34",
        "probability_X_percent": "27",
        "probability_2_percent": "39",
        "predictedScore": "1 - 2",
        "averageGoals": "2.84",
        "probability_under_percent": "42",
        "probability_over_percent": "58",
        "probability_btts_yes_percent": "63",
        "probability_btts_no_percent": "37",
    },
    {
        "matchDate": "2026-09-02",
        "matchTime": "20:00",
        "leagueName": "Other League",
        "home": "Antwerp Youth",
        "away": "STVV Youth",
        "probability_1_percent": "45",
        "probability_X_percent": "25",
        "probability_2_percent": "30",
        "predictedScore": "2 - 1",
        "averageGoals": "2.5",
        "probability_under_percent": "50",
        "probability_over_percent": "50",
        "probability_btts_yes_percent": "55",
        "probability_btts_no_percent": "45",
    },
]


class ForebetAutoTests(unittest.TestCase):
    def test_fuzzy_match_tolerates_common_suffixes(self):
        found = fa.select_match(SAMPLE, "Royal Antwerp", "Sint Truiden", "2026-09-02")
        self.assertEqual(found["home"], "Royal Antwerp FC")

    def test_snapshot_maps_all_required_fields(self):
        original = fa._actor_items
        fa._actor_items = lambda force=False: SAMPLE
        try:
            data = fa.build_snapshot(12345, "Royal Antwerp", "Sint Truiden", "2026-09-02")
        finally:
            fa._actor_items = original
        self.assertEqual(data["match_id"], 12345)
        self.assertEqual(data["home_win"], 34.0)
        self.assertEqual(data["draw"], 27.0)
        self.assertEqual(data["away_win"], 39.0)
        self.assertEqual(data["btts_yes"], 63.0)
        self.assertEqual(data["over_2_5"], 58.0)
        self.assertEqual(data["predicted_score"], "1-2")
        self.assertEqual(data["average_goals"], 2.84)

    def test_ambiguous_or_weak_match_is_rejected(self):
        with self.assertRaises(fa.ForebetAutoError):
            fa.select_match(SAMPLE, "Completely Different", "Unknown Team", "2026-09-02")


if __name__ == "__main__":
    unittest.main()
