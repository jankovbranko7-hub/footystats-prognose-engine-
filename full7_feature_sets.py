from __future__ import annotations

from typing import Any, Dict, Mapping, Sequence


RESEARCH_OWNERS={"provider_potentials_research","h2h_secondary"}
QUALITY_OWNERS={"sample_exposure","form_exposure","form_match_venue_exposure"}

AUXILIARY_TOKENS=("possession","corner")
TABLE_RAW_TOKENS=("_points","_position")
FORM_REDUNDANT_WINDOW_TOKENS=("_last6_","_last10_","form_last6_","form_last10_")


def classify_feature_set(name:str,owner:str)->str:
    low=name.lower()

    if owner in RESEARCH_OWNERS:
        return "RESEARCH_ONLY"
    if owner in QUALITY_OWNERS:
        return "QUALITY_ONLY"
    if "secondary_affiliation" in low or "ambiguous_team_change" in low:
        return "QUALITY_ONLY"

    # Last 5 is the direct short-form window. Last 6/10 remain represented through
    # form-delta features, preventing nested windows from becoming three copies.
    if owner in {"form_windows","form_match_venue"} and any(t in low for t in FORM_REDUNDANT_WINDOW_TOKENS):
        return "REDUNDANT_NESTED_WINDOW"
    if owner in {"form_deltas","form_match_venue_deltas"} and (
        low.startswith("form_last6_") or low.startswith("form_last10_")
    ):
        return "REDUNDANT_NESTED_WINDOW"

    # Under 2.5 percentage is an exact complement of Over 2.5 percentage in the
    # same sample. Keep Over 2.5 representation; derive Under direction as needed.
    if "under25percentage" in low:
        return "REDUNDANT_COMPLEMENT"

    # Raw table positions/points are represented by rank percentile and PPG.
    if owner=="table_relative_strength" and any(t in low for t in TABLE_RAW_TOKENS):
        return "REDUNDANT_TABLE_RAW"

    # Possession/corners are retained in an extended research set but not the
    # first compact probability core. Shots remain core.
    if any(t in low for t in AUXILIARY_TOKENS):
        return "AUXILIARY_RESEARCH"

    return "CORE_PROBABILITY_CANDIDATE"


def build_feature_sets(
    gold_features:Mapping[str,Any],
)->Dict[str,Any]:
    features=gold_features.get("features") or {}
    owners=gold_features.get("feature_owners") or {}

    buckets:Dict[str,list]={}
    classification={}
    for name in sorted(features):
        owner=str(owners.get(name) or "UNKNOWN")
        status=classify_feature_set(name,owner)
        classification[name]={"owner":owner,"status":status}
        buckets.setdefault(status,[]).append(name)

    core=buckets.get("CORE_PROBABILITY_CANDIDATE",[])
    extended=[
        name for name in sorted(features)
        if classification[name]["status"] not in {"QUALITY_ONLY"}
    ]
    research=[
        name for name in sorted(features)
        if classification[name]["status"] in {"RESEARCH_ONLY","AUXILIARY_RESEARCH"}
    ]
    quality=[
        name for name in sorted(features)
        if classification[name]["status"]=="QUALITY_ONLY"
    ]

    return {
        "feature_set_version":"FULL7_FEATURE_SETS_0.1",
        "core_probability":core,
        "extended_probability_research":extended,
        "research_only":research,
        "quality_gate":quality,
        "classification":classification,
        "counts":{
            "all_gold":len(features),
            "core_probability":len(core),
            "extended_probability_research":len(extended),
            "research_only":len(research),
            "quality_gate":len(quality),
            **{k:len(v) for k,v in sorted(buckets.items())},
        },
        "policy":{
            "outcome_blind":True,
            "last_x":"Last5 retained directly; Last6/10 represented through deltas rather than separate full windows.",
            "over_under":"Under2.5 percentage complements removed where Over2.5 carries identical information.",
            "table":"PPG/rank-percentile preferred over raw points/position duplication.",
            "provider_potentials":"Research-only; excluded from first probability core.",
            "h2h":"Secondary research only.",
            "auxiliary":"Corners/possession research-only initially; shots remain core.",
            "quality":"Sample/coverage/ambiguity variables reserved for reliability gates unless OOS evidence later justifies model use.",
        },
    }
