from __future__ import annotations

from typing import Dict, Iterable, List, Sequence

MARKET_FAMILIES = ("1X2", "BTTS", "TOTALS")

PLAYER_TOKENS = (
    "players_found", "active_players", "active_player_share", "active_minutes",
    "player_minutes", "goals_per90_minutes_weighted", "assists_per90_minutes_weighted",
    "involvement_per90_minutes_weighted", "goal_share", "assist_share",
    "involvement_share", "goalkeeper_", "defender_", "midfielder_", "forward_",
)
HALF_TOKENS = (
    "seasonbttspercentageht", "seasoncspercentageht", "seasonftspercentageht",
    "scoredavght", "concededavght", "avght", "_2hg", "2hg_",
)
GOAL_PATTERN_TOKENS = (
    "seasonbttspercentage", "seasonover25percentage", "seasonunder25percentage",
    "seasoncspercentage", "seasonftspercentage", "clean_sheet", "failed_to_score",
    "btts_2hg_percentage", "fts_2hg_percentage",
)
SCORING_TOKENS = (
    "seasonscoredavg", "seasonconcededavg", "scoredavg", "concededavg",
    "scored_2hg", "conceded_2hg", "goal_difference",
)
STRENGTH_TOKENS = ("seasonppg", "rank_pct", "rank_percentile", "prematch_ppg")
SHOT_TOKENS = ("shotsavg", "shotsontargetavg", "shotsofftargetavg", "conversion")
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
    if low.startswith("referee_"):
        return "REFEREE"
    if "manager_" in low:
        return "MANAGER"
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
    if "form_" in low or "last5_" in low or "last6_" in low or "last10_" in low:
        return "FORM"
    if low.startswith("league_derived_") or low.startswith("league_"):
        return "LEAGUE_CONTEXT"
    if low.startswith("prematch_"):
        return "MATCH_CONTEXT"
    return "OTHER"


def structural_status(name: str) -> str:
    """Outcome-blind technical eligibility only.

    This function intentionally does NOT exclude a football domain by target market.
    Market-specific usefulness is learned/validated OOS rather than hard-coded.
    """
    low = name.lower()
    family = domain_family(name)
    if family == "BLOCKED_ODDS":
        return "BLOCKED"
    if family == "PROVIDER_DERIVED":
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
    # H2H and auxiliary context remain available to the architecture. They are not
    # auto-promoted by this function; OOS/ablation decides whether they enter an ML
    # artifact. Referee/Manager are eligible when strict data exists.
    return "ELIGIBLE"


def build_market_feature_sets(core_features: Iterable[str]) -> Dict[str, object]:
    """Build one common broad technical feature universe for all three target systems.

    The architecture has three model target families but seven output markets.
    We do not hard-code domain exclusions such as "table cannot inform totals".
    Every technically eligible core feature is offered to each target family;
    learned model behavior and OOS ablation decide its incremental value.
    """
    unique = sorted(set(core_features))
    eligible = [name for name in unique if structural_status(name) == "ELIGIBLE"]

    market_sets: Dict[str, List[str]] = {
        market: list(eligible) for market in MARKET_FAMILIES
    }
    family_counts: Dict[str, Dict[str, int]] = {}
    for market, names in market_sets.items():
        counts: Dict[str, int] = {}
        for name in names:
            family = domain_family(name)
            counts[family] = counts.get(family, 0) + 1
        family_counts[market] = dict(sorted(counts.items()))

    return {
        "market_feature_set_version": "FULL7_MARKET_FEATURE_SETS_1.0",
        "markets": market_sets,
        "feature_counts": {k: len(v) for k, v in market_sets.items()},
        "family_counts": family_counts,
        "policy": {
            "outcome_blind": True,
            "same_broad_core_for_all_target_families": True,
            "hard_market_domain_exclusions": False,
            "odds": "blocked",
            "provider_potentials": "research-only until forward-OOS ablation",
            "h2h": "architecturally available; promotion to trained ML requires incremental OOS evidence",
            "referee_manager": "eligible when strict historical data exists; never fabricated/backfilled",
            "nested_form_windows": "direct overlapping Last6/10 may be redundancy-reduced; form deltas remain",
            "under25": "exact percentage complement may be represented once without losing direction",
            "many_factors": True,
            "independence": "feature multiplicity never equals evidence-vote multiplicity",
        },
    }
