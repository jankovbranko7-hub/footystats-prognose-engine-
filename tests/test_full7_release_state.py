import unittest

from full7_contract_engine import contract_model_support
from full7_contract_ensemble import ensemble_and_calibrate
from full7_contract_evidence import build_evidence_engine
from full7_contract_decision import build_decision_engine


RELEASE_STATUS = "PRODUCTION_RELEASED_OOS_VALIDATED"


class Full7ReleaseStateTests(unittest.TestCase):
    def test_all_contract_layers_report_released_state(self):
        gold = {"features": {}, "feature_owners": {}}
        model = contract_model_support(gold)
        ensemble = ensemble_and_calibrate(gold)
        evidence = build_evidence_engine(gold)
        decision = build_decision_engine(gold)

        for layer in (model, ensemble, evidence, decision):
            self.assertEqual(layer["status"], RELEASE_STATUS)

        for layer in (model, ensemble, decision):
            stage = layer["contract_stage"]
            self.assertTrue(all(value is True for value in stage.values()), stage)


if __name__ == "__main__":
    unittest.main()
