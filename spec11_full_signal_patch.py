"""Production wrapper for SPEC v1.1 full-signal strongest-market analysis."""
from __future__ import annotations
import time
from typing import Any, Dict
from spec11_strongest_market_engine import ENGINE_NAME, ENGINE_VERSION, SPEC_VERSION
from spec11_strongest_market_patch import apply_patch as apply_base_patch


def apply_patch(legacy: Any) -> Any:
    app = apply_base_patch(legacy)
    legacy.INDEX_HTML = legacy.INDEX_HTML.replace(
        "5 Dateien · Strict Pre-Match · COLD START und LOW SAMPLE erlaubt · kein V0.4.3 · kein V0.4.2 · kein Fallback · keine Odds · keine SPIELEN/BEOBACHTEN/AUSLASSEN-Engine.",
        "5 Dateien · vollständige sinnvolle SPEC-v1.1-Signalbreite · verwandte Felder als Evidenzblöcke · unabhängige Quellen zuerst · COLD START/LOW SAMPLE erlaubt · kein V0.4.x · kein Fallback · keine Odds · keine Decision Engine.",
    ).replace(
        "Keine versteckten Gewichte und keine Modellwahrscheinlichkeit. Die Rangfolge basiert auf der Richtung der tatsächlich verfügbaren SPEC-v1.1-Signale.",
        "Keine Modellwahrscheinlichkeit. Verwandte FootyStats-Felder werden gruppiert; primär zählt die Richtung unabhängiger zentraler Quellen. Diagnostik zählt nicht als Ranking-Stimme.",
    )
    app.router.routes = [r for r in app.router.routes if getattr(r, "path", None) != "/api/health"]

    def health() -> Dict[str, Any]:
        return {
            "ok": True,
            "production": True,
            "engine": ENGINE_NAME,
            "version": ENGINE_VERSION,
            "spec_version": SPEC_VERSION,
            "architecture": "SPEC_V1_1_FULL_SIGNAL_COMPARISON",
            "analysis_type": "STRONGEST_MARKET",
            "decision_engine": "NONE",
            "probability_core": "NONE",
            "v043_used": False,
            "v042_used": False,
            "fallback": "NONE",
            "odds_used": False,
            "cold_start_supported": True,
            "low_sample_supported": True,
            "player_analysis_scope": "TARGET_HOME_AWAY_ONLY",
            "league_player_pages_role": "RETRIEVAL_COMPLETENESS_AND_AUDIT_ONLY",
            "other_league_players_market_evidence": False,
            "shortcut_capture_unix": int(time.time()),
        }

    app.add_api_route("/api/health", health, methods=["GET"])
    app.version = ENGINE_VERSION
    app.title = "FootyStats SPEC v1.1 Full-Signal Strongest Market"
    return app
