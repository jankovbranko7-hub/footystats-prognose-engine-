"""Render entry point: FootyStats SPEC v1.1 strongest-market analysis."""
import app_v040 as legacy
from spec11_strongest_market_patch import apply_patch

app = apply_patch(legacy)
