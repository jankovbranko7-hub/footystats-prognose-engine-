"""FootyStats V1 final production lock.

This module wires the full V1 specialist layer onto the frozen V0.4.3 FULL-5
probability core and applies two production fixes found during the final audit:

1. FormDaten from the existing iPhone exporter stores form pages under
   ``teams``. The initial full-specialist draft also looked for ``pages`` and
   would therefore miss real FormDaten in production. This lock accepts the
   real ``teams`` shape while retaining compatibility with ``pages``/``data``.
2. Cross-family robust-market selection must use the same normalized family
   strength logic already established by the V0.4.3/V0.4.1 family selector.
   Comparing raw percentages first would structurally disadvantage 1X2 versus
   binary BTTS/O-U markets.

No lambda, FULL-5 coefficient, Dixon-Coles parameter or market probability is
changed here.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

import v1_full_engine as engine

VERSION = engine.VERSION
BASELINE = engine.BASELINE


def _form_records_production(form_data: Any) -> List[Dict[str, Any]]:
    """Read the real five-file FormDaten export without inventing fallback data."""
    records: List[Dict[str, Any]] = []
    if not isinstance(form_data, dict):
        return records

    containers = []
    teams = form_data.get("teams")
    if isinstance(teams, list):
        containers.extend(teams)
    pages = form_data.get("pages")
    if isinstance(pages, list):
        containers.extend(pages)

    for page in containers:
        if isinstance(page, dict):
            data = page.get("data")
            if isinstance(data, list):
                records.extend(item for item in data if isinstance(item, dict))

    if not records:
        data = form_data.get("data")
        if isinstance(data, list):
            records.extend(item for item in data if isinstance(item, dict))
    return records


def _num_obj(value: Any) -> Optional[float]:
    try:
        if value is None or isinstance(value, bool):
            return None
        return float(value)
    except Exception:
        return None


def _select_robust_market_production(
    assessments: Sequence[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Prefer decision quality, then normalized family strength, then probability."""
    if not assessments:
        return None
    for decision in ("SPIELEN", "BEOBACHTEN", "AUSLASSEN"):
        candidates = [item for item in assessments if item.get("decision") == decision]
        if candidates:
            return max(
                candidates,
                key=lambda item: (
                    _num_obj(item.get("family_strength_pct")) or -1.0,
                    _num_obj(item.get("probability_pct")) or -1.0,
                ),
            )
    return None


# Install the audited production fixes before the full engine is applied.
engine._form_records = _form_records_production
engine._select_robust_market = _select_robust_market_production


def apply_patch(legacy: Any) -> Any:
    """Install final V1 while keeping the entire V0.4.3 probability path frozen."""
    return engine.apply_patch(legacy)
