"""Fact-only interpreter linking live availability/lineup evidence to FootyStats players.

This module deliberately contains no injury penalty, news score, lineup score,
manual betting threshold, or hand-written probability adjustment.  It resolves
source-backed player names against the five-file PlayerDaten roster by exact
normalized identity and exposes the matched player's real historical facts plus
same-position alternatives.  Ambiguous/unresolved names stay unresolved.
"""
from __future__ import annotations

import copy
import re
import unicodedata
from typing import Any, Dict, Iterable, List, Optional


def _norm(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = text.encode("ascii", "ignore").decode("ascii").lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def _num(value: Any) -> Optional[float]:
    try:
        if value is None or isinstance(value, bool):
            return None
        return float(value)
    except Exception:
        return None


def _same_id(a: Any, b: Any) -> bool:
    try:
        return int(float(a)) == int(float(b))
    except Exception:
        return False


def _walk_dicts(obj: Any) -> Iterable[Dict[str, Any]]:
    if isinstance(obj, dict):
        yield obj
        for value in obj.values():
            yield from _walk_dicts(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from _walk_dicts(value)


def _is_player(row: Dict[str, Any]) -> bool:
    return row.get("id") is not None and row.get("club_team_id") is not None and any(
        key in row for key in ("full_name", "known_as", "position", "minutes_played_overall")
    )


def _players_for_team(player_data: Any, team_id: Any) -> List[Dict[str, Any]]:
    found: Dict[int, Dict[str, Any]] = {}
    for row in _walk_dicts(player_data):
        if not _is_player(row) or not _same_id(row.get("club_team_id"), team_id):
            continue
        try:
            pid = int(float(row.get("id")))
        except Exception:
            continue
        found.setdefault(pid, row)
    return list(found.values())


def _name_variants(player: Dict[str, Any]) -> set[str]:
    variants = {
        _norm(player.get("full_name")),
        _norm(player.get("known_as")),
        _norm(player.get("first_name")),
        _norm(player.get("last_name")),
        _norm(f"{player.get('first_name') or ''} {player.get('last_name') or ''}"),
        _norm(str(player.get("shorthand") or "").replace("-", " ")),
    }
    return {value for value in variants if value}


def _safe_div(numerator: Optional[float], denominator: float) -> Optional[float]:
    if numerator is None or denominator <= 0:
        return None
    return numerator / denominator


def _player_fact(player: Dict[str, Any], roster: List[Dict[str, Any]]) -> Dict[str, Any]:
    minutes = _num(player.get("minutes_played_overall")) or 0.0
    goals = _num(player.get("goals_overall")) or 0.0
    assists = _num(player.get("assists_overall")) or 0.0
    total_minutes = sum((_num(p.get("minutes_played_overall")) or 0.0) for p in roster)
    total_goals = sum((_num(p.get("goals_overall")) or 0.0) for p in roster)
    total_assists = sum((_num(p.get("assists_overall")) or 0.0) for p in roster)
    return {
        "footystats_player_id": player.get("id"),
        "name": player.get("full_name") or player.get("known_as") or player.get("shorthand"),
        "position": player.get("position"),
        "appearances_overall": _num(player.get("appearances_overall")),
        "minutes_played_overall": minutes,
        "goals_overall": goals,
        "assists_overall": assists,
        "goals_per_90_overall": _num(player.get("goals_per_90_overall")),
        "assists_per_90_overall": _num(player.get("assists_per_90_overall")),
        "goals_involved_per_90_overall": _num(player.get("goals_involved_per_90_overall")),
        "rank_in_club_top_scorer": _num(player.get("rank_in_club_top_scorer")),
        "share_of_recorded_team_player_minutes": _safe_div(minutes, total_minutes),
        "share_of_recorded_team_player_goals": _safe_div(goals, total_goals),
        "share_of_recorded_team_player_assists": _safe_div(assists, total_assists),
    }


def _alternative_fact(player: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "footystats_player_id": player.get("id"),
        "name": player.get("full_name") or player.get("known_as") or player.get("shorthand"),
        "position": player.get("position"),
        "minutes_played_overall": _num(player.get("minutes_played_overall")),
        "appearances_overall": _num(player.get("appearances_overall")),
        "goals_overall": _num(player.get("goals_overall")),
        "assists_overall": _num(player.get("assists_overall")),
        "goals_per_90_overall": _num(player.get("goals_per_90_overall")),
        "assists_per_90_overall": _num(player.get("assists_per_90_overall")),
    }


def _resolve_player(name: Any, roster: List[Dict[str, Any]]) -> Dict[str, Any]:
    target = _norm(name)
    if not target:
        return {"status": "UNRESOLVED_NO_NAME"}
    matches = [player for player in roster if target in _name_variants(player)]
    if len(matches) == 0:
        return {"status": "UNRESOLVED_EXACT_NAME", "normalized_source_name": target}
    if len(matches) > 1:
        return {
            "status": "AMBIGUOUS_EXACT_NAME",
            "normalized_source_name": target,
            "candidate_footystats_player_ids": [player.get("id") for player in matches],
        }
    player = matches[0]
    fact = _player_fact(player, roster)
    position = player.get("position")
    alternatives = [p for p in roster if p.get("id") != player.get("id") and p.get("position") == position]
    alternatives.sort(key=lambda p: (_num(p.get("minutes_played_overall")) or 0.0), reverse=True)
    return {
        "status": "EXACT_NORMALIZED_NAME",
        "player": fact,
        "same_position_alternatives": [_alternative_fact(p) for p in alternatives],
    }


def interpret_current_context(match_identity: Dict[str, Any], player_data: Any, context: Dict[str, Any]) -> Dict[str, Any]:
    home_roster = _players_for_team(player_data, match_identity.get("home_id"))
    away_roster = _players_for_team(player_data, match_identity.get("away_id"))
    rosters = {"home": home_roster, "away": away_roster}

    interpreted_events: List[Dict[str, Any]] = []
    for event in (context.get("news_availability") or {}).get("events") or []:
        copied = copy.deepcopy(event)
        side = copied.get("team_side")
        roster = rosters.get(side, [])
        copied["footystats_entity_link"] = _resolve_player(copied.get("player_name"), roster)
        interpreted_events.append(copied)

    lineup = copy.deepcopy(context.get("lineup_context") or {"status": "UNAVAILABLE"})
    for side, key in (("home", "home_players"), ("away", "away_players")):
        enriched = []
        for item in lineup.get(key) or []:
            row = copy.deepcopy(item)
            row["footystats_entity_link"] = _resolve_player(row.get("name"), rosters[side])
            enriched.append(row)
        if key in lineup:
            lineup[key] = enriched

    exact_events = sum(
        1 for event in interpreted_events
        if ((event.get("footystats_entity_link") or {}).get("status") == "EXACT_NORMALIZED_NAME")
    )
    unresolved_events = len(interpreted_events) - exact_events
    return {
        "policy": "FACT_ONLY_ENTITY_LINKING_NO_NUMERIC_PENALTY",
        "manual_injury_penalty": False,
        "manual_news_score": False,
        "manual_lineup_score": False,
        "roster_rows": {"home": len(home_roster), "away": len(away_roster)},
        "availability": {
            "source_status": (context.get("news_availability") or {}).get("status"),
            "events": interpreted_events,
            "event_count": len(interpreted_events),
            "exact_player_links": exact_events,
            "unresolved_or_ambiguous_links": unresolved_events,
        },
        "lineup": lineup,
        "interpretation_rule": (
            "Source-backed facts are linked to real FootyStats player history and alternatives. "
            "No fixed probability deduction or betting threshold is generated from news or lineup data."
        ),
    }
