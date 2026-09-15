import unittest

from full7_goal_probability import learn_rho, market_probabilities, score_matrix


class GoalProbabilityTests(unittest.TestCase):
    def test_probability_coherence(self):
        p=market_probabilities(1.4,1.1,-0.1)
        self.assertAlmostEqual(p["home_win"]+p["draw"]+p["away_win"],1.0,places=10)
        self.assertAlmostEqual(p["btts_yes"]+p["btts_no"],1.0,places=10)
        self.assertAlmostEqual(p["over_2_5"]+p["under_2_5"],1.0,places=10)

    def test_score_matrix_normalized(self):
        m=score_matrix(1.5,0.9,-0.15)
        self.assertAlmostEqual(sum(sum(row) for row in m),1.0,places=10)

    def test_higher_lambdas_raise_over_probability(self):
        low=market_probabilities(0.7,0.6)["over_2_5"]
        high=market_probabilities(1.8,1.5)["over_2_5"]
        self.assertGreater(high,low)

    def test_learn_rho_is_from_candidate_grid(self):
        scores=[(0,0),(1,0),(0,1),(1,1),(2,1)]
        lambdas=[(1.0,1.0)]*len(scores)
        result=learn_rho(scores,lambdas,[-0.2,-0.1,0.0,0.1])
        self.assertIn(result["rho"],[-0.2,-0.1,0.0,0.1])
        self.assertEqual(result["n"],5)

    def test_empty_rho_calibration_rejected(self):
        self.assertRaises(ValueError,learn_rho,[],[])


if __name__=="__main__":
    unittest.main()
