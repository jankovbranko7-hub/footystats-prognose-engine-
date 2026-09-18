import unittest

from full7_contract_api import RELEASE_STATUS, _production_release_view
from full7_contract_decision import build_decision_engine
from full7_v3_live import predict_v3_live


def _sample_v3():
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
    return predict_v3_live(gold, features)


class Full7ReleaseStateTests(unittest.TestCase):
    def test_production_view_reports_release_without_mutating_v2_fit_provenance(self):
        gold = {"features": {}, "feature_owners": {}}
        core = build_decision_engine(gold)
        original_status = core["status"]
        original_stage = dict(core["contract_stage"])
        released = _production_release_view(core, _sample_v3())

        self.assertEqual(core["status"], original_status)
        self.assertEqual(core["contract_stage"], original_stage)
        self.assertEqual(released["status"], RELEASE_STATUS)
        self.assertEqual(released["contract_stage"], core["contract_stage"])
        self.assertEqual(released["evidence"]["status"], core["evidence"]["status"])
        self.assertEqual(
            released["v2_reference"]["probabilities"],
            core["probabilities"],
        )
        self.assertEqual(
            released["v2_reference"]["families"],
            core["families"],
        )

    def test_production_view_replaces_final_probabilities_with_v3(self):
        core = build_decision_engine({"features": {}, "feature_owners": {}})
        v3 = _sample_v3()
        released = _production_release_view(core, v3)
        self.assertEqual(released["probabilities"], v3["probabilities"])
        self.assertEqual(released["families"], v3["families"])
        self.assertEqual(released["markets"], v3["markets"])
        self.assertNotEqual(released["probabilities"], core["probabilities"])


if __name__ == "__main__":
    unittest.main()
