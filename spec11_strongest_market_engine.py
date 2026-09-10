"""FootyStats SPEC v1.1 strongest-market analysis.

Uses exactly five SPEC-v1.1 FootyStats files. The analysis combines the
baseline SPEC evidence with the complete meaningful registered signal breadth,
groups correlated fields into evidence blocks, and ranks markets primarily by
independent source agreement. No V0.4.3/V0.4.2 core, no fallback, no odds and
no SPIELEN/BEOBACHTEN/AUSLASSEN decision engine are used.
"""
from __future__ import annotations

from typing import Any, Dict, List

from spec11_native_engine import (
    CENTRAL_SOURCES, CONTRADICT, LABELS, MARKETS, NEUTRAL, SPEC_VERSION,
    SUPPORT, UNAVAILABLE, _form_signals, _h2h_signals, _league_context,
    _league_signals, _league_team_rows, _match_signals, _pagination_audit,
    _pair, _player_signals, _sample, _sample_class, _table_signals,
    _team_by_id, _temporal_audit,
)
from spec11_signal_expansion import (
    extended_form, extended_league, extended_match, extended_player,
    extended_table, normalize_existing,
)

ENGINE_NAME = "FOOTYSTATS_SPEC_V1_1_STRONGEST_MARKET_ANALYSIS"
ENGINE_VERSION = "1.1.2-full-signal-breadth"


def _aggregate(signals: List[Dict[str, Any]], market: str) -> Dict[str, Any]:
    selected = [s for s in signals if s.get("market") == market]
    ranking = [s for s in selected if s.get("ranking_eligible", True)]
    support = [s for s in ranking if s.get("status") == SUPPORT]
    contradict = [s for s in ranking if s.get("status") == CONTRADICT]
    neutral = [s for s in ranking if s.get("status") == NEUTRAL]
    unavailable = [s for s in ranking if s.get("status") == UNAVAILABLE]
    available = len(ranking) - len(unavailable)

    source_evidence: Dict[str, Dict[str, Any]] = {}
    for source in sorted(CENTRAL_SOURCES):
        rows = [s for s in ranking if s.get("source") == source]
        sp = sum(s.get("status") == SUPPORT for s in rows)
        sn = sum(s.get("status") == CONTRADICT for s in rows)
        sa = sum(s.get("status") != UNAVAILABLE for s in rows)
        if sa == 0:
            status = UNAVAILABLE
        elif sp > sn:
            status = SUPPORT
        elif sn > sp:
            status = CONTRADICT
        else:
            status = NEUTRAL
        source_evidence[source] = {
            "status": status,
            "support_blocks": sp,
            "contradiction_blocks": sn,
            "available_blocks": sa,
        }

    supporting_sources = [s for s, x in source_evidence.items() if x["status"] == SUPPORT]
    contradicting_sources = [s for s, x in source_evidence.items() if x["status"] == CONTRADICT]
    available_sources = [s for s, x in source_evidence.items() if x["status"] != UNAVAILABLE]
    source_net = len(supporting_sources) - len(contradicting_sources)
    source_balance = source_net / len(available_sources) if available_sources else None
    net_evidence = len(support) - len(contradict)
    evidence_balance = net_evidence / available if available else None
    diagnostics = [s for s in selected if not s.get("ranking_eligible", True)]

    return {
        "key": market,
        "label": LABELS[market],
        "support_count": len(support),
        "contradiction_count": len(contradict),
        "neutral_count": len(neutral),
        "unavailable_count": len(unavailable),
        "available_signal_count": available,
        "diagnostic_signal_count": len(diagnostics),
        "net_evidence": net_evidence,
        "evidence_balance": round(evidence_balance, 6) if evidence_balance is not None else None,
        "central_support_sources": supporting_sources,
        "central_contradiction_sources": contradicting_sources,
        "available_central_sources": available_sources,
        "source_net_evidence": source_net,
        "source_balance": round(source_balance, 6) if source_balance is not None else None,
        "source_evidence": source_evidence,
        "signals": selected,
    }


def _rank_key(m: Dict[str, Any]) -> tuple:
    sb = m.get("source_balance")
    eb = m.get("evidence_balance")
    return (
        int(m.get("source_net_evidence") or 0),
        len(m.get("central_support_sources") or []),
        -len(m.get("central_contradiction_sources") or []),
        float(sb if sb is not None else -2.0),
        float(eb if eb is not None else -2.0),
        int(m.get("net_evidence") or 0),
        -int(m.get("contradiction_count") or 0),
        int(m.get("available_signal_count") or 0),
    )


def _same_rank(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    return _rank_key(a) == _rank_key(b)


def analyze_bundle(parsed_files: List[Dict[str, Any]]) -> Dict[str, Any]:
    pair = _pair(parsed_files)
    if not pair.get("ok"):
        return pair
    files, match, identity = pair["files"], pair["match"], pair["identity"]
    kickoff = identity["kickoff_unix"]
    temporal = _temporal_audit(files, kickoff)
    pagination = _pagination_audit(files)
    strict_all = all(x["strict"] for x in temporal.values())
    pagination_all = pagination["league_teams"]["complete"] and pagination["players"]["complete"]
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
    signals.extend(normalize_existing(_match_signals(match, home_sample, away_sample, league_context, teams)))
    signals.extend(extended_match(match, home_sample, away_sample, league_context, teams))
    signals.extend(normalize_existing(_league_signals(teams, home_team, away_team)))
    signals.extend(extended_league(teams, home_team, away_team))

    form_base, form_coverage = _form_signals(files["form"]["data"], identity["home_id"], identity["away_id"])
    signals.extend(normalize_existing(form_base))
    signals.extend(extended_form(files["form"]["data"], identity["home_id"], identity["away_id"]))

    table_base, table_coverage = _table_signals(files["table"]["data"], identity["home_id"], identity["away_id"])
    signals.extend(normalize_existing(table_base))
    signals.extend(extended_table(files["table"]["data"], identity["home_id"], identity["away_id"]))

    player_base, player_coverage = _player_signals(files["player"]["data"], identity["home_id"], identity["away_id"])
    signals.extend(normalize_existing(player_base))
    player_extra, player_scope = extended_player(files["player"]["data"], identity["home_id"], identity["away_id"])
    signals.extend(player_extra)
    signals.extend(normalize_existing(_h2h_signals(match)))

    markets = [_aggregate(signals, key) for key, _ in MARKETS]
    markets.sort(key=_rank_key, reverse=True)
    for rank, row in enumerate(markets, 1):
        row["rank"] = rank

    top = markets[0]
    second = markets[1] if len(markets) > 1 else None
    positive = top["source_net_evidence"] > 0 and len(top["central_support_sources"]) >= 2
    unique = second is None or not _same_rank(top, second)
    clear = bool(positive and unique)
    strongest = {
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
        "central_contradiction_sources": top["central_contradiction_sources"],
        "source_net_evidence": top["source_net_evidence"],
        "source_balance": top["source_balance"],
        "clear_lead": clear,
    }
    recommendation = top["label"] if clear else "KEINE KLARE EMPFEHLUNG"
    reason = (
        f"{top['label']} wird von mehreren unabhängigen SPEC-v1.1-Quellen am stärksten unterstützt: " + ", ".join(top["central_support_sources"]) + "."
        if clear else
        "Kein Markt besitzt einen eindeutigen positiven Vorsprung aus mindestens zwei unabhängigen zentralen FootyStats-Quellen."
    )

    file_names = {kind: item["name"] for kind, item in files.items()}
    audit_match = {
        "match_id": identity["match_id"], "home_id": identity["home_id"],
        "away_id": identity["away_id"], "competition_id": identity["competition_id"],
        "kickoff_unix": kickoff, "home_name": match.get("home_name"),
        "away_name": match.get("away_name"), "season": match.get("season"),
    }
    domains = sorted({str(s.get("domain")) for s in signals})
    return {
        "ok": True,
        "engine": ENGINE_NAME,
        "engine_version": ENGINE_VERSION,
        "spec_version": SPEC_VERSION,
        "analysis_type": "SPEC_V1_1_STRONGEST_MARKET",
        "strongest_market": strongest,
        "recommendation": recommendation,
        "recommendation_reason": reason,
        "markets": markets,
        "sample_state": sample_state,
        "data_coverage": {
            "form": form_coverage,
            "table": table_coverage,
            "player": player_coverage,
            "player_scope": player_scope,
            "league_team_count": len(teams),
            "signal_domain_count": len(domains),
            "signal_domains": domains,
        },
        "integrity": {"strict_prematch": strict_all, "temporal": temporal, "pagination": pagination},
        "pairing": {**identity, "files": file_names},
        "audit": {"valid": True, "errors": [], "match": audit_match},
        "input_sources": file_names,
        "method": {
            "architecture": "SPEC_V1_1_FULL_SIGNAL_COMPARISON",
            "probability_core": "NONE", "v043_used": False, "v042_used": False,
            "fallback": "NONE", "odds_used": False, "decision_engine": "NONE",
            "missing_values": "NICHT VERFÜGBAR; niemals als 0-Stärke oder Ersatzwert",
            "cold_start_exclusion": False,
            "player_analysis_scope": "Nur HOME_ID/AWAY_ID; ligaweite Player-Seiten nur für Vollständigkeitsprüfung und Competition-Referenz.",
            "ranking_policy": "Verwandte Felder werden zu Evidenzblöcken gruppiert. Primär zählt die Richtung unabhängiger zentraler Quellen; Blockbilanz dient nur nachrangig als Tie-Breaker. Diagnostik zählt nicht als Ranking-Stimme.",
            "footystats_official_recommendation_claimed": False,
        },
        "notes": [
            "Stärkster Markt = unsere SPEC-v1.1-Auswertung der gelieferten FootyStats-Daten, keine von FootyStats veröffentlichte Wettentscheidung.",
            "Keine SPIELEN/BEOBACHTEN/AUSLASSEN-Regel und keine Modellwahrscheinlichkeit.",
            "COLD START und LOW SAMPLE werden analysiert; fehlende Competition-Signale bleiben NICHT VERFÜGBAR.",
            "Alle für die sieben Zielmärkte sinnvoll interpretierbaren registrierten Familien werden verwendet; Diagnostik bleibt sichtbar, aber ohne Ranking-Stimme.",
        ],
    }
