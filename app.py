"""Render entry point for FootyStats Prognose Engine V0.4.3 FULL-5 production."""
import app_v040 as legacy
import v043_engine
from v043_release import apply_patch

# FastAPI/Pydantic resolves the postponed legacy Payload annotation from the
# patch module globals. Keep this explicit binding from the tested candidate.
v043_engine.legacy = legacy

app = apply_patch(legacy)
