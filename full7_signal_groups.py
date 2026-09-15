from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, Iterable, List, Optional, Set

ALL_MARKETS = (
    "home_win", "draw", "away_win",
    "btts_yes", "btts_no", "over_2_5", "under_2_5",
)

GROUP_META: Dict[str, Dict[str, Any]] = {
    "EXPECTED_GOALS_XGA": {
        "cluster": "underlying_performance",
        "role": "CORE_CANDIDATE",
        "evidence_eligible": True,
        "markets": ALL_MARKETS,
    },
    "GOALS_DEFENCE": {
        "cluster": "scoring_defence",
        "role": "CORE_CANDIDATE",
        "evidence_eligible": True,
        "markets": ALL_MARKETS,
    },
    "VENUE_STRENGTH": {
        "cluster": "venue_strength",
        "role": "CORE_CANDIDATE",
        "evidence_eligible": True,
        "markets": ALL_MARKETS,
    },
    "CURRENT_FORM": {
        "cluster": "current_form",
        "role": "CORE_CANDIDATE",
        "evidence_eligible": True,
        "markets": ALL_MARKETS,
    },
    "LEAGUE_CONTEXT": {
        "cluster": "league_environment",
        "role": "CONTEXT_CANDIDATE",
        "evidence_eligible": True,
        "markets": ALL_MARKETS,
    },
    "TABLE_STRENGTH": {
        "cluster": "relative_strength",
        "role": "CORE_CANDIDATE",
        "evidence_eligible": True,
        "markets": ALL_MARKETS,
    },
    "SHOTS_CHANCE_CREATION": {
        "cluster": "chance_creation",
        "role": "SUPPORT_CANDIDATE",
        "evidence_eligible": True,
        "markets": ALL_MARKETS,
    },
    "FIRST_SECOND_HALF": {
        "cluster": "half_profile",
        "role": "SUPPORT_CANDIDATE",
        "evidence_eligible": True,
        "markets": ("btts_yes", "btts_no", "over_2_5", "under_2_5"),
    },
    "BTTS_OU_PROFILE": {
        "cluster": "goal_pattern",
        "role": "CORE_CANDIDATE",
        "evidence_eligible": True,
        "markets": ("btts_yes", "btts_no", "over_2_5", "under_2_5"),
    },
    "PLAYER_DEPTH": {
        "cluster": "player",
        "role": "SUPPORT_CANDIDATE",
        "evidence_eligible": True,
        "markets": ALL_MARKETS,
    },
    "PLAYER_QUALITY": {
        "cluster": "player",
        "role": "SUPPORT_CANDIDATE",
        "evidence_eligible": True,
        "markets": ALL_MARKETS,
    },
    "PLAYER_CONCENTRATION": {
        "cluster": "player",
        "role": "SUPPORT_CANDIDATE",
        "evidence_eligible": True,
        "markets": ALL_MARKETS,
    },
    "H2H_SECONDARY": {
        "cluster": "h2h",
        "role": "DIAGNOSTIC_SECONDARY",
        "evidence_eligible": False,
        "markets": ALL_MARKETS,
    },
    "REFEREE": {
        "cluster": "referee",
        "role": "SUPPORT_CANDIDATE",
        "evidence_eligible": True,
        "markets": ALL_MARKETS,
    },
    "MANAGER": {
        "cluster": "manager",
        "role": "SUPPORT_CANDIDATE",
        "evidence_eligible": True,
        "markets": ALL_MARKETS,
    },
    "AUXILIARY_CONTEXT": {
        "cluster": "auxiliary_context",
        "role": "DIAGNOSTIC",
        "evidence_eligible": False,
        "markets": ALL_MARKETS,
    },
    "PROVIDER_POTENTIALS_RESEARCH": {
        "cluster": "provider_derived",
        "role": "RESEARCH_ONLY",
        "evidence_eligible": False,
        "markets": ("btts_yes", "btts_no", "over_2_5", "under_2_5"),
    },
    "DATA_QUALITY": {
        "cluster": "data_quality",
        "role": "GATE_ONLY",
        "evidence_eligible": False,
        "markets": (),
    },
}


FORM_OWNERS = {
    "form_windows", "form_deltas", "form_exposure",
    "form_match_venue", "form_match_venue_deltas", "form_match_venue_exposure",
}


def classify_gold_feature(name: str, owner: str) -> str:
    low = name.lower()

    if owner == "provider_potentials_research":
        return "PROVIDER_POTENTIALS_RESEARCH"
    if owner in FORM_OWNERS:
        return "CURRENT_FORM"
    if owner == "table_relative_strength":
        return "TABLE_STRENGTH"
    if owner == "h2h_secondary":
        return "H2H_SECONDARY"
    if owner == "referee":
        return "REFEREE"
    if owner == "manager":
        if "ambiguous_team_change" in low:
            return "DATA_QUALITY"
        return "MANAGER"
    if owner in {"sample_exposure"}:
        return "DATA_QUALITY"
    if owner in {"league_context", "league_derived_context"}:
        return "LEAGUE_CONTEXT"

    if owner == "player_depth_quality_concentration":
        if "secondary_affiliation" in low:
            return "DATA_QUALITY"
        if any(token in low for token in (
            "players_found", "active_players", "active_player_share",
            "player_minutes", "active_minutes",
            "goalkeeper_count", "defender_count", "midfielder_count", "forward_count",
            "goalkeeper_minutes", "defender_minutes", "midfielder_minutes", "forward_minutes",
        )):
            return "PLAYER_DEPTH"
        if "share" in low:
            return "PLAYER_CONCENTRATION"
        return "PLAYER_QUALITY"

    # Domain classification for Match + League team/relative blocks.
    # Order matters: half-time BTTS belongs to the half profile, not to full-match BTTS.
    if any(token in low for token in (
        "bttspercentageht", "cspercentageht", "ftspercentageht",
        "scoredavght", "concededavght", "avght",
        "2hg", "_ht", "first_half", "second_half",
    )):
        return "FIRST_SECOND_HALF"
    if "xg" in low:
        return "EXPECTED_GOALS_XGA"
    if "shot" in low:
        return "SHOTS_CHANCE_CREATION"
    if any(token in low for token in (
        "btts", "over25", "under25", "seasoncs", "seasonfts",
        "clean_sheet", "failed_to_score",
    )):
        return "BTTS_OU_PROFILE"
    if any(token in low for token in ("scoredavg", "concededavg")):
        return "GOALS_DEFENCE"
    if "ppg" in low:
        return "VENUE_STRENGTH"
    if any(token in low for token in ("possession", "corner")):
        return "AUXILIARY_CONTEXT"

    # Any remaining explicit league-team profile feature is retained but not allowed
    # to become an independent evidence vote until a domain rule is added.
    return "AUXILIARY_CONTEXT"


def audit_signal_groups(gold_features: Dict[str, Any]) -> Dict[str, Any]:
    features: Dict[str, float] = gold_features.get("features") or {}
    owners: Dict[str, str] = gold_features.get("feature_owners") or {}

    groups: Dict[str, Dict[str, Any]] = {}
    feature_to_group: Dict[str, str] = {}
    owner_sets: Dict[str, Set[str]] = defaultdict(set)

    missing_owner: List[str] = []
    forbidden_odds: List[str] = []

    for name in features:
        owner = owners.get(name)
        if owner is None:
            missing_owner.append(name)
            continue
        if "odds" in name.lower():
            forbidden_odds.append(name)

        group = classify_gold_feature(name, owner)
        feature_to_group[name] = group
        owner_sets[group].add(owner)

        if group not in groups:
            meta = GROUP_META[group]
            groups[group] = {
                "group": group,
                "cluster": meta["cluster"],
                "role": meta["role"],
                "evidence_eligible": meta["evidence_eligible"],
                "markets": list(meta["markets"]),
                "feature_count": 0,
                "available": False,
                "owners": [],
            }
        groups[group]["feature_count"] += 1
        groups[group]["available"] = True

    for group, owners_for_group in owner_sets.items():
        groups[group]["owners"] = sorted(owners_for_group)

    # Emit absent known groups too, so Referee/Manager unavailability is explicit.
    for group, meta in GROUP_META.items():
        groups.setdefault(group, {
            "group": group,
            "cluster": meta["cluster"],
            "role": meta["role"],
            "evidence_eligible": meta["evidence_eligible"],
            "markets": list(meta["markets"]),
            "feature_count": 0,
            "available": False,
            "owners": [],
        })

    available_eligible_clusters = {
        row["cluster"]
        for row in groups.values()
        if row["available"] and row["evidence_eligible"]
    }

    cluster_to_groups: Dict[str, List[str]] = defaultdict(list)
    for row in groups.values():
        if row["available"]:
            cluster_to_groups[row["cluster"]].append(row["group"])

    return {
        "signal_group_version": "0.1.0",
        "feature_count": len(features),
        "assigned_feature_count": len(feature_to_group),
        "unassigned_feature_count": len(missing_owner),
        "forbidden_odds_feature_count": len(forbidden_odds),
        "forbidden_odds_features": forbidden_odds,
        "available_group_count": sum(1 for row in groups.values() if row["available"]),
        "available_evidence_cluster_count": len(available_eligible_clusters),
        "available_evidence_clusters": sorted(available_eligible_clusters),
        "cluster_to_groups": {k: sorted(v) for k, v in sorted(cluster_to_groups.items())},
        "groups": [groups[k] for k in GROUP_META],
        "feature_to_group": feature_to_group,
        "policy": {
            "model_features": "Many features may enter a trained model after OOS selection.",
            "evidence_votes": "At most one independent confirmation per evidence cluster per market.",
            "player_groups": "Depth, quality and concentration share the PLAYER independence cluster.",
            "form_windows": "Last5/6/10 and form deltas share CURRENT_FORM and can never become separate confirmations.",
            "provider_potentials": "Research-only until isolated forward-OOS ablation proves incremental value.",
            "thresholds": "No SPIELEN/BEOBACHTEN threshold is hard-coded here; thresholds must be learned and validated OOS.",
        },
    }
