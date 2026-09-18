"""Strict pre-match validator for each historical target match."""
from __future__ import annotations
from typing import Any

POSTMATCH_FORBIDDEN = {
    "homeGoalCount", "awayGoalCount", "overallGoalCount", "totalGoalCount",
    "homeGoals", "awayGoals", "homeGoals_timings", "awayGoals_timings",
    "HTGoalCount", "ht_goals_team_a", "ht_goals_team_b",
    "winningTeam", "attendance", "team_a_shots", "team_b_shots",
    "team_a_possession", "team_b_possession", "totalCornerCount",
    "actual_1x2", "actual_btts", "actual_over25", "hit_ou", "hit_btts",
}


def _to_int(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def validate_match_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    reasons: list[str] = []
    kick = bundle.get("kickoff_unix")
    mt = bundle.get("requested_max_time")
    if kick is None or mt is None:
        reasons.append("missing_kick_or_max_time")
    elif mt != kick - 1:
        reasons.append(f"max_time_not_kickoff_minus_1 ({mt} vs {kick-1})")

    match = bundle.get("match") or {}
    ident = match.get("identity") or {}
    pre = match.get("prematch_optional") or {}
    if not match.get("found"):
        reasons.append("target_missing")
    if match.get("stored_postmatch"):
        reasons.append("stored_postmatch_flag")
    leak = sorted(k for k in {**ident, **pre} if k in POSTMATCH_FORBIDDEN)
    if leak:
        reasons.append("match_postmatch_fields:" + ",".join(leak))

    form = bundle.get("form") or {}
    for side in ("home", "away"):
        block = form.get(side) or {}
        src = block.get("source_matches") or []
        if block.get("source_ok") is False:
            reasons.append(f"form_{side}_source_ok_false")
        for row in src:
            if _to_int(row.get("match_id")) == _to_int(bundle.get("match_id")):
                reasons.append(f"form_{side}_contains_target")
                break
            ts = _to_int(row.get("date_unix"))
            if ts is not None and kick is not None and ts >= kick:
                reasons.append(f"form_{side}_future_or_same_kick")
                break
        max_ts = _to_int(block.get("max_source_match_timestamp"))
        if max_ts is not None and kick is not None and max_ts >= kick:
            reasons.append(f"form_{side}_max_ts_not_before_kick")

    league = (bundle.get("league") or {}).get("league_aggregates_derived") or {}
    lmax = _to_int(league.get("league_source_max_timestamp"))
    if lmax is not None and kick is not None and lmax >= kick:
        reasons.append("league_source_not_before_kick")
    ids = {_to_int(x) for x in (league.get("league_source_match_ids") or [])}
    if _to_int(bundle.get("match_id")) in ids:
        reasons.append("league_source_contains_target")
    source_n = _to_int(league.get("league_source_count"))
    expected_n = _to_int(bundle.get("league_expected_matches_completed"))
    if source_n is not None and expected_n is not None and source_n != expected_n:
        reasons.append(f"league_source_count_mismatch:{source_n}!={expected_n}")

    pag = (bundle.get("player") or {}).get("pagination") or {}
    if not pag.get("pagination_complete"):
        reasons.append("player_pagination_incomplete")
    else:
        total = _to_int(pag.get("total_results"))
        rows = _to_int(pag.get("loaded_rows"))
        max_page = _to_int(pag.get("max_page"))
        loaded_pages = _to_int(pag.get("loaded_pages"))
        if total not in (None, 0) and rows != total:
            reasons.append("player_row_count_mismatch")
        if max_page not in (None, 0) and loaded_pages != max_page:
            reasons.append("player_page_count_mismatch")

    if bundle.get("result_in_features"):
        reasons.append("result_merged_into_features")
    if bundle.get("odds_used_as_feature"):
        reasons.append("odds_used_as_feature")
    if bundle.get("table_team_consistent") is False:
        reasons.append("table_team_mismatch")

    return {
        "strict_prematch": not reasons,
        "reason_if_false": None if not reasons else reasons,
    }
