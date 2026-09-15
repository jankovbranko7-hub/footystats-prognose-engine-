"""Render entry point: V1.1.6 production engine + FULL-7 validation infrastructure.

The existing V1.1.6 recommendation engine remains the active production decision
path. FULL-7 is mounted as validation/audit endpoints only until its market models
are separately production-validated.
"""
import app_v040 as legacy
from spec11_joint_core_patch import apply_patch
from full7_dev_api import router as full7_router
from full7_final_api import router as full7_final_router

app = apply_patch(legacy)
app.include_router(full7_router)
app.include_router(full7_final_router)
