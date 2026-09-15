import unittest

import app as production_entry


class Full7ProductionWiringTests(unittest.TestCase):
    def test_full7_routes_are_mounted(self):
        paths={getattr(route,"path",None) for route in production_entry.app.routes}
        self.assertIn("/api/full7/health",paths)
        self.assertIn("/api/full7/validate",paths)

    def test_existing_app_still_has_non_full7_routes(self):
        paths={getattr(route,"path",None) for route in production_entry.app.routes}
        legacy=[p for p in paths if isinstance(p,str) and not p.startswith("/api/full7")]
        self.assertTrue(legacy)


if __name__=="__main__":
    unittest.main()
