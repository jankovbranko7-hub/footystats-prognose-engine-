import copy
import unittest

from full7_v3_live import build_live_record, predict_v3_live, PLAY_THRESHOLDS


def sample():
    gold = {
        "namespaces": {
            "league": {"league": {"data": {"country": "Brazil", "db_english_name": "Serie A"}}}
        }
    }
    features = {
        "features": {
            "league_seasonAVG_home": 1.51,
            "league_seasonAVG_away": 1.15,
            "league_matchesCompleted": 265,
            "prematch_xg_home": 1.69,
            "prematch_xg_away": 1.18,
            "provider_o25_potential": 54,
            "provider_btts_potential": 62,
            "provider_avg_potential": 2.77,
            "prematch_ppg_home": 1.62,
            "prematch_ppg_away": 0.69,
        }
    }
    return gold, features


class V3LiveTests(unittest.TestCase):
    def test_adapter_maps_only_live_prematch_fields(self):
        gold, features = sample()
        out = build_live_record(gold, features)
        self.assertTrue(out["supported"])
        self.assertEqual(out["league"], "Brazil Serie A")
        self.assertEqual(out["record"]["fs_xg_prematch_heim"], 1.69)

    def test_missing_required_input_fails_closed(self):
        gold, features = sample()
        del features["features"]["prematch_xg_home"]
        out = predict_v3_live(gold, features)
        self.assertFalse(out["supported"])
        self.assertEqual(out["playable"], [])

    def test_probabilities_are_coherent(self):
        gold, features = sample()
        out = predict_v3_live(gold, features)
        p = out["probabilities"]
        self.assertAlmostEqual(p["home_win"] + p["draw"] + p["away_win"], 1.0, places=12)
        self.assertAlmostEqual(p["over_2_5"] + p["under_2_5"], 1.0, places=12)
        self.assertAlmostEqual(p["btts_yes"] + p["btts_no"], 1.0, places=12)

    def test_odds_and_results_cannot_change_prediction(self):
        gold, features = sample()
        a = predict_v3_live(gold, features)
        b_features = copy.deepcopy(features)
        b_features["features"].update({"fs_quote_over25": 99.0, "actual_home_goals": 9, "actual_btts": 1})
        b = predict_v3_live(gold, b_features)
        self.assertEqual(a["probabilities"], b["probabilities"])
        self.assertEqual(a["families"], b["families"])

    def test_play_thresholds_are_frozen(self):
        self.assertEqual(PLAY_THRESHOLDS, {"1X2": 0.71, "TOTALS": 0.70, "BTTS": 0.605})


if __name__ == "__main__":
    unittest.main()
