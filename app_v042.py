"""Parallel test entry point for FootyStats Prognose Engine V0.4.2."""
import app_v040 as legacy
from v042_engine import apply_patch

app = apply_patch(legacy)
