from __future__ import annotations

import ast
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent


class FinalDecisionDependencyTests(unittest.TestCase):
    def test_01_removed_manual_gate_constants_are_absent(self):
        source = (ROOT / "full5_next_engine.py").read_text(encoding="utf-8")
        for name in ("MIN_CONFIRMATION_RATIO", "MAX_COUNTER_BLOCKS", "MIN_RANK_STABILITY"):
            self.assertNotIn(name, source)

    def test_02_engine_calls_trained_abstention_policy(self):
        source = (ROOT / "full5_next_engine.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        calls = {
            ast.unparse(node.func)
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
        }
        self.assertIn("learned_ai.apply_abstention_policy", calls)
        self.assertIn('"FINAL_DECISION_SOURCE": "TRAINED_AI_POLICY"', source)
        self.assertIn('"MANUAL_PERFORMANCE_GATES": "NONE"', source)

    def test_03_manual_performance_rules_are_non_decisive_in_audit(self):
        audit = json.loads((ROOT / "FINAL_DECISION_DEPENDENCY_AUDIT.json").read_text(encoding="utf-8"))
        rules = [
            item for item in audit["components"]
            if item["manual_policy"] and not item["integrity_only"]
        ]
        self.assertTrue(rules)
        self.assertTrue(all(item["affects_final_decision"] is False for item in rules))
        integrity = [item for item in audit["components"] if item["integrity_only"]]
        self.assertEqual({item["name"] for item in integrity}, {
            "STRICT_PREMATCH", "FIVE_FILES", "AUDIT", "LEAKAGE", "REQUIRED_INPUTS",
        })
        self.assertTrue(all(item["affects_final_decision"] is True for item in integrity))

    def test_04_model_boundaries_are_learned_and_oos_excluded(self):
        model = json.loads((ROOT / "full5_next_ai_model.json").read_text(encoding="utf-8"))
        policy = model["abstention_policy"]
        self.assertIn("kmeans", policy["boundaries"]["learning_method"])
        self.assertEqual(len(policy["bootstrap_models"]), 80)
        self.assertEqual(model["abstention_validation"]["former_87_match_oos_rows_used"], 0)
        self.assertTrue(model["abstention_validation"]["no_untouched_oos_claim"])


if __name__ == "__main__":
    unittest.main()
