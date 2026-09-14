"""Render entry point: FootyStats V1.1.6 Joint-Outcome production integration.

This entry point activates the validated Joint-Outcome core for V1.1.6.
"""
import app_v040 as legacy
from spec11_joint_core_patch import apply_patch

app = apply_patch(legacy)
