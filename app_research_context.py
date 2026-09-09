"""Research-only entry point: V0.4.3 FULL-5 plus audited current pre-match context.

Production must continue to use app:app. This module is intentionally isolated
on a research branch and must not be wired to production without explicit approval.
"""
import app_v040 as legacy
import v043_engine
from v043_observe_fazit_ui import apply_patch as apply_v043_production
from research.research_context_engine import install_research_context

v043_engine.legacy = legacy
app = apply_v043_production(legacy)
app = install_research_context(legacy)

legacy.INDEX_HTML = legacy.INDEX_HTML.replace(
    "fetch('/api/predict-bundle',{method:'POST',body:formFor(files)})",
    "fetch('/api/research/predict-context',{method:'POST',body:formFor(files)})",
    1,
)
app.title = "FootyStats V0.4.3 FULL-5 + Current Context (RESEARCH ONLY)"
