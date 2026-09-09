"""Qualitative five-file FootyStats match logic for V0.5.0.

This layer does not retrain or alter the frozen V0.4.3 FULL-5 probabilities and
uses no hand-written percentage adjustment or weighted evidence score. It reads
additional leakage-safe context already present in the five FootyStats files and
checks whether that context unanimously supports, contradicts, or is mixed for
the strongest market.

Decision rule:
- the result-supervised reliability action is the starting point;
- unanimous support across every required directional domain may promote by one
  action level;
- any explicit contradiction demotes by one action level;
- mixed, neutral, or unavailable context preserves the reliability action;
- probabilities are never changed.

All directional comparisons are relative to the supplied league itself (median
of the relevant home/away metric) or direct recent-vs-reference / team-vs-team
comparisons. No global betting cutoff is introduced.
"""
from __future__ import annotations

import copy
import math
from statistics import median
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

LOGIC_VERSION = "1.0.0"
LOGIC_NAME = "FOOTYSTATS_UNIFIED_QUALITATIVE_MATCH_LOGIC"
FINAL_DECISION_SOURCE = (
    "RESULT_SUPERVISED_OOF_RELIABILITY_POLICY_PLUS_"
    "FOOTYSTATS_UNIFIED_CONTEXT_LOGIC"
)

SUPPORT = "BESTÄTIGEND"
CONTRADICT = "WIDERSPRUCH"
NEUTRAL = "NEUTRAL"
UNAVAILABLE = "NICHT VERFÜGBAR"

_ACTION_ORDER = ("AUSLASSEN / KEIN BET", "BEOBACHTEN", "SPIELEN")
_ACTION_ALIASES = {
    "AUSLASSEN": "AUSLASSEN / KEIN BET",
    "AUSLASSEN / KEIN BET": "AUSLASSEN / KEIN BET",
    "BEOBACHTEN": "BEOBACHTEN",
    "SPIELEN": "SPIELEN",
}


def _num(value: Any) -> Optional[float]:
    try:
        if value is None or isinstance(value, bool):
            return None
        out = float(value)
        return out if math.isfinite(out) else None
    except Exception:
        return None


def _median_known(values: Iterable[Any]) -> Optional[float]:
    known = [v for value in values if (v := _num(value)) is not None]
    return float(median(known)) if known else None


def _signal(domain: str, status: str, reason: str, **values: Any) -> Dict[str, Any]:
    return {
        "domain": domain,
        "status": status,
        "reason": reason,
        "values": values,
    }


def _both_relative(
    home_value: Optional[float],
    home_reference: Optional[float],
    away_value: Optional[float],
    away_reference: Optional[float],
    *,
    high_supports: bool,
) -> str:
    if None in (home_value, home_reference, away_value, away_reference):
        return UNAVAILABLE
    home_cmp = 1 if home_value > home_reference else (-1 if home_value < home_reference else 0)
    away_cmp = 1 if away_value > away_reference else (-1 if away_value < away_reference else 0)
    if not high_supports:
        home_cmp, away_cmp = -home_cmp, -away_cmp
    if home_cmp > 0 and away_cmp > 0:
        return SUPPORT
    if home_cmp < 0 and away_cmp < 0:
        return CONTRADICT
    return NEUTRAL


def _league_teams(legacy: Any, league_data: Any) -> List[Any]:
    try:
        return list(legacy.league_team_list(league_data))
    except Exception:
        return []


def _league_metric_context(
    legacy: Any,
    league_data: Any,
    home_team: Any,
    away_team: Any,
    metric: str,
) -> Tuple[Optional[float], Optional[float], Optional[float], Optional[float]]:
    teams = _league_teams(legacy, league_data)
    if not teams:
        return None, None, None, None
    try:
        home_value = _num(legacy.tnum(home_team, metric, "home"))
        away_value = _num(legacy.tnum(away_team, metric, "away"))
        home_median = _median_known(legacy.tnum(team, metric, "home") for team in teams)
        away_median = _median_known(legacy.tnum(team, metric, "away") for team in teams)
        return home_value, home_median, away_value, away_median
    except Exception:
        return None, None, None, None


def _league_direct_context(
    legacy: Any,
    league_data: Any,
    home_team: Any,
    away_team: Any,
    home_key: str,
    away_key: str,
) -> Tuple[Optional[float], Optional[float], Optional[float], Optional[float]]:
    teams = _league_teams(legacy, league_data)
    if not teams:
        return None, None, None, None
    try:
        home_value = _num(legacy.firstnum(home_team, [home_key]))
        away_value = _num(legacy.firstnum(away_team, [away_key]))
        home_median = _median_known(legacy.firstnum(team, [home_key]) for team in teams)
        away_median = _median_known(legacy.firstnum(team, [away_key]) for team in teams)
        return home_value, home_median, away_value, away_median
    except Exception:
        return None, None, None, None


def _venue_market_signal(
    legacy: Any,
    league_data: Any,
    home_team: Any,
    away_team: Any,
    market: str,
) -> Dict[str, Any]:
    if market in {"btts_yes", "btts_no"}:
        metric = "btts"
        high_supports = market == "btts_yes"
    elif market in {"over_2_5", "under_2_5"}:
        metric = "o25" if market == "over_2_5" else "u25"
        high_supports = True
    elif market in {"home_win", "away_win"}:
        hv, hm, av, am = _league_metric_context(legacy, league_data, home_team, away_team, "ppg")
        if None in (hv, hm, av, am):
            return _signal("VENUE_PROFILE", UNAVAILABLE, "Venue-PPG nicht vollständig verfügbar.")
        home_edge = (hv > hm and av < am)
        away_edge = (av > am and hv < hm)
        status = SUPPORT if (home_edge if market == "home_win" else away_edge) else (
            CONTRADICT if (away_edge if market == "home_win" else home_edge) else NEUTRAL
        )
        return _signal(
            "VENUE_PROFILE",
            status,
            "Heim-/Auswärts-PPG wird ausschließlich relativ zum Median der gelieferten Liga verglichen.",
            home_value=hv,
            home_league_median=hm,
            away_value=av,
            away_league_median=am,
        )
    else:
        return _signal("VENUE_PROFILE", UNAVAILABLE, "Markt wird von diesem Kontextblock nicht abgebildet.")

    hv, hm, av, am = _league_metric_context(legacy, league_data, home_team, away_team, metric)
    status = _both_relative(hv, hm, av, am, high_supports=high_supports)
    return _signal(
        "VENUE_PROFILE",
        status,
        "Beide Venue-Werte werden relativ zum jeweiligen Liga-Median geprüft; keine globale Prozentgrenze.",
        home_value=hv,
        home_league_median=hm,
        away_value=av,
        away_league_median=am,
    )


def _first_half_btts_signal(
    legacy: Any,
    league_data: Any,
    home_team: Any,
    away_team: Any,
    market: str,
) -> Dict[str, Any]:
    if market not in {"btts_yes", "btts_no", "over_2_5", "under_2_5"}:
        return _signal("FIRST_HALF_BTTS", NEUTRAL, "First-Half-BTTS ist kein direkter Richtungsblock für 1X2.")
    hv, hm, av, am = _league_direct_context(
        legacy,
        league_data,
        home_team,
        away_team,
        "seasonBTTSPercentageHT_home",
        "seasonBTTSPercentageHT_away",
    )
    high_supports = market in {"btts_yes", "over_2_5"}
    status = _both_relative(hv, hm, av, am, high_supports=high_supports)
    return _signal(
        "FIRST_HALF_BTTS",
        status,
        "First-Half-BTTS Home/Away wird relativ zum gelieferten Liga-Median bewertet.",
        home_value=hv,
        home_league_median=hm,
        away_value=av,
        away_league_median=am,
    )


def _cs_fts_signal(
    legacy: Any,
    league_data: Any,
    home_team: Any,
    away_team: Any,
    market: str,
) -> Dict[str, Any]:
    if market not in {"btts_yes", "btts_no", "over_2_5", "under_2_5"}:
        return _signal("CS_FTS_PROFILE", NEUTRAL, "CS/FTS ist kein direkter Richtungsblock für 1X2.")

    h_fts, hm_fts, a_fts, am_fts = _league_metric_context(legacy, league_data, home_team, away_team, "fts")
    h_cs, hm_cs, a_cs, am_cs = _league_metric_context(legacy, league_data, home_team, away_team, "cs")
    all_values = (h_fts, hm_fts, a_fts, am_fts, h_cs, hm_cs, a_cs, am_cs)
    if any(value is None for value in all_values):
        return _signal("CS_FTS_PROFILE", UNAVAILABLE, "CS-/FTS-Venueprofil nicht vollständig verfügbar.")

    open_profile = (
        h_fts < hm_fts and a_fts < am_fts and h_cs < hm_cs and a_cs < am_cs
    )
    closed_profile = (
        h_fts > hm_fts and a_fts > am_fts and h_cs > hm_cs and a_cs > am_cs
    )
    wants_open = market in {"btts_yes", "over_2_5"}
    status = SUPPORT if (open_profile if wants_open else closed_profile) else (
        CONTRADICT if (closed_profile if wants_open else open_profile) else NEUTRAL
    )
    return _signal(
        "CS_FTS_PROFILE",
        status,
        "CS und FTS müssen auf beiden Seiten gemeinsam dieselbe liga-relative Richtung zeigen; sonst bleibt der Block neutral.",
        home_fts=h_fts,
        home_fts_median=hm_fts,
        away_fts=a_fts,
        away_fts_median=am_fts,
        home_cs=h_cs,
        home_cs_median=hm_cs,
        away_cs=a_cs,
        away_cs_median=am_cs,
    )


def _form_delta(team: Dict[str, Any], metric: str) -> Optional[float]:
    recent = team.get("recent_5") or {}
    reference = team.get("reference") or {}
    current = _num(recent.get(metric))
    baseline = _num(reference.get(metric))
    if current is None or baseline is None:
        return None
    return current - baseline


def _current_form_signal(form: Dict[str, Any], market: str) -> Dict[str, Any]:
    home = form.get("home") or {}
    away = form.get("away") or {}
    if not (home.get("available") and away.get("available")):
        return _signal("CURRENT_FORM", UNAVAILABLE, "Formfenster fehlen für mindestens ein Team.")

    if market in {"btts_yes", "btts_no"}:
        metric = "btts_pct"
        high_supports = market == "btts_yes"
        hd, ad = _form_delta(home, metric), _form_delta(away, metric)
        if hd is None or ad is None:
            return _signal("CURRENT_FORM", UNAVAILABLE, "BTTS Last-5-vs-Referenz ist nicht vollständig verfügbar.")
        if not high_supports:
            hd, ad = -hd, -ad
        status = SUPPORT if hd > 0 and ad > 0 else (CONTRADICT if hd < 0 and ad < 0 else NEUTRAL)
        return _signal("CURRENT_FORM", status, "Last 5 wird direkt gegen das längere Formfenster beider Teams verglichen.", home_delta=hd, away_delta=ad)

    if market in {"over_2_5", "under_2_5"}:
        metric = "over_25_pct" if market == "over_2_5" else "under_25_pct"
        hd, ad = _form_delta(home, metric), _form_delta(away, metric)
        if hd is None or ad is None:
            return _signal("CURRENT_FORM", UNAVAILABLE, "O/U Last-5-vs-Referenz ist nicht vollständig verfügbar.")
        status = SUPPORT if hd > 0 and ad > 0 else (CONTRADICT if hd < 0 and ad < 0 else NEUTRAL)
        return _signal("CURRENT_FORM", status, "Last 5 wird direkt gegen das längere Formfenster beider Teams verglichen.", home_delta=hd, away_delta=ad)

    if market in {"home_win", "away_win"}:
        hd, ad = _form_delta(home, "ppg"), _form_delta(away, "ppg")
        if hd is None or ad is None:
            return _signal("CURRENT_FORM", UNAVAILABLE, "PPG Last-5-vs-Referenz ist nicht vollständig verfügbar.")
        selected_delta, opponent_delta = (hd, ad) if market == "home_win" else (ad, hd)
        status = SUPPORT if selected_delta > opponent_delta else (CONTRADICT if selected_delta < opponent_delta else NEUTRAL)
        return _signal("CURRENT_FORM", status, "Die PPG-Entwicklung des ausgewählten Teams wird direkt mit der gegnerischen Entwicklung verglichen.", selected_delta=selected_delta, opponent_delta=opponent_delta)

    return _signal("CURRENT_FORM", UNAVAILABLE, "Markt wird vom Formblock nicht abgebildet.")


def _table_signal(table: Dict[str, Any], market: str) -> Dict[str, Any]:
    if market not in {"home_win", "away_win"}:
        return _signal("RELATIVE_TABLE_STRENGTH", NEUTRAL, "Tabellenstärke wird für Tor-/BTTS-Märkte nicht als Richtungsbeweis verwendet.")
    home = table.get("home") or {}
    away = table.get("away") or {}
    if not (home.get("available") and away.get("available")):
        return _signal("RELATIVE_TABLE_STRENGTH", UNAVAILABLE, "Venue-Tabelle fehlt für mindestens ein Team.")
    hp, ap = _num(home.get("ppg")), _num(away.get("ppg"))
    hr, ar = _num(home.get("position")), _num(away.get("position"))
    if None in (hp, ap, hr, ar):
        return _signal("RELATIVE_TABLE_STRENGTH", UNAVAILABLE, "PPG oder Tabellenposition ist nicht vollständig verfügbar.")
    home_better = hp > ap and hr < ar
    away_better = ap > hp and ar < hr
    status = SUPPORT if (home_better if market == "home_win" else away_better) else (
        CONTRADICT if (away_better if market == "home_win" else home_better) else NEUTRAL
    )
    return _signal("RELATIVE_TABLE_STRENGTH", status, "Venue-PPG und Tabellenposition müssen gemeinsam dieselbe Richtung zeigen.", home_ppg=hp, away_ppg=ap, home_position=hr, away_position=ar)


def _player_depth_signal(player: Dict[str, Any], market: str) -> Dict[str, Any]:
    home = player.get("home") or {}
    away = player.get("away") or {}
    if not (home.get("available") and away.get("available")):
        return _signal("PLAYER_DEPTH", UNAVAILABLE, "PlayerDaten fehlen für mindestens ein Team.")
    if market not in {"home_win", "away_win"}:
        return _signal("PLAYER_DEPTH", NEUTRAL, "Player Depth wird ohne bestätigte Aufstellung nicht als Richtung für BTTS/O-U erzwungen.")
    hp, ap = _num(home.get("players_found")), _num(away.get("players_found"))
    hc, ac = _num(home.get("minutes_coverage_pct")), _num(away.get("minutes_coverage_pct"))
    if None in (hp, ap, hc, ac):
        return _signal("PLAYER_DEPTH", UNAVAILABLE, "Spieleranzahl oder Minutenabdeckung ist nicht vollständig verfügbar.")
    home_deeper = hp > ap and hc > ac
    away_deeper = ap > hp and ac > hc
    status = SUPPORT if (home_deeper if market == "home_win" else away_deeper) else (
        CONTRADICT if (away_deeper if market == "home_win" else home_deeper) else NEUTRAL
    )
    return _signal("PLAYER_DEPTH", status, "Spieleranzahl und Minutenabdeckung müssen gemeinsam dieselbe Richtung zeigen; keine Aufstellung wird erfunden.", home_players=hp, away_players=ap, home_minutes_coverage_pct=hc, away_minutes_coverage_pct=ac)


def _required_domains_for_market(market: str) -> Tuple[str, ...]:
    if market in {"btts_yes", "btts_no", "over_2_5", "under_2_5"}:
        return ("VENUE_PROFILE", "FIRST_HALF_BTTS", "CS_FTS_PROFILE", "CURRENT_FORM")
    if market in {"home_win", "away_win"}:
        return ("VENUE_PROFILE", "CURRENT_FORM", "RELATIVE_TABLE_STRENGTH", "PLAYER_DEPTH")
    return tuple()


def _step_action(action: str, direction: int) -> str:
    canonical = _ACTION_ALIASES.get(str(action).strip().upper(), str(action).strip().upper())
    if canonical not in _ACTION_ORDER:
        return action
    index = _ACTION_ORDER.index(canonical)
    return _ACTION_ORDER[max(0, min(len(_ACTION_ORDER) - 1, index + direction))]


def resolve_action(base_action: str, market: str, signals: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    required = _required_domains_for_market(market)
    by_domain = {str(signal.get("domain")): signal for signal in signals}
    required_signals = [by_domain.get(domain) for domain in required]
    contradictions = [signal for signal in required_signals if signal and signal.get("status") == CONTRADICT]
    unanimous_support = bool(required_signals) and all(
        signal is not None and signal.get("status") == SUPPORT for signal in required_signals
    )

    if contradictions:
        final_action = _step_action(base_action, -1)
        mode = "CONTEXT_VETO"
        reason = "Mindestens ein erforderlicher FootyStats-Kontextblock widerspricht dem stärksten Markt."
    elif unanimous_support:
        final_action = _step_action(base_action, +1)
        mode = "UNANIMOUS_CONTEXT_CONFIRMATION"
        reason = "Alle erforderlichen FootyStats-Kontextblöcke bestätigen denselben Markt ohne Gegenblock."
    else:
        final_action = _ACTION_ALIASES.get(str(base_action).strip().upper(), base_action)
        mode = "RELIABILITY_ACTION_PRESERVED"
        reason = "Der FootyStats-Kontext ist gemischt, neutral oder unvollständig; keine künstliche Hoch-/Herabstufung."

    return {
        "base_action": _ACTION_ALIASES.get(str(base_action).strip().upper(), base_action),
        "final_action": final_action,
        "mode": mode,
        "reason": reason,
        "required_domains": list(required),
        "contradicting_domains": [str(signal.get("domain")) for signal in contradictions],
        "unanimous_support": unanimous_support,
    }


def apply_footystats_match_logic(
    legacy: Any,
    pair: Dict[str, Any],
    result: Dict[str, Any],
) -> Dict[str, Any]:
    """Apply qualitative five-file context as one final decision layer."""
    if not isinstance(result, dict) or not result.get("ok"):
        return result

    out = copy.deepcopy(result)
    original_probabilities = copy.deepcopy(out.get("probabilities"))
    strongest = out.get("strongest_market") or {}
    market = str(strongest.get("key") or "").strip()
    if not market:
        return out

    match_data = pair.get("match_data")
    league_data = pair.get("league_data")
    extras = pair.get("supplemental_data") or {}
    match_fields = legacy.mf(match_data)
    home_team = legacy.team_obj(league_data, match_fields.get("home_id"))
    away_team = legacy.team_obj(league_data, match_fields.get("away_id"))

    report = legacy.supplemental_report(
        match_data,
        league_data,
        extras.get("form"),
        extras.get("table"),
        extras.get("player"),
    )
    coverage = report.get("coverage") or {}

    signals = [
        _venue_market_signal(legacy, league_data, home_team, away_team, market),
        _first_half_btts_signal(legacy, league_data, home_team, away_team, market),
        _cs_fts_signal(legacy, league_data, home_team, away_team, market),
        _current_form_signal(coverage.get("form") or {}, market),
        _table_signal(coverage.get("table") or {}, market),
        _player_depth_signal(coverage.get("player") or {}, market),
    ]

    resolution = resolve_action(str(out.get("decision") or ""), market, signals)
    base_action = resolution["base_action"]
    out["decision_before_footystats_context"] = base_action
    out["decision"] = resolution["final_action"]
    out["final_decision_source"] = FINAL_DECISION_SOURCE

    statuses = [signal.get("status") for signal in signals]
    if resolution["mode"] == "UNANIMOUS_CONTEXT_CONFIRMATION":
        overall = SUPPORT
    elif resolution["mode"] == "CONTEXT_VETO":
        overall = CONTRADICT
    elif any(status == SUPPORT for status in statuses):
        overall = "GEMISCHT"
    else:
        overall = NEUTRAL

    out["footystats_match_logic"] = {
        "name": LOGIC_NAME,
        "version": LOGIC_VERSION,
        "market": market,
        "market_label": strongest.get("label"),
        "overall_status": overall,
        "signals": signals,
        "resolution": resolution,
        "probabilities_modified": False,
        "artificial_percentage_adjustments": False,
        "manual_feature_weights": False,
        "global_numeric_betting_cutoffs": False,
        "league_relative_reference": "MEDIAN_OF_SUPPLIED_LEAGUEDATEN",
        "promotion_rule": "ONLY_IF_ALL_REQUIRED_DIRECTIONAL_DOMAINS_SUPPORT",
        "veto_rule": "ANY_REQUIRED_DIRECTIONAL_CONTRADICTION_DEMOTES_ONE_ACTION_LEVEL",
        "missing_or_neutral_rule": "PRESERVE_RELIABILITY_ACTION",
        "five_file_unit": True,
    }

    method = dict(out.get("method") or {})
    method.update({
        "final_decision_source": FINAL_DECISION_SOURCE,
        "footystats_unified_context_logic": True,
        "footystats_context_numeric_probability_adjustment": False,
        "footystats_context_manual_weights": False,
        "footystats_context_can_change_action": True,
    })
    out["method"] = method

    research = dict(out.get("research_context") or {})
    research.update({
        "final_decision_source": FINAL_DECISION_SOURCE,
        "footystats_unified_context_logic": True,
        "footystats_context_changes_probabilities": False,
        "footystats_context_can_change_action": True,
        "footystats_context_manual_weights": False,
    })
    out["research_context"] = research

    if original_probabilities != out.get("probabilities"):
        raise RuntimeError("FootyStats qualitative context logic must not modify probabilities.")
    return out
