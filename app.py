"""Render entry point for FootyStats V0.5.0 CONTEXT-AWARE production."""
import app_v040 as legacy
import v043_engine
from v050_context_release import apply_patch

# Keep the frozen V0.4.3 FULL-5 probability stack bound exactly as before.
v043_engine.legacy = legacy

app = apply_patch(legacy)

# V0.5.0 is the only visible product identity. Historical protocol internals
# remain available in backend diagnostics, but old V5.2 naming must not appear
# as if it were the active decision engine.
legacy.INDEX_HTML = legacy.INDEX_HTML.replace(
    "Legacy V5.2-Diagnostik", "Interne Diagnose (ohne Einfluss)"
).replace(
    "V5.2-Protokoll", "Interne Diagnose (ohne Einfluss)"
)
