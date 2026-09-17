import unittest

import app as production_entry
import full7_contract_api


class Full7ContractPreviewApiTests(unittest.TestCase):
    def test_preview_health_declares_development_only(self):
        out = full7_contract_api.health()
        self.assertTrue(out["ok"])
        self.assertTrue(out["development_only"])
        self.assertFalse(out["production_mounted"])
        self.assertTrue(out["new_untouched_oos_required"])
        self.assertEqual(out["expected_files"], 7)
        self.assertEqual(len(out["markets"]), 7)

    def test_preview_routes_exist_in_standalone_app(self):
        paths = {
            getattr(route, "path", None)
            for route in full7_contract_api.app.routes
        }
        self.assertIn("/api/full7/contract-preview", paths)
        self.assertIn("/api/full7/contract-preview/health", paths)

    def test_preview_routes_are_not_mounted_in_production(self):
        paths = {
            getattr(route, "path", None)
            for route in production_entry.app.routes
        }
        self.assertNotIn("/api/full7/contract-preview", paths)
        self.assertNotIn("/api/full7/contract-preview/health", paths)


if __name__ == "__main__":
    unittest.main()
