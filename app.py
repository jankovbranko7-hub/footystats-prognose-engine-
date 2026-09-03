"""Render entry point for FootyStats Prognose Engine V0.4.3 FULL-5 candidate."""
import app_v040 as legacy
from v043_engine import apply_patch

app = apply_patch(legacy)
