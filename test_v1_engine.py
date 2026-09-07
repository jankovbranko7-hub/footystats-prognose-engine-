import unittest

import v042_engine
import v043_engine
import v043_release
import v1_engine


class V1GateTests(unittest.TestCase):
    def _result(self, family="BTTS", key="btts_yes", sample="NIEDRIG", strength=.34, p=0.67):
        return {
            "ok": True,
            "strongest_market": {"key": key, "label": "BTTS Yes" if key == "btts_yes" else key, "probability_pct": round(p * 100, 1)},
            "samples": {"security": sample},
            "diagnostics": {"data_quality": "HOCH", "robustness_status": "BESTANDEN"},
            "probabilities": {key: p},
        }

    def _protocol(self, family="BTTS", key="btts_yes", confirmations=None, counters=None, strength=.34):
        confirmations = confirmations if confirmations is not None else ["UNDERLYING", "MATCH", "FORM"]
        counters = counters or []
        evidence = {}
        for block in ["UNDERLYING", "MATCH", "FORM", "TABLE", "PLAYER"]:
            if block in confirmations:
                status = "BESTÄTIGEND"
            elif block in counters:
                status = "GEGENARGUMENT"
            elif family == "BTTS" and block in {"TABLE", "PLAYER"}:
                status = "NICHT ANWENDBAR"
            elif family == "1X2" and block == "PLAYER":
                status = "NICHT ANWENDBAR"
            elif family == "OU_2_5" and block == "TABLE":
                status = "NICHT ANWENDBAR"
            else:
                status = "NEUTRAL"
            evidence[block] = {"status": status}
        return {
            "selected_market_family": {"family": family, "key": key, "strength": strength},
            "evidence_blocks": evidence,
            "confirming_blocks": list(confirmations),
            "counter_blocks": list(counters),
            "gates": {
                "pre_match_integrity": {"strict_pre_match": True},
                "robustness": "BESTANDEN",
                "data_quality": "HOCH",
                "coherence": {"passed": True},
            },
            "final_decision": "BEOBACHTEN",
        }

    def test_v043_probability_core_is_locked(self):
        self.assertEqual(v043_engine.FEATURE_COUNT, 40)
        self.assertEqual(v043_release.FULL5_ALPHA, 3.0)
        self.assertEqual(v042_engine.RHO, -0.25)

    def test_structural_applicability_is_family_not_availability(self):
        self.assertEqual(v1_engine.STRUCTURAL_APPLICABLE_BLOCKS["BTTS"], 3)
        self.assertEqual(v1_engine.STRUCTURAL_APPLICABLE_BLOCKS["1X2"], 4)
        self.assertEqual(v1_engine.STRUCTURAL_APPLICABLE_BLOCKS["OU_2_5"], 4)

    def test_low_sample_btts_three_of_three_can_play(self):
        result = self._result()
        protocol = self._protocol()
        out = v1_engine.apply_gate_v1_to_protocol(result, {}, protocol)
        gate = out["gates"]["gate_v1"]
        self.assertEqual(gate["original_required"], 4)
        self.assertEqual(gate["structural_applicable_max"], 3)
        self.assertEqual(gate["required"], 3)
        self.assertTrue(gate["availability_does_not_reduce_requirement"])
        self.assertEqual(out["final_decision"], "SPIELEN")

    def test_low_sample_btts_two_of_three_stays_observe(self):
        result = self._result()
        protocol = self._protocol(confirmations=["UNDERLYING", "MATCH"])
        out = v1_engine.apply_gate_v1_to_protocol(result, {}, protocol)
        self.assertEqual(out["gates"]["gate_v1"]["required"], 3)
        self.assertEqual(out["final_decision"], "BEOBACHTEN")
        self.assertIn("Wahrscheinlichkeit ist stark genug", out["decision_reasons"][0])
        self.assertIn("2 von 3", out["decision_reasons"][0])

    def test_low_sample_1x2_is_not_relaxed(self):
        result = self._result(family="1X2", key="home_win", strength=.34, p=.56)
        result["strongest_market"] = {"key": "home_win", "label": "Sieg Heim", "probability_pct": 56.0}
        protocol = self._protocol(family="1X2", key="home_win", confirmations=["UNDERLYING", "MATCH", "FORM"], strength=.34)
        out = v1_engine.apply_gate_v1_to_protocol(result, {}, protocol)
        self.assertEqual(out["gates"]["gate_v1"]["required"], 4)
        self.assertEqual(out["final_decision"], "BEOBACHTEN")

    def test_counterargument_still_blocks(self):
        result = self._result()
        protocol = self._protocol(confirmations=["UNDERLYING", "MATCH", "FORM"], counters=["MATCH"])
        out = v1_engine.apply_gate_v1_to_protocol(result, {}, protocol)
        self.assertEqual(out["final_decision"], "BEOBACHTEN")
        self.assertTrue(any("Gegenargument" in reason for reason in out["decision_reasons"]))

    def test_v1_never_claims_probability_reweighting(self):
        result = self._result()
        protocol = self._protocol()
        out = v1_engine.apply_gate_v1_to_protocol(result, {}, protocol)
        self.assertFalse(out["probability_core_lock"]["probabilities_modified_by_v1"])
        self.assertEqual(out["probability_core_lock"]["baseline"], "0.4.3 FULL-5")


class V1RuntimeUITests(unittest.TestCase):
    def test_render_entry_preserves_pairing_and_observe_explanation(self):
        import app  # noqa: F401
        import app_v040 as legacy
        html = legacy.INDEX_HTML
        self.assertIn("Spielpaarung", html)
        self.assertIn("Warum BEOBACHTEN?", html)
        self.assertIn("confirming_block_labels", html)

    def test_health_contract_uses_five_files_only(self):
        import app  # noqa: F401
        import app_v040 as legacy
        route = next(r for r in legacy.app.router.routes if getattr(r, "path", None) == "/api/health")
        payload = route.endpoint()
        self.assertEqual(payload["version"], "1.0.0")
        self.assertTrue(payload["v043_probability_core_locked"])
        self.assertEqual(payload["full5_features"], 40)
        self.assertEqual(payload["alpha"], 3.0)
        self.assertEqual(payload["rho"], -0.25)
        self.assertTrue(payload["five_source_only"])
        self.assertFalse(payload["new_shortcut_required"])
        self.assertFalse(payload["player_detail_required"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
