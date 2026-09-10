"""Final SPEC v1.1 target-player scope patch.

The league-wide /league-players response remains fully paginated for retrieval
completeness, but only HOME_ID/AWAY_ID player rows may influence market
analysis. No league-wide player benchmark is used as market evidence.
"""
from __future__ import annotations
from typing import Any, Dict, List, Tuple

import spec11_strongest_market_engine as engine
import spec11_strongest_market_patch as surface
from spec11_native_engine import MARKETS, SUPPORT, CONTRADICT, NEUTRAL, UNAVAILABLE, _num, _payload, _page_rows
from spec11_signal_expansion import sig

ENGINE_NAME = "FOOTYSTATS_SPEC_V1_1_FULL_SIGNAL_STRONGEST_MARKET"
ENGINE_VERSION = "1.1.3-target-player-scope"


def _rows(wrapper: Any) -> List[Dict[str, Any]]:
    payload = _payload(wrapper)
    return _page_rows(payload.get("pages")) if isinstance(payload, dict) else []


def _target(rows: List[Dict[str, Any]], team_id: int) -> List[Dict[str, Any]]:
    out = []
    for row in rows:
        ids = (_num(row.get("club_team_id")), _num(row.get("club_team_2_id")))
        if any(v is not None and int(v) == int(team_id) for v in ids):
            out.append(row)
    return out


def _summary(players: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not players:
        return {"available": False, "players_found": 0, "active_players": 0}
    active = [p for p in players if (_num(p.get("minutes_played_overall")) or 0) > 0]
    minutes = sum(_num(p.get("minutes_played_overall")) or 0 for p in players)
    appearances = sum(_num(p.get("appearances_overall")) or 0 for p in players)
    goals = sum(_num(p.get("goals_overall")) or 0 for p in players)
    assists = sum(_num(p.get("assists_overall")) or 0 for p in players)
    inv90 = ((goals + assists) * 90.0 / minutes) if minutes > 0 else None
    per90 = [_num(p.get("goals_involved_per_90_overall")) for p in active]
    per90 = [v for v in per90 if v is not None]
    mean_inv90 = (sum(per90) / len(per90)) if per90 else None
    advanced_fields = ("xg_per_90_overall", "npxg_per_90_overall", "xa_per_90_overall", "shots", "shots_on_target")
    advanced = {
        field: [v for v in (_num(p.get(field)) for p in active) if v is not None]
        for field in advanced_fields
    }
    return {
        "available": True,
        "players_found": len(players),
        "active_players": len(active),
        "minutes_total": round(minutes, 2),
        "appearances_total": round(appearances, 2),
        "goals_total": round(goals, 2),
        "assists_total": round(assists, 2),
        "team_involvement_per90": round(inv90, 4) if inv90 is not None else None,
        "mean_player_involvement_per90": round(mean_inv90, 4) if mean_inv90 is not None else None,
        "advanced_available_counts": {k: len(v) for k, v in advanced.items()},
    }


def _direction(a: Any, b: Any):
    a, b = _num(a), _num(b)
    if a is None or b is None:
        return None
    return 1 if a > b else (-1 if a < b else 0)


def _triplet(domain: str, direction, reason: str, **values):
    if direction is None:
        statuses = {m: UNAVAILABLE for m in ("home_win", "draw", "away_win")}
    elif direction > 0:
        statuses = {"home_win": SUPPORT, "draw": NEUTRAL, "away_win": CONTRADICT}
    elif direction < 0:
        statuses = {"home_win": CONTRADICT, "draw": NEUTRAL, "away_win": SUPPORT}
    else:
        statuses = {"home_win": NEUTRAL, "draw": SUPPORT, "away_win": NEUTRAL}
    return [sig("PLAYER", domain, m, statuses[m], reason, "PLAYER", True, **values) for m in ("home_win", "draw", "away_win")]


def _disabled_native_player_signals(wrapper: Any, home_id: int, away_id: int):
    """Disable legacy league-player reference logic; target-only extension owns Player evidence."""
    rows = _rows(wrapper)
    hp, ap = _target(rows, home_id), _target(rows, away_id)
    return [], {
        "mode": "TARGET_ONLY_VIA_SPEC11_EXTENSION",
        "raw_league_players": len(rows),
        "home_players": len(hp),
        "away_players": len(ap),
    }


def target_only_extended_player(wrapper: Any, home_id: int, away_id: int) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    rows = _rows(wrapper)
    hp, ap = _target(rows, home_id), _target(rows, away_id)
    home, away = _summary(hp), _summary(ap)
    scope = {
        "raw_league_players": len(rows),
        "analysis_players": len(hp) + len(ap),
        "home_players": len(hp),
        "away_players": len(ap),
        "analysis_scope": "ONLY_HOME_AND_AWAY_TARGET_PLAYERS",
        "other_league_players_used_as_market_evidence": False,
        "home_summary": home,
        "away_summary": away,
    }
    out: List[Dict[str, Any]] = []
    if not (home["available"] and away["available"]):
        for market, _ in MARKETS:
            out.append(sig("PLAYER", "TARGET_PLAYER_COVERAGE", market, UNAVAILABLE,
                           "Mindestens ein Zielteam fehlt in PlayerDaten; niemals 0-Stärke oder ligaweiter Ersatz.",
                           "PLAYER", True, home_players=len(hp), away_players=len(ap)))
        return out, scope

    # Target-team player depth: one grouped 1X2 evidence block.
    depth_votes = [
        _direction(home.get("active_players"), away.get("active_players")),
        _direction(home.get("players_found"), away.get("players_found")),
    ]
    known_depth = [v for v in depth_votes if v is not None]
    depth_direction = None if not known_depth else (1 if sum(known_depth) > 0 else (-1 if sum(known_depth) < 0 else 0))
    out.extend(_triplet("TARGET_PLAYER_DEPTH", depth_direction,
                        "Nur Spieler der beiden Zielteams: verfügbare/aktive Kadertiefe; keine Liga-Spieler als Referenz.",
                        home_active=home["active_players"], away_active=away["active_players"],
                        home_found=home["players_found"], away_found=away["players_found"]))

    # Target-team attacking contribution can compare relative team attacking strength for 1X2.
    attack_direction = _direction(home.get("mean_player_involvement_per90"), away.get("mean_player_involvement_per90"))
    out.extend(_triplet("TARGET_PLAYER_ATTACK_OUTPUT", attack_direction,
                        "Nur Zielteams: mittlere Goal-Involvement/90 der Spieler mit Minuten.",
                        home=home.get("mean_player_involvement_per90"),
                        away=away.get("mean_player_involvement_per90")))

    # For BTTS/O-U there is no official absolute target-player threshold in SPEC v1.1.
    # Preserve the information as diagnostics instead of inventing a market vote.
    for market in ("btts_yes", "btts_no", "over_2_5", "under_2_5"):
        out.append(sig("PLAYER", "TARGET_PLAYER_GOAL_CONTEXT", market, NEUTRAL,
                       "Nur Zielteam-Spieler. Ohne offizielle absolute Player-Schwelle keine künstliche BTTS/O-U-Ranking-Stimme.",
                       "DIAGNOSTIC", False,
                       home_involvement=home.get("mean_player_involvement_per90"),
                       away_involvement=away.get("mean_player_involvement_per90")))
        out.append(sig("PLAYER", "TARGET_PLAYER_ADVANCED_COVERAGE", market, NEUTRAL,
                       "xG/npxG/xA/Shots der Zielteam-Spieler werden genutzt, wenn geliefert; reine Coverage ist keine Marktstimme.",
                       "DIAGNOSTIC", False,
                       home_counts=home.get("advanced_available_counts"),
                       away_counts=away.get("advanced_available_counts")))
    return out, scope


def apply_patch(legacy: Any) -> Any:
    # The strongest-market function resolves these module globals at runtime.
    engine._player_signals = _disabled_native_player_signals
    engine.extended_player = target_only_extended_player
    engine.ENGINE_NAME = ENGINE_NAME
    engine.ENGINE_VERSION = ENGINE_VERSION

    surface.analyze_bundle = engine.analyze_bundle
    surface.ENGINE_NAME = ENGINE_NAME
    surface.ENGINE_VERSION = ENGINE_VERSION

    import spec11_full_signal_patch as full
    full.ENGINE_NAME = ENGINE_NAME
    full.ENGINE_VERSION = ENGINE_VERSION
    app = full.apply_patch(legacy)

    # Replace the earlier health wording: league-wide player pages are retrieval completeness only.
    app.router.routes = [r for r in app.router.routes if getattr(r, "path", None) != "/api/health"]
    import time
    def health():
        return {
            "ok": True, "production": True, "engine": ENGINE_NAME, "version": ENGINE_VERSION,
            "spec_version": "1.1", "architecture": "SPEC_V1_1_FULL_SIGNAL_COMPARISON",
            "analysis_type": "STRONGEST_MARKET", "decision_engine": "NONE",
            "probability_core": "NONE", "v043_used": False, "v042_used": False,
            "fallback": "NONE", "odds_used": False, "cold_start_supported": True,
            "low_sample_supported": True, "player_analysis_scope": "TARGET_HOME_AWAY_ONLY",
            "league_player_pages_role": "RETRIEVAL_COMPLETENESS_AND_AUDIT_ONLY",
            "other_league_players_market_evidence": False,
            "shortcut_capture_unix": int(time.time()),
        }
    app.add_api_route("/api/health", health, methods=["GET"])
    app.version = ENGINE_VERSION
    app.title = "FootyStats SPEC v1.1 Full-Signal Strongest Market"
    return app
