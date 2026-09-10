"""FootyStats SPEC v1.1 strongest-market analysis.

Consumes exactly five SPEC v1.1 FootyStats files, audits strict pre-match
integrity, keeps COLD START / LOW SAMPLE matches analyzable, and compares the
available FootyStats signal directions across markets.

This is deliberately NOT a SPIELEN/BEOBACHTEN/AUSLASSEN decision engine.
It does not call V0.4.3, V0.4.2, any probability core, or any fallback.
"""
from __future__ import annotations

from typing import Any, Dict, List

from spec11_native_engine import (
    CENTRAL_SOURCES,
    CONTRADICT,
    LABELS,
    MARKETS,
    NEUTRAL,
    SPEC_VERSION,
    SUPPORT,
    UNAVAILABLE,
    _form_signals,
    _h2h_signals,
    _league_context,
    _league_signals,
    _league_team_rows,
    _match_signals,
    _pagination_audit,
    _pair,
    _player_signals,
    _sample,
    _sample_class,
    _table_signals,
    _team_by_id,
    _temporal_audit,
)

ENGINE_NAME = "FOOTYSTATS_SPEC_V1_1_STRONGEST_MARKET_ANALYSIS"
ENGINE_VERSION = "1.1.1-strongest-market"


def _aggregate(signals: List[Dict[str, Any]], market: str) -> Dict[str, Any]:
    selected = [signal for signal in signals if signal.get("market") == market]
    support = [signal for signal in selected if signal.get("status") == SUPPORT]
    contradict = [signal for signal in selected if signal.get("status") == CONTRADICT]
    neutral = [signal for signal in selected if signal.get("status") == NEUTRAL]
    unavailable = [signal for signal in selected if signal.get("status") == UNAVAILABLE]
    available = len(selected) - len(unavailable)

    supporting_sources = sorted({
        signal.get("source") for signal in support
        if signal.get("source") in CENTRAL_SOURCES
    })
    contradicting_sources = sorted({
        signal.get("source") for signal in contradict
        if signal.get("source") in CENTRAL_SOURCES
    })

    net_evidence = len(support) - len(contradict)
    evidence_balance = (net_evidence / available) if available else None
    source_balance = len(supporting_sources) - len(contradicting_sources)

    return {
        "key": market,
        "label": LABELS[market],
        "support_count": len(support),
        "contradiction_count": len(contradict),
        "neutral_count": len(neutral),
        "unavailable_count": len(unavailable),
        "available_signal_count": available,
        "net_evidence": net_evidence,
        "evidence_balance": round(evidence_balance, 6) if evidence_balance is not None else None,
        "central_support_sources": supporting_sources,
        "central_contradiction_sources": contradicting_sources,
        "source_balance": source_balance,
        "signals": selected,
    }


def _rank_key(market: Dict[str, Any]) -> tuple:
    """Transparent, unweighted ordering; later terms only break ties."""
    balance = market.get("evidence_balance")
    if balance is None:
        balance = -2.0
    return (
        float(balance),
        int(market.get("source_balance") or 0),
        int(market.get("net_evidence") or 0),
        -int(market.get("contradiction_count") or 0),
        int(market.get("support_count") or 0),
        int(market.get("available_signal_count") or 0),
    )


def _same_rank(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    return _rank_key(a) == _rank_key(b)


def analyze_bundle(parsed_files: List[Dict[str, Any]]) -> Dict[str, Any]:
    pair = _pair(parsed_files)
    if not pair.get("ok"):
        return pair

    files = pair["files"]
    match = pair["match"]
    identity = pair["identity"]
    kickoff = identity["kickoff_unix"]

    temporal = _temporal_audit(files, kickoff)
    pagination = _pagination_audit(files)
    strict_all = all(item["strict"] for item in temporal.values())
    pagination_all = (
        pagination["league_teams"]["complete"]
        and pagination["players"]["complete"]
    )

    if not strict_all or not pagination_all:
        return {
            "ok": False,
            "phase": "SPEC11_INTEGRITY_FAILED",
            "error": "SPEC v1.1 Integritätsprüfung nicht bestanden. Keine Fallback-Analyse wird ausgeführt.",
            "spec_version": SPEC_VERSION,
            "engine": ENGINE_NAME,
            "temporal_audit": temporal,
            "pagination": pagination,
            "fallback_used": False,
        }

    teams = _league_team_rows(files["league"]["data"])
    home_team = _team_by_id(teams, identity["home_id"])
    away_team = _team_by_id(teams, identity["away_id"])
    if home_team is None or away_team is None:
        return {
            "ok": False,
            "phase": "SPEC11_TEAM_PAIRING_FAILED",
            "error": "LeagueDaten enthält nicht beide Zielteams. Keine Fallback-Analyse.",
            "fallback_used": False,
        }

    home_sample = _sample(home_team, "overall")
    away_sample = _sample(away_team, "overall")
    sample_state = {
        "home": {"matches": home_sample, "class": _sample_class(home_sample)},
        "away": {"matches": away_sample, "class": _sample_class(away_sample)},
        "policy": "0 Spiele=COLD START; 1-3=LOW SAMPLE; niemals automatischer Ausschluss.",
    }

    league_context = _league_context(files["league"]["data"])
    signals: List[Dict[str, Any]] = []
    signals.extend(_match_signals(match, home_sample, away_sample, league_context, teams))
    signals.extend(_league_signals(teams, home_team, away_team))

    form_signals, form_coverage = _form_signals(
        files["form"]["data"], identity["home_id"], identity["away_id"]
    )
    signals.extend(form_signals)

    table_signals, table_coverage = _table_signals(
        files["table"]["data"], identity["home_id"], identity["away_id"]
    )
    signals.extend(table_signals)

    player_signals, player_coverage = _player_signals(
        files["player"]["data"], identity["home_id"], identity["away_id"]
    )
    signals.extend(player_signals)
    signals.extend(_h2h_signals(match))

    markets = [_aggregate(signals, key) for key, _ in MARKETS]
    markets.sort(key=_rank_key, reverse=True)
    for rank, market_row in enumerate(markets, 1):
        market_row["rank"] = rank

    top = markets[0]
    second = markets[1] if len(markets) > 1 else None
    positive = top["available_signal_count"] > 0 and top["net_evidence"] > 0
    unique = second is None or not _same_rank(top, second)
    clear = bool(positive and unique)

    strongest_market = {
        "key": top["key"],
        "label": top["label"],
        "support_count": top["support_count"],
        "contradiction_count": top["contradiction_count"],
        "neutral_count": top["neutral_count"],
        "unavailable_count": top["unavailable_count"],
        "available_signal_count": top["available_signal_count"],
        "net_evidence": top["net_evidence"],
        "evidence_balance": top["evidence_balance"],
        "central_support_sources": top["central_support_sources"],
        "clear_lead": clear,
    }

    recommendation = top["label"] if clear else "KEINE KLARE EMPFEHLUNG"
    recommendation_reason = (
        f"{top['label']} hat im transparenten SPEC-v1.1-Signalvergleich die stärkste positive Evidenzbilanz."
        if clear
        else "Die verfügbaren FootyStats-Signale ergeben keinen eindeutig führenden Markt mit positiver Evidenzbilanz."
    )

    file_names = {kind: item["name"] for kind, item in files.items()}
    audit_match = {
        "match_id": identity["match_id"],
        "home_id": identity["home_id"],
        "away_id": identity["away_id"],
        "competition_id": identity["competition_id"],
        "kickoff_unix": kickoff,
        "home_name": match.get("home_name"),
        "away_name": match.get("away_name"),
        "season": match.get("season"),
    }

    return {
        "ok": True,
        "engine": ENGINE_NAME,
        "engine_version": ENGINE_VERSION,
        "spec_version": SPEC_VERSION,
        "analysis_type": "SPEC_V1_1_STRONGEST_MARKET",
        "strongest_market": strongest_market,
        "recommendation": recommendation,
        "recommendation_reason": recommendation_reason,
        "markets": markets,
        "sample_state": sample_state,
        "data_coverage": {
            "form": form_coverage,
            "table": table_coverage,
            "player": player_coverage,
            "league_team_count": len(teams),
        },
        "integrity": {
            "strict_prematch": strict_all,
            "temporal": temporal,
            "pagination": pagination,
        },
        "pairing": {**identity, "files": file_names},
        "audit": {"valid": True, "errors": [], "match": audit_match},
        "input_sources": file_names,
        "method": {
            "architecture": "SPEC_V1_1_SIGNAL_COMPARISON",
            "probability_core": "NONE",
            "v043_used": False,
            "v042_used": False,
            "fallback": "NONE",
            "odds_used": False,
            "decision_engine": "NONE",
            "missing_values": "NICHT VERFÜGBAR; niemals als 0-Stärke oder Ersatzwert",
            "cold_start_exclusion": False,
            "ranking_policy": "Ungewichteter Signalvergleich: zuerst Evidenzbilanz pro verfügbarem Signal; danach Quellenbilanz, Netto-Evidenz, weniger Widersprüche, Bestätigungen und Datenabdeckung als Tie-Breaker.",
            "footystats_official_recommendation_claimed": False,
        },
        "notes": [
            "Die Ausgabe 'stärkster Markt' ist eine SPEC-v1.1-Auswertung der gelieferten FootyStats-Daten, keine von FootyStats veröffentlichte Wettentscheidung.",
            "Keine SPIELEN/BEOBACHTEN/AUSLASSEN-Regel wird angewendet.",
            "Keine Wahrscheinlichkeiten werden aus V0.4.3/V0.4.2 übernommen.",
            "COLD START und LOW SAMPLE werden analysiert; fehlende Competition-Signale bleiben NICHT VERFÜGBAR.",
            "H2H bleibt sekundäre Evidenz und ist keine zentrale Quelle.",
        ],
    }
