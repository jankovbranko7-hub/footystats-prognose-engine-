"""Render entry point: FootyStats SPEC v1.1 full-signal strongest-market analysis."""
import app_v040 as legacy
from spec11_target_player_scope_patch import apply_patch

app = apply_patch(legacy)
