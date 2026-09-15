"""Render entry point: legacy V1.1.6 routes + FULL7_GATED_1.0.0.

The existing V1.1.6 production application remains mounted for backward
compatibility. FULL-7 validation and the OOS-validated gated prediction API are
mounted alongside it. In FULL7_GATED_1.0.0 only BTTS is recommendation-eligible;
1X2 and O/U 2.5 remain probability-only.
"""
import app_v040 as legacy
from spec11_joint_core_patch import apply_patch
from full7_dev_api import router as full7_router
from full7_final_api import router as full7_final_router

app = apply_patch(legacy)
app.include_router(full7_router)
app.include_router(full7_final_router)
