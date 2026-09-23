import unittest

import full7_homepage_patch


class Full7HomepageV3Tests(unittest.TestCase):
    def test_homepage_does_not_claim_btts_only_play_release(self):
        card = full7_homepage_patch.FULL7_CARD
        script = full7_homepage_patch.FULL7_SCRIPT
        self.assertNotIn("SPIELEN nur BTTS", card)
        self.assertNotIn("1X2 und Totals hoechstens BEOBACHTEN", card)
        self.assertNotIn('<div class="b">BTTS</div>', script)
        self.assertIn("FULL7_FINAL_RC_1.0.0", card)
        self.assertIn("SPIELEN: HOME | AWAY | BTTS YES", card)
        self.assertIn("O25/U25: HOLD", card)
        self.assertIn("contract.spielen_allowed_families", script)
        self.assertIn("allowedFamilies", script)

    def test_family_probability_supports_v3_probability_field(self):
        script = full7_homepage_patch.FULL7_SCRIPT
        self.assertIn("row.probability", script)
        self.assertIn("row.base_probability", script)

    def test_matchup_is_prominent_and_can_use_uploaded_match_names(self):
        script = full7_homepage_patch.FULL7_SCRIPT
        self.assertIn("matchDisplay", script)
        self.assertIn("localDisplay.home_name", script)
        self.assertIn("localDisplay.away_name", script)
        self.assertIn("full7-matchup", script)
        self.assertIn("Match-ID", script)


if __name__ == "__main__":
    unittest.main()
