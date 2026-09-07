"""Render entry point for FootyStats V1 on the frozen V0.4.3 FULL-5 core."""
import app_v040 as legacy
import v043_engine
from v1_full_engine import apply_patch

# FastAPI/Pydantic resolves the postponed legacy Payload annotation from the
# patch module globals. Keep this explicit binding from the proven V0.4.3 path.
v043_engine.legacy = legacy

app = apply_patch(legacy)
