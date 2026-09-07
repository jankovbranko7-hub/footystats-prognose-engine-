"""FootyStats V1 full multi-market specialist overlay.

This module intentionally keeps the V0.4.3 FULL-5 probability core frozen.
It extends the already-installed Gate V1 layer with the complete V1 specialist
set required by the production handoff:

- BTTS Specialist
- Over/Under 2.5 Specialist
- 1X2 Specialist
- Player Structure
- Form Regime
- Relative Table Strength
- H2H Diagnostics
- Leakage Guard
- Double-Counting Guard
- explicit assessment of all six requested markets

No specialist changes lambdas or market probabilities. Specialist signals can
only add transparent support/contradiction, reliability/fragility context, and
a decision cap when a market's structural specialist profile clearly runs in
the opposite direction.
"""
from __future__ import annotations

from collections import Counter
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import v041_engine
import v042_engine
import v043_engine
import v043_release
import v1_engine

VERSION = "1.0.0"
BASELINE = "0.4.3 FULL-5"

MARKETS: Tuple[str, ...] = (
    "home_win",
    "away_win",
    "btts_yes",
    "btts_no",
    "over_2_5",
    "under_2_5",
)

MARKET_LABELS = {
    "home_win": "Sieg Heim",
    "away_win": "Sieg Auswärts",
    "btts_yes": "BTTS Yes",
    "btts_no": "BTTS No",
    "over_2_5": "Over 2.5",
    "under_2_5": "Under 2.5",
}

FAMILY_BY_MARKET = {
    "home_win": "1X2",
    "away_win": "1X2",
    "btts_yes": "BTTS",
    "btts_no": "BTTS",
    "over_2_5": "OU_2_5",
    "under_2_5": "OU_2_5",
}

OPPOSITE_DIRECTION = {
    "BTTS_YES": "BTTS_NO",
    "BTTS_NO": "BTTS_YES",
    "OVER_2_5": "UNDER_2_5",
    "UNDER_2_5": "OVER_2_5",
    "HOME_WIN": "AWAY_WIN",
    "AWAY_WIN": "HOME_WIN",
}

TECHNICAL_BLOCK_LABELS = dict(v1_engine.TECHNICAL_BLOCK_LABELS)


def _num(legacy: Any, value: Any) -> Optional[float]:
    try:
        out = legacy.num(value)
        return float(out) if out is not None else None
    except Exception:
        try:
            if value is None or isinstance(value, bool):
                return None
            return float(value)
        except Exception:
            return None


def _round(value: Optional[float], digits: int = 2) -> Optional[float]:
    return round(float(value), digits) if value is not None else None


def _ratio(value: Optional[float], baseline: Optional[float]) -> Optional[float]:
    if value is None or baseline is None or baseline == 0:
        return None
    return float(value) / float(baseline)


def _mean(values: Iterable[Optional[float]]) -> Optional[float]:
    clean = [float(value) for value in values if value is not None]
    return sum(clean) / len(clean) if clean else None


def _weighted_mean(rows: Iterable[Tuple[Optional[float], Optional[float]]]) -> Optional[float]:
    clean = [(float(v), float(w)) for v, w in rows if v is not None and w is not None and float(w) > 0]
    if not clean:
        return None
    total = sum(weight for _, weight in clean)
    return sum(value * weight for value, weight in clean) / total


def _firstnum(legacy: Any, obj: Any, aliases: Sequence[str]) -> Optional[float]:
    try:
        value = legacy.firstnum(obj, list(aliases))
        return float(value) if value is not None else None
    except Exception:
        return None


def _team_metric(legacy: Any, team: Any, metric: str, split: str) -> Optional[float]:
    try:
        value = legacy.tnum(team, metric, split)
        return float(value) if value is not None else None
    except Exception:
        return None


def _team_matches(legacy: Any, team: Any, split: str) -> Optional[float]:
    return _team_metric(legacy, team, "matches", split)


def _league_metric_mean(legacy: Any, teams: Sequence[Any], metric: str, split: str) -> Optional[float]:
    rows = []
    for team in teams:
        rows.append((_team_metric(legacy, team, metric, split), _team_matches(legacy, team, split)))
    return _weighted_mean(rows)


def _league_direct_mean(legacy: Any, teams: Sequence[Any], key: str, split: str) -> Optional[float]:
    rows = []
    match_key = f"seasonMatchesPlayed_{split}"
    for team in teams:
        rows.append((_firstnum(legacy, team, [key]), _firstnum(legacy, team, [match_key])))
    return _weighted_mean(rows)


def _pair_direction(
    home_delta: Optional[float],
    away_delta: Optional[float],
    positive: str,
    negative: str,
) -> str:
    if home_delta is None or away_delta is None:
        return "NICHT BEWERTBAR"
    if home_delta > 0 and away_delta > 0:
        return positive
    if home_delta < 0 and away_delta < 0:
        return negative
    return "GEMISCHT"


def _consensus_direction(signals: Sequence[str], positive: str, negative: str) -> Dict[str, Any]:
    applicable = [signal for signal in signals if signal in {positive, negative}]
    counts = Counter(applicable)
    pos = counts.get(positive, 0)
    neg = counts.get(negative, 0)
    # A specialist becomes a clear directional blocker/supporter only when
    # at least two applicable subprofiles agree without an opposite signal.
    # This deliberately avoids invented numeric weights or majority scoring.
    if len(applicable) < 2:
        direction = "NICHT BEWERTBAR" if not applicable else "GEMISCHT"
    elif pos == len(applicable):
        direction = positive
    elif neg == len(applicable):
        direction = negative
    else:
        direction = "GEMISCHT"
    return {
        "direction": direction,
        "positive_count": pos,
        "negative_count": neg,
        "applicable_signal_count": len(applicable),
        "balance": pos - neg,
    }


def _form_records(form_data: Any) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    if not isinstance(form_data, dict):
        return records
    for page in form_data.get("pages") or []:
        if isinstance(page, dict):
            records.extend(item for item in (page.get("data") or []) if isinstance(item, dict))
    if not records:
        data = form_data.get("data")
        if isinstance(data, list):
            records.extend(item for item in data if isinstance(item, dict))
    return records


def _same_id(legacy: Any, value: Any, target: Any) -> bool:
    a, b = _num(legacy, value), _num(legacy, target)
    return a is not None and b is not None and int(a) == int(b)


def _form_windows(legacy: Any, form_data: Any, team_id: Any) -> Dict[int, Dict[str, Any]]:
    windows: Dict[int, Dict[str, Any]] = {}
    for row in _form_records(form_data):
        if not _same_id(legacy, row.get("id"), team_id):
            continue
        stats = row.get("stats") or {}
        sample = _num(legacy, row.get("last_x_match_num"))
        if sample is None:
            sample = _num(legacy, stats.get("last_x"))
        if sample is None:
            continue
        sample_i = int(sample)
        goals = _num(legacy, stats.get("seasonScoredAVG_overall"))
        shots = _num(legacy, stats.get("shotsAVG_overall"))
        sot = _num(legacy, stats.get("shotsOnTargetAVG_overall"))
        windows[sample_i] = {
            "sample": sample_i,
            "ppg": _num(legacy, stats.get("seasonPPG_overall")),
            "xg": _num(legacy, stats.get("xg_for_avg_overall")),
            "xga": _num(legacy, stats.get("xg_against_avg_overall")),
            "goals_for_per_match": goals,
            "goals_against_per_match": _num(legacy, stats.get("seasonConcededAVG_overall")),
            "shots_avg": shots,
            "shots_on_target_avg": sot,
            "shot_conversion": (goals / shots) if goals is not None and shots is not None and shots > 0 else None,
            "btts_pct": _num(legacy, stats.get("seasonBTTSPercentage_overall")),
            "over_25_pct": _num(legacy, stats.get("seasonOver25Percentage_overall")),
            "under_25_pct": _num(legacy, stats.get("seasonUnder25Percentage_overall")),
            "cs_pct": _num(legacy, stats.get("seasonCSPercentage_overall")),
            "fts_pct": _num(legacy, stats.get("seasonFTSPercentage_overall")),
            "ht_btts_pct": _num(legacy, stats.get("seasonBTTSPercentageHT_overall")),
            "btts_2hg_pct": _num(legacy, stats.get("btts_2hg_percentage_overall")),
            "over05_ht_pct": _num(legacy, stats.get("seasonOver05PercentageHT_overall")),
            "over15_ht_pct": _num(legacy, stats.get("seasonOver15PercentageHT_overall")),
            "over05_2hg_pct": _num(legacy, stats.get("over05_2hg_percentage_overall")),
            "over15_2hg_pct": _num(legacy, stats.get("over15_2hg_percentage_overall")),
        }
    return windows


def _delta(recent: Dict[str, Any], reference: Dict[str, Any], key: str) -> Optional[float]:
    a, b = _num_obj(recent.get(key)), _num_obj(reference.get(key))
    return a - b if a is not None and b is not None else None


def _num_obj(value: Any) -> Optional[float]:
    try:
        if value is None or isinstance(value, bool):
            return None
        return float(value)
    except Exception:
        return None


def _form_regime_team(legacy: Any, form_data: Any, team_id: Any) -> Dict[str, Any]:
    windows = _form_windows(legacy, form_data, team_id)
    if not windows:
        return {
            "available": False,
            "window_policy": "Last5/Last6/Last10 are one FORM family and never independent confirmations.",
        }
    reference = windows.get(10) or windows[max(windows)]
    recent = windows.get(5) or windows[min(windows)]
    attack = {
        key: reference.get(key)
        for key in ("xg", "goals_for_per_match", "shots_avg", "shots_on_target_avg", "shot_conversion", "ppg")
    }
    defence = {
        key: reference.get(key)
        for key in ("xga", "goals_against_per_match", "cs_pct")
    }
    btts = {
        key: reference.get(key)
        for key in ("btts_pct", "ht_btts_pct", "btts_2hg_pct", "fts_pct", "cs_pct")
    }
    tempo = {
        key: reference.get(key)
        for key in ("over_25_pct", "over05_ht_pct", "over15_ht_pct", "over05_2hg_pct", "over15_2hg_pct")
    }
    trend = {
        key: _round(_delta(recent, reference, key), 3)
        for key in (
            "ppg",
            "xg",
            "xga",
            "goals_for_per_match",
            "goals_against_per_match",
            "shots_on_target_avg",
            "btts_pct",
            "over_25_pct",
        )
    }
    return {
        "available": True,
        "reference_sample": reference.get("sample"),
        "recent_sample": recent.get("sample"),
        "windows_available": sorted(windows),
        "FORM_ATTACK": attack,
        "FORM_DEFENCE": defence,
        "FORM_BTTS": btts,
        "FORM_TEMPO": tempo,
        "trend_recent_vs_reference": trend,
        "window_policy": "Last5/Last6/Last10 are one FORM family and never independent confirmations.",
    }


def _form_regime(legacy: Any, form_data: Any, home_id: Any, away_id: Any) -> Dict[str, Any]:
    return {
        "name": "Form Regime",
        "mode": "SPECIALIST_DIAGNOSTIC_SINGLE_FAMILY",
        "home": _form_regime_team(legacy, form_data, home_id),
        "away": _form_regime_team(legacy, form_data, away_id),
        "independent_confirmation_count_added": 0,
    }


def _player_rows(player_data: Any) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if not isinstance(player_data, dict):
        return rows
    for page in player_data.get("pages") or []:
        if isinstance(page, dict):
            rows.extend(item for item in (page.get("data") or []) if isinstance(item, dict))
    if not rows and isinstance(player_data.get("data"), list):
        rows.extend(item for item in player_data.get("data") if isinstance(item, dict))
    return rows


def _player_team_id(legacy: Any, player: Dict[str, Any]) -> Optional[int]:
    for key in ("club_team_id", "club_team_2_id"):
        value = _num(legacy, player.get(key))
        if value is not None and value > 0:
            return int(value)
    return None


def _player_structure_team(legacy: Any, rows: Sequence[Dict[str, Any]], team_id: Any) -> Dict[str, Any]:
    players = [row for row in rows if _player_team_id(legacy, row) == int(team_id)]
    if not players:
        return {"available": False, "players_found": 0}

    def val(player: Dict[str, Any], key: str) -> float:
        return _num(legacy, player.get(key)) or 0.0

    total_minutes = sum(val(p, "minutes_played_overall") for p in players)
    total_goals = sum(val(p, "goals_overall") for p in players)
    total_assists = sum(val(p, "assists_overall") for p in players)
    total_contrib = total_goals + total_assists
    goals_rank = sorted((val(p, "goals_overall") for p in players), reverse=True)
    contrib_rank = sorted((val(p, "goals_overall") + val(p, "assists_overall") for p in players), reverse=True)
    minutes_rank = sorted((val(p, "minutes_played_overall") for p in players), reverse=True)
    top3_goal_share = sum(goals_rank[:3]) / total_goals if total_goals > 0 else None
    top5_goal_share = sum(goals_rank[:5]) / total_goals if total_goals > 0 else None
    top3_contrib_share = sum(contrib_rank[:3]) / total_contrib if total_contrib > 0 else None
    top5_minutes_share = sum(minutes_rank[:5]) / total_minutes if total_minutes > 0 else None

    home_minutes = sum(val(p, "minutes_played_home") for p in players)
    away_minutes = sum(val(p, "minutes_played_away") for p in players)
    home_goals = sum(val(p, "goals_home") for p in players)
    away_goals = sum(val(p, "goals_away") for p in players)

    return {
        "available": True,
        "players_found": len(players),
        "players_with_minutes": sum(1 for p in players if val(p, "minutes_played_overall") > 0),
        "appearances": {
            "overall": sum(val(p, "appearances_overall") for p in players),
            "home": sum(val(p, "appearances_home") for p in players),
            "away": sum(val(p, "appearances_away") for p in players),
        },
        "minutes": {
            "overall": _round(total_minutes, 1),
            "home": _round(home_minutes, 1),
            "away": _round(away_minutes, 1),
        },
        "goals_involved_per_90_overall": _round(total_contrib * 90.0 / total_minutes, 3) if total_minutes > 0 else None,
        "goals_per_90": {
            "overall": _round(total_goals * 90.0 / total_minutes, 3) if total_minutes > 0 else None,
            "home": _round(home_goals * 90.0 / home_minutes, 3) if home_minutes > 0 else None,
            "away": _round(away_goals * 90.0 / away_minutes, 3) if away_minutes > 0 else None,
        },
        "top3_goal_share_pct": _round(top3_goal_share * 100.0, 1) if top3_goal_share is not None else None,
        "top5_goal_share_pct": _round(top5_goal_share * 100.0, 1) if top5_goal_share is not None else None,
        "top3_contribution_share_pct": _round(top3_contrib_share * 100.0, 1) if top3_contrib_share is not None else None,
        "production_outside_top3_pct": _round((1.0 - top3_contrib_share) * 100.0, 1) if top3_contrib_share is not None else None,
        "top5_minutes_share_pct": _round(top5_minutes_share * 100.0, 1) if top5_minutes_share is not None else None,
        "venue_player_production": {
            "home_goals_per_90": _round(home_goals * 90.0 / home_minutes, 3) if home_minutes > 0 else None,
            "away_goals_per_90": _round(away_goals * 90.0 / away_minutes, 3) if away_minutes > 0 else None,
        },
        "top_scorer_ranks_found": sorted(
            {int(rank) for rank in (_num(legacy, p.get("rank_in_club_top_scorer")) for p in players) if rank is not None}
        )[:10],
    }


def _player_structure(
    legacy: Any,
    player_data: Any,
    home_id: Any,
    away_id: Any,
    existing_depth: Dict[str, Any],
) -> Dict[str, Any]:
    rows = _player_rows(player_data)
    return {
        "name": "Player Structure",
        "mode": "RELIABILITY_FRAGILITY_NO_LAMBDA_WEIGHT",
        "home": _player_structure_team(legacy, rows, home_id),
        "away": _player_structure_team(legacy, rows, away_id),
        "depth_status": existing_depth.get("status"),
        "depth_explanation": existing_depth.get("explanation"),
        "policy": "Player Structure affects robustness/confidence context only; it never adds lambda automatically.",
    }


def _relative_table_strength(
    legacy: Any,
    report: Dict[str, Any],
    teams: Sequence[Any],
    home_team: Any,
    away_team: Any,
) -> Dict[str, Any]:
    coverage = ((report.get("coverage") or {}).get("table") or {})
    home = coverage.get("home") or {}
    away = coverage.get("away") or {}
    team_count = len(teams)
    home_pos = _num_obj(home.get("position"))
    away_pos = _num_obj(away.get("position"))
    denominator = team_count - 1
    normalized_home = (home_pos - 1.0) / denominator if home_pos is not None and denominator > 0 else None
    normalized_away = (away_pos - 1.0) / denominator if away_pos is not None and denominator > 0 else None

    home_ppg = _team_metric(legacy, home_team, "ppg", "home")
    away_ppg = _team_metric(legacy, away_team, "ppg", "away")
    league_home_ppg = _league_metric_mean(legacy, teams, "ppg", "home")
    league_away_ppg = _league_metric_mean(legacy, teams, "ppg", "away")
    return {
        "name": "Relative Table Strength",
        "mode": "1X2_SPECIALIST_DIAGNOSTIC",
        "teams": team_count,
        "home_position": home_pos,
        "away_position": away_pos,
        "home_normalized_position": _round(normalized_home, 4),
        "away_normalized_position": _round(normalized_away, 4),
        "home_ppg": home_ppg,
        "away_ppg": away_ppg,
        "league_home_ppg": _round(league_home_ppg, 3),
        "league_away_ppg": _round(league_away_ppg, 3),
        "home_ppg_vs_league_ratio": _round(_ratio(home_ppg, league_home_ppg), 3),
        "away_ppg_vs_league_ratio": _round(_ratio(away_ppg, league_away_ppg), 3),
        "formula": "normalized_position = (Position - 1) / (Teams - 1)",
    }


def _league_pair_relative_direction(
    home_value: Optional[float],
    home_baseline: Optional[float],
    away_value: Optional[float],
    away_baseline: Optional[float],
    positive: str,
    negative: str,
    higher_is_positive: bool = True,
) -> str:
    if None in (home_value, home_baseline, away_value, away_baseline):
        return "NICHT BEWERTBAR"
    home_delta = float(home_value) - float(home_baseline)
    away_delta = float(away_value) - float(away_baseline)
    if not higher_is_positive:
        home_delta, away_delta = -home_delta, -away_delta
    return _pair_direction(home_delta, away_delta, positive, negative)


def _btts_specialist(
    legacy: Any,
    teams: Sequence[Any],
    home_team: Any,
    away_team: Any,
    form_regime: Dict[str, Any],
    player_structure: Dict[str, Any],
    existing: Dict[str, Any],
) -> Dict[str, Any]:
    fh = existing.get("fh_btts") or {}
    cs_fts = existing.get("cs_fts") or {}

    home_2h = _firstnum(legacy, home_team, ["btts_2hg_percentage_home"])
    away_2h = _firstnum(legacy, away_team, ["btts_2hg_percentage_away"])
    league_home_2h = _league_direct_mean(legacy, teams, "btts_2hg_percentage_home", "home")
    league_away_2h = _league_direct_mean(legacy, teams, "btts_2hg_percentage_away", "away")
    second_half = _league_pair_relative_direction(
        home_2h, league_home_2h, away_2h, league_away_2h, "BTTS_YES", "BTTS_NO"
    )

    home_form = ((form_regime.get("home") or {}).get("FORM_BTTS") or {})
    away_form = ((form_regime.get("away") or {}).get("FORM_BTTS") or {})
    form_btts = _pair_direction(
        (_num_obj(home_form.get("btts_pct")) - 50.0) if _num_obj(home_form.get("btts_pct")) is not None else None,
        (_num_obj(away_form.get("btts_pct")) - 50.0) if _num_obj(away_form.get("btts_pct")) is not None else None,
        "BTTS_YES",
        "BTTS_NO",
    )

    signals = [
        str(fh.get("direction") or "NICHT BEWERTBAR"),
        str(cs_fts.get("direction") or "NICHT BEWERTBAR"),
        second_half,
        form_btts,
    ]
    consensus = _consensus_direction(signals, "BTTS_YES", "BTTS_NO")
    return {
        "name": "BTTS Specialist",
        "mode": "STRUCTURED_EVIDENCE_NO_PROBABILITY_REWEIGHTING",
        **consensus,
        "signals": {
            "first_half_btts_venue": fh,
            "cs_fts_scoring_survival": cs_fts,
            "second_half_btts": {
                "direction": second_half,
                "home_pct": _round(home_2h),
                "away_pct": _round(away_2h),
                "league_home_pct": _round(league_home_2h),
                "league_away_pct": _round(league_away_2h),
            },
            "form_btts": {
                "direction": form_btts,
                "home_reference_btts_pct": home_form.get("btts_pct"),
                "away_reference_btts_pct": away_form.get("btts_pct"),
            },
        },
        "player_reliability": {
            "depth_status": player_structure.get("depth_status"),
            "policy": "Player depth/concentration is robustness context, not a BTTS confirmation block.",
        },
        "classic_confirmation_blocks_added": 0,
    }


def _finishing_efficiency_direction(
    home: Dict[str, Optional[float]],
    away: Dict[str, Optional[float]],
) -> str:
    signals: List[str] = []
    for side in (home, away):
        conv = side.get("conversion")
        conv_base = side.get("conversion_baseline")
        spg = side.get("shots_per_goal")
        spg_base = side.get("shots_per_goal_baseline")
        sotpg = side.get("sot_per_goal")
        sotpg_base = side.get("sot_per_goal_baseline")
        votes: List[str] = []
        if conv is not None and conv_base is not None:
            votes.append("OVER_2_5" if conv > conv_base else ("UNDER_2_5" if conv < conv_base else "GEMISCHT"))
        if spg is not None and spg_base is not None:
            votes.append("OVER_2_5" if spg < spg_base else ("UNDER_2_5" if spg > spg_base else "GEMISCHT"))
        if sotpg is not None and sotpg_base is not None:
            votes.append("OVER_2_5" if sotpg < sotpg_base else ("UNDER_2_5" if sotpg > sotpg_base else "GEMISCHT"))
        c = Counter(v for v in votes if v in {"OVER_2_5", "UNDER_2_5"})
        if c.get("OVER_2_5", 0) > c.get("UNDER_2_5", 0):
            signals.append("OVER_2_5")
        elif c.get("UNDER_2_5", 0) > c.get("OVER_2_5", 0):
            signals.append("UNDER_2_5")
        else:
            signals.append("GEMISCHT")
    if len(signals) == 2 and signals[0] == signals[1] and signals[0] in {"OVER_2_5", "UNDER_2_5"}:
        return signals[0]
    return "GEMISCHT" if signals else "NICHT BEWERTBAR"


def _goal_intensity_direction(
    legacy: Any,
    teams: Sequence[Any],
    home_team: Any,
    away_team: Any,
    suffix: str,
) -> Dict[str, Any]:
    if suffix == "HT":
        keys = ("seasonOver05PercentageHT_home", "seasonOver15PercentageHT_home",
                "seasonOver05PercentageHT_away", "seasonOver15PercentageHT_away")
    else:
        keys = ("over05_2hg_percentage_home", "over15_2hg_percentage_home",
                "over05_2hg_percentage_away", "over15_2hg_percentage_away")
    h05 = _firstnum(legacy, home_team, [keys[0]])
    h15 = _firstnum(legacy, home_team, [keys[1]])
    a05 = _firstnum(legacy, away_team, [keys[2]])
    a15 = _firstnum(legacy, away_team, [keys[3]])
    lh05 = _league_direct_mean(legacy, teams, keys[0], "home")
    lh15 = _league_direct_mean(legacy, teams, keys[1], "home")
    la05 = _league_direct_mean(legacy, teams, keys[2], "away")
    la15 = _league_direct_mean(legacy, teams, keys[3], "away")
    home_delta = _mean([
        (h05 - lh05) if h05 is not None and lh05 is not None else None,
        (h15 - lh15) if h15 is not None and lh15 is not None else None,
    ])
    away_delta = _mean([
        (a05 - la05) if a05 is not None and la05 is not None else None,
        (a15 - la15) if a15 is not None and la15 is not None else None,
    ])
    return {
        "direction": _pair_direction(home_delta, away_delta, "OVER_2_5", "UNDER_2_5"),
        "home_over05_pct": _round(h05),
        "home_over15_pct": _round(h15),
        "away_over05_pct": _round(a05),
        "away_over15_pct": _round(a15),
        "home_delta_vs_league": _round(home_delta),
        "away_delta_vs_league": _round(away_delta),
    }


def _over_under_specialist(
    legacy: Any,
    teams: Sequence[Any],
    home_team: Any,
    away_team: Any,
    form_regime: Dict[str, Any],
) -> Dict[str, Any]:
    def efficiency(team: Any, split: str) -> Dict[str, Optional[float]]:
        gf = _team_metric(legacy, team, "gf", split)
        shots = _team_metric(legacy, team, "shots", split)
        sot = _team_metric(legacy, team, "sot", split)
        league_gf = _league_metric_mean(legacy, teams, "gf", split)
        league_shots = _league_metric_mean(legacy, teams, "shots", split)
        league_sot = _league_metric_mean(legacy, teams, "sot", split)
        conversion = gf / shots if gf is not None and shots is not None and shots > 0 else None
        shots_per_goal = shots / gf if gf is not None and gf > 0 and shots is not None else None
        sot_per_goal = sot / gf if gf is not None and gf > 0 and sot is not None else None
        conversion_base = league_gf / league_shots if league_gf is not None and league_shots is not None and league_shots > 0 else None
        spg_base = league_shots / league_gf if league_gf is not None and league_gf > 0 and league_shots is not None else None
        sotpg_base = league_sot / league_gf if league_gf is not None and league_gf > 0 and league_sot is not None else None
        return {
            "conversion": conversion,
            "conversion_baseline": conversion_base,
            "shots_per_goal": shots_per_goal,
            "shots_per_goal_baseline": spg_base,
            "sot_per_goal": sot_per_goal,
            "sot_per_goal_baseline": sotpg_base,
        }

    home_eff = efficiency(home_team, "home")
    away_eff = efficiency(away_team, "away")
    finishing_direction = _finishing_efficiency_direction(home_eff, away_eff)
    first_half = _goal_intensity_direction(legacy, teams, home_team, away_team, "HT")
    second_half = _goal_intensity_direction(legacy, teams, home_team, away_team, "2H")

    h_fts = _team_metric(legacy, home_team, "fts", "home")
    a_fts = _team_metric(legacy, away_team, "fts", "away")
    lh_fts = _league_metric_mean(legacy, teams, "fts", "home")
    la_fts = _league_metric_mean(legacy, teams, "fts", "away")
    scoring_failure = _league_pair_relative_direction(
        h_fts, lh_fts, a_fts, la_fts, "UNDER_2_5", "OVER_2_5", higher_is_positive=True
    )

    home_form = ((form_regime.get("home") or {}).get("FORM_TEMPO") or {})
    away_form = ((form_regime.get("away") or {}).get("FORM_TEMPO") or {})
    h_o25 = _num_obj(home_form.get("over_25_pct"))
    a_o25 = _num_obj(away_form.get("over_25_pct"))
    form_tempo = _pair_direction(
        (h_o25 - 50.0) if h_o25 is not None else None,
        (a_o25 - 50.0) if a_o25 is not None else None,
        "OVER_2_5",
        "UNDER_2_5",
    )

    signals = [
        finishing_direction,
        first_half.get("direction"),
        second_half.get("direction"),
        scoring_failure,
        form_tempo,
    ]
    consensus = _consensus_direction(signals, "OVER_2_5", "UNDER_2_5")
    return {
        "name": "Over/Under 2.5 Specialist",
        "mode": "STRUCTURED_EVIDENCE_NO_PROBABILITY_REWEIGHTING",
        **consensus,
        "signals": {
            "finishing_efficiency": {
                "direction": finishing_direction,
                "home": {k: _round(v, 4) for k, v in home_eff.items()},
                "away": {k: _round(v, 4) for k, v in away_eff.items()},
                "policy": "Shot Conversion, Shots/Goal and SOT/Goal are one correlated finishing group, not three confirmations.",
            },
            "first_half_goal_intensity": first_half,
            "second_half_goal_intensity": second_half,
            "scoring_failure": {
                "direction": scoring_failure,
                "home_fts_pct": _round(h_fts),
                "away_fts_pct": _round(a_fts),
                "league_home_fts_pct": _round(lh_fts),
                "league_away_fts_pct": _round(la_fts),
            },
            "form_tempo": {
                "direction": form_tempo,
                "home_over25_pct": h_o25,
                "away_over25_pct": a_o25,
            },
        },
        "classic_confirmation_blocks_added": 0,
    }


def _direction_from_votes(votes: Sequence[str], positive: str, negative: str) -> str:
    applicable = [vote for vote in votes if vote in {positive, negative}]
    if not applicable:
        return "NICHT BEWERTBAR"
    if all(vote == positive for vote in applicable):
        return positive
    if all(vote == negative for vote in applicable):
        return negative
    return "GEMISCHT"


def _one_x_two_specialist(
    legacy: Any,
    teams: Sequence[Any],
    home_team: Any,
    away_team: Any,
    result: Dict[str, Any],
    report: Dict[str, Any],
    form_regime: Dict[str, Any],
    relative_table: Dict[str, Any],
    player_structure: Dict[str, Any],
) -> Dict[str, Any]:
    h_ppg = _team_metric(legacy, home_team, "ppg", "home")
    a_ppg = _team_metric(legacy, away_team, "ppg", "away")
    l_h_ppg = _league_metric_mean(legacy, teams, "ppg", "home")
    l_a_ppg = _league_metric_mean(legacy, teams, "ppg", "away")
    ppg_home_ratio, ppg_away_ratio = _ratio(h_ppg, l_h_ppg), _ratio(a_ppg, l_a_ppg)
    ppg_direction = (
        "HOME_WIN" if ppg_home_ratio is not None and ppg_away_ratio is not None and ppg_home_ratio > ppg_away_ratio
        else "AWAY_WIN" if ppg_home_ratio is not None and ppg_away_ratio is not None and ppg_away_ratio > ppg_home_ratio
        else "GEMISCHT"
    )

    h_xg = _team_metric(legacy, home_team, "xg", "home")
    a_xg = _team_metric(legacy, away_team, "xg", "away")
    h_xga = _team_metric(legacy, home_team, "xga", "home")
    a_xga = _team_metric(legacy, away_team, "xga", "away")
    l_h_xg = _league_metric_mean(legacy, teams, "xg", "home")
    l_a_xg = _league_metric_mean(legacy, teams, "xg", "away")
    l_h_xga = _league_metric_mean(legacy, teams, "xga", "home")
    l_a_xga = _league_metric_mean(legacy, teams, "xga", "away")
    strength_votes = []
    if None not in (h_xg, l_h_xg, a_xg, l_a_xg):
        strength_votes.append("HOME_WIN" if _ratio(h_xg, l_h_xg) > _ratio(a_xg, l_a_xg) else "AWAY_WIN")
    if None not in (h_xga, l_h_xga, a_xga, l_a_xga):
        # Lower xGA ratio is stronger defence.
        strength_votes.append("HOME_WIN" if _ratio(h_xga, l_h_xga) < _ratio(a_xga, l_a_xga) else "AWAY_WIN")
    xg_direction = _direction_from_votes(strength_votes, "HOME_WIN", "AWAY_WIN")

    h_norm = _num_obj(relative_table.get("home_normalized_position"))
    a_norm = _num_obj(relative_table.get("away_normalized_position"))
    table_direction = (
        "HOME_WIN" if h_norm is not None and a_norm is not None and h_norm < a_norm
        else "AWAY_WIN" if h_norm is not None and a_norm is not None and a_norm < h_norm
        else "GEMISCHT"
    )

    h_overall_ppg = _team_metric(legacy, home_team, "ppg", "overall")
    a_overall_ppg = _team_metric(legacy, away_team, "ppg", "overall")
    h_venue_delta = h_ppg - h_overall_ppg if h_ppg is not None and h_overall_ppg is not None else None
    a_venue_delta = a_ppg - a_overall_ppg if a_ppg is not None and a_overall_ppg is not None else None
    venue_vs_overall = (
        "HOME_WIN" if h_venue_delta is not None and a_venue_delta is not None and h_venue_delta > a_venue_delta
        else "AWAY_WIN" if h_venue_delta is not None and a_venue_delta is not None and a_venue_delta > h_venue_delta
        else "GEMISCHT"
    )

    home_form_signal = v041_engine._form_signal(report, "home_win")
    away_form_signal = v041_engine._form_signal(report, "away_win")
    if home_form_signal.get("status") == "BESTÄTIGEND" and away_form_signal.get("status") != "BESTÄTIGEND":
        form_direction = "HOME_WIN"
    elif away_form_signal.get("status") == "BESTÄTIGEND" and home_form_signal.get("status") != "BESTÄTIGEND":
        form_direction = "AWAY_WIN"
    else:
        form_direction = "GEMISCHT"

    signals = [ppg_direction, xg_direction, table_direction, venue_vs_overall, form_direction]
    consensus = _consensus_direction(signals, "HOME_WIN", "AWAY_WIN")
    return {
        "name": "1X2 Specialist",
        "mode": "RELATIVE_STRENGTH_DIAGNOSTIC_NO_PROBABILITY_REWEIGHTING",
        **consensus,
        "signals": {
            "venue_ppg_relative_to_league": {
                "direction": ppg_direction,
                "home_ratio": _round(ppg_home_ratio, 3),
                "away_ratio": _round(ppg_away_ratio, 3),
            },
            "relative_attack_defence_xg": {
                "direction": xg_direction,
                "home_xg_ratio": _round(_ratio(h_xg, l_h_xg), 3),
                "away_xg_ratio": _round(_ratio(a_xg, l_a_xg), 3),
                "home_xga_ratio": _round(_ratio(h_xga, l_h_xga), 3),
                "away_xga_ratio": _round(_ratio(a_xga, l_a_xga), 3),
            },
            "normalized_table_position": {
                "direction": table_direction,
                "home": h_norm,
                "away": a_norm,
            },
            "venue_vs_overall": {
                "direction": venue_vs_overall,
                "home_ppg_delta": _round(h_venue_delta, 3),
                "away_ppg_delta": _round(a_venue_delta, 3),
            },
            "current_form": {
                "direction": form_direction,
                "home_signal": home_form_signal,
                "away_signal": away_form_signal,
            },
        },
        "reliability": {
            "sample_security": (result.get("samples") or {}).get("security"),
            "player_depth_status": player_structure.get("depth_status"),
        },
        "classic_confirmation_blocks_added": 0,
    }


def _h2h_sample(h2h: Dict[str, Any]) -> Optional[int]:
    for key in ("previous_matches", "matches", "results", "data"):
        value = h2h.get(key)
        if isinstance(value, list):
            return len(value)
    for key in ("sample", "sample_size", "matches_count"):
        value = _num_obj(h2h.get(key))
        if value is not None:
            return int(value)
    return None


def _h2h_diagnostic(legacy: Any, match_data: Any) -> Dict[str, Any]:
    try:
        match_obj = legacy.match_obj(match_data) or {}
    except Exception:
        match_obj = {}
    h2h = match_obj.get("h2h") if isinstance(match_obj, dict) else None
    if not isinstance(h2h, dict):
        return {
            "name": "H2H Diagnostics",
            "status": "NICHT VERFÜGBAR",
            "gate_weight": 0,
            "independent_confirmation": False,
        }
    betting = h2h.get("betting_stats") or h2h.get("bettingStats") or {}
    btts = _firstnum(legacy, betting, ["bttsPercentage", "btts_percentage"])
    avg_goals = _firstnum(legacy, h2h, ["avg_goals", "avgGoals"])
    if avg_goals is None:
        avg_goals = _firstnum(legacy, betting, ["avg_goals", "avgGoals"])
    over25 = _firstnum(legacy, betting, ["over25Percentage", "over_25_percentage", "over25"])
    sample = _h2h_sample(h2h)
    btts_direction = (
        "BTTS_YES" if btts is not None and btts > 50
        else "BTTS_NO" if btts is not None and btts < 50
        else "GEMISCHT" if btts is not None
        else "NICHT BEWERTBAR"
    )
    goals_direction = (
        "OVER_2_5" if avg_goals is not None and avg_goals > 2.5
        else "UNDER_2_5" if avg_goals is not None and avg_goals < 2.5
        else "GEMISCHT" if avg_goals is not None
        else "NICHT BEWERTBAR"
    )
    return {
        "name": "H2H Diagnostics",
        "status": "BERECHNET",
        "btts_pct": _round(btts),
        "avg_goals": _round(avg_goals),
        "over25_pct": _round(over25),
        "sample_size": sample,
        "sample_note": "KLEIN" if sample is not None and sample < 5 else ("VERFÜGBAR" if sample is not None else "NICHT ERMITTELBAR"),
        "btts_direction": btts_direction,
        "goal_direction": goals_direction,
        "gate_weight": 0,
        "independent_confirmation": False,
        "policy": "H2H is a small diagnostic/counterargument context only and never dominates V1.",
    }


def _norm_key(value: Any) -> str:
    return "".join(ch.lower() for ch in str(value) if ch.isalnum() or ch == "_")


LEAKAGE_KEYS = {
    "homegoalcount",
    "awaygoalcount",
    "home_goal_count",
    "away_goal_count",
    "team_a_xg",
    "team_b_xg",
    "home_xg",
    "away_xg",
    "team_a_shots",
    "team_b_shots",
    "home_shots",
    "away_shots",
    "team_a_shotsontarget",
    "team_b_shotsontarget",
    "home_shots_on_target",
    "away_shots_on_target",
    "team_a_corners",
    "team_b_corners",
    "home_corners",
    "away_corners",
    "team_a_cards",
    "team_b_cards",
    "home_cards",
    "away_cards",
    "team_a_possession",
    "team_b_possession",
    "home_possession",
    "away_possession",
    "gpt_en",
}


def _leakage_guard(legacy: Any, match_data: Any) -> Dict[str, Any]:
    try:
        target = legacy.match_obj(match_data) or {}
    except Exception:
        target = {}
    blocked_present: List[str] = []
    if isinstance(target, dict):
        for key in target:
            normalized = _norm_key(key)
            if normalized in LEAKAGE_KEYS:
                blocked_present.append(str(key))
    return {
        "name": "Leakage Guard",
        "status": "AKTIV",
        "blocked_fields_present_and_ignored": sorted(blocked_present),
        "prematch_fields_allowed": [
            "team_a_xg_prematch",
            "team_b_xg_prematch",
            "pre_match_home_ppg",
            "pre_match_away_ppg",
        ],
        "target_live_fields_used": False,
        "gpt_en_used": False,
        "policy": "Target-match live/post-kickoff fields and gpt_en are never read by V1 specialists or gates.",
    }


def _double_counting_guard() -> Dict[str, Any]:
    return {
        "name": "Double-Counting Guard",
        "status": "AKTIV",
        "CORE_EVIDENCE": [
            "V0.4.3 40-feature FULL-5 inputs",
            "V0.4.3 lambdas",
            "Dixon-Coles probabilities",
        ],
        "SPECIALIST_EVIDENCE": [
            "BTTS scoring-survival / half splits",
            "O/U finishing / half-goal intensity / scoring failure",
            "1X2 relative strength",
            "Form Regime",
            "Player Structure",
            "Relative Table Strength",
        ],
        "INDEPENDENT_CONFIRMATION": {
            "1X2": ["UNDERLYING", "MATCH", "FORM", "TABLE"],
            "BTTS": ["UNDERLYING", "MATCH", "FORM"],
            "OU_2_5": ["UNDERLYING", "MATCH", "FORM", "PLAYER"],
        },
        "DIAGNOSTIC": [
            "H2H",
            "Player fragility/concentration",
            "specialist direction/alignment",
        ],
        "specialists_added_to_confirmation_count": False,
        "last5_last6_last10_counted_separately": False,
        "policy": "A signal does not become stronger merely because the same data family appears in core and specialist layers.",
    }


def _build_full_specialists(
    legacy: Any,
    match_data: Any,
    league_data: Any,
    form_data: Any,
    table_data: Any,
    player_data: Any,
    report: Dict[str, Any],
    result: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    match = legacy.mf(match_data)
    home_id, away_id = match.get("home_id"), match.get("away_id")
    existing = report.get("v1_specialist_profiles") or {}
    leakage = _leakage_guard(legacy, match_data)
    double_count = _double_counting_guard()

    try:
        home_team = legacy.team_obj(league_data, home_id)
        away_team = legacy.team_obj(league_data, away_id)
        teams = legacy.league_team_list(league_data)
    except Exception:
        home_team = away_team = None
        teams = []

    form_regime = _form_regime(legacy, form_data, home_id, away_id)
    player_structure = _player_structure(
        legacy,
        player_data,
        home_id,
        away_id,
        existing.get("player_depth") or {},
    )
    h2h = _h2h_diagnostic(legacy, match_data)

    if not home_team or not away_team or not teams:
        return {
            "status": "EINGESCHRÄNKT",
            "reason": "LeagueDaten do not contain both mapped teams; no replacement values are invented.",
            "form_regime": form_regime,
            "player_structure": player_structure,
            "h2h": h2h,
            "leakage_guard": leakage,
            "double_counting_guard": double_count,
        }

    relative_table = _relative_table_strength(legacy, report, teams, home_team, away_team)
    btts = _btts_specialist(
        legacy, teams, home_team, away_team, form_regime, player_structure, existing
    )
    over_under = _over_under_specialist(
        legacy, teams, home_team, away_team, form_regime
    )
    one_x_two = _one_x_two_specialist(
        legacy,
        teams,
        home_team,
        away_team,
        result or {},
        report,
        form_regime,
        relative_table,
        player_structure,
    )
    return {
        "status": "BERECHNET",
        "probability_core": BASELINE,
        "probability_reweighting": False,
        "btts": btts,
        "over_under_2_5": over_under,
        "one_x_two": one_x_two,
        "player_structure": player_structure,
        "form_regime": form_regime,
        "relative_table_strength": relative_table,
        "h2h": h2h,
        "leakage_guard": leakage,
        "double_counting_guard": double_count,
    }


def _family_leader(result: Dict[str, Any], market: str) -> bool:
    probabilities = result.get("probabilities") or {}
    p = _num_obj(probabilities.get(market))
    if p is None:
        return False
    if market in {"home_win", "away_win"}:
        draw = _num_obj(probabilities.get("draw"))
        other = _num_obj(probabilities.get("away_win" if market == "home_win" else "home_win"))
        return draw is not None and other is not None and p >= draw and p >= other
    if market in {"btts_yes", "btts_no"}:
        other = _num_obj(probabilities.get("btts_no" if market == "btts_yes" else "btts_yes"))
        return other is not None and p >= other
    other = _num_obj(probabilities.get("under_2_5" if market == "over_2_5" else "over_2_5"))
    return other is not None and p >= other


def _market_strength(result: Dict[str, Any], market: str) -> float:
    p = _num_obj((result.get("probabilities") or {}).get(market))
    if p is None or not _family_leader(result, market):
        return 0.0
    family_size = 3 if FAMILY_BY_MARKET[market] == "1X2" else 2
    return float(v041_engine._family_strength(p, family_size))


def _underlying_signal(result: Dict[str, Any], market: str, strength: float) -> Dict[str, Any]:
    if _family_leader(result, market):
        return {
            "status": "BESTÄTIGEND",
            "reason": "V0.4.3 Probability Core selects this side within its market family.",
            "value": strength,
        }
    return {
        "status": "GEGENARGUMENT",
        "reason": "V0.4.3 Probability Core does not select this side within its market family.",
        "value": strength,
    }


def _specialist_alignment(full: Dict[str, Any], market: str) -> Dict[str, Any]:
    if market in {"btts_yes", "btts_no"}:
        profile = full.get("btts") or {}
        wanted = "BTTS_YES" if market == "btts_yes" else "BTTS_NO"
    elif market in {"over_2_5", "under_2_5"}:
        profile = full.get("over_under_2_5") or {}
        wanted = "OVER_2_5" if market == "over_2_5" else "UNDER_2_5"
    else:
        profile = full.get("one_x_two") or {}
        wanted = "HOME_WIN" if market == "home_win" else "AWAY_WIN"

    direction = str(profile.get("direction") or "NICHT BEWERTBAR")
    balance = int(profile.get("balance") or 0)
    opposite = OPPOSITE_DIRECTION[wanted]
    applicable_count = int(profile.get("applicable_signal_count") or 0)
    clear_support = direction == wanted and applicable_count >= 2
    clear_contradiction = direction == opposite and applicable_count >= 2
    return {
        "wanted_direction": wanted,
        "specialist_direction": direction,
        "signal_balance": balance,
        "applicable_signal_count": applicable_count,
        "clear_support": clear_support,
        "clear_contradiction": clear_contradiction,
        "confirmation_count_added": 0,
    }


def _classic_evidence(legacy: Any, result: Dict[str, Any], report: Dict[str, Any], market: str) -> Dict[str, Any]:
    return {
        "UNDERLYING": _underlying_signal(result, market, _market_strength(result, market)),
        "MATCH": v041_engine._match_signal(legacy, result, market),
        "FORM": v041_engine._form_signal(report, market),
        "TABLE": v041_engine._table_signal(report, market),
        "PLAYER": v041_engine._player_signal(report, market),
    }


def _coherence(legacy: Any, result: Dict[str, Any]) -> Dict[str, Any]:
    try:
        return legacy._coherence_check(result.get("probabilities") or {})
    except Exception:
        return {"passed": False, "checks": {}}


def _assess_market(
    legacy: Any,
    result: Dict[str, Any],
    report: Dict[str, Any],
    full: Dict[str, Any],
    market: str,
) -> Dict[str, Any]:
    family = FAMILY_BY_MARKET[market]
    probability = _num_obj((result.get("probabilities") or {}).get(market))
    probability_pct = probability * 100.0 if probability is not None else None
    strength = _market_strength(result, market)
    evidence = _classic_evidence(legacy, result, report, market)
    confirmations = [name for name, sig in evidence.items() if (sig or {}).get("status") == "BESTÄTIGEND"]
    counters = [name for name, sig in evidence.items() if (sig or {}).get("status") == "GEGENARGUMENT"]

    sample_security = (result.get("samples") or {}).get("security")
    original_required = 4 if sample_security == "NIEDRIG" else 3
    structural_max = v1_engine.STRUCTURAL_APPLICABLE_BLOCKS[family]
    required = min(original_required, structural_max)
    diagnostics = result.get("diagnostics") or {}
    quality = diagnostics.get("data_quality") or "MITTEL"
    robustness = diagnostics.get("robustness_status") or "NICHT PRÜFBAR"
    coherence = _coherence(legacy, result)
    pre = result.get("pre_match_integrity") or {}
    specialist = _specialist_alignment(full, market)

    reasons: List[str] = []
    if pre.get("strict_pre_match") is False:
        decision = "AUSLASSEN"
        reasons.append("Pre-Match-Integrität nicht bestanden; Zielspiel liegt nicht mehr sicher vor Kickoff.")
    elif strength < 0.20 or len(counters) >= 2:
        decision = "AUSLASSEN"
        if strength < 0.20:
            reasons.append("Marktfamilienstärke liegt unter dem bestehenden Beobachtungsniveau.")
        else:
            reasons.append("Mindestens zwei klassische Gate-Blöcke widersprechen diesem Markt.")
    elif strength < 0.30:
        decision = "BEOBACHTEN"
        reasons.append("Marktfamilienstärke reicht nach dem bestehenden Gate für BEOBACHTEN, nicht für SPIELEN.")
    else:
        blockers: List[str] = []
        if len(confirmations) < required:
            blockers.append(f"nur {len(confirmations)}/{required} strukturell erforderliche klassische Bestätigungen")
        if counters:
            blockers.append("klassisches Gegenargument: " + ", ".join(counters))
        if robustness == "NICHT BESTANDEN":
            blockers.append("Removal-Robustness nicht bestanden")
        if quality == "NIEDRIG":
            blockers.append("Datenqualität niedrig")
        if not coherence.get("passed"):
            blockers.append("Wahrscheinlichkeitskohärenz nicht bestanden")
        decision = "SPIELEN" if not blockers else "BEOBACHTEN"
        reasons.extend(blockers or [f"Gate V1 bestanden: {len(confirmations)}/{required} klassische Bestätigungen ohne harten Blocker."])

    if decision == "SPIELEN" and specialist.get("clear_contradiction"):
        decision = "BEOBACHTEN"
        reasons.append(
            "Der marktbezogene V1-Specialist widerspricht strukturell klar; "
            "die Probability bleibt unverändert, aber die Freigabe wird auf BEOBACHTEN begrenzt."
        )
    elif specialist.get("clear_support"):
        reasons.append(
            "Der V1-Specialist stützt dieselbe Richtung als Robustheitskontext; "
            "er erhöht weder Probability noch Confirmation Count."
        )

    return {
        "key": market,
        "label": MARKET_LABELS[market],
        "family": family,
        "probability_pct": _round(probability_pct, 1),
        "family_strength_pct": _round(strength * 100.0, 1),
        "family_leader": _family_leader(result, market),
        "decision": decision,
        "evidence_blocks": evidence,
        "confirming_blocks": confirmations,
        "counter_blocks": counters,
        "confirming_block_labels": [TECHNICAL_BLOCK_LABELS.get(name, name) for name in confirmations],
        "counter_block_labels": [TECHNICAL_BLOCK_LABELS.get(name, name) for name in counters],
        "required_confirmations": required,
        "original_required_confirmations": original_required,
        "structural_applicable_max": structural_max,
        "specialist_alignment": specialist,
        "reasons": reasons,
        "probability_modified_by_v1": False,
    }


def _market_assessments(
    legacy: Any,
    result: Dict[str, Any],
    report: Dict[str, Any],
    full: Dict[str, Any],
) -> List[Dict[str, Any]]:
    return [_assess_market(legacy, result, report, full, market) for market in MARKETS]


def _select_robust_market(assessments: Sequence[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not assessments:
        return None
    for decision in ("SPIELEN", "BEOBACHTEN", "AUSLASSEN"):
        candidates = [item for item in assessments if item.get("decision") == decision]
        if candidates:
            return max(
                candidates,
                key=lambda item: (
                    _num_obj(item.get("probability_pct")) or -1.0,
                    _num_obj(item.get("family_strength_pct")) or -1.0,
                ),
            )
    return None


def _apply_full_protocol(
    legacy: Any,
    result: Dict[str, Any],
    report: Dict[str, Any],
    base: Dict[str, Any],
) -> Dict[str, Any]:
    out = dict(base)
    if not result.get("ok"):
        out["version"] = "V1 / V0.4.3 FULL-5 Core + Full Specialist Layer"
        return out

    full = report.get("v1_full_specialists") or {}
    assessments = _market_assessments(legacy, result, report, full)
    selected = _select_robust_market(assessments)
    core_top = result.get("strongest_market") or {}
    out["version"] = "V1 / V0.4.3 FULL-5 Core + Gate V1 + Full Multi-Market Specialists"
    out["phase_2_all_six_markets"] = "JA" if len(assessments) == 6 else "NEIN"
    out["market_assessments"] = assessments
    out["full_v1_specialists"] = full
    out["probability_core_lock"] = {
        "baseline": BASELINE,
        "full5_features": v043_engine.FEATURE_COUNT,
        "alpha": v043_release.FULL5_ALPHA,
        "dixon_coles_rho": v042_engine.RHO,
        "probabilities_modified_by_v1": False,
        "new_lambda_core": False,
    }

    if selected:
        out["selected_robust_market"] = {
            "key": selected.get("key"),
            "label": selected.get("label"),
            "family": selected.get("family"),
            "probability_pct": selected.get("probability_pct"),
            "family_strength_pct": selected.get("family_strength_pct"),
            "decision": selected.get("decision"),
        }
        out["core_strongest_market"] = {
            "key": core_top.get("key"),
            "label": core_top.get("label"),
            "probability_pct": core_top.get("probability_pct"),
        }
        differs = selected.get("key") != core_top.get("key")
        out["robust_market_differs_from_core_strongest"] = differs
        out["final_decision"] = selected.get("decision")
        reasons = list(selected.get("reasons") or [])
        if differs:
            reasons.insert(
                0,
                "V1 bevorzugt den robusteren freigegebenen Markt gegenüber dem reinen Core-Topmarkt; "
                "keine Probability wurde verändert.",
            )
        out["decision_reasons"] = reasons
        out["decision_reason_summary"] = reasons[0] if reasons else "Keine zusätzliche Begründung verfügbar."
        out["confirming_blocks"] = list(selected.get("confirming_blocks") or [])
        out["counter_blocks"] = list(selected.get("counter_blocks") or [])
        out["confirming_block_labels"] = list(selected.get("confirming_block_labels") or [])
        out["counter_block_labels"] = list(selected.get("counter_block_labels") or [])
        out["selected_market_family"] = {
            "family": selected.get("family"),
            "key": selected.get("key"),
            "strength": (_num_obj(selected.get("family_strength_pct")) or 0.0) / 100.0,
        }
    return out


def _install_full_v1_ui(legacy: Any) -> None:
    html = legacy.INDEX_HTML
    js_anchor = "    const strongest=data.strongest_market||{};"
    if js_anchor not in html:
        raise RuntimeError("Full V1 UI JS anchor not found.")

    js_extra = r"""
    const v1Markets=Array.isArray(protocol.market_assessments)?protocol.market_assessments:[];
    const v1Selected=protocol.selected_robust_market||{};
    const v1Specs=protocol.full_v1_specialists||{};
    const v1MarketGrid=v1Markets.map(function(m){
      return '<div class="m"><div class="s">'+escapeHtml(m.label||m.key||'—')+'</div>'+ 
             '<div class="b">'+escapeHtml(m.probability_pct==null?'—':m.probability_pct+' %')+'</div>'+ 
             '<div class="s">'+escapeHtml(m.decision||'—')+' · '+escapeHtml((m.confirming_blocks||[]).length+'/'+(m.required_confirmations||'—'))+' Best.</div></div>';
    }).join('');
    const v1BTTS=(v1Specs.btts||{}).direction||'—';
    const v1OU=(v1Specs.over_under_2_5||{}).direction||'—';
    const v11X2=(v1Specs.one_x_two||{}).direction||'—';
    const v1Player=(v1Specs.player_structure||{}).depth_status||'—';
    const v1Leak=((v1Specs.leakage_guard||{}).status)||'—';
    const v1Double=((v1Specs.double_counting_guard||{}).status)||'—';
    const v1FullCard='<div class="c"><h3>V1 Multi-Market & Specialists</h3>'+ 
      '<div class="g">'+
      '<div class="m"><div class="s">V1 robuste Wahl</div><div class="b">'+escapeHtml(v1Selected.label||'—')+'</div><div class="s">'+escapeHtml(v1Selected.decision||'—')+' · '+escapeHtml(v1Selected.probability_pct==null?'—':v1Selected.probability_pct+' %')+'</div></div>'+ 
      '<div class="m"><div class="s">BTTS Specialist</div><div class="b">'+escapeHtml(v1BTTS)+'</div></div>'+ 
      '<div class="m"><div class="s">O/U Specialist</div><div class="b">'+escapeHtml(v1OU)+'</div></div>'+ 
      '<div class="m"><div class="s">1X2 Specialist</div><div class="b">'+escapeHtml(v11X2)+'</div></div>'+ 
      '<div class="m"><div class="s">Player Structure</div><div class="b">'+escapeHtml(v1Player)+'</div></div>'+ 
      '<div class="m"><div class="s">Guards</div><div class="b">Leakage '+escapeHtml(v1Leak)+' · Double Count '+escapeHtml(v1Double)+'</div></div>'+ 
      '</div><h3>Alle sechs Märkte</h3><div class="g">'+v1MarketGrid+'</div></div>';
"""
    html = html.replace(js_anchor, js_anchor + js_extra, 1)
    card_anchor = "      observeCard+\n"
    if card_anchor not in html:
        raise RuntimeError("Full V1 UI card anchor not found.")
    html = html.replace(card_anchor, "      v1FullCard+\n" + card_anchor, 1)
    # The legacy short card remains visible, but label it explicitly as the
    # frozen probability-core top market so it cannot be confused with the V1
    # robust selection shown above.
    html = html.replace('<div class="s">Bester Markt</div>', '<div class="s">Core-Topmarkt</div>', 1)
    # The BEOBACHTEN lead should describe the robust V1 selection when one is
    # available, not blindly repeat the raw core top market.
    html = html.replace('(strongest.label&&strongest.probability_pct!=null)', '(v1Selected.label&&v1Selected.probability_pct!=null)', 1)
    html = html.replace("? strongest.label+' liegt bei '+strongest.probability_pct+' %, ist aber", "? v1Selected.label+' liegt bei '+v1Selected.probability_pct+' %, ist aber", 1)
    legacy.INDEX_HTML = html


def apply_patch(legacy: Any) -> Any:
    """Install the final V1 layer on top of the frozen V0.4.3 + Gate V1 path."""
    app = v1_engine.apply_patch(legacy)
    base_supplemental = legacy.supplemental_report
    base_protocol = legacy.elite_protocol_report

    def supplemental_full(
        match_data: Any,
        league_data: Any = None,
        form_data: Any = None,
        table_data: Any = None,
        player_data: Any = None,
    ) -> Dict[str, Any]:
        report = dict(base_supplemental(match_data, league_data, form_data, table_data, player_data))
        report["v1_full_specialists"] = _build_full_specialists(
            legacy,
            match_data,
            league_data,
            form_data,
            table_data,
            player_data,
            report,
        )
        report["v1_final_policy"] = {
            "all_specialists_active": True,
            "all_six_markets_assessed": True,
            "probability_reweighting": False,
            "new_lambda_core": False,
            "new_shortcut_required": False,
            "five_files_only": True,
        }
        return report

    def protocol_full(result: Dict[str, Any], report: Dict[str, Any]) -> Dict[str, Any]:
        # Rebuild result-dependent relative-strength details without touching probabilities.
        full = dict(report.get("v1_full_specialists") or {})
        if result.get("ok"):
            try:
                if "one_x_two" in full:
                    rel = dict(full.get("one_x_two") or {})
                    rel.setdefault("reliability", {})
                    rel["reliability"]["sample_security"] = (result.get("samples") or {}).get("security")
                    full["one_x_two"] = rel
            except Exception:
                pass
        report = dict(report)
        report["v1_full_specialists"] = full
        base = base_protocol(result, report)
        return _apply_full_protocol(legacy, result, report, base)

    legacy.supplemental_report = supplemental_full
    legacy.elite_protocol_report = protocol_full

    legacy.app.router.routes = [
        route for route in legacy.app.router.routes if getattr(route, "path", None) != "/api/health"
    ]

    def health() -> Dict[str, Any]:
        return {
            "ok": True,
            "version": VERSION,
            "engine": "v1-v043-full5-full-multimarket-specialists",
            "baseline": BASELINE,
            "v043_probability_core_locked": True,
            "full5_features": v043_engine.FEATURE_COUNT,
            "alpha": v043_release.FULL5_ALPHA,
            "rho": v042_engine.RHO,
            "gate_v1": True,
            "all_six_markets": list(MARKETS),
            "specialists": {
                "btts": True,
                "over_under_2_5": True,
                "one_x_two": True,
                "player_structure": True,
                "form_regime": True,
                "relative_table_strength": True,
                "h2h_diagnostics": True,
                "leakage_guard": True,
                "double_counting_guard": True,
            },
            "specialist_probability_weights": False,
            "probabilities_modified_by_v1": False,
            "new_lambda_core": False,
            "five_source_only": True,
            "new_shortcut_required": False,
            "player_detail_required": False,
            "production": True,
        }

    legacy.app.add_api_route("/api/health", health, methods=["GET"])
    legacy.app.version = VERSION
    legacy.app.title = "FootyStats V1 — V0.4.3 FULL-5 + Gate V1 + Full Specialists"
    _install_full_v1_ui(legacy)
    return app
