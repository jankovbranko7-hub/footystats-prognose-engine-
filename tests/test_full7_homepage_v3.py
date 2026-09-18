import unittest

import full7_homepage_patch


class Full7HomepageV3Tests(unittest.TestCase):
    def test_homepage_does_not_claim_btts_only_play_release(self):
        card = full7_homepage_patch.FULL7_CARD
        script = full7_homepage_patch.FULL7_SCRIPT
        self.assertNotIn("SPIELEN nur BTTS", card)
        self.assertNotIn("1X2 und Totals hoechstens BEOBACHTEN", card)
        self.assertNotIn('<div class="b">BTTS</div>', script)
        self.assertIn("1X2 | BTTS | TOTALS", card)
        self.assertIn("contract.spielen_allowed_families", script)
        self.assertIn("allowedFamilies", script)

    def test_family_probability_supports_v3_probability_field(self):
        script = full7_homepage_patch.FULL7_SCRIPT
        self.assertIn("row.probability", script)
        self.assertIn("row.base_probability", script)


if __name__ == "__main__":
    unittest.main()
