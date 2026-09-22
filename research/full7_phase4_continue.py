#!/usr/bin/env python3
"""FULL-7 Phase 4 continuation after V3.1 coverage diagnosis.

Consumes ONLY the already materialized Phase-4 matrix/selection and frozen
CP2/CP3 artifacts. It never rebuilds CP1/CP2/CP3 or the FULL-7 matrix.

Method:
1) deterministically reconstruct V3.1 compatibility inputs from frozen sources;
2) diagnose paired support by chronological split/fold;
3) use TRAIN-only screening;
4) use DEVELOPMENT prequential segments for feature-group ablation/model choice;
5) freeze one candidate per market BEFORE OOS;
6) evaluate locked candidates once on walk-forward OOS;
7) compare to V3.1 only on exactly paired rows when support is adequate.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import math
import socket
from collections import Counter, defaultdict
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence
from unittest.mock import patch

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.linear_model import SGDClassifier

from research.full7_phase4_model_research import (
    ABLATION_PARAMS,
    DIRECT_VARIANTS,
    PHASE4_VERSION,
    POISSON_PARAMS,
    PRIORITY_GROUPS,
    RESEARCH_ONLY_GROUPS,
    V3_NUMERIC,
    Phase4Error,
    _manifest,
    _metrics_binary,
    _metrics_multiclass,
    _sha256,
    _validate_inputs,
)

CONTINUATION_VERSION="FULL7_PHASE4_CONTINUATION_1.0"
MIN_PAIRED_TRAIN=1000
MIN_PAIRED_DEV=100
MIN_PAIRED_FOLD=50
SCREEN_PER_GROUP=28
DEV_SEGMENTS=3
TARGETS=("1X2","BTTS","O25")


def _utcnow():
    return datetime.now(timezone.utc).isoformat()


def _json_atomic(path:Path,obj:Any):
    tmp=path.with_suffix(path.suffix+".tmp")
    tmp.write_text(json.dumps(obj,indent=2,ensure_ascii=False,sort_keys=True),encoding="utf-8")
    tmp.replace(path)


def _finite(v):
    if v is None or isinstance(v,bool): return None
    try: x=float(v)
    except (TypeError,ValueError): return None
    return x if math.isfinite(x) else None


def _v3_partial_from_row(row:Mapping[str,Any]):
    src=json.loads(row["feature_sources_json"])
    match=src.get("match") or {}
    league=src.get("league") or {}
    prematch=match.get("prematch_optional") or {}
    season=league.get("season_safe_identity") or {}
    base={
        "liga_avg_heim_vor_spiel":_finite(season.get("seasonAVG_home")),
        "liga_avg_aus_vor_spiel":_finite(season.get("seasonAVG_away")),
        "liga_spiele_bisher":_finite(season.get("matchesCompleted")),
        "fs_xg_prematch_heim":_finite(prematch.get("team_a_xg_prematch")),
        "fs_xg_prematch_aus":_finite(prematch.get("team_b_xg_prematch")),
        "fs_o25_potential":_finite(prematch.get("o25_potential")),
        "fs_btts_potential":_finite(prematch.get("btts_potential")),
        "fs_avg_potential":_finite(prematch.get("avg_potential")),
        "fs_pre_ppg_heim":_finite(prematch.get("pre_match_home_ppg")),
        "fs_pre_ppg_aus":_finite(prematch.get("pre_match_away_ppg")),
    }
    out=dict(base)
    lh,la=base["liga_avg_heim_vor_spiel"],base["liga_avg_aus_vor_spiel"]
    xh,xa=base["fs_xg_prematch_heim"],base["fs_xg_prematch_aus"]
    ph,pa=base["fs_pre_ppg_heim"],base["fs_pre_ppg_aus"]
    op,bp,av=base["fs_o25_potential"],base["fs_btts_potential"],base["fs_avg_potential"]
    if lh is not None and la is not None:
        out.update({
            "league_goal_total":lh+la,
            "league_goal_diff":lh-la,
            "league_goal_absdiff":abs(lh-la),
        })
    if xh is not None and xa is not None:
        out.update({
            "fs_xg_total":xh+xa,
            "fs_xg_diff":xh-xa,
            "fs_xg_absdiff":abs(xh-xa),
            "fs_xg_min":min(xh,xa),
            "fs_xg_product":xh*xa,
        })
    if ph is not None and pa is not None:
        out.update({
            "ppg_diff":ph-pa,
            "ppg_absdiff":abs(ph-pa),
            "ppg_total":ph+pa,
            "ppg_product":ph*pa,
        })
    if op is not None:
        out["o25_potential_frac"]=op/100.0
    if bp is not None:
        out["btts_potential_frac"]=bp/100.0
    if av is not None:
        out["avg_potential_copy"]=av
    if op is not None and bp is not None:
        of,bf=op/100.0,bp/100.0
        out["potential_diff"]=of-bf
        out["potential_absdiff"]=abs(of-bf)
        out["potential_product"]=of*bf
    if av is not None and xh is not None and xa is not None:
        out["avg_minus_fsxg"]=av-(xh+xa)
    if xh is not None and xa is not None and lh is not None and la is not None:
        out["fsxg_minus_league"]=(xh+xa)-(lh+la)

    country=str(season.get("country") or "").strip()
    name=str(season.get("db_english_name") or season.get("name") or season.get("division") or row.get("competition") or "").strip()
    league_name=(f"{country} {name}".strip() if country else name) or str(row.get("competition") or "").strip()
    return out,league_name


def _reconstruct_v3_only(master:Path,stage:Path,match_ids:np.ndarray):
    matrix_path=stage/"PHASE4_V3_COMPAT_MATRIX.npy"
    league_path=stage/"PHASE4_V3_COMPAT_LEAGUES.npy"
    audit_path=stage/"PHASE4_V3_RECONSTRUCTION.json"
    if matrix_path.is_file() and league_path.is_file() and audit_path.is_file():
        return json.loads(audit_path.read_text()),np.load(matrix_path,mmap_mode="r"),np.load(league_path,mmap_mode="r")
    idx={int(mid):i for i,mid in enumerate(match_ids)}
    X=np.lib.format.open_memmap(matrix_path,mode="w+",dtype=np.float32,shape=(len(match_ids),len(V3_NUMERIC)))
    X[:]=np.nan
    leagues=np.empty(len(match_ids),dtype="U160")
    leagues[:]=""
    counts=Counter()
    seen=0
    with master.open(encoding="utf-8") as fh:
        for line in fh:
            if not line.strip(): continue
            row=json.loads(line)
            mid=int(row["match_id"])
            if mid not in idx:
                raise Phase4Error(f"v3_reconstruction_unknown_match:{mid}")
            i=idx[mid]
            values,league=_v3_partial_from_row(row)
            for j,name in enumerate(V3_NUMERIC):
                v=values.get(name)
                if v is not None:
                    X[i,j]=v
                    counts[name]+=1
            leagues[i]=league
            seen+=1
    X.flush()
    np.save(league_path,leagues)
    if seen!=len(match_ids):
        raise Phase4Error(f"v3_reconstruction_row_mismatch:{seen}:{len(match_ids)}")
    audit={
        "version":"FULL7_V3_COMPAT_RECONSTRUCTION_1.0",
        "rows":seen,
        "definition_source":"production full7_v3_live.py exact feature definitions",
        "source":"frozen CP2 feature_sources_json only",
        "new_collection":False,
        "api_calls":False,
        "imputation":False,
        "postmatch":False,
        "per_input_non_null":{k:int(counts[k]) for k in V3_NUMERIC},
        "matrix_sha256":_sha256(matrix_path),
        "league_file_sha256":_sha256(league_path),
    }
    _json_atomic(audit_path,audit)
    return audit,np.load(matrix_path,mmap_mode="r"),np.load(league_path,mmap_mode="r")


def _split_indices(labels,splits):
    dates=labels["dates"]
    train=np.asarray([i for i,d in enumerate(dates) if str(d)<=splits["train_end_date"]],dtype=int)
    dev=np.asarray([i for i,d in enumerate(dates) if splits["train_end_date"]<str(d)<=splits["development_end_date"]],dtype=int)
    oos=[]
    for meta in splits["oos_folds"]:
        test=np.asarray([i for i,d in enumerate(dates) if meta["test_start_date"]<=str(d)<=meta["test_end_date"]],dtype=int)
        oos.append((np.arange(int(test.min()),dtype=int),test,f"OOS{meta['fold']}"))
    return train,dev,oos


def _dev_folds(labels,train_idx,dev_idx):
    dates=labels["dates"]
    unique=sorted({str(dates[i]) for i in dev_idx})
    counts={d:int(sum(str(dates[i])==d for i in dev_idx)) for d in unique}
    target=len(dev_idx)/DEV_SEGMENTS
    groups=[[] for _ in range(DEV_SEGMENTS)]
    g=0;acc=0
    for d in unique:
        if g<DEV_SEGMENTS-1 and acc>=target:
            g+=1;acc=0
        groups[g].append(d);acc+=counts[d]
    folds=[]
    for n,ds in enumerate(groups,1):
        s=set(ds)
        test=np.asarray([i for i in dev_idx if str(dates[i]) in s],dtype=int)
        start=int(test.min())
        train=np.arange(start,dtype=int)
        folds.append((train,test,f"DEV{n}"))
    return folds


def _diag_slice(name,idx,X,leagues):
    idx=np.asarray(idx,dtype=int)
    finite=np.isfinite(X[idx])
    league_ok=np.asarray([bool(str(leagues[i])) for i in idx],dtype=bool)
    complete=finite.all(axis=1)&league_ok
    miss_counts={}
    for j,f in enumerate(V3_NUMERIC):
        count=int((~finite[:,j]).sum())
        miss_counts[f]={"missing_count":count,"missing_rate":count/len(idx) if len(idx) else None}
    combos=Counter()
    for r,row_ok in enumerate(finite):
        missing=[V3_NUMERIC[j] for j,ok in enumerate(row_ok) if not ok]
        if not league_ok[r]: missing.append("liga")
        if missing: combos[tuple(missing)]+=1
    return {
        "split":name,
        "total_matches":int(len(idx)),
        "compatible_matches":int(complete.sum()),
        "coverage_pct":float(100.0*complete.mean()) if len(idx) else 0.0,
        "incompatible_matches":int(len(idx)-complete.sum()),
        "missing_by_input":miss_counts,
        "missing_combinations":[{"inputs":list(k),"count":v,"rate":v/len(idx)} for k,v in combos.most_common()],
    },complete


def _coverage_diagnostic(stage,labels,splits,Xv3,leagues,train,dev,oos):
    path=stage/"PHASE4_V3_COVERAGE_DIAGNOSTIC_V2.json"
    if path.is_file():
        obj=json.loads(path.read_text())
        return obj
    sections={}
    sections["TRAIN"],_= _diag_slice("TRAIN",train,Xv3,leagues)
    sections["DEVELOPMENT"],_= _diag_slice("DEVELOPMENT",dev,Xv3,leagues)
    for tr,te,label in oos:
        sections[label],_= _diag_slice(label,te,Xv3,leagues)

    # Structural time/league diagnosis across all rows.
    month_stats=defaultdict(lambda:[0,0])
    league_stats=defaultdict(lambda:[0,0])
    complete_all=np.isfinite(Xv3).all(axis=1)&np.asarray([bool(str(x)) for x in leagues])
    for i,ok in enumerate(complete_all):
        month=str(labels["dates"][i])[:7]
        league=str(leagues[i]) or "<MISSING_LEAGUE>"
        month_stats[month][0]+=1;month_stats[month][1]+=int(ok)
        league_stats[league][0]+=1;league_stats[league][1]+=int(ok)
    structural={
        "by_month":[{"month":k,"n":v[0],"compatible":v[1],"coverage_pct":100*v[1]/v[0]} for k,v in sorted(month_stats.items())],
        "by_league":[{"league":k,"n":v[0],"compatible":v[1],"coverage_pct":100*v[1]/v[0]} for k,v in sorted(league_stats.items(),key=lambda kv:(kv[1][1]/kv[1][0],-kv[1][0],kv[0]))],
    }

    global_missing={f:int((~np.isfinite(Xv3[:,j])).sum()) for j,f in enumerate(V3_NUMERIC)}
    top=sorted(global_missing.items(),key=lambda kv:(-kv[1],kv[0]))
    availability={}
    dependencies={
        "liga_avg_heim_vor_spiel":["league.season_safe_identity.seasonAVG_home"],
        "liga_avg_aus_vor_spiel":["league.season_safe_identity.seasonAVG_away"],
        "liga_spiele_bisher":["league.season_safe_identity.matchesCompleted"],
        "fs_xg_prematch_heim":["match.prematch_optional.team_a_xg_prematch"],
        "fs_xg_prematch_aus":["match.prematch_optional.team_b_xg_prematch"],
        "fs_o25_potential":["match.prematch_optional.o25_potential"],
        "fs_btts_potential":["match.prematch_optional.btts_potential"],
        "fs_avg_potential":["match.prematch_optional.avg_potential"],
        "fs_pre_ppg_heim":["match.prematch_optional.pre_match_home_ppg"],
        "fs_pre_ppg_aus":["match.prematch_optional.pre_match_away_ppg"],
        "league_goal_total":["liga_avg_heim_vor_spiel","liga_avg_aus_vor_spiel"],
        "league_goal_diff":["liga_avg_heim_vor_spiel","liga_avg_aus_vor_spiel"],
        "league_goal_absdiff":["liga_avg_heim_vor_spiel","liga_avg_aus_vor_spiel"],
        "fs_xg_total":["fs_xg_prematch_heim","fs_xg_prematch_aus"],
        "fs_xg_diff":["fs_xg_prematch_heim","fs_xg_prematch_aus"],
        "fs_xg_absdiff":["fs_xg_prematch_heim","fs_xg_prematch_aus"],
        "fs_xg_min":["fs_xg_prematch_heim","fs_xg_prematch_aus"],
        "fs_xg_product":["fs_xg_prematch_heim","fs_xg_prematch_aus"],
        "ppg_diff":["fs_pre_ppg_heim","fs_pre_ppg_aus"],
        "ppg_absdiff":["fs_pre_ppg_heim","fs_pre_ppg_aus"],
        "ppg_total":["fs_pre_ppg_heim","fs_pre_ppg_aus"],
        "ppg_product":["fs_pre_ppg_heim","fs_pre_ppg_aus"],
        "o25_potential_frac":["fs_o25_potential"],
        "btts_potential_frac":["fs_btts_potential"],
        "avg_potential_copy":["fs_avg_potential"],
        "potential_diff":["fs_o25_potential","fs_btts_potential"],
        "potential_absdiff":["fs_o25_potential","fs_btts_potential"],
        "potential_product":["fs_o25_potential","fs_btts_potential"],
        "avg_minus_fsxg":["fs_avg_potential","fs_xg_prematch_heim","fs_xg_prematch_aus"],
        "fsxg_minus_league":["fs_xg_prematch_heim","fs_xg_prematch_aus","liga_avg_heim_vor_spiel","liga_avg_aus_vor_spiel"],
    }
    for f in V3_NUMERIC:
        non_null=len(labels["match_ids"])-global_missing[f]
        availability[f]={
            "classification":"A_FROZEN_DETERMINISTIC_WHERE_SOURCE_PRESENT" if non_null>0 else "B_NOT_AVAILABLE_FROM_FROZEN_DATA",
            "non_null_rows":int(non_null),
            "missing_rows":int(global_missing[f]),
            "dependencies":dependencies[f],
            "category_c_used":False,
        }
    obj={
        "version":"FULL7_V3_COVERAGE_DIAGNOSTIC_2.0",
        "created_at_utc":_utcnow(),
        "splits":sections,
        "top_limiting_inputs":[{"input":f,"missing_count":n,"missing_rate":n/len(labels["match_ids"])} for f,n in top],
        "input_availability":availability,
        "structural_distribution":structural,
        "no_global_intersection_filter_for_full7":True,
        "category_c_used":False,
    }
    _json_atomic(path,obj)
    print("V3_1_COVERAGE_TRAIN="+json.dumps(sections["TRAIN"],sort_keys=True),flush=True)
    print("V3_1_COVERAGE_DEVELOPMENT="+json.dumps(sections["DEVELOPMENT"],sort_keys=True),flush=True)
    print("V3_1_COVERAGE_OOS_BY_FOLD="+json.dumps({k:v for k,v in sections.items() if k.startswith("OOS")},sort_keys=True),flush=True)
    print("TOP_LIMITING_V3_INPUTS="+json.dumps(obj["top_limiting_inputs"][:10],sort_keys=True),flush=True)
    return obj


def _target_y(labels,target):
    return labels[{"1X2":"y1","BTTS":"yb","O25":"yo"}[target]]


def _metrics(target,y,p):
    return _metrics_multiclass(y,p) if target=="1X2" else _metrics_binary(y,p)


def _hgb(params):
    return HistGradientBoostingClassifier(loss="log_loss",random_state=42,early_stopping=False,max_bins=63,**params)


def _fit_hgb(X,y,tr,te,cols,target,params):
    xtr=np.asarray(X[np.ix_(np.asarray(tr),np.asarray(cols))],dtype=np.float32)
    xte=np.asarray(X[np.ix_(np.asarray(te),np.asarray(cols))],dtype=np.float32)
    model=_hgb(params);model.fit(xtr,y[np.asarray(tr)])
    raw=model.predict_proba(xte)
    if target=="1X2":
        p=np.zeros((len(te),3),dtype=float)
        for j,c in enumerate(model.classes_):p[:,int(c)]=raw[:,j]
    else:
        c={int(v):j for j,v in enumerate(model.classes_)}
        p=raw[:,c[1]]
    return p


def _poisson_probs(lh,la):
    lh=np.clip(np.asarray(lh,dtype=float),0.03,8.0);la=np.clip(np.asarray(la,dtype=float),0.03,8.0)
    n=len(lh);p1=np.zeros((n,3));pb=np.zeros(n);po=np.zeros(n)
    fact=[math.factorial(k) for k in range(13)]
    for r in range(n):
        ph=np.array([math.exp(-lh[r])*lh[r]**k/fact[k] for k in range(13)])
        pa=np.array([math.exp(-la[r])*la[r]**k/fact[k] for k in range(13)])
        mat=np.outer(ph,pa);mat/=mat.sum() or 1.0
        p1[r]=[np.tril(mat,-1).sum(),np.trace(mat),np.triu(mat,1).sum()]
        pb[r]=mat[1:,1:].sum()
        po[r]=sum(mat[i,j] for i in range(13) for j in range(13) if i+j>=3)
    return p1,pb,po


def _fit_poisson_all(X,labels,tr,te,cols):
    xtr=np.asarray(X[np.ix_(np.asarray(tr),np.asarray(cols))],dtype=np.float32)
    xte=np.asarray(X[np.ix_(np.asarray(te),np.asarray(cols))],dtype=np.float32)
    mh=HistGradientBoostingRegressor(loss="poisson",random_state=42,early_stopping=False,max_bins=63,**POISSON_PARAMS)
    ma=HistGradientBoostingRegressor(loss="poisson",random_state=43,early_stopping=False,max_bins=63,**POISSON_PARAMS)
    mh.fit(xtr,labels["yh"][np.asarray(tr)]);lh=mh.predict(xte)
    ma.fit(xtr,labels["ya"][np.asarray(tr)]);la=ma.predict(xte)
    return _poisson_probs(lh,la)


def _screen_scores(X,labels,train,meta,selection):
    path=Path(meta["_stage"])/"PHASE4_TRAIN_ONLY_SCREENING.json"
    if path.is_file():return json.loads(path.read_text())
    names=list(meta["feature_names"]);groups=meta["feature_groups"];index={n:i for i,n in enumerate(names)}
    selected=set(selection["full_research_features"])
    result={"version":"FULL7_TRAIN_ONLY_SCREENING_1.0","per_group_cap":SCREEN_PER_GROUP,"targets":{}}
    for target in TARGETS:
        y=_target_y(labels,target)[train]
        scored=defaultdict(list)
        for name in selected:
            j=index[name]
            x=np.asarray(X[train,j],dtype=float)
            ok=np.isfinite(x)
            if ok.sum()<100:continue
            vals=x[ok];yy=y[ok]
            sd=float(np.std(vals))
            if sd<=1e-12:continue
            if target=="1X2":
                means=[float(vals[yy==c].mean()) if np.any(yy==c) else 0.0 for c in (0,1,2)]
                score=(max(means)-min(means))/sd
            else:
                if not np.any(yy==0) or not np.any(yy==1):continue
                score=abs(float(vals[yy==1].mean())-float(vals[yy==0].mean()))/sd
            scored[groups[name]].append((score,float(ok.mean()),name))
        chosen=[]
        details={}
        for group,rows in scored.items():
            rows.sort(key=lambda z:(-z[0],-z[1],z[2]))
            keep=rows[:SCREEN_PER_GROUP]
            chosen.extend(r[2] for r in keep)
            details[group]=[{"feature":n,"effect_score":s,"train_coverage":c} for s,c,n in keep]
        result["targets"][target]={"selected_features":sorted(chosen),"selected_count":len(chosen),"groups":details}
    _json_atomic(path,result)
    return result


def _run_hgb_cv(X,labels,target,features,meta,folds,params):
    idx={n:i for i,n in enumerate(meta["feature_names"])};cols=[idx[n] for n in features]
    y=_target_y(labels,target);all_y=[];all_p=[];fold_metrics=[]
    for tr,te,label in folds:
        p=_fit_hgb(X,y,tr,te,cols,target,params)
        fold_metrics.append({"fold":label,**_metrics(target,y[te],p)})
        all_y.append(y[te]);all_p.append(p)
    yy=np.concatenate(all_y);pp=np.concatenate(all_p,axis=0)
    return {"metrics":_metrics(target,yy,pp),"folds":fold_metrics}


def _run_poisson_cv(X,labels,target,features,meta,folds):
    idx={n:i for i,n in enumerate(meta["feature_names"])};cols=[idx[n] for n in features]
    y=_target_y(labels,target);all_y=[];all_p=[];fold_metrics=[]
    for tr,te,label in folds:
        p1,pb,po=_fit_poisson_all(X,labels,tr,te,cols)
        p={"1X2":p1,"BTTS":pb,"O25":po}[target]
        fold_metrics.append({"fold":label,**_metrics(target,y[te],p)})
        all_y.append(y[te]);all_p.append(p)
    yy=np.concatenate(all_y);pp=np.concatenate(all_p,axis=0)
    return {"metrics":_metrics(target,yy,pp),"folds":fold_metrics}


def _dev_group_ablation(stage,X,labels,meta,selection,screening,dev_folds):
    path=stage/"PHASE4_GROUP_ABLATIONS_DEVELOPMENT.json"
    if path.is_file():return json.loads(path.read_text())
    groups=meta["feature_groups"];out={"version":"FULL7_DEV_GROUP_ABLATION_1.0","selection_source":"TRAIN_ONLY_SCREENING","targets":{}}
    for target in TARGETS:
        screened=screening["targets"][target]["selected_features"]
        all_groups=sorted({groups[n] for n in screened})
        core=[n for n in screened if groups[n] not in RESEARCH_ONLY_GROUPS]
        full=list(screened)
        target_out={"groups":{}}
        ref_core=_run_hgb_cv(X,labels,target,core,meta,dev_folds,ABLATION_PARAMS)
        ref_full=_run_hgb_cv(X,labels,target,full,meta,dev_folds,ABLATION_PARAMS)
        for group in all_groups:
            reference=ref_full if group in RESEARCH_ONLY_GROUPS else ref_core
            ref_features=full if group in RESEARCH_ONLY_GROUPS else core
            without=[n for n in ref_features if groups[n]!=group]
            if not without:continue
            removed=_run_hgb_cv(X,labels,target,without,meta,dev_folds,ABLATION_PARAMS)
            agg_ll=removed["metrics"]["logloss"]-reference["metrics"]["logloss"]
            agg_br=removed["metrics"]["brier"]-reference["metrics"]["brier"]
            fold_deltas=[]
            positive=0
            for a,b in zip(reference["folds"],removed["folds"]):
                dll=b["logloss"]-a["logloss"];dbr=b["brier"]-a["brier"]
                positive+=int(dll>0)
                fold_deltas.append({"fold":a["fold"],"logloss_deterioration_when_removed":dll,"brier_deterioration_when_removed":dbr})
            supported=(agg_ll>0 and agg_br>=-1e-6 and positive>=2)
            target_out["groups"][group]={
                "feature_count":sum(groups[n]==group for n in ref_features),
                "aggregate_logloss_deterioration_when_removed":agg_ll,
                "aggregate_brier_deterioration_when_removed":agg_br,
                "positive_logloss_segments":positive,
                "segments":fold_deltas,
                "development_support":"SUPPORTED" if supported else "NOT_SUPPORTED",
            }
        supported_groups={g for g,v in target_out["groups"].items() if v["development_support"]=="SUPPORTED"}
        locked=[n for n in screened if groups[n] in supported_groups]
        # Fail-safe: if ablation is too aggressive, retain non-research screened base.
        if len(locked)<20:
            locked=core
            target_out["fallback"]="CORE_SCREENED_RETAINED_DUE_TO_TOO_FEW_SUPPORTED_GROUP_FEATURES"
        target_out["locked_features"]=sorted(locked)
        target_out["locked_feature_count"]=len(locked)
        target_out["supported_groups"]=sorted(supported_groups)
        out["targets"][target]=target_out
        print(f"PHASE4_DEV_ABLATION_COMPLETE={target}",flush=True)
    _json_atomic(path,out)
    return out


def _development_models(stage,X,labels,meta,ablation,dev_folds):
    path=stage/"PHASE4_DEVELOPMENT_MODEL_COMPARISON.json"
    pred_path=stage/"PHASE4_DEVELOPMENT_PREDICTIONS.npz"
    if path.is_file() and pred_path.is_file():return json.loads(path.read_text())
    out={"version":"FULL7_DEV_MODEL_COMPARE_1.0","targets":{}}
    saved={}
    for target in TARGETS:
        feats=ablation["targets"][target]["locked_features"]
        variants={}
        for name,spec in DIRECT_VARIANTS.items():
            # FULL_RESEARCH variant uses same locked dev-approved set; research-only
            # groups only survive if their DEVELOPMENT ablation was supported.
            res=_run_hgb_cv(X,labels,target,feats,meta,dev_folds,spec["params"])
            variants[name]=res
        po=_run_poisson_cv(X,labels,target,feats,meta,dev_folds)
        variants["GOAL_POISSON_LOCKED"]=po

        # Fixed 50/50 ensemble scored segment by segment.
        idx={n:i for i,n in enumerate(meta["feature_names"])};cols=[idx[n] for n in feats]
        y=_target_y(labels,target);all_y=[];all_p=[];folds_out=[]
        for tr,te,label in dev_folds:
            hp=_fit_hgb(X,y,tr,te,cols,target,DIRECT_VARIANTS["HGB_REGULARIZED_CORE"]["params"])
            p1,pb,p25=_fit_poisson_all(X,labels,tr,te,cols)
            pp={"1X2":p1,"BTTS":pb,"O25":p25}[target]
            ep=(hp+pp)/2.0
            folds_out.append({"fold":label,**_metrics(target,y[te],ep)})
            all_y.append(y[te]);all_p.append(ep)
        variants["ENSEMBLE_HGB_POISSON_LOCKED"]={"metrics":_metrics(target,np.concatenate(all_y),np.concatenate(all_p,axis=0)),"folds":folds_out}

        ranked=sorted(variants,key=lambda v:(variants[v]["metrics"]["logloss"],variants[v]["metrics"]["brier"]))
        best=ranked[0]
        out["targets"][target]={
            "locked_feature_count":len(feats),
            "variants":variants,
            "development_rank":ranked,
            "selected_for_oos":best,
            "selection_basis":"DEVELOPMENT_ONLY_LOGLOSS_THEN_BRIER",
        }
        print(f"PHASE4_DEV_MODEL_SELECTED={target}:{best}",flush=True)
    _json_atomic(path,out)
    return out


def _prior_for_fold(y,tr,target):
    if target=="1X2":
        counts=np.bincount(y[tr],minlength=3).astype(float)+1.0
        return counts/counts.sum()
    return float((y[tr].sum()+1)/(len(tr)+2))


def _oos_locked(stage,X,labels,meta,ablation,dev_models,oos_folds):
    lock_path=stage/"PHASE4_OOS_LOCK.json"
    result_path=stage/"PHASE4_LOCKED_OOS_RESULTS.json"
    pred_path=stage/"PHASE4_LOCKED_OOS_PREDICTIONS.npz"
    if result_path.is_file() and pred_path.is_file() and lock_path.is_file():
        return json.loads(result_path.read_text()),np.load(pred_path)
    lock={
        "freeze_time_utc":_utcnow(),
        "policy":"all feature-group/model choices made on TRAIN/DEVELOPMENT before OOS",
        "targets":{
            t:{
                "variant":dev_models["targets"][t]["selected_for_oos"],
                "features":ablation["targets"][t]["locked_features"],
                "feature_sha256":hashlib.sha256(("\n".join(ablation["targets"][t]["locked_features"])+"\n").encode()).hexdigest(),
            } for t in TARGETS
        },
    }
    _json_atomic(lock_path,lock)
    out={"version":"FULL7_LOCKED_OOS_1.0","oos_lock_sha256":_sha256(lock_path),"targets":{}}
    saved={}
    for target in TARGETS:
        variant=lock["targets"][target]["variant"];feats=lock["targets"][target]["features"]
        idx={n:i for i,n in enumerate(meta["feature_names"])};cols=[idx[n] for n in feats]
        y=_target_y(labels,target)
        shape=(len(y),3) if target=="1X2" else (len(y),)
        pred=np.full(shape,np.nan,dtype=np.float32)
        prior=np.full(shape,np.nan,dtype=np.float32)
        folds=[]
        for tr,te,label in oos_folds:
            if variant.startswith("HGB_"):
                p=_fit_hgb(X,y,tr,te,cols,target,DIRECT_VARIANTS[variant]["params"])
            elif variant=="GOAL_POISSON_LOCKED":
                p1,pb,p25=_fit_poisson_all(X,labels,tr,te,cols);p={"1X2":p1,"BTTS":pb,"O25":p25}[target]
            elif variant=="ENSEMBLE_HGB_POISSON_LOCKED":
                hp=_fit_hgb(X,y,tr,te,cols,target,DIRECT_VARIANTS["HGB_REGULARIZED_CORE"]["params"])
                p1,pb,p25=_fit_poisson_all(X,labels,tr,te,cols);pp={"1X2":p1,"BTTS":pb,"O25":p25}[target];p=(hp+pp)/2.0
            else:raise Phase4Error(f"unknown_locked_variant:{variant}")
            pred[te]=p
            pr=_prior_for_fold(y,tr,target)
            if target=="1X2":prior[te]=np.tile(pr,(len(te),1))
            else:prior[te]=pr
            folds.append({"fold":label,**_metrics(target,y[te],p)})
            print(f"PHASE4_LOCKED_OOS_FOLD={target}:{label}",flush=True)
        oi=np.concatenate([te for _tr,te,_label in oos_folds])
        out["targets"][target]={
            "variant":variant,
            "feature_count":len(feats),
            "oos_metrics":_metrics(target,y[oi],pred[oi]),
            "rolling_prior_metrics":_metrics(target,y[oi],prior[oi]),
            "folds":folds,
        }
        saved[f"{target}_pred"]=pred;saved[f"{target}_prior"]=prior
    np.savez_compressed(pred_path,**saved)
    out["prediction_sha256"]=_sha256(pred_path)
    _json_atomic(result_path,out)
    return out,np.load(pred_path)


def _v3_design(Xv3,leagues,tr,te):
    xtr=np.asarray(Xv3[tr],dtype=float);xte=np.asarray(Xv3[te],dtype=float)
    mean=xtr.mean(axis=0);scale=xtr.std(axis=0);scale[scale<1e-12]=1.0
    ztr=(xtr-mean)/scale;zte=(xte-mean)/scale
    cats=sorted({str(leagues[i]) for i in tr});cm={c:j for j,c in enumerate(cats)}
    a=np.zeros((len(tr),len(cats)),dtype=np.float32);b=np.zeros((len(te),len(cats)),dtype=np.float32)
    for r,i in enumerate(tr):
        j=cm.get(str(leagues[i]))
        if j is not None:a[r,j]=1
    for r,i in enumerate(te):
        j=cm.get(str(leagues[i]))
        if j is not None:b[r,j]=1
    return np.hstack([ztr,a]),np.hstack([zte,b])


def _v3_fit(Xv3,leagues,y,tr,te,target):
    a,b=_v3_design(Xv3,leagues,tr,te)
    m=SGDClassifier(loss="log_loss",penalty="l2",alpha=0.0001,max_iter=3000,tol=1e-5,random_state=42,shuffle=True)
    m.fit(a,y[tr]);raw=m.predict_proba(b)
    if target=="1X2":
        p=np.zeros((len(te),3))
        for j,c in enumerate(m.classes_):p[:,int(c)]=raw[:,j]
        return p
    cm={int(c):j for j,c in enumerate(m.classes_)}
    return raw[:,cm[1]]


def _paired_v3(stage,labels,Xv3,leagues,dev,oos_folds,oos_predictions,coverage):
    path=stage/"PHASE4_V3_PAIRED_BASELINE.json"
    if path.is_file():return json.loads(path.read_text())
    complete=np.isfinite(Xv3).all(axis=1)&np.asarray([bool(str(x)) for x in leagues])
    train_end=int(dev.min())
    train_support=np.where(complete[:train_end])[0]
    dev_support=dev[complete[dev]]
    fold_support=[(tr[complete[tr]],te[complete[te]],label) for tr,te,label in oos_folds]
    sufficient=(len(train_support)>=MIN_PAIRED_TRAIN and len(dev_support)>=MIN_PAIRED_DEV and all(len(te)>=MIN_PAIRED_FOLD for _tr,te,_ in fold_support))
    out={
        "V3_1_PAIRED_BASELINE_STATUS":"AVAILABLE" if sufficient else "INSUFFICIENT_SUPPORT",
        "train_supported":int(len(train_support)),
        "development_supported":int(len(dev_support)),
        "oos_supported_by_fold":{label:int(len(te)) for _tr,te,label in fold_support},
        "coverage_diagnostic":"PHASE4_V3_COVERAGE_DIAGNOSTIC_V2.json",
        "comparison_level":"FULLY_PAIRED_ON_AVAILABLE_ROWS" if sufficient else "HISTORICAL_REFERENCE_ONLY",
        "targets":{},
    }
    if sufficient:
        for target in TARGETS:
            y=_target_y(labels,target)
            # Development paired
            pd=_v3_fit(Xv3,leagues,y,train_support,dev_support,target)
            new_dev=None  # not used for final paired claim; DEVELOPMENT is model-selection only.
            fold_rows=[];v3_all=[];new_all=[];y_all=[]
            new_pred=oos_predictions[f"{target}_pred"]
            for tr,te,label in fold_support:
                p=_v3_fit(Xv3,leagues,y,tr,te,target)
                npair=np.asarray(new_pred[te],dtype=float)
                fold_rows.append({
                    "fold":label,"n":int(len(te)),
                    "v3":_metrics(target,y[te],p),
                    "full7_locked":_metrics(target,y[te],npair),
                })
                v3_all.append(p);new_all.append(npair);y_all.append(y[te])
            yy=np.concatenate(y_all);vp=np.concatenate(v3_all,axis=0);npred=np.concatenate(new_all,axis=0)
            out["targets"][target]={
                "development_v3":_metrics(target,y[dev_support],pd),
                "walkforward_paired_n":int(len(yy)),
                "walkforward_v3":_metrics(target,yy,vp),
                "walkforward_full7":_metrics(target,yy,npred),
                "folds":fold_rows,
            }
    _json_atomic(path,out)
    print("V3_1_PAIRED_BASELINE_STATUS="+out["V3_1_PAIRED_BASELINE_STATUS"],flush=True)
    return out


def _phase5_freeze(stage,labels,oos_result,oos_predictions,ablation,dev_models,input_info):
    path=stage/"PHASE4_PHASE5_FREEZE.json"
    cal=stage/"PHASE4_CALIBRATION_INPUT.jsonl.gz"
    if not cal.is_file():
        oi=[]
        splits=json.loads((stage/"PHASE4_SPLITS.json").read_text())
        dates=labels["dates"]
        for meta in splits["oos_folds"]:
            oi.extend(i for i,d in enumerate(dates) if meta["test_start_date"]<=str(d)<=meta["test_end_date"])
        with gzip.open(cal,"wt",encoding="utf-8") as fh:
            for i in oi:
                rec={"match_id":int(labels["match_ids"][i]),"date":str(labels["dates"][i]),"split":"walkforward_oos",
                     "actual_1x2":int(labels["y1"][i]),"actual_btts":int(labels["yb"][i]),"actual_o25":int(labels["yo"][i]),
                     "candidate_probabilities":{}}
                for t in TARGETS:
                    p=oos_predictions[f"{t}_pred"][i]
                    rec["candidate_probabilities"][t]=[float(x) for x in p] if t=="1X2" else float(p)
                fh.write(json.dumps(rec,sort_keys=True)+"\n")
    candidates={}
    for t in TARGETS:
        m=oos_result["targets"][t]["oos_metrics"];pr=oos_result["targets"][t]["rolling_prior_metrics"]
        candidates[t]={
            "variant":oos_result["targets"][t]["variant"],
            "feature_count":oos_result["targets"][t]["feature_count"],
            "oos_logloss":m["logloss"],"oos_brier":m["brier"],
            "rolling_prior_logloss":pr["logloss"],"rolling_prior_brier":pr["brier"],
            "phase5_ready":bool(m["logloss"]<pr["logloss"] and m["brier"]<pr["brier"]),
        }
    freeze={
        "freeze_version":"FULL7_PHASE5_INPUT_FREEZE_2.0",
        "created_at_utc":_utcnow(),
        "cp2_master_sha256":input_info["cp2_master_sha256"],
        "cp3_manifest_sha256":input_info["cp3_manifest_sha256"],
        "oos_lock_sha256":_sha256(stage/"PHASE4_OOS_LOCK.json"),
        "calibration_input":cal.name,
        "calibration_input_sha256":_sha256(cal),
        "candidates":candidates,
        "production_release_allowed":False,
    }
    _json_atomic(path,freeze)
    return freeze


def _network_disabled(*_a,**_k):
    raise Phase4Error("network_disabled_during_phase4")


@contextmanager
def block_network():
    with patch("socket.create_connection",_network_disabled),patch.object(socket.socket,"connect",_network_disabled),patch.object(socket.socket,"connect_ex",_network_disabled):
        yield


def run_phase4_continue(cp2_dir:Path,cp3_dir:Path,output_dir:Path):
    cp2_dir=Path(cp2_dir);cp3_dir=Path(cp3_dir);output_dir=Path(output_dir)
    if output_dir.is_dir() and (output_dir/"PHASE4_MODEL_RESEARCH.json").is_file():
        obj=json.loads((output_dir/"PHASE4_MODEL_RESEARCH.json").read_text())
        if obj.get("PHASE4_MODEL_RESEARCH")=="PASS":
            print("PHASE4_REUSE_PASS",flush=True);return obj
    stage=output_dir.parent/".phase4.stage"
    required=["PHASE4_MATRIX.npy","PHASE4_LABELS.npz","PHASE4_MATRIX_METADATA.json","PHASE4_FEATURE_SELECTION.json","PHASE4_SPLITS.json"]
    missing=[x for x in required if not (stage/x).is_file()]
    if missing:raise Phase4Error("existing_phase4_matrix_required:"+",".join(missing))
    input_info=_validate_inputs(cp2_dir,cp3_dir)
    meta=json.loads((stage/"PHASE4_MATRIX_METADATA.json").read_text());meta["_stage"]=str(stage)
    selection=json.loads((stage/"PHASE4_FEATURE_SELECTION.json").read_text())
    splits=json.loads((stage/"PHASE4_SPLITS.json").read_text())
    npz=np.load(stage/"PHASE4_LABELS.npz")
    labels={k:npz[k] for k in ("match_ids","dates","y1","yb","yo","yh","ya")}
    if len(labels["match_ids"])!=16137 or selection["selected_feature_count"]!=3774:
        raise Phase4Error("frozen_phase4_matrix_or_selection_changed")
    train,dev,oos=_split_indices(labels,splits)
    dev_folds=_dev_folds(labels,train,dev)
    X=np.load(stage/"PHASE4_MATRIX.npy",mmap_mode="r")

    recon,Xv3,leagues=_reconstruct_v3_only(cp2_dir/"FULL7_MASTER_STRICT.jsonl",stage,labels["match_ids"])
    coverage=_coverage_diagnostic(stage,labels,splits,Xv3,leagues,train,dev,oos)
    screening=_screen_scores(X,labels,train,meta,selection)
    print("PHASE4_TRAINING_STARTED=true",flush=True)
    ablation=_dev_group_ablation(stage,X,labels,meta,selection,screening,dev_folds)
    dev_models=_development_models(stage,X,labels,meta,ablation,dev_folds)
    oos_result,oos_predictions=_oos_locked(stage,X,labels,meta,ablation,dev_models,oos)
    paired=_paired_v3(stage,labels,Xv3,leagues,dev,oos,oos_predictions,coverage)
    freeze=_phase5_freeze(stage,labels,oos_result,oos_predictions,ablation,dev_models,input_info)

    hist={
        "comparison_type":"HISTORICAL_NON_PAIRED_REFERENCE_ONLY",
        "1X2":{"logloss":1.0396850943631781,"brier":0.6225651144475047},
        "O25":{"logloss":0.685542350878984,"brier":0.24609469841197407},
        "BTTS":{"logloss":0.6884483008570162,"brier":0.24759332465487544},
    }
    report={
        "PHASE4_MODEL_RESEARCH":"PASS",
        "status":"COMPLETE",
        "phase4_continuation_version":CONTINUATION_VERSION,
        "completed_at_utc":_utcnow(),
        "FULL7_RESEARCH_DATASET_MATCHES":16137,
        "structural_feature_pool":3774,
        "cp2_rebuilt":False,"cp3_rebuilt":False,"collection_performed":False,"api_calls_performed":False,
        "V3_1_COVERAGE_TRAIN":coverage["splits"]["TRAIN"],
        "V3_1_COVERAGE_DEVELOPMENT":coverage["splits"]["DEVELOPMENT"],
        "V3_1_COVERAGE_OOS_BY_FOLD":{k:v for k,v in coverage["splits"].items() if k.startswith("OOS")},
        "TOP_LIMITING_V3_INPUTS":coverage["top_limiting_inputs"][:10],
        "V3_INPUT_RECONSTRUCTABLE_FROM_FROZEN_DATA":[k for k,v in coverage["input_availability"].items() if v["classification"].startswith("A_")],
        "V3_INPUT_NOT_AVAILABLE_FROM_FROZEN_DATA":[k for k,v in coverage["input_availability"].items() if v["classification"].startswith("B_")],
        "V3_1_PAIRED_BASELINE_STATUS":paired["V3_1_PAIRED_BASELINE_STATUS"],
        "V3_COMPARISON_MODE":paired["comparison_level"],
        "historical_v3_reference":hist,
        "feature_group_ablation":"PHASE4_GROUP_ABLATIONS_DEVELOPMENT.json",
        "development_model_comparison":"PHASE4_DEVELOPMENT_MODEL_COMPARISON.json",
        "oos_lock":"PHASE4_OOS_LOCK.json",
        "locked_oos_results":oos_result,
        "paired_v3_results":paired,
        "phase5_freeze":freeze,
        "production_release_allowed":False,
        "next_phase":"PHASE 5 — CALIBRATION only for phase5_ready candidates",
    }
    _json_atomic(stage/"PHASE4_MODEL_RESEARCH.json",report)
    _manifest(stage)
    if output_dir.exists():
        raise Phase4Error("phase4_output_appeared_before_publish")
    stage.rename(output_dir)
    print("PHASE4_MODEL_RESEARCH=PASS",flush=True)
    print("PHASE4_FINAL="+json.dumps({
        "V3_1_PAIRED_BASELINE_STATUS":paired["V3_1_PAIRED_BASELINE_STATUS"],
        "V3_COMPARISON_MODE":paired["comparison_level"],
        "candidates":freeze["candidates"],
        "manifest_sha256":_sha256(output_dir/"PHASE4_MANIFEST.json"),
    },sort_keys=True),flush=True)
    return report


def run_phase4_continue_offline(cp2_dir:Path,cp3_dir:Path,output_dir:Path):
    with block_network():
        return run_phase4_continue(cp2_dir,cp3_dir,output_dir)
