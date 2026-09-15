from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from typing import Any, Dict, Iterable, List, Optional, Tuple

SOURCES = ("match", "league", "form", "table", "player", "referee", "manager")

STATUSES = {
    "ENTITY_KEY",
    "TARGET_ONLY",
    "POST_MATCH_BLOCKED",
    "ODDS_BLOCKED",
    "TEXT_BLOCKED",
    "QUALITY_SIGNAL",
    "PROVIDER_DERIVED",
    "CANDIDATE_DIRECT",
    "CANDIDATE_DERIVED",
    "REDUNDANCY_CHECK_REQUIRED",
    "REVIEW_REQUIRED",
    "METADATA_ONLY",
}

FAMILIES = {
    "expected_goals_xga",
    "goals_defence",
    "venue",
    "form",
    "league_context",
    "table_strength",
    "shots_chance_creation",
    "first_second_half",
    "btts_ou_profile",
    "player_depth",
    "player_quality",
    "player_concentration",
    "h2h",
    "referee",
    "manager",
    "data_quality",
}

TARGET_KEYS = {
    "winningTeam", "homeGoalCount", "awayGoalCount", "totalGoalCount",
    "HTGoalCount", "GoalCount_2hg", "overallGoalCount",
}

MATCH_ACTUAL_KEYS = {
    "team_a_xg", "team_b_xg", "total_xg", "team_a_possession", "team_b_possession",
    "team_a_shots", "team_b_shots", "team_a_shotsOnTarget", "team_b_shotsOnTarget",
    "team_a_shotsOffTarget", "team_b_shotsOffTarget", "team_a_corners", "team_b_corners",
    "totalCornerCount", "team_a_fouls", "team_b_fouls", "team_a_offsides", "team_b_offsides",
    "team_a_yellow_cards", "team_b_yellow_cards", "team_a_red_cards", "team_b_red_cards",
    "team_a_attacks", "team_b_attacks", "team_a_dangerous_attacks", "team_b_dangerous_attacks",
    "corner_fh_count", "corner_2h_count", "total_fh_cards", "total_2h_cards",
    "team_a_goal_details", "team_b_goal_details", "homeGoals", "awayGoals",
    "homeGoals_timings", "awayGoals_timings", "team_a_card_details", "team_b_card_details",
}

MATCH_IDENTITY_KEYS = {
    "id", "homeID", "awayID", "competition_id", "date_unix", "season",
    "home_name", "away_name", "roundID", "game_week", "revised_game_week",
    "match_url", "status", "refereeID", "coach_a_ID", "coach_b_ID",
}

TEXT_KEYS = {"gpt_en", "gpt_int", "trends", "tv_stations", "message", "request_reset_message"}

@dataclass(frozen=True)
class RegistryEntry:
    source: str
    path: str
    key: str
    status: str
    family: Optional[str]
    exposure_path: Optional[str]
    split: Optional[str]
    redundancy_group: Optional[str]
    sentinel_policy: str
    zero_policy: str
    temporal_policy: str
    reason: str
    sample_value_type: str


def _key(path: str) -> str:
    return path.rsplit(".", 1)[-1].replace("[]", "")


def _split(key: str) -> Optional[str]:
    low = key.lower()
    for suffix in ("_overall", "_home", "_away"):
        if low.endswith(suffix):
            return suffix[1:]
    if "_overall_" in low: return "overall"
    if "_home_" in low: return "home"
    if "_away_" in low: return "away"
    return None


def _is_meta(path: str) -> bool:
    low = path.lower()
    return low.startswith("_footystats_meta.") or ".metadata." in low or ".pager." in low or low.startswith("payload.metadata.")


def _is_odds(path: str, key: str) -> bool:
    low = path.lower()
    return key.lower().startswith("odds_") or "odds_comparison" in low


def _is_text(path: str, key: str) -> bool:
    low = path.lower()
    return key in TEXT_KEYS or ".trends" in low or ".tv_stations" in low or "official_sites" in low or key in {"url", "image", "flag_element"}


def _is_h2h(path: str) -> bool:
    return ".h2h" in path.lower() or path.lower().startswith("h2h")


def _family(source: str, path: str, key: str) -> Optional[str]:
    kl = key.lower()
    if source == "referee": return "referee"
    if source == "manager": return "manager"
    if _is_h2h(path): return "h2h"
    if source == "form": return "form"
    if source == "table": return "table_strength"
    if source == "player":
        if any(t in kl for t in ("minutes", "appearances", "min_per_match", "position")): return "player_depth"
        if any(t in kl for t in ("rank_in_club_top", "goals_overall", "assists_overall", "goals_home", "goals_away", "assists_home", "assists_away")): return "player_concentration"
        return "player_quality"
    if any(t in kl for t in ("xg_for", "xg_against", "xg_prematch", "total_xg_prematch")): return "expected_goals_xga"
    if any(t in kl for t in ("shot", "conversion")): return "shots_chance_creation"
    if any(t in kl for t in ("btts", "seasonover25", "seasonunder25", "seasoncs", "seasonfts", "clean_sheet", "failed_to_score")): return "btts_ou_profile"
    if any(t in kl for t in ("fhg", "ht", "2hg", "2h_", "first_half", "second_half")): return "first_second_half"
    if any(t in kl for t in ("scoredavg", "concededavg", "seasongoals", "seasonconceded", "goaldifference", "goals_per_match")): return "goals_defence"
    if any(t in kl for t in ("seasonppg", "pre_match_home_ppg", "pre_match_away_ppg", "winpercentage")): return "venue"
    if source == "league": return "league_context"
    if source == "match": return "league_context"
    return None


def _exposure_path(source: str, path: str, key: str, split: Optional[str]) -> Optional[str]:
    base = path.rsplit(".", 1)[0] if "." in path else ""
    if source in {"league", "form"} and ".stats." in path and split:
        return f"{base}.seasonMatchesPlayed_{split}"
    if source == "form" and ".data[]." in path:
        record_base = path.split(".stats.", 1)[0] if ".stats." in path else base
        return f"{record_base}.last_x_match_num"
    if source == "table" and "[]" in path:
        return f"{base}.matchesPlayed"
    if source == "player":
        if split in {"home", "away"}:
            return f"{base}.minutes_played_{split}"
        return f"{base}.minutes_played_overall"
    if source in {"referee", "manager"}:
        if split in {"home", "away"}:
            return f"{base}.appearances_{split}"
        return f"{base}.appearances_overall"
    return None


def _sentinel_policy(source: str, key: str, path: str) -> Tuple[str, str]:
    kl = key.lower()
    if key == "winningTeam":
        return "-1_IS_DRAW_TARGET; do not convert globally", "0 is a valid team/result code if documented"
    if key in {"club_team_2_id"}:
        return "-1_MEANS_NO_SECOND_CLUB", "0 is not assumed missing"
    if key in {"coach_a_ID", "coach_b_ID", "refereeID"}:
        return "negative_or_null_means_unassigned/unknown; do not infer identity", "0 is not assumed a valid ID"
    if kl.startswith("rank_in_"):
        return "-1_MEANS_UNRANKED/UNAVAILABLE; never treat as strongest rank", "0 is not treated as rank without explicit docs"
    if key in MATCH_ACTUAL_KEYS:
        return "pre-match -1/null/empty are placeholders; field is blocked anyway", "0 may be an actual post-match value; field is blocked"
    if source in {"league", "form", "table", "player", "referee", "manager"}:
        return "no global sentinel conversion; apply field-specific rule only after docs/sample validation", "0 is valid only with positive exposure; with zero exposure classify NO_EXPOSURE"
    return "no global sentinel conversion", "0 is not automatically missing"


def _redundancy_group(source: str, path: str, key: str, family: Optional[str], split: Optional[str]) -> Optional[str]:
    kl = key.lower()
    normalized = kl
    normalized = re.sub(r"(_percentage|percentage|_num|num|_total|total|_avg|avg|_per_match|permatch)", "", normalized)
    normalized = re.sub(r"_(overall|home|away)$", "", normalized)
    normalized = re.sub(r"\d+", "#", normalized)
    if family in {"btts_ou_profile", "first_second_half", "shots_chance_creation", "goals_defence", "referee", "manager"}:
        return f"{source}:{family}:{normalized}:{split or 'na'}"
    if source in {"league", "form", "table", "player"} and any(t in kl for t in ("percentage", "num", "avg", "total", "per_90", "per_match")):
        return f"{source}:{family or 'misc'}:{normalized}:{split or 'na'}"
    return None


def classify(source: str, path: str, value: Any) -> RegistryEntry:
    if source not in SOURCES:
        raise ValueError(f"unknown source: {source}")
    key = _key(path); split = _split(key); family = _family(source, path, key)
    exposure = _exposure_path(source, path, key, split)
    sentinel, zero = _sentinel_policy(source, key, path)
    redundancy = _redundancy_group(source, path, key, family, split)
    temporal = "must be known before kickoff; source snapshot must pass Silver temporal validation"

    if _is_meta(path):
        status, family, exposure, redundancy = "METADATA_ONLY", None, None, None
        reason = "API lineage/request/pagination metadata; never a predictive feature"
    elif key in TARGET_KEYS:
        status, family, exposure, redundancy = "TARGET_ONLY", None, None, None
        reason = "Outcome label only; prohibited from pre-match features"
    elif source == "match" and key in MATCH_ACTUAL_KEYS:
        status, family, exposure, redundancy = "POST_MATCH_BLOCKED", None, None, None
        reason = "Actual/live match measurement; prohibited from pre-match features"
    elif _is_odds(path, key):
        status, family, exposure, redundancy = "ODDS_BLOCKED", None, None, None
        reason = "Probability mode excludes market odds and bookmaker-derived information"
    elif _is_text(path, key):
        status, exposure, redundancy = "TEXT_BLOCKED", None, None
        reason = "Narrative/URL/media/provider text is not admitted to numerical prediction"
    elif source == "match" and key in MATCH_IDENTITY_KEYS:
        status, family, exposure, redundancy = "ENTITY_KEY", None, None, None
        reason = "Identity/join/lineage only"
    elif key in {"id", "competition_id", "club_team_id", "club_team_2_id", "team_a_id", "team_b_id"}:
        status, family, exposure, redundancy = "ENTITY_KEY", None, None, None
        reason = "Entity key for deterministic joins only"
    elif key in {"last_match_timestamp", "last_updated_match_timestamp", "last_x_match_num", "matches_completed_minimum"} or "recorded_matches" in key.lower() or "recorded_matches" in path.lower():
        status, family = "QUALITY_SIGNAL", "data_quality"
        reason = "Exposure/freshness/coverage field; used to qualify another signal, not as a standalone football edge"
    elif "potential" in key.lower():
        status = "PROVIDER_DERIVED"
        reason = "Provider-derived aggregate; requires isolated OOS ablation before model activation"
    elif source == "table" and key in {"seasonWins", "seasonWins_home", "seasonWins_away", "seasonWins_overall", "seasonDraws", "seasonDraws_home", "seasonDraws_away", "seasonDraws_overall", "seasonLosses_home", "seasonLosses_away", "seasonLosses_overall", "seasonGoals", "seasonGoals_home", "seasonGoals_away", "seasonConceded", "seasonConceded_home", "seasonConceded_away"}:
        status = "REDUNDANCY_CHECK_REQUIRED"
        reason = "Table result totals overlap strongly with League team-season stats; use mainly for cross-check or derived relative table features"
    elif source == "player" and key in {"age", "birthday", "height", "weight", "nationality", "continent", "full_name", "first_name", "last_name", "known_as", "shorthand", "league", "league_type", "season", "starting_year", "ending_year"}:
        status, family, exposure, redundancy = "REVIEW_REQUIRED", None, None, None
        reason = "Biographical/label field; blocked unless a specific derived football hypothesis is defined and validated"
    elif source in {"referee", "manager"} and key in {"age", "birthday", "nationality", "continent", "full_name", "first_name", "last_name", "known_as", "shorthand", "league", "league_type", "season", "starting_year", "ending_year"}:
        status, family, exposure, redundancy = "REVIEW_REQUIRED", None, None, None
        reason = "Identity/biographical field; not a direct predictive statistic"
    elif family in FAMILIES:
        if source in {"referee", "manager", "player", "table"}:
            status = "CANDIDATE_DERIVED"
            reason = "Use only through exposure-aware/shrunk/relative derived feature; raw value is not admitted directly"
        elif source in {"league", "form"} and (redundancy is not None or split is not None):
            status = "CANDIDATE_DERIVED"
            reason = "Team/form statistic requires split-aware exposure, normalization and redundancy control"
        elif source == "match":
            status = "CANDIDATE_DIRECT"
            reason = "Pre-match match-level statistic; still requires coverage and OOS validation"
        else:
            status = "CANDIDATE_DERIVED"
            reason = "Potential model input after semantic and OOS validation"
    else:
        status = "REVIEW_REQUIRED"
        reason = "No approved semantic rule yet; blocked by default"

    return RegistryEntry(
        source=source, path=path, key=key, status=status, family=family,
        exposure_path=exposure, split=split, redundancy_group=redundancy,
        sentinel_policy=sentinel, zero_policy=zero, temporal_policy=temporal,
        reason=reason, sample_value_type=type(value).__name__,
    )


def leaves(value: Any, prefix: str = "") -> Iterable[Tuple[str, Any]]:
    if isinstance(value, dict):
        for k, v in value.items():
            yield from leaves(v, f"{prefix}.{k}" if prefix else str(k))
    elif isinstance(value, list):
        p = f"{prefix}[]" if prefix else "[]"
        if not value:
            yield p, []
        else:
            for v in value:
                if isinstance(v, (dict, list)):
                    yield from leaves(v, p)
                else:
                    yield p, v
    else:
        yield prefix, value


def build_registry(namespaces: Dict[str, Any]) -> Dict[str, Any]:
    rows: List[RegistryEntry] = []
    for source in SOURCES:
        seen: Dict[str, RegistryEntry] = {}
        for path, value in leaves(namespaces.get(source)):
            if path not in seen:
                seen[path] = classify(source, path, value)
        rows.extend(seen.values())

    status_counts: Dict[str, int] = {}
    family_counts: Dict[str, int] = {}
    source_counts: Dict[str, int] = {}
    redundancy_counts: Dict[str, int] = {}
    for row in rows:
        status_counts[row.status] = status_counts.get(row.status, 0) + 1
        source_counts[row.source] = source_counts.get(row.source, 0) + 1
        if row.family:
            family_counts[row.family] = family_counts.get(row.family, 0) + 1
        if row.redundancy_group:
            redundancy_counts[row.redundancy_group] = redundancy_counts.get(row.redundancy_group, 0) + 1

    review_required = sum(1 for r in rows if r.status == "REVIEW_REQUIRED")
    model_candidates = sum(1 for r in rows if r.status in {"CANDIDATE_DIRECT", "CANDIDATE_DERIVED", "PROVIDER_DERIVED", "REDUNDANCY_CHECK_REQUIRED"})
    blocked = sum(1 for r in rows if r.status in {"TARGET_ONLY", "POST_MATCH_BLOCKED", "ODDS_BLOCKED", "TEXT_BLOCKED", "METADATA_ONLY"})

    return {
        "registry_version": "0.2.0",
        "field_count": len(rows),
        "status_counts": status_counts,
        "family_counts": family_counts,
        "source_counts": source_counts,
        "redundancy_group_count": len(redundancy_counts),
        "redundancy_groups_with_multiple_fields": sum(1 for c in redundancy_counts.values() if c > 1),
        "review_required_count": review_required,
        "model_candidate_count": model_candidates,
        "blocked_or_nonpredictive_count": blocked,
        "activation_policy": "Only fields promoted to USED_DIRECT/USED_DERIVED after coverage, leakage, redundancy and temporal OOS tests may enter models.",
        "evidence_policy": "Multiple fields in one redundancy group can inform a derived feature but count as at most one independent evidence family vote.",
        "rows": [asdict(r) for r in rows],
    }
