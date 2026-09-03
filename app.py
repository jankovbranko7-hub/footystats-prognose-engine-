"""Render entry point for FootyStats Prognose Engine V0.4.3 FULL-5 candidate."""
import app_v040 as legacy
import v043_engine

# v043_engine uses a postponed annotation for the legacy Payload model.
# Expose the frozen legacy module in the patch module's globals so FastAPI/
# Pydantic can resolve that annotation without changing production V0.4.2.
v043_engine.legacy = legacy

app = v043_engine.apply_patch(legacy)
