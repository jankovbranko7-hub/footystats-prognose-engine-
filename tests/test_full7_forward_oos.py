import copy
import unittest

from full7_forward_oos import (
    FROZEN_STATUS,
    SPENT_STATUS,
    evaluate_frozen_prediction,
    verify_frozen_prediction,
)


def frozen_fixture():
    probabilities = {
        "home_win": 0.20,
        "draw": 0.25,
        "away_win": 0.55,
        "btts_yes": 0.60,
        "btts_no": 0.40,
        "over_2_5": 0.65,
        "under_2_5": 0.35,
    }
    selected = {
        "1X2": "away_win",
        "BTTS": "btts_yes",
        "TOTALS": "over_2_5",
    }
    family_markets = {
        "1X2": ("home_win", "draw", "away_win"),
        "BTTS": ("btts_yes", "btts_no"),
        "TOTALS": ("over_2_5", "under_2_5"),
    }

    markets = {}
    for family, names in family_markets.items():
        for market in names:
            markets[market] = {
                "market": market,
                "family": family,
                "selected_in_family": market == selected[family],
                "probability": probabilities[market],
                "decision": "BEOBACHTEN" if market == selected[family] else "AUSLASSEN",
                "decision_reason": "EMPIRICAL_GATE" if market == selected[family] else "COHERENCE_NOT_SELECTED",
            }

    families = {
        family: {
            "selected_market": market,
            "base_probability": probabilities[market],
            "reliability_score": probabilities[market],
            "decision": "BEOBACHTEN",
        }
        for family, market in selected.items()
    }

    return {
        "oos_id": "OOS_TEST_1",
        "status": FROZEN_STATUS,
        "bundle_sha256": "bundle",
        "file_sha256": {"x.json": "abc"},
        "identity": {"match_id": 1, "home_id": 10, "away_id": 20, "season_id": 30, "kickoff_unix": 1000},
        "quality": {"status": "VALID"},
        "gold": {"feature_count": 620},
        "probabilities": probabilities,
        "model_support": {"catboost": probabilities, "goal_model": probabilities},
        "families": families,
        "markets": markets,
        "sample_security": {"status": "HIGH"},
        "data_quality_support": {"pass": True},
        "coherence": {"one_active_candidate_per_family": True},
        "contract_stage": {"decision_all_7": True},
        "secondary_context": {},
        "freeze_audit": {
            "frozen_before_result_join": True,
            "result_joined": False,
        },
    }


class ForwardOOSTests(unittest.TestCase):
    def test_verify_frozen_prediction_is_deterministic(self):
        frozen = frozen_fixture()
        h1 = verify_frozen_prediction(frozen)
        h2 = verify_frozen_prediction(copy.deepcopy(frozen))
        self.assertEqual(h1, h2)
        self.assertEqual(len(h1), 64)

    def test_join_result_creates_separate_spent_artifact(self):
        frozen = frozen_fixture()
        before = copy.deepcopy(frozen)
        spent = evaluate_frozen_prediction(
            frozen,
            home_goals=1,
            away_goals=2,
            result_source="verified-two-source-join",
            verified_at="2026-09-15T23:00:00+02:00",
        )
        self.assertEqual(frozen, before)
        self.assertEqual(spent["status"], SPENT_STATUS)
        self.assertTrue(spent["markets"]["away_win"]["hit"])
        self.assertTrue(spent["markets"]["btts_yes"]["hit"])
        self.assertTrue(spent["markets"]["over_2_5"]["hit"])
        self.assertTrue(spent["integrity"]["freeze_verified_before_join"])
        self.assertFalse(spent["integrity"]["freeze_mutated"])
        self.assertEqual(len(spent["spent_oos_sha256"]), 64)

    def test_refuses_result_join_without_pre_result_freeze(self):
        frozen = frozen_fixture()
        frozen["freeze_audit"]["result_joined"] = True
        with self.assertRaises(ValueError):
            evaluate_frozen_prediction(
                frozen,
                home_goals=1,
                away_goals=0,
                result_source="bad",
                verified_at="2026-09-15T23:00:00+02:00",
            )

    def test_all_seven_markets_are_evaluated(self):
        spent = evaluate_frozen_prediction(
            frozen_fixture(),
            home_goals=0,
            away_goals=0,
            result_source="verified",
            verified_at="2026-09-15T23:00:00+02:00",
        )
        self.assertEqual(len(spent["markets"]), 7)
        self.assertTrue(spent["markets"]["draw"]["hit"])
        self.assertTrue(spent["markets"]["btts_no"]["hit"])
        self.assertTrue(spent["markets"]["under_2_5"]["hit"])


if __name__ == "__main__":
    unittest.main()
