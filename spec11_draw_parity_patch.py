"""Draw-parity correction for FootyStats SPEC v1.1 strongest-market analysis.

General strength parity is neutral evidence, not draw evidence. Draw support must
come from draw-specific evidence such as draw/WDL profiles, never merely from
PPG/xG/table/player equality.
"""
from __future__ import annotations
import time
from typing import Any, Dict, List, Tuple

import spec11_full_signal_patch as full
import spec11_strongest_market_engine as engine
import spec11_strongest_market_patch as surface
import spec11_target_player_scope_patch as target
import spec11_ui_cleanup_patch as ui
from spec11_native_engine import SUPPORT, CONTRADICT, NEUTRAL, UNAVAILABLE, _num

ENGINE_NAME = "FOOTYSTATS_SPEC_V1_1_FULL_SIGNAL_STRONGEST_MARKET"
ENGINE_VERSION = "1.1.5-draw-parity"

_GENERIC_PARITY_DOMAINS = {
    "OVERALL_PREMATCH_PPG",
    "VENUE_PPG",
    "UNDERLYING_XG",
    "SCORING_CONCEDING_STRENGTH",
    "HALF_TIME_PPG",
    "CURRENT_FORM_PPG",
    "RESULT_FORM_TREND",
    "HTPPG_FORM_TREND",
    "RELATIVE_TABLE_STRENGTH",
    "GOAL_DIFFERENCE_PER_MATCH",
    "TARGET_PLAYER_DEPTH",
    "TARGET_PLAYER_ATTACK_OUTPUT",
}


def _cmp(a: Any, b: Any):
    a, b = _num(a), _num(b)
    if a is None or b is None:
        return None
    return 1 if a > b else (-1 if a < b else 0)


def _neutralize_generic_draw_parity(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """A tie in a generic strength measure is neutral, never a draw vote."""
    for signal in rows:
        if (
            signal.get("market") == "draw"
            and signal.get("domain") in _GENERIC_PARITY_DOMAINS
            and signal.get("status") == SUPPORT
        ):
            signal["status"] = NEUTRAL
            signal["reason"] = str(signal.get("reason") or "") + (
                " Gleichstand/Parität eines allgemeinen Stärkeindikators ist NEUTRAL und keine Draw-Evidenz."
            )
    return rows


def _recompute_prematch_strength(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """For PPG+xG, zero is a neutral component; one real directional edge may decide the block."""
    group = [s for s in rows if s.get("domain") == "PREMATCH_STRENGTH" and s.get("market") in {"home_win", "draw", "away_win"}]
    if not group:
        return rows
    values = group[0].get("values") or {}
    comparisons = []
    for home_key, away_key in (("home_ppg", "away_ppg"), ("home_xg", "away_xg")):
        c = _cmp(values.get(home_key), values.get(away_key))
        if c is not None:
            comparisons.append(c)

    if not comparisons:
        statuses = {"home_win": UNAVAILABLE, "draw": UNAVAILABLE, "away_win": UNAVAILABLE}
    else:
        directional = [c for c in comparisons if c != 0]
        if not directional or len(set(directional)) > 1:
            statuses = {"home_win": NEUTRAL, "draw": NEUTRAL, "away_win": NEUTRAL}
        elif directional[0] > 0:
            statuses = {"home_win": SUPPORT, "draw": NEUTRAL, "away_win": CONTRADICT}
        else:
            statuses = {"home_win": CONTRADICT, "draw": NEUTRAL, "away_win": SUPPORT}

    for signal in group:
        signal["status"] = statuses[signal["market"]]
        signal["reason"] = (
            "Echte Pre-Match-PPG/xG-Werte: Gleichstand eines Teilindikators ist neutral; "
            "nur eine konsistente nicht-null Richtung erzeugt 1X2-Stärke-Evidenz. Parität erzeugt keine Draw-Stimme."
        )
    return rows


def _wrap_rows(fn, *, prematch: bool = False):
    def wrapped(*args, **kwargs):
        rows = fn(*args, **kwargs)
        if prematch:
            rows = _recompute_prematch_strength(rows)
        return _neutralize_generic_draw_parity(rows)
    return wrapped


def _wrap_pair(fn):
    def wrapped(*args, **kwargs):
        rows, coverage = fn(*args, **kwargs)
        return _neutralize_generic_draw_parity(rows), coverage
    return wrapped


def apply_patch(legacy: Any) -> Any:
    app = ui.apply_patch(legacy)

    # Patch the signal functions used dynamically by the frozen strongest-market analyzer.
    engine._match_signals = _wrap_rows(engine._match_signals, prematch=True)
    engine.extended_match = _wrap_rows(engine.extended_match)
    engine._league_signals = _wrap_rows(engine._league_signals)
    engine.extended_league = _wrap_rows(engine.extended_league)
    engine._form_signals = _wrap_pair(engine._form_signals)
    engine.extended_form = _wrap_rows(engine.extended_form)
    engine._table_signals = _wrap_pair(engine._table_signals)
    engine.extended_table = _wrap_rows(engine.extended_table)
    engine.extended_player = _wrap_pair(engine.extended_player)

    # Promote the implementation version without changing SPEC v1.1.
    target.ENGINE_VERSION = ENGINE_VERSION
    engine.ENGINE_VERSION = ENGINE_VERSION
    surface.ENGINE_VERSION = ENGINE_VERSION
    full.ENGINE_VERSION = ENGINE_VERSION
    ui.ENGINE_VERSION = ENGINE_VERSION

    base_analyze = legacy._analyze_bundle
    def analyze_with_draw_parity(parsed_files: List[Dict[str, Any]]) -> Dict[str, Any]:
        result = base_analyze(parsed_files)
        if isinstance(result, dict) and result.get("ok"):
            result["engine"] = ENGINE_NAME
            result["engine_version"] = ENGINE_VERSION
            result.setdefault("method", {})["draw_parity_policy"] = (
                "Gleichstand/Parität allgemeiner 1X2-Stärkeindikatoren ist NEUTRAL. "
                "Draw-Bestätigung darf nur aus draw-spezifischer Evidenz entstehen, nicht aus bloßer PPG/xG/Table/Player-Gleichheit."
            )
            result.setdefault("notes", []).append(
                "Draw-Parity-Guard: Gleichheit generischer Stärkeindikatoren erzeugt keine Unentschieden-Stimme."
            )
        return result
    legacy._analyze_bundle = analyze_with_draw_parity

    legacy.INDEX_HTML = legacy.INDEX_HTML.replace("Engine v1.1.4", "Engine v1.1.5").replace(
        "Build 1.1.4-ranking-consistency", "Build 1.1.5-draw-parity"
    )

    app.router.routes = [r for r in app.router.routes if getattr(r, "path", None) != "/api/health"]
    def health() -> Dict[str, Any]:
        return {
            "ok": True, "production": True, "engine": ENGINE_NAME, "version": ENGINE_VERSION,
            "spec_version": "1.1", "architecture": "SPEC_V1_1_FULL_SIGNAL_COMPARISON",
            "analysis_type": "STRONGEST_MARKET", "decision_engine": "NONE",
            "probability_core": "NONE", "v043_used": False, "v042_used": False,
            "fallback": "NONE", "odds_used": False, "cold_start_supported": True,
            "low_sample_supported": True, "player_analysis_scope": "TARGET_HOME_AWAY_ONLY",
            "league_player_pages_role": "RETRIEVAL_COMPLETENESS_AND_AUDIT_ONLY",
            "other_league_players_market_evidence": False,
            "ranking_consistency_guard": True,
            "clear_requires_positive_total_evidence": True,
            "draw_parity_guard": True,
            "generic_strength_parity_is_draw_evidence": False,
            "shortcut_capture_unix": int(time.time()),
        }
    app.add_api_route("/api/health", health, methods=["GET"])
    app.version = ENGINE_VERSION
    app.title = "FootyStats SPEC v1.1 · Engine v1.1.5"
    return app
