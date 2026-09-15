from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


def _ordered_unique(rows: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    seen=set()
    out=[]
    for raw in sorted(rows,key=lambda r:(int(r["kickoff_unix"]),int(r["match_id"]))):
        mid=int(raw["match_id"])
        if mid in seen:
            raise ValueError(f"duplicate match_id before temporal split: {mid}")
        seen.add(mid)
        out.append(dict(raw))
    return out


def _kickoff_groups(rows: Sequence[Mapping[str, Any]]) -> List[List[Dict[str, Any]]]:
    groups=defaultdict(list)
    for row in rows:
        groups[int(row["kickoff_unix"])].append(dict(row))
    return [groups[k] for k in sorted(groups)]


def _flatten(groups: Sequence[Sequence[Mapping[str, Any]]]) -> List[Dict[str, Any]]:
    return [dict(row) for group in groups for row in group]


def chronological_partition(
    rows: Sequence[Mapping[str, Any]],
    *,
    train_fraction: float = 0.60,
    development_fraction: float = 0.15,
    calibration_fraction: float = 0.10,
    forward_oos_fraction: float = 0.15,
) -> Dict[str, Any]:
    fractions=(train_fraction,development_fraction,calibration_fraction,forward_oos_fraction)
    if any(f<=0 for f in fractions):
        raise ValueError("all split fractions must be > 0")
    if abs(sum(fractions)-1.0)>1e-9:
        raise ValueError("split fractions must sum to 1")

    ordered=_ordered_unique(rows)
    groups=_kickoff_groups(ordered)
    total=len(ordered)
    if total<4:
        raise ValueError("at least 4 matches required")

    targets=[
        total*train_fraction,
        total*(train_fraction+development_fraction),
        total*(train_fraction+development_fraction+calibration_fraction),
    ]

    cuts=[]
    cumulative=0
    next_target_idx=0
    for gi,group in enumerate(groups):
        cumulative+=len(group)
        while next_target_idx<len(targets) and cumulative>=targets[next_target_idx]:
            # Boundary is after entire kickoff group, never through simultaneous matches.
            cuts.append(gi+1)
            next_target_idx+=1

    while len(cuts)<3:
        # Fallback to latest legal group boundary while preserving order.
        candidate=max((cuts[-1] if cuts else 0)+1, len(groups)-(3-len(cuts)))
        if candidate>=len(groups):
            raise ValueError("insufficient distinct kickoff groups for four-way split")
        cuts.append(candidate)

    c1,c2,c3=cuts[:3]
    if not (0<c1<c2<c3<len(groups)):
        # Recompute deterministic group-count boundaries if data are highly bunched.
        g=len(groups)
        if g<4:
            raise ValueError("at least 4 distinct kickoff groups required")
        c1=max(1,round(g*train_fraction))
        c2=max(c1+1,round(g*(train_fraction+development_fraction)))
        c3=max(c2+1,round(g*(train_fraction+development_fraction+calibration_fraction)))
        c3=min(c3,g-1)
        c2=min(c2,c3-1)
        c1=min(c1,c2-1)

    parts={
        "train":_flatten(groups[:c1]),
        "development":_flatten(groups[c1:c2]),
        "calibration":_flatten(groups[c2:c3]),
        "forward_oos":_flatten(groups[c3:]),
    }
    if any(not v for v in parts.values()):
        raise ValueError("temporal split produced an empty partition")

    ranges={}
    for name,part in parts.items():
        ranges[name]={
            "rows":len(part),
            "first_kickoff_unix":int(part[0]["kickoff_unix"]),
            "last_kickoff_unix":int(part[-1]["kickoff_unix"]),
            "match_ids":[int(r["match_id"]) for r in part],
        }

    if not (
        ranges["train"]["last_kickoff_unix"] <= ranges["development"]["first_kickoff_unix"]
        <= ranges["calibration"]["first_kickoff_unix"]
        <= ranges["forward_oos"]["first_kickoff_unix"]
    ):
        raise AssertionError("temporal ordering failure")

    return {
        "split_version":"FULL7_CHRONOLOGICAL_SPLIT_0.1",
        "row_count":total,
        "parts":parts,
        "ranges":ranges,
        "policy":{
            "shuffle":False,
            "same_kickoff_group":"never split across partitions",
            "calibration":"separate from model-fit train/development data",
            "forward_oos":"chronologically latest holdout and never used for feature selection/calibration",
        },
    }


def expanding_walk_forward(
    rows: Sequence[Mapping[str, Any]],
    *,
    min_train_fraction: float = 0.50,
    validation_fraction: float = 0.10,
    fold_count: int = 4,
) -> Dict[str, Any]:
    if not 0<min_train_fraction<1:
        raise ValueError("min_train_fraction must be within (0,1)")
    if not 0<validation_fraction<1:
        raise ValueError("validation_fraction must be within (0,1)")
    if fold_count<1:
        raise ValueError("fold_count must be >=1")

    ordered=_ordered_unique(rows)
    groups=_kickoff_groups(ordered)
    g=len(groups)
    if g<3:
        raise ValueError("at least 3 distinct kickoff groups required")

    min_train_groups=max(1,int(round(g*min_train_fraction)))
    val_groups=max(1,int(round(g*validation_fraction)))
    latest_train_end=g-val_groups
    if min_train_groups>=latest_train_end:
        raise ValueError("not enough future groups after minimum train window")

    possible_ends=list(range(min_train_groups,latest_train_end+1))
    if len(possible_ends)<=fold_count:
        train_ends=possible_ends
    else:
        # Evenly spaced expanding endpoints, always including earliest and latest.
        train_ends=[]
        for i in range(fold_count):
            pos=round(i*(len(possible_ends)-1)/(fold_count-1)) if fold_count>1 else len(possible_ends)-1
            train_ends.append(possible_ends[pos])
        train_ends=sorted(set(train_ends))

    folds=[]
    for idx,train_end in enumerate(train_ends,1):
        val_end=min(g,train_end+val_groups)
        train=_flatten(groups[:train_end])
        validation=_flatten(groups[train_end:val_end])
        if not validation:
            continue
        if int(train[-1]["kickoff_unix"])>int(validation[0]["kickoff_unix"]):
            raise AssertionError("walk-forward leakage")
        folds.append({
            "fold":idx,
            "train":train,
            "validation":validation,
            "train_rows":len(train),
            "validation_rows":len(validation),
            "train_first_kickoff_unix":int(train[0]["kickoff_unix"]),
            "train_last_kickoff_unix":int(train[-1]["kickoff_unix"]),
            "validation_first_kickoff_unix":int(validation[0]["kickoff_unix"]),
            "validation_last_kickoff_unix":int(validation[-1]["kickoff_unix"]),
        })

    if not folds:
        raise ValueError("no valid walk-forward folds")

    return {
        "walk_forward_version":"FULL7_EXPANDING_WALK_FORWARD_0.1",
        "fold_count":len(folds),
        "folds":folds,
        "policy":{
            "shuffle":False,
            "expanding_train":True,
            "future_only_validation":True,
            "same_kickoff_group":"never split between train and validation",
        },
    }
