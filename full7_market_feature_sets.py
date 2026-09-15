from __future__ import annotations

from typing import Dict, Iterable, List, Mapping, Sequence


MARKET_FAMILIES = ("1X2", "BTTS", "TOTALS")

PLAYER_TOKENS = (
    "players_found", "active_players", "active_player_share", "active_minutes",
    "player_minutes", "goals_per90_minutes_weighted", "assists_per90_minutes_weighted",
    "involvement_per90_minutes_weighted", "goal_share", "involvement_share",
    "goalkeeper_", "defender_", "midfielder_", "forward_",
)

HALF_TOKENS = (
    "seasonbttspercentageht", "seasoncspercentageht", "seasonftspercentageht",
    "scoredavght", "concededavght", "avght", "_2hg", "2hg_",
)

GOAL_PATTERN_TOKENS = (
    "seasonbttspercentage", "seasonover25percentage",
    "seasoncspercentage", "seasonftspercentage",
    "btts_2hg_percentage", "fts_2hg_percentage",
)

SCORING_TOKENS = (
    "seasonscoredavg", "seasonconcededavg", "scoredavg", "concededavg",
    "scored_2hg", "conceded_2hg", "goal_difference",
)

STRENGTH_TOKENS = ("seasonppg", "rank_pct", "rank_percentile", "prematch_ppg")
SHOT_TOKENS = ("shotsavg", "shotsontargetavg", "shotsofftargetavg")
XG_TOKENS = ("xg_for_avg", "xg_against_avg", "prematch_xg")


def _has(low: str, tokens: Sequence[str]) -> bool:
    return any(token in low for token in tokens)


def domain_family(name: str) -> str:
    low = name.lower()
    if "odds" in low:
        return "BLOCKED_ODDS"
    if low.startswith("provider_"):
        return "PROVIDER_DERIVED"
    if low.startswith("h2h_"):
        return "H2H"
    if "secondary_affiliation" in low or "ambiguous_team_change" in low:
        return "DATA_QUALITY"
    if "corner" in low or "possession" in low:
        return "AUXILIARY"
    if _has(low, PLAYER_TOKENS):
        return "PLAYER"
    if _has(low, HALF_TOKENS):
        return "HALF"
    if _has(low, XG_TOKENS):
        return "XG"
    if _has(low, SHOT_TOKENS):
        return "SHOTS"
    if _has(low, GOAL_PATTERN_TOKENS):
        return "GOAL_PATTERN"
    if _has(low, SCORING_TOKENS):
        return "SCORING_DEFENCE"
    if _has(low, STRENGTH_TOKENS):
        return "STRENGTH"
    if low.startswith("table_") or "_table_" in low:
        return "TABLE"
    if "form_" in low or "last5_" in low:
        return "FORM"
    if low.startswith("league_derived_") or low.startswith("league_"):
        return "LEAGUE_CONTEXT"
    if low.startswith("prematch_"):
        return "MATCH_CONTEXT"
    return "OTHER"


def structural_status(name: str) -> str:
    low = name.lower()
    family = domain_family(name)
    if family == "BLOCKED_ODDS":
        return "BLOCKED"
    if family in {"PROVIDER_DERIVED", "H2H", "AUXILIARY"}:
        return "RESEARCH_ONLY"
    if family == "DATA_QUALITY":
        return "QUALITY_ONLY"
    if "under25percentage" in low:
        return "REDUNDANT_COMPLEMENT"
    if ("last6_" in low or "last10_" in low) and "delta" not in low:
        return "REDUNDANT_NESTED_WINDOW"
    if (low.startswith("table_") or "_table_" in low) and (
        "_points" in low or "_position" in low
    ):
        return "REDUNDANT_TABLE_RAW"
    return "ELIGIBLE"


ALLOWED = {
    "1X2": {
        "XG", "SCORING_DEFENCE", "SHOTS", "STRENGTH", "TABLE", "PLAYER",
        "FORM", "LEAGUE_CONTEXT", "MATCH_CONTEXT", "GOAL_PATTERN", "HALF",
    },
    "BTTS": {
        "XG", "SCORING_DEFENCE", "SHOTS", "GOAL_PATTERN", "HALF", "PLAYER",
        "FORM", "LEAGUE_CONTEXT", "MATCH_CONTEXT", "STRENGTH",
    },
    "TOTALS": {
        "XG", "SCORING_DEFENCE", "SHOTS", "GOAL_PATTERN", "HALF", "PLAYER",
        "FORM", "LEAGUE_CONTEXT", "MATCH_CONTEXT",
    },
}


def build_market_feature_sets(core_features: Iterable[str]) -> Dict[str, object]:
    unique = sorted(set(core_features))
    market_sets: Dict[str, List[str]] = {}
    family_counts: Dict[str, Dict[str, int]] = {}

    for market in MARKET_FAMILIES:
        names: List[str] = []
        counts: Dict[str, int] = {}
        for name in unique:
            if structural_status(name) != "ELIGIBLE":
                continue
            family = domain_family(name)
            if family not in ALLOWED[market]:
                continue
            names.append(name)
            counts[family] = counts.get(family, 0) + 1
        market_sets[market] = names
        family_counts[market] = dict(sorted(counts.items()))

    return {
        "market_feature_set_version": "FULL7_MARKET_FEATURE_SETS_0.2",
        "markets": market_sets,
        "feature_counts": {k: len(v) for k, v in market_sets.items()},
        "family_counts": family_counts,
        "policy": {
            "outcome_blind": True,
            "odds": "blocked",
            "provider_potentials": "research-only",
            "h2h": "secondary/research-only",
            "nested_form_windows": "Last6/10 direct windows removed; deltas remain eligible",
            "under25": "exact percentage complement removed; direction derived from Over2.5",
            "auxiliary": "corners/possession excluded from first market specialists",
            "many_factors": True,
            "independence": "feature multiplicity never equals evidence-vote multiplicity",
        },
    }
