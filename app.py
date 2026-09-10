"""Render entry point: standalone FootyStats SPEC v1.1 native engine."""
import app_v040 as legacy
from spec11_native_patch import apply_patch

app = apply_patch(legacy)
