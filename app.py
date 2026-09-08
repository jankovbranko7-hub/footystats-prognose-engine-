"""Render entry point for FootyStats FULL-5 NEXT production."""
import app_v040 as legacy
import v043_engine
from full5_next_release import apply_patch

# FastAPI/Pydantic resolves the postponed legacy Payload annotation from the
# patch module globals. Keep this explicit binding from the tested candidate.
v043_engine.legacy = legacy

app = apply_patch(legacy)
