from __future__ import annotations

import math
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


def _num(v: Any) -> Optional[float]:
    if v is None or isinstance(v, bool):
        return None
    try:
        x=float(v)
    except (TypeError,ValueError):
        return None
    return x if math.isfinite(x) else None


def _mean(values:Sequence[float])->Optional[float]:
    return sum(values)/len(values) if values else None


def _variance(values:Sequence[float])->Optional[float]:
    if len(values)<2:
        return None
    m=_mean(values)
    return sum((x-m)**2 for x in values)/(len(values)-1)


def _pearson_pairs(xs:Sequence[Optional[float]],ys:Sequence[Optional[float]],min_pairs:int)->Optional[Tuple[float,int]]:
    pairs=[(x,y) for x,y in zip(xs,ys) if x is not None and y is not None]
    if len(pairs)<min_pairs:
        return None
    xv=[x for x,_ in pairs]; yv=[y for _,y in pairs]
    mx,my=_mean(xv),_mean(yv)
    sx=sum((x-mx)**2 for x in xv); sy=sum((y-my)**2 for y in yv)
    if sx<=0 or sy<=0:
        return None
    cov=sum((x-mx)*(y-my) for x,y in pairs)
    return cov/math.sqrt(sx*sy),len(pairs)


def _feature_names(rows:Sequence[Mapping[str,Any]])->List[str]:
    names=set()
    for row in rows:
        names.update((row.get("features") or {}).keys())
    return sorted(names)


def _vectors(rows:Sequence[Mapping[str,Any]],names:Sequence[str])->Dict[str,List[Optional[float]]]:
    out={name:[] for name in names}
    for row in rows:
        f=row.get("features") or {}
        for name in names:
            out[name].append(_num(f.get(name)))
    return out


def _bucket_indices(rows:Sequence[Mapping[str,Any]],bucket_count:int)->List[List[int]]:
    if bucket_count<1:
        raise ValueError("bucket_count must be >=1")
    ordered=sorted(range(len(rows)),key=lambda i:(int(rows[i]["kickoff_unix"]),int(rows[i]["match_id"])))
    if not ordered:
        return []
    buckets=[[] for _ in range(min(bucket_count,len(ordered)))]
    for pos,idx in enumerate(ordered):
        b=min(len(buckets)-1,(pos*len(buckets))//len(ordered))
        buckets[b].append(idx)
    return buckets


def feature_diagnostics(
    rows:Sequence[Mapping[str,Any]],
    *,
    min_coverage_review:float=0.50,
    high_corr_threshold:float=0.98,
    min_corr_pairs:int=30,
    temporal_bucket_count:int=4,
)->Dict[str,Any]:
    if not 0<=min_coverage_review<=1:
        raise ValueError("min_coverage_review must be within [0,1]")
    if not 0<high_corr_threshold<=1:
        raise ValueError("high_corr_threshold must be within (0,1]")
    if min_corr_pairs<2:
        raise ValueError("min_corr_pairs must be >=2")

    rows=list(rows)
    names=_feature_names(rows)
    vecs=_vectors(rows,names)
    n=len(rows)
    buckets=_bucket_indices(rows,temporal_bucket_count)

    stats=[]
    signatures=defaultdict(list)
    for name in names:
        v=vecs[name]
        present=[x for x in v if x is not None]
        coverage=len(present)/n if n else 0.0
        unique=sorted(set(present))
        temporal=[]
        for bucket in buckets:
            count=sum(1 for i in bucket if v[i] is not None)
            temporal.append(count/len(bucket) if bucket else None)
        finite_temporal=[x for x in temporal if x is not None]
        coverage_range=(max(finite_temporal)-min(finite_temporal)) if finite_temporal else None

        status="KEEP_FOR_OOS_REVIEW"
        if present and len(unique)==1:
            status="CONSTANT_REVIEW"
        elif coverage<min_coverage_review:
            status="LOW_COVERAGE_REVIEW"

        stats.append({
            "feature":name,
            "present_count":len(present),
            "row_count":n,
            "coverage":coverage,
            "unique_numeric_count":len(unique),
            "mean":_mean(present),
            "variance":_variance(present),
            "min":min(present) if present else None,
            "max":max(present) if present else None,
            "temporal_bucket_coverage":temporal,
            "temporal_coverage_range":coverage_range,
            "status":status,
        })

        signature=tuple(v)
        signatures[signature].append(name)

    exact_duplicate_groups=[
        group for group in signatures.values()
        if len(group)>1 and any(x is not None for x in vecs[group[0]])
    ]

    eligible=[
        s["feature"] for s in stats
        if s["present_count"]>=min_corr_pairs
        and s["variance"] is not None
        and s["variance"]>0
    ]

    # Union-find over only correlations above threshold.
    parent={name:name for name in eligible}
    def find(x):
        while parent[x]!=x:
            parent[x]=parent[parent[x]]
            x=parent[x]
        return x
    def union(a,b):
        ra,rb=find(a),find(b)
        if ra!=rb:
            parent[rb]=ra

    high_pairs=[]
    for i,a in enumerate(eligible):
        for b in eligible[i+1:]:
            result=_pearson_pairs(vecs[a],vecs[b],min_corr_pairs)
            if result is None:
                continue
            corr,pairs=result
            if abs(corr)>=high_corr_threshold:
                high_pairs.append({"a":a,"b":b,"corr":corr,"pair_count":pairs})
                union(a,b)

    clusters=defaultdict(list)
    for name in eligible:
        clusters[find(name)].append(name)
    high_corr_clusters=[sorted(v) for v in clusters.values() if len(v)>1]

    owner_counts=defaultdict(lambda:{"features":set(),"rows":0})
    for row in rows:
        owners=row.get("feature_owners") or {}
        seen=set()
        for name,owner in owners.items():
            owner_counts[str(owner)]["features"].add(name)
            seen.add(str(owner))
        for owner in seen:
            owner_counts[owner]["rows"]+=1

    return {
        "diagnostic_version":"FULL7_FEATURE_DIAGNOSTICS_0.1",
        "row_count":n,
        "feature_count":len(names),
        "feature_stats":stats,
        "low_coverage_count":sum(1 for s in stats if s["status"]=="LOW_COVERAGE_REVIEW"),
        "constant_count":sum(1 for s in stats if s["status"]=="CONSTANT_REVIEW"),
        "exact_duplicate_group_count":len(exact_duplicate_groups),
        "exact_duplicate_groups":exact_duplicate_groups,
        "high_correlation_threshold":high_corr_threshold,
        "high_correlation_pair_count":len(high_pairs),
        "high_correlation_pairs":high_pairs,
        "high_correlation_cluster_count":len(high_corr_clusters),
        "high_correlation_clusters":high_corr_clusters,
        "owner_summary":{
            owner:{
                "feature_count":len(data["features"]),
                "row_presence_count":data["rows"],
                "row_presence_rate":data["rows"]/n if n else 0.0,
            }
            for owner,data in sorted(owner_counts.items())
        },
        "policy":{
            "no_auto_activation":"Diagnostics never promote a feature into production by themselves.",
            "low_coverage":"Review flag only; threshold is configurable and must be validated against OOS performance.",
            "correlation":"High correlation is a redundancy flag, not automatic deletion.",
            "constant":"Constant features carry no information in the observed dataset and should not be model inputs.",
            "missing":"Missing values stay missing; diagnostics do not impute.",
        },
    }
