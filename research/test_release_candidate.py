"""Release-candidate smoke: import the real V0.5.0 patch over the real V0.4.3 stack."""
import inspect

import app_v040 as legacy
import v042_engine
import v043_engine
import v043_release
from research.learned_reliability_policy import LEARNED_CENTROIDS, POLICY_SOURCE
from v050_context_release import VERSION, apply_patch

v043_engine.legacy = legacy
app = apply_patch(legacy)

assert VERSION == "0.5.0"
assert app.version == "0.5.0"
assert "V0.5.0 CONTEXT-AWARE" in app.title
assert v043_release.FULL5_ALPHA == 3.0
assert v043_engine.FULL5_ALPHA == 3.0
assert v042_engine.RHO == -0.25
assert v043_engine.FEATURE_COUNT == 40
assert len(v043_engine.FULL5_FEATURES) == 40
assert len(v043_engine.FULL5_COEF) == 40
assert len(LEARNED_CENTROIDS) == 3
assert tuple(sorted(LEARNED_CENTROIDS)) == LEARNED_CENTROIDS

routes={getattr(route,"path",None):route for route in app.router.routes}
assert "/api/predict-bundle" in routes
assert "/api/archive-bundle" in routes
assert "/api/health" in routes
health=routes["/api/health"].endpoint()
assert health["ok"] is True
assert health["version"] == "0.5.0"
assert health["production"] is True
assert health["probability_core"] == "V0.4.3 FULL-5"
assert health["full5_alpha"] == 3.0
assert health["dixon_coles_rho"] == -0.25
assert health["iphone_files"] == 5
assert health["final_decision_source"] == POLICY_SOURCE
assert health["manual_performance_gates"] == "NONE"
assert health["current_context_numeric_probability_adjustment"] is False

# The promoted bundle analysis must be the context wrapper, while the wrapper's
# frozen baseline is the pre-promotion V0.4.3 analyzer captured in its closure.
assert legacy._analyze_bundle.__name__ == "context_analyze"
closure=inspect.getclosurevars(legacy._analyze_bundle).nonlocals
assert "baseline_analyze" in closure
assert callable(closure["baseline_analyze"])
assert closure["baseline_analyze"] is not legacy._analyze_bundle

assert "Current Match Context" not in legacy.INDEX_HTML  # German UI label below
assert "Aktueller Match-Kontext" in legacy.INDEX_HTML
assert "keine erfundene Prozentkorrektur" in legacy.INDEX_HTML

print("V0.5.0 real release candidate smoke passed")
