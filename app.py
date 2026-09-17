"""Render entry point: legacy compatibility + final FULL7 contract engine.

The existing legacy application remains mounted for backward compatibility.
FULL-7 validation stays available and the stable /api/full7/predict plus
/api/full7/engine-health routes are served by the validated FULL7 contract
engine with all seven markets receiving probability, evidence and a decision.
"""
import app_v040 as legacy
from spec11_joint_core_patch import apply_patch
from full7_dev_api import router as full7_router
from full7_contract_api import production_router as full7_final_router

app = apply_patch(legacy)
app.include_router(full7_router)
app.include_router(full7_final_router)
