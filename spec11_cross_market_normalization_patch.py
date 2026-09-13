"""Cross-market ranking normalization for SPEC v1.1.

This is a ranking-comparison correction only. Signal extraction, source semantics,
draw parity, integrity gates, player scope, missing-value handling and the
underlying football logic remain unchanged.

Problem fixed:
1X2 can have up to five ranking-eligible central sources, while BTTS/O-U
normally have three. Ranking by absolute source-net or summed source-block score
can therefore structurally favor a market family merely because it has more
applicable sources.

Correction:
Rank markets first by normalized source agreement among the sources that are
actually ranking-eligible for that market, then by normalized within-source and
raw-signal balances. Absolute source/signal counts remain visible for audit but
are not used as primary cross-market advantages.
"""
from __future__ import annotations

from typing import Any, Dict, List
import time

import spec11_strongest_market_engine as engine
import spec11_strongest_market_patch as surface
import spec11_target_player_scope_patch as target
import spec11_draw_parity_patch as draw
import spec11_full_signal_patch as full
import spec11_ui_cleanup_patch as ui

from spec11_report_download_patch import apply_patch as apply_report_patch

ENGINE_NAME = "FOOTYSTATS_SPEC_V1_1_FULL_SIGNAL_STRONGEST_MARKET"
ENGINE_VERSION = "1.1.6-cross-market-normalized"

_BASE_CONSISTENT_AGGREGATE = target._consistent_aggregate


def _rate(numerator: int, denominator: int):
    return (float(numerator) / float(denominator)) if denominator > 0 else None


def _normalized_aggregate(signals: List[Dict[str, Any]], market: str) -> Dict[str, Any]:
    row = _BASE_CONSISTENT_AGGREGATE(signals, market)

    available_sources = len(row.get("available_central_sources") or [])
    support_sources = len(row.get("central_support_sources") or [])
    contradiction_sources = len(row.get("central_contradiction_sources") or [])
    neutral_sources = max(available_sources - support_sources - contradiction_sources, 0)

    row["applicable_central_source_count"] = available_sources
    row["central_support_source_count"] = support_sources
    row["central_contradiction_source_count"] = contradiction_sources
    row["central_neutral_source_count"] = neutral_sources
    row["source_support_rate"] = round(_rate(support_sources, available_sources), 6) if available_sources else None
    row["source_contradiction_rate"] = round(_rate(contradiction_sources, available_sources), 6) if available_sources else None
    row["source_neutral_rate"] = round(_rate(neutral_sources, available_sources), 6) if available_sources else None

    available_signals = int(row.get("available_signal_count") or 0)
    support_signals = int(row.get("support_count") or 0)
    contradiction_signals = int(row.get("contradiction_count") or 0)
    neutral_signals = int(row.get("neutral_count") or 0)
    row["signal_support_rate"] = round(_rate(support_signals, available_signals), 6) if available_signals else None
    row["signal_contradiction_rate"] = round(_rate(contradiction_signals, available_signals), 6) if available_signals else None
    row["signal_neutral_rate"] = round(_rate(neutral_signals, available_signals), 6) if available_signals else None
    row["cross_market_normalized"] = True
    return row


def _normalized_rank_key(m: Dict[str, Any]) -> tuple:
    """Compare market families without rewarding a larger possible source count."""
    source_balance = m.get("source_balance")
    support_rate = m.get("source_support_rate")
    contradiction_rate = m.get("source_contradiction_rate")
    block_balance = m.get("source_block_balance")
    evidence_balance = m.get("evidence_balance")
    signal_support_rate = m.get("signal_support_rate")
    signal_contradiction_rate = m.get("signal_contradiction_rate")

    return (
        float(source_balance if source_balance is not None else -2.0),
        -float(contradiction_rate if contradiction_rate is not None else 2.0),
        float(support_rate if support_rate is not None else -2.0),
        float(block_balance if block_balance is not None else -2.0),
        float(evidence_balance if evidence_balance is not None else -2.0),
        -float(signal_contradiction_rate if signal_contradiction_rate is not None else 2.0),
        float(signal_support_rate if signal_support_rate is not None else -2.0),
    )


def _same_normalized_rank(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    return _normalized_rank_key(a) == _normalized_rank_key(b)


def apply_patch(legacy: Any) -> Any:
    app = apply_report_patch(legacy)

    # The analyzer resolves these names dynamically at request time.
    target._consistent_aggregate = _normalized_aggregate
    target._consistent_rank_key = _normalized_rank_key
    target._same_consistent_rank = _same_normalized_rank
    engine._aggregate = _normalized_aggregate
    engine._rank_key = _normalized_rank_key
    engine._same_rank = _same_normalized_rank

    # Same engine family; traceable patch-level build revision.
    target.ENGINE_NAME = ENGINE_NAME
    target.ENGINE_VERSION = ENGINE_VERSION
    engine.ENGINE_NAME = ENGINE_NAME
    engine.ENGINE_VERSION = ENGINE_VERSION
    surface.ENGINE_NAME = ENGINE_NAME
    surface.ENGINE_VERSION = ENGINE_VERSION
    draw.ENGINE_NAME = ENGINE_NAME
    draw.ENGINE_VERSION = ENGINE_VERSION
    full.ENGINE_NAME = ENGINE_NAME
    full.ENGINE_VERSION = ENGINE_VERSION
    ui.ENGINE_NAME = ENGINE_NAME
    ui.ENGINE_VERSION = ENGINE_VERSION

    base_analyze = legacy._analyze_bundle

    def analyze_cross_market_normalized(parsed_files: List[Dict[str, Any]]) -> Dict[str, Any]:
        result = base_analyze(parsed_files)
        if isinstance(result, dict) and result.get("ok"):
            result["engine"] = ENGINE_NAME
            result["engine_version"] = ENGINE_VERSION
            result.setdefault("method", {})["cross_market_ranking_policy"] = (
                "Märkte mit unterschiedlich vielen anwendbaren zentralen Quellen werden "
                "über normalisierte Quellenkonsistenz verglichen. 3/3 wird nicht allein "
                "deshalb gegenüber 1X2 benachteiligt, weil 1X2 bis zu fünf Quellen haben kann. "
                "Absolute Quellensummen bleiben Auditwerte, aber kein primärer Cross-Market-Vorteil."
            )
            result.setdefault("notes", []).append(
                "Cross-Market-Normalisierung aktiv: Ranking priorisiert source_balance, "
                "Contra-/Support-Raten sowie normalisierte Block- und Roh-Evidenz."
            )
        return result

    legacy._analyze_bundle = analyze_cross_market_normalized

    # Keep the quick view aligned with the corrected denominator and build.
    legacy.INDEX_HTML = legacy.INDEX_HTML.replace("Engine v1.1.5", "Engine v1.1.6")
    legacy.INDEX_HTML = legacy.INDEX_HTML.replace("Build 1.1.5-draw-parity", "Build 1.1.6-cross-market-normalized")
    legacy.INDEX_HTML = legacy.INDEX_HTML.replace(
        "esc((topMarket.central_support_sources||[]).length)+'/5'",
        "esc((topMarket.central_support_sources||[]).length)+'/'+esc((topMarket.available_central_sources||[]).length)+' aktiv'"
    )
    legacy.INDEX_HTML = legacy.INDEX_HTML.replace(
        "V1.1.5 rankt primär nach unabhängiger Quellenrichtung und Quellenbilanz; die Roh-Netto-Evidenz ist nachrangig und entscheidet nicht allein.",
        "V1.1.6 vergleicht Marktfamilien über normalisierte Quellenkonsistenz; absolute Quellensummen und Roh-Netto-Evidenz bleiben Auditwerte und entscheiden nicht allein."
    )
    legacy.INDEX_HTML = legacy.INDEX_HTML.replace(
        "SPEC_V1_1_ENGINE_V1_1_5_BACKTEST_REPORT",
        "SPEC_V1_1_ENGINE_V1_1_6_BACKTEST_REPORT"
    ).replace(
        "1.1.5-draw-parity",
        "1.1.6-cross-market-normalized"
    ).replace(
        "ENGINE-v1.1.5_BACKTEST.json",
        "ENGINE-v1.1.6_BACKTEST.json"
    )

    app.router.routes = [r for r in app.router.routes if getattr(r, "path", None) != "/api/health"]

    def health() -> Dict[str, Any]:
        return {
            "ok": True,
            "production": True,
            "engine": ENGINE_NAME,
            "version": ENGINE_VERSION,
            "spec_version": "1.1",
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
            "ranking_consistency_guard": True,
            "clear_requires_positive_total_evidence": True,
            "draw_parity_guard": True,
            "generic_strength_parity_is_draw_evidence": False,
            "cross_market_normalization": True,
            "cross_market_primary_metric": "NORMALIZED_APPLICABLE_SOURCE_BALANCE",
            "shortcut_capture_unix": int(time.time()),
        }

    app.add_api_route("/api/health", health, methods=["GET"])
    app.version = ENGINE_VERSION
    app.title = "FootyStats SPEC v1.1 · Engine v1.1.6"
    return app
