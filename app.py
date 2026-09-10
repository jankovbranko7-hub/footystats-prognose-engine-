"""Render entry point: FootyStats SPEC v1.1 full-signal strongest-market analysis."""
import app_v040 as legacy
from spec11_full_signal_patch import apply_patch

app = apply_patch(legacy)
