import unittest

from full7_probability_contract import build_probability_contract


class ProbabilityContractTests(unittest.TestCase):
    def base(self,totals=None,totals_state="HOLD_NO_INCREMENTAL_SIGNAL_YET"):
        return build_probability_contract(
            one_x_two={"home_win":0.45,"draw":0.28,"away_win":0.27},
            btts={"btts_yes":0.56,"btts_no":0.44},
            totals=totals,
            sources={"1X2":"CATBOOST_FULL_CORE","BTTS":"GOAL_INTENSITY_DC","TOTALS":"TOTAL_GOALS"},
            readiness={
                "1X2":"DEVELOPMENT_CANDIDATE_STRONG",
                "BTTS":"DEVELOPMENT_CANDIDATE_NEEDS_NEW_OOS",
                "TOTALS":totals_state,
            },
            model_versions={"1X2":"a","BTTS":"b","TOTALS":"c"},
        )

    def test_coherent_contract(self):
        out=self.base()
        self.assertTrue(out["coherence"]["pass"])
        self.assertFalse(out["families"]["1X2"]["recommendation_eligible"])
        self.assertFalse(out["families"]["TOTALS"]["probability_available"])

    def test_invalid_sum_rejected(self):
        with self.assertRaises(ValueError):
            build_probability_contract(
                one_x_two={"home_win":0.5,"draw":0.3,"away_win":0.3},
                btts={"btts_yes":0.5,"btts_no":0.5},
                totals=None,
                sources={"1X2":"x","BTTS":"y"},
                readiness={"1X2":"DEVELOPMENT_CANDIDATE_STRONG","BTTS":"DEVELOPMENT_CANDIDATE_NEEDS_NEW_OOS","TOTALS":"HOLD_NO_INCREMENTAL_SIGNAL_YET"},
                model_versions={"1X2":"1","BTTS":"1"},
            )

    def test_totals_can_be_present_but_not_recommendation_eligible(self):
        out=self.base({"over_2_5":0.6,"under_2_5":0.4})
        self.assertTrue(out["families"]["TOTALS"]["probability_available"])
        self.assertFalse(out["families"]["TOTALS"]["recommendation_eligible"])

    def test_missing_totals_cannot_claim_ready(self):
        with self.assertRaises(ValueError):
            self.base(None,"PRODUCTION_VALIDATED")


if __name__=="__main__":
    unittest.main()
