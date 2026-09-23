"""Production copy of the frozen Phase-4 feature transformation.

The names and semantics intentionally match
``research.full7_phase4_model_research._extract_features``. Missing inputs are
left missing; this module never imputes or invents replacement values.
"""
from __future__ import annotations

import math
from typing import Any, Mapping, Sequence


class Phase7FeatureError(RuntimeError):
    pass


def _finite(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _safe_key(key: str) -> bool:
    low = key.lower()
    exact = {
        "id", "match_id", "homeid", "awayid", "home_id", "away_id", "team_id",
        "competition_id", "season_id", "club_team_id", "club_team_2_id",
        "refereeid", "coach_a_id", "coach_b_id", "roundid",
    }
    if low in exact or low.endswith("_id"):
        return False
    if "timestamp" in low or low.endswith("date_unix") or "source_max_timestamp" in low:
        return False
    return "odd" not in low


def _walk_dict_numbers(value: Any, prefix: str = ""):
    if isinstance(value, dict):
        for key, child in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            if isinstance(child, dict):
                yield from _walk_dict_numbers(child, path)
            elif not isinstance(child, list):
                number = _finite(child)
                if number is not None:
                    yield path, str(key), number


def _find_numeric_key(value: Any, wanted: str) -> float | None:
    if isinstance(value, dict):
        if wanted in value:
            number = _finite(value.get(wanted))
            if number is not None:
                return number
        for child in value.values():
            found = _find_numeric_key(child, wanted)
            if found is not None:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _find_numeric_key(child, wanted)
            if found is not None:
                return found
    return None


def _player_number(row: Mapping[str, Any], keys: Sequence[str]) -> float | None:
    for key in keys:
        number = _finite(row.get(key))
        if number is not None:
            return number
    return None


def _assign_group(name: str, source_context: str, side: str | None = None) -> str:
    low = name.lower()
    if source_context == "provider":
        return "PROVIDER_POTENTIALS"
    if source_context == "h2h":
        return "H2H"
    if source_context == "table":
        return "B4_RELATIVE_TABLE_STRENGTH"
    if "seasonbttspercentageht" in low:
        if side == "home" and low.endswith("_home"):
            return "A1_FH_BTTS_VENUE"
        if side == "away" and low.endswith("_away"):
            return "A1_FH_BTTS_VENUE"
        return "HALF_OTHER"
    if any(token in low for token in ("cspercentage", "ftspercentage", "cs_rate", "fts_rate", "clean_sheet", "failed_to_score", "zerogoal")):
        return "B1_CS_FTS_ZERO_GOAL"
    if any(token in low for token in ("seasonppg", "table_position", "position", "ppg_overall", "points", "goaldifference", "goal_difference")):
        return "B4_RELATIVE_TABLE_STRENGTH"
    if source_context == "form":
        return "FORM_XG" if any(token in low for token in ("xg", "xga")) else "FORM"
    if source_context == "league_team":
        if any(token in low for token in ("shots", "possession", "corners")):
            return "LEAGUE_TEAM_AUXILIARY"
        if any(token in low for token in ("xg", "scored", "conceded", "btts", "over25", "under25")):
            return "LEAGUE_TEAM_GOAL_PROFILE"
        return "LEAGUE_TEAM_PROFILE"
    if source_context == "league_context":
        return "LEAGUE_CONTEXT"
    if source_context == "match":
        return "MATCH_XG_PPG"
    return "OTHER"


def _add(out: dict[str, float], groups: dict[str, str], name: str, value: Any, group: str) -> None:
    number = _finite(value)
    if number is None:
        return
    previous = groups.get(name)
    if previous is not None and previous != group:
        raise Phase7FeatureError(f"feature_group_conflict:{name}:{previous}!={group}")
    out[name] = number
    groups[name] = group


def _target_team_rows(league: Mapping[str, Any], home_id: int, away_id: int):
    home = away = None
    for row in league.get("teams_full_home_away") or []:
        if not isinstance(row, dict):
            continue
        team_id = row.get("id", row.get("team_id"))
        try:
            team_id = int(float(team_id))
        except (TypeError, ValueError):
            continue
        if team_id == home_id:
            home = row
        elif team_id == away_id:
            away = row
    return home or {}, away or {}


def extract_phase4_features(
    sources: Mapping[str, Any], *, home_id: int, away_id: int
) -> tuple[dict[str, float], dict[str, str]]:
    match = sources.get("match") or {}
    league = sources.get("league") or {}
    form = sources.get("form") or {}
    table = sources.get("table") or {}
    player = sources.get("player") or {}
    out: dict[str, float] = {}
    groups: dict[str, str] = {}

    for key, value in (match.get("prematch_optional") or {}).items():
        if _safe_key(str(key)):
            group = "PROVIDER_POTENTIALS" if "potential" in str(key).lower() else "MATCH_XG_PPG"
            _add(out, groups, f"match.{key}", value, group)

    identity = match.get("identity") or {}
    if isinstance(identity, dict):
        for path, key, value in _walk_dict_numbers(identity):
            if _safe_key(key) and key.lower() in {"game_week", "revised_game_week", "matches_completed_minimum", "no_home_away"}:
                _add(out, groups, f"match_identity.{path}", value, "MATCH_CONTEXT")

    for path, key, value in _walk_dict_numbers(league.get("season_safe_identity") or {}):
        if _safe_key(key):
            group = "SAMPLE_SECURITY" if any(token in key.lower() for token in ("matchescompleted", "totalmatches", "progress", "round")) else "LEAGUE_CONTEXT"
            _add(out, groups, f"league_context.{path}", value, group)

    for path, key, value in _walk_dict_numbers(league.get("league_aggregates_derived") or {}):
        if _safe_key(key):
            group = "SAMPLE_SECURITY" if key == "league_source_count" or key.endswith("_recorded_n") else "LEAGUE_CONTEXT"
            _add(out, groups, f"league_derived.{path}", value, group)

    home_team, away_team = _target_team_rows(league, home_id, away_id)
    for side, team in (("home", home_team), ("away", away_team)):
        for path, key, value in _walk_dict_numbers(team):
            if _safe_key(key):
                group = _assign_group(key, "league_team", side)
                if "seasonmatchesplayed" in key.lower():
                    group = "SAMPLE_SECURITY"
                _add(out, groups, f"league_team.{side}.{path}", value, group)

    a1_home = _find_numeric_key(home_team, "seasonBTTSPercentageHT_home")
    a1_away = _find_numeric_key(away_team, "seasonBTTSPercentageHT_away")
    _add(out, groups, "A1.fh_btts_venue_home", a1_home, "A1_FH_BTTS_VENUE")
    _add(out, groups, "A1.fh_btts_venue_away", a1_away, "A1_FH_BTTS_VENUE")
    if a1_home is not None and a1_away is not None:
        _add(out, groups, "A1.fh_btts_venue_diff", a1_home - a1_away, "A1_FH_BTTS_VENUE")
        _add(out, groups, "A1.fh_btts_venue_mean", (a1_home + a1_away) / 2.0, "A1_FH_BTTS_VENUE")

    for side in ("home", "away"):
        side_obj = form.get(side) or {}
        for block in ("last5", "last6", "last10", "home_split", "away_split"):
            payload = side_obj.get(block) or {}
            if isinstance(payload, dict):
                for path, key, value in _walk_dict_numbers(payload):
                    if _safe_key(key):
                        group = "SAMPLE_SECURITY" if key == "n" else _assign_group(key, "form", side)
                        _add(out, groups, f"form.{side}.{block}.{path}", value, group)

    for side, table_row in (("home", table.get("home_row") or {}), ("away", table.get("away_row") or {})):
        if isinstance(table_row, dict):
            for path, key, value in _walk_dict_numbers(table_row):
                if _safe_key(key):
                    group = "SAMPLE_SECURITY" if "matchesplayed" in key.lower() or key.lower() == "played" else "B4_RELATIVE_TABLE_STRENGTH"
                    _add(out, groups, f"table.{side}.{path}", value, group)

    if isinstance(table.get("home_row"), dict) and isinstance(table.get("away_row"), dict):
        hflat = {path: value for path, key, value in _walk_dict_numbers(table["home_row"]) if _safe_key(key)}
        aflat = {path: value for path, key, value in _walk_dict_numbers(table["away_row"]) if _safe_key(key)}
        for key in sorted(set(hflat) & set(aflat)):
            if any(token in key.lower() for token in ("ppg", "point", "position", "goaldifference", "goal_difference")):
                _add(out, groups, f"B4.diff.{key}", hflat[key] - aflat[key], "B4_RELATIVE_TABLE_STRENGTH")

    players = [row for row in (player.get("players") or []) if isinstance(row, dict)]
    by_team = {
        home_id: [row for row in players if int(float(row.get("club_team_id", row.get("team_id", -1)) or -1)) == home_id],
        away_id: [row for row in players if int(float(row.get("club_team_id", row.get("team_id", -1)) or -1)) == away_id],
    }
    depths: dict[str, int] = {}
    side_metrics: dict[str, dict[str, float]] = {}
    for side, team_id in (("home", home_id), ("away", away_id)):
        team_players = by_team[team_id]
        depths[side] = len(team_players)
        _add(out, groups, f"A2.players_found_{side}", len(team_players), "A2_PLAYER_DEPTH")
        goals: list[float] = []
        assists: list[float] = []
        involvement: list[float] = []
        goals90: list[float] = []
        assists90: list[float] = []
        involvement90: list[float] = []
        for row in team_players:
            goals_value = _player_number(row, ("goals_overall", "goals", "total_goals"))
            assists_value = _player_number(row, ("assists_overall", "assists", "total_assists"))
            minutes = _player_number(row, ("minutes_played_overall", "minutes_played", "minutes"))
            if goals_value is not None:
                goals.append(goals_value)
            if assists_value is not None:
                assists.append(assists_value)
            if goals_value is not None and assists_value is not None:
                involvement.append(goals_value + assists_value)
            if minutes is not None and minutes > 0:
                if goals_value is not None:
                    goals90.append(goals_value * 90.0 / minutes)
                if assists_value is not None:
                    assists90.append(assists_value * 90.0 / minutes)
                if goals_value is not None and assists_value is not None:
                    involvement90.append((goals_value + assists_value) * 90.0 / minutes)
        for metric, values in (("goals", goals), ("assists", assists), ("involvement", involvement)):
            ordered = sorted(values, reverse=True)
            total = sum(ordered)
            for count in (1, 2, 3):
                if len(ordered) >= count:
                    subtotal = sum(ordered[:count])
                    _add(out, groups, f"B2.{metric}_top{count}_{side}", subtotal, "B2_PLAYER_CONCENTRATION")
                    if total > 0:
                        _add(out, groups, f"B2.{metric}_share_top{count}_{side}", subtotal / total, "B2_PLAYER_CONCENTRATION")
        for metric, values in (("goals_per90", goals90), ("assists_per90", assists90), ("involvement_per90", involvement90)):
            if values:
                mean = sum(values) / len(values)
                _add(out, groups, f"B3.{metric}_mean_{side}", mean, "B3_PLAYER_CHANCE_QUALITY")
                side_metrics.setdefault(side, {})[metric] = mean

    _add(out, groups, "A2.player_depth_min", min(depths.values()), "A2_PLAYER_DEPTH")
    _add(out, groups, "A2.player_depth_mean", sum(depths.values()) / 2.0, "A2_PLAYER_DEPTH")
    _add(out, groups, "A2.player_depth_diff", depths["home"] - depths["away"], "A2_PLAYER_DEPTH")
    for metric in ("goals_per90", "assists_per90", "involvement_per90"):
        home_value = (side_metrics.get("home") or {}).get(metric)
        away_value = (side_metrics.get("away") or {}).get(metric)
        if home_value is not None and away_value is not None:
            _add(out, groups, f"B3.{metric}_home_minus_away", home_value - away_value, "B3_PLAYER_CHANCE_QUALITY")

    h2h = match.get("h2h")
    if isinstance(h2h, dict):
        for path, key, value in _walk_dict_numbers(h2h):
            if _safe_key(key):
                _add(out, groups, f"h2h.{path}", value, "H2H")
    return out, groups
