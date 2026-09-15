import inspect
import unittest

import full7_contract_decision
import full7_contract_evidence


class ContractReleaseSemanticsTests(unittest.TestCase):
    def test_no_stale_pre_step5_labels_remain(self):
        source = inspect.getsource(full7_contract_evidence)
        self.assertNotIn("MEASURED_PENDING_EMPIRICAL_DECISION_GATE", source)
        self.assertNotIn("LOCKED_PENDING_STEP5_EMPIRICAL_GATE", source)
        self.assertNotIn("NO_DECISION_YET", source)

    def test_empirical_decision_gate_is_current(self):
        self.assertEqual(
            full7_contract_decision.DECISION_GATE_VERSION,
            "FULL7_CONTRACT_DECISION_GATE_1.0",
        )

    def test_evidence_is_explicitly_delegated_to_decision_engine(self):
        source = inspect.getsource(full7_contract_evidence)
        self.assertIn("DELEGATED_TO_FULL7_CONTRACT_DECISION", source)
        self.assertIn("DECISION_COMPUTED_IN_DECISION_ENGINE", source)


if __name__ == "__main__":
    unittest.main()
