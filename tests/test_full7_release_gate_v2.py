import unittest

from research.check_full7_release_gate import evaluate_final_oos_release_constraints


class Full7ReleaseGateV2Tests(unittest.TestCase):
    def _audit(self, **overrides):
        audit = {
            "status": "PASS",
            "untouched_forward_oos_complete": True,
            "all_predictions_frozen_before_results": True,
            "no_result_leakage": True,
            "no_architecture_change_during_validation": True,
            "main_merge_allowed": True,
            "render_deploy_allowed": True,
            "decision_performance": {
                "SPIELEN": {"n": 5, "correct": 4, "hit_rate": 0.8},
            },
        }
        audit.update(overrides)
        return audit

    def test_explicit_main_merge_prohibition_blocks_release(self):
        result = evaluate_final_oos_release_constraints(
            self._audit(main_merge_allowed=False)
        )
        self.assertFalse(result["pass"])
        self.assertIn("FORWARD_OOS_MAIN_MERGE_FORBIDDEN", result["blockers"])

    def test_explicit_render_deploy_prohibition_blocks_release(self):
        result = evaluate_final_oos_release_constraints(
            self._audit(render_deploy_allowed=False)
        )
        self.assertFalse(result["pass"])
        self.assertIn("FORWARD_OOS_RENDER_DEPLOY_FORBIDDEN", result["blockers"])

    def test_zero_spielen_forward_oos_exposure_blocks_playing_release(self):
        result = evaluate_final_oos_release_constraints(
            self._audit(
                decision_performance={
                    "SPIELEN": {
                        "n": 0,
                        "correct": 0,
                        "hit_rate": None,
                        "status": "NO_EXPOSURE",
                    }
                }
            )
        )
        self.assertFalse(result["pass"])
        self.assertIn("FORWARD_OOS_NO_SPIELEN_EXPOSURE", result["blockers"])

    def test_release_constraints_pass_only_with_authorization_and_exposure(self):
        result = evaluate_final_oos_release_constraints(self._audit())
        self.assertTrue(result["pass"])
        self.assertEqual(result["blockers"], [])
        self.assertEqual(result["spielen_exposure"], 5)


if __name__ == "__main__":
    unittest.main()
