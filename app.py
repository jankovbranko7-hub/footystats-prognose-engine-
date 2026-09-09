"""Render entry point for FootyStats V0.5.0 CONTEXT-AWARE production."""
import app_v040 as legacy
import v043_engine
from v050_context_release import apply_patch

# Keep the frozen V0.4.3 FULL-5 probability stack bound exactly as before.
v043_engine.legacy = legacy

app = apply_patch(legacy)
