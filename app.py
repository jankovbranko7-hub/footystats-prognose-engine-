"""Render entry point for FootyStats Prognose Engine V0.4.1."""
import app_v040 as legacy
from v041_engine import apply_patch

app = apply_patch(legacy)
