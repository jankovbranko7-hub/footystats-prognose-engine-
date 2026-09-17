import unittest

from full7_contract_decision import (
    ARTIFACT,
    DECISION_GATE_VERSION,
    FAMILY_MARKETS,
    PRODUCTION_FAMILY_POLICY,
    apply_precision_policy,
    build_decision_engine,
)
from full7_contract_engine import MARKETS


class Full7ContractDecisionTests(unittest.TestCase):
    def test_all_seven_markets_receive_a_decision(self):
        out = build_decision_engine({"features": {}, "feature_owners": {}})
        self.assertEqual(out["decision_gate_version"], "FULL7_CONTRACT_DECISION_GATE_1.0")
        self.assertEqual(set(out["markets"]), set(MARKETS))
        self.assertTrue(all(
            row["decision"] in {"SPIELEN", "BEOBACHTEN", "AUSLASSEN"}
            for row in out["markets"].values()
        ))

    def test_exactly_one_market_per_family_is_selected(self):
        out = build_decision_engine({"features": {}, "feature_owners": {}})
        for family, markets in FAMILY_MARKETS.items():
            selected = [
                market for market in markets
                if out["markets"][market]["selected_in_family"]
            ]
            self.assertEqual(len(selected), 1, family)
            self.assertEqual(selected[0], out["families"][family]["selected_market"])

    def test_nonselected_complementary_markets_fail_closed(self):
        out = build_decision_engine({"features": {}, "feature_owners": {}})
        for market, row in out["markets"].items():
            if not row["selected_in_family"]:
                self.assertEqual(row["decision"], "AUSLASSEN")
                self.assertEqual(row["decision_reason"], "COHERENCE_NOT_SELECTED")

    def test_missing_core_data_cannot_produce_play(self):
        out = build_decision_engine({"features": {}, "feature_owners": {}})
        self.assertFalse(out["data_quality_support"]["pass"])
        for family, row in out["families"].items():
            self.assertEqual(row["decision"], "AUSLASSEN")
            self.assertEqual(row["decision_reason"], "OUTSIDE_DEVELOPMENT_SUPPORT")

    def test_decision_artifact_is_empirical_and_monotonic(self):
        self.assertEqual(ARTIFACT["development_rows"], 180)
        self.assertEqual(
            ARTIFACT["selection_rule"],
            "Among evidence-active candidates, require prospective SPIELEN>=BEOBACHTEN>=AUSLASSEN; choose lowest prospective LogLoss.",
        )
        for family in ("1X2", "BTTS", "TOTALS"):
            cfg = ARTIFACT["families"][family]
            self.assertIn(
                cfg["strategy"],
                {"EVIDENCE_ADJUSTED", "EVIDENCE_DOWNGRADE"},
            )
            prospective = cfg["prospective_last3"]
            self.assertTrue(prospective["monotonic"])
            states = prospective["states"]
            self.assertGreaterEqual(
                states["SPIELEN"]["rate"],
                states["BEOBACHTEN"]["rate"],
            )
            self.assertGreaterEqual(
                states["BEOBACHTEN"]["rate"],
                states["AUSLASSEN"]["rate"],
            )

    def test_contract_is_complete_except_new_untouched_oos(self):
        out = build_decision_engine({"features": {}, "feature_owners": {}})
        stage = out["contract_stage"]
        for key, value in stage.items():
            if key == "new_untouched_oos":
                self.assertEqual(value, "PENDING")
            else:
                self.assertTrue(value, key)
        self.assertEqual(
            out["status"],
            "DEVELOPMENT_ONLY_NEW_UNTOUCHED_OOS_REQUIRED",
        )

    def test_precision_policy_caps_1x2_and_totals(self):
        self.assertFalse(PRODUCTION_FAMILY_POLICY["1X2"]["spielen_allowed"])
        self.assertFalse(PRODUCTION_FAMILY_POLICY["TOTALS"]["spielen_allowed"])
        self.assertTrue(PRODUCTION_FAMILY_POLICY["BTTS"]["spielen_allowed"])
        state, reason = apply_precision_policy(
            "1X2", "SPIELEN", "EMPIRICAL_GATE",
            sample_status="HIGH", family_margin=0.2,
            catboost_prefers_market=1.0, goal_prefers_market=1.0,
        )
        self.assertEqual(state, "BEOBACHTEN")
        self.assertEqual(reason, "FAMILY_OOS_OBSERVE_ONLY")
        state, reason = apply_precision_policy(
            "TOTALS", "SPIELEN", "EMPIRICAL_GATE",
            sample_status="HIGH", family_margin=0.2,
            catboost_prefers_market=1.0, goal_prefers_market=1.0,
        )
        self.assertEqual(state, "BEOBACHTEN")
        self.assertEqual(reason, "FAMILY_OOS_OBSERVE_ONLY")

    def test_precision_policy_blocks_low_sample_btts_spielen(self):
        state, reason = apply_precision_policy(
            "BTTS", "SPIELEN", "EMPIRICAL_GATE",
            sample_status="LOW", family_margin=0.2,
            catboost_prefers_market=1.0, goal_prefers_market=1.0,
        )
        self.assertEqual(state, "BEOBACHTEN")
        self.assertEqual(reason, "SAMPLE_SECURITY_LOW")

    def test_precision_policy_requires_btts_margin_and_agreement(self):
        state, reason = apply_precision_policy(
            "BTTS", "SPIELEN", "EMPIRICAL_GATE",
            sample_status="HIGH", family_margin=0.03,
            catboost_prefers_market=1.0, goal_prefers_market=1.0,
        )
        self.assertEqual(state, "BEOBACHTEN")
        self.assertEqual(reason, "FAMILY_MARGIN_BELOW_MIN")
        state, reason = apply_precision_policy(
            "BTTS", "SPIELEN", "EMPIRICAL_GATE",
            sample_status="HIGH", family_margin=0.20,
            catboost_prefers_market=1.0, goal_prefers_market=0.0,
        )
        self.assertEqual(state, "BEOBACHTEN")
        self.assertEqual(reason, "MODEL_DISAGREEMENT")
        state, reason = apply_precision_policy(
            "BTTS", "SPIELEN", "EMPIRICAL_GATE",
            sample_status="HIGH", family_margin=0.20,
            catboost_prefers_market=1.0, goal_prefers_market=1.0,
        )
        self.assertEqual(state, "SPIELEN")
        self.assertEqual(reason, "EMPIRICAL_GATE")


if __name__ == "__main__":
    unittest.main()
