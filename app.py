"""Render entry point: FootyStats V1.1.6 Joint-Core research integration.

The main production branch remains unchanged. This entry point is committed only
to research/v116-joint-core until validation and explicit release authorization.
"""
import app_v040 as legacy
from spec11_joint_core_patch import apply_patch

app = apply_patch(legacy)
