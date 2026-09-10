"""Final SPEC v1.1 target-player scope and ranking-consistency patch.

The league-wide /league-players response remains fully paginated for retrieval
completeness, but only HOME_ID/AWAY_ID player rows may influence market
analysis. No league-wide player benchmark is used as market evidence.

Ranking consistency rule:
- independent central sources remain primary;
- each source preserves its internal block balance instead of collapsing to a
  single +/- vote only;
- a market can be CLEAR only when both independent-source direction and total
  eligible evidence are positive and do not disagree in sign.
"""
from __future__ import annotations
from typing import Any, Dict, List, Tuple

import spec11_strongest_market_engine as engine
import spec11_strongest_market_patch as surface
from spec11_native_engine import MARKETS, SUPPORT, CONTRADICT, NEUTRAL, UNAVAILABLE, _num, _payload, _page_rows
from spec11_signal_expansion import sig

ENGINE_NAME = "FOOTYSTATS_SPEC_V1_1_FULL_SIGNAL_STRONGEST_MARKET"
ENGINE_VERSION = "1.1.4-ranking-consistency"

_BASE_AGGREGATE = engine._aggregate
_BASE_ANALYZE_BUNDLE = engine.analyze_bundle


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

    attack_direction = _direction(home.get("mean_player_involvement_per90"), away.get("mean_player_involvement_per90"))
    out.extend(_triplet("TARGET_PLAYER_ATTACK_OUTPUT", attack_direction,
                        "Nur Zielteams: mittlere Goal-Involvement/90 der Spieler mit Minuten.",
                        home=home.get("mean_player_involvement_per90"),
                        away=away.get("mean_player_involvement_per90")))

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


def _consistent_aggregate(signals: List[Dict[str, Any]], market: str) -> Dict[str, Any]:
    """Preserve the magnitude of each central source's internal evidence balance."""
    row = _BASE_AGGREGATE(signals, market)
    balances: Dict[str, float] = {}
    for source, evidence in row.get("source_evidence", {}).items():
        available = int(evidence.get("available_blocks") or 0)
        support = int(evidence.get("support_blocks") or 0)
        contradict = int(evidence.get("contradiction_blocks") or 0)
        balance = ((support - contradict) / available) if available > 0 else None
        evidence["block_balance"] = round(balance, 6) if balance is not None else None
        if balance is not None:
            balances[source] = balance

    score = sum(balances.values()) if balances else None
    mean = (score / len(balances)) if balances else None
    evidence_balance = row.get("evidence_balance")
    source_net = int(row.get("source_net_evidence") or 0)
    net = int(row.get("net_evidence") or 0)
    sign_conflict = bool(
        (source_net > 0 and net < 0) or
        (source_net < 0 and net > 0) or
        (mean is not None and evidence_balance is not None and mean * evidence_balance < 0)
    )
    row["source_block_balances"] = {k: round(v, 6) for k, v in balances.items()}
    row["source_block_score"] = round(score, 6) if score is not None else None
    row["source_block_balance"] = round(mean, 6) if mean is not None else None
    row["direction_conflict"] = sign_conflict
    return row


def _consistent_rank_key(m: Dict[str, Any]) -> tuple:
    """Independent source breadth first; source-internal balance resolves compression."""
    score = m.get("source_block_score")
    source_balance = m.get("source_balance")
    evidence_balance = m.get("evidence_balance")
    return (
        int(m.get("source_net_evidence") or 0),
        float(score if score is not None else -99.0),
        len(m.get("central_support_sources") or []),
        -len(m.get("central_contradiction_sources") or []),
        float(source_balance if source_balance is not None else -2.0),
        float(evidence_balance if evidence_balance is not None else -2.0),
        int(m.get("net_evidence") or 0),
        -int(m.get("contradiction_count") or 0),
        int(m.get("available_signal_count") or 0),
    )


def _same_consistent_rank(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    return _consistent_rank_key(a) == _consistent_rank_key(b)


def _clear_market(top: Dict[str, Any], second: Dict[str, Any] | None) -> Tuple[bool, str]:
    unique = second is None or not _same_consistent_rank(top, second)
    enough_independent_support = (
        int(top.get("source_net_evidence") or 0) > 0 and
        len(top.get("central_support_sources") or []) >= 2
    )
    positive_total_evidence = (
        int(top.get("net_evidence") or 0) > 0 and
        (top.get("evidence_balance") is not None and float(top.get("evidence_balance")) > 0)
    )
    no_direction_conflict = not bool(top.get("direction_conflict"))
    clear = bool(unique and enough_independent_support and positive_total_evidence and no_direction_conflict)
    if clear:
        return True, "CLEAR_POSITIVE_CONSISTENT"
    if not no_direction_conflict:
        return False, "SOURCE_AND_TOTAL_EVIDENCE_CONFLICT"
    if not positive_total_evidence:
        return False, "TOTAL_EVIDENCE_NOT_POSITIVE"
    if not enough_independent_support:
        return False, "INSUFFICIENT_INDEPENDENT_SOURCE_SUPPORT"
    return False, "NO_UNIQUE_LEAD"


def analyze_bundle_consistent(parsed_files: List[Dict[str, Any]]) -> Dict[str, Any]:
    result = _BASE_ANALYZE_BUNDLE(parsed_files)
    if not result.get("ok"):
        return result

    markets = result.get("markets") or []
    markets.sort(key=_consistent_rank_key, reverse=True)
    for rank, market in enumerate(markets, 1):
        market["rank"] = rank

    top = markets[0]
    second = markets[1] if len(markets) > 1 else None
    clear, clear_reason = _clear_market(top, second)
    top["clear_lead"] = clear
    top["clear_lead_reason"] = clear_reason

    strongest = dict(result.get("strongest_market") or {})
    for key in (
        "key", "label", "support_count", "contradiction_count", "neutral_count",
        "unavailable_count", "available_signal_count", "net_evidence", "evidence_balance",
        "central_support_sources", "central_contradiction_sources", "source_net_evidence",
        "source_balance", "source_block_balances", "source_block_score", "source_block_balance",
        "direction_conflict",
    ):
        strongest[key] = top.get(key)
    strongest["clear_lead"] = clear
    strongest["clear_lead_reason"] = clear_reason
    result["strongest_market"] = strongest

    if clear:
        result["recommendation"] = top.get("label")
        result["recommendation_reason"] = (
            f"{top.get('label')} führt mit positiver Gesamtbilanz und konsistenter Unterstützung aus mehreren unabhängigen SPEC-v1.1-Quellen: "
            + ", ".join(top.get("central_support_sources") or []) + "."
        )
    elif clear_reason == "SOURCE_AND_TOTAL_EVIDENCE_CONFLICT":
        result["recommendation"] = "KEINE KLARE EMPFEHLUNG"
        result["recommendation_reason"] = (
            f"{top.get('label')} ist im Quellenvergleich der stärkste Markt, aber Quellenrichtung und gesamte Evidenzbilanz widersprechen sich. "
            "Deshalb wird der Markt nicht als klar bezeichnet."
        )
    elif clear_reason == "TOTAL_EVIDENCE_NOT_POSITIVE":
        result["recommendation"] = "KEINE KLARE EMPFEHLUNG"
        result["recommendation_reason"] = (
            f"{top.get('label')} liegt im Quellenvergleich vorne, aber die gesamte verfügbare Evidenzbilanz ist nicht positiv."
        )
    elif clear_reason == "INSUFFICIENT_INDEPENDENT_SOURCE_SUPPORT":
        result["recommendation"] = "KEINE KLARE EMPFEHLUNG"
        result["recommendation_reason"] = (
            f"{top.get('label')} liegt im Vergleich vorne, wird aber nicht von mindestens zwei unabhängigen zentralen Quellen positiv getragen."
        )
    else:
        result["recommendation"] = "KEINE KLARE EMPFEHLUNG"
        result["recommendation_reason"] = "Kein Markt besitzt einen eindeutigen konsistenten Vorsprung."

    table_cov = dict((result.get("data_coverage") or {}).get("table") or {})
    home_present = bool(table_cov.pop("home_available", False))
    away_present = bool(table_cov.pop("away_available", False))
    table_rank_signals = []
    for market in markets:
        table_rank_signals.extend(
            s for s in (market.get("signals") or [])
            if s.get("source") == "TABLE" and s.get("ranking_eligible", True)
        )
    usable_markets = sorted({
        m.get("key") for m in markets
        if any(
            s.get("source") == "TABLE" and s.get("ranking_eligible", True) and s.get("status") != UNAVAILABLE
            for s in (m.get("signals") or [])
        )
    })
    table_cov["home_row_present"] = home_present
    table_cov["away_row_present"] = away_present
    table_cov["usable_market_data"] = bool(usable_markets)
    table_cov["usable_markets"] = usable_markets
    result["data_coverage"]["table"] = table_cov

    method = result.setdefault("method", {})
    method["player_analysis_scope"] = (
        "Alle Player-Seiten werden nur für vollständiges Auffinden der Zielteam-Spieler und Pagination-Audit geladen; "
        "Markt-Evidenz ausschließlich aus HOME_ID/AWAY_ID. Fremdspieler liefern keine Markt-Referenz."
    )
    method["ranking_policy"] = (
        "Verwandte Felder werden zu Evidenzblöcken gruppiert. Unabhängige zentrale Quellen bleiben primär; "
        "innerhalb jeder Quelle bleibt (Bestätigungen-Widersprüche)/verfügbare Blöcke erhalten. "
        "KLAR nur bei positiver Gesamt-Evidenz und konsistenter Quellenrichtung. Diagnostik zählt nicht als Ranking-Stimme."
    )
    result.setdefault("notes", []).append(
        "Ranking-Konsistenz: Ein stärkster Markt mit negativer/neutraler Gesamtbilanz oder Vorzeichenkonflikt zwischen Quellen- und Gesamtevidenz wird als KEINE KLARE EMPFEHLUNG ausgegeben."
    )
    result["engine"] = ENGINE_NAME
    result["engine_version"] = ENGINE_VERSION
    return result


def apply_patch(legacy: Any) -> Any:
    engine._player_signals = _disabled_native_player_signals
    engine.extended_player = target_only_extended_player
    engine._aggregate = _consistent_aggregate
    engine._rank_key = _consistent_rank_key
    engine._same_rank = _same_consistent_rank
    engine.ENGINE_NAME = ENGINE_NAME
    engine.ENGINE_VERSION = ENGINE_VERSION

    surface.analyze_bundle = analyze_bundle_consistent
    surface.ENGINE_NAME = ENGINE_NAME
    surface.ENGINE_VERSION = ENGINE_VERSION

    import spec11_full_signal_patch as full
    full.ENGINE_NAME = ENGINE_NAME
    full.ENGINE_VERSION = ENGINE_VERSION
    app = full.apply_patch(legacy)

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
            "ranking_consistency_guard": True,
            "clear_requires_positive_total_evidence": True,
            "shortcut_capture_unix": int(time.time()),
        }
    app.add_api_route("/api/health", health, methods=["GET"])
    app.version = ENGINE_VERSION
    app.title = "FootyStats SPEC v1.1 Full-Signal Strongest Market"
    return app
