"""Development-only temporal research runner for FULL-7.

Not imported by production app.py. Requires optional research dependencies from
requirements-research.txt. It consumes model-ready rows produced by the FULL-7
dataset pipeline and evaluates strictly forward date blocks.
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from typing import Any, Dict, List, Mapping, Sequence, Tuple

import numpy as np
from catboost import CatBoostClassifier
from sklearn.metrics import accuracy_score, brier_score_loss, log_loss

from full7_feature_sets import build_feature_sets


RESEARCH_VERSION = "FULL7_PREQUENTIAL_RESEARCH_0.2"


def _date(row: Mapping[str, Any]) -> str:
    value = row.get("kickoff_at_utc")
    if isinstance(value, str) and len(value) >= 10:
        return value[:10]
    raise ValueError("row missing kickoff_at_utc ISO date")


def _target_1x2(row: Mapping[str, Any]) -> int:
    t=row.get("targets") or {}
    if int(t.get("home_win",0))==1:return 0
    if int(t.get("draw",0))==1:return 1
    if int(t.get("away_win",0))==1:return 2
    raise ValueError("invalid 1X2 target")


def _matrix(rows: Sequence[Mapping[str,Any]], feature_names: Sequence[str]) -> np.ndarray:
    X=np.full((len(rows),len(feature_names)),np.nan,dtype=float)
    for i,row in enumerate(rows):
        features=row.get("features") or {}
        for j,name in enumerate(feature_names):
            value=features.get(name)
            if value is None or isinstance(value,bool):
                continue
            try:
                x=float(value)
            except (TypeError,ValueError):
                continue
            if math.isfinite(x):
                X[i,j]=x
    return X


def _multiclass_brier(y: np.ndarray, p: np.ndarray) -> float:
    return float(np.mean(np.sum((p-np.eye(3)[y])**2,axis=1)))


def _poisson_probability(lambda_home: float, lambda_away: float) -> Tuple[np.ndarray,float,float]:
    max_goals=12
    def pois(lam:int|float,k:int)->float:
        return math.exp(-lam)*(lam**k)/math.factorial(k)
    ph=np.array([pois(lambda_home,k) for k in range(max_goals+1)])
    pa=np.array([pois(lambda_away,k) for k in range(max_goals+1)])
    matrix=np.outer(ph,pa)
    matrix/=matrix.sum()
    home=float(np.tril(matrix,-1).sum())
    draw=float(np.trace(matrix))
    away=float(np.triu(matrix,1).sum())
    btts=float(matrix[1:,1:].sum())
    over25=float(sum(matrix[i,j] for i in range(max_goals+1) for j in range(max_goals+1) if i+j>=3))
    return np.array([home,draw,away]),btts,over25


def run_prequential_research(
    rows: Sequence[Mapping[str,Any]],
    *,
    seed_date_blocks: int = 4,
) -> Dict[str,Any]:
    """Evaluate fixed CatBoost specialists on future-only date blocks.

    This function is deliberately a research benchmark. It does not choose a
    release threshold and does not treat its own evaluation data as untouched
    final OOS after the results are inspected.
    """
    rows=sorted((dict(r) for r in rows),key=lambda r:(r["kickoff_unix"],r["match_id"]))
    dates=sorted({_date(r) for r in rows})
    if len(dates)<=seed_date_blocks:
        raise ValueError("not enough date blocks for prequential evaluation")

    # Prefer the exact frozen feature list carried by a dataset export. This
    # prevents a research replay from silently reclassifying features when only
    # partial owner metadata is present.
    core=list(rows[0].get("core_features") or [])
    if not core:
        first={
            "features":rows[0].get("features") or {},
            "feature_owners":rows[0].get("feature_owners") or {},
        }
        sets=build_feature_sets(first)
        core=list(sets["core_probability"])
    if not core:
        raise ValueError("no deterministic core feature set")

    frozen=set(core)
    for row in rows[1:]:
        carried=row.get("core_features")
        if carried is not None and set(carried)!=frozen:
            raise ValueError("mixed frozen core feature sets in one research run")

    X=_matrix(rows,core)
    y1=np.array([_target_1x2(r) for r in rows],dtype=int)
    yb=np.array([int((r.get("targets") or {})["btts_yes"]) for r in rows],dtype=int)
    yo=np.array([int((r.get("targets") or {})["over_2_5"]) for r in rows],dtype=int)
    row_dates=np.array([_date(r) for r in rows])

    params=dict(
        iterations=250,
        depth=4,
        learning_rate=0.03,
        l2_leaf_reg=20.0,
        random_strength=1.0,
        random_seed=42,
        verbose=False,
        allow_writing_files=False,
        thread_count=4,
    )

    predictions=[]
    folds=[]
    for date in dates[seed_date_blocks:]:
        train=np.where(row_dates<date)[0]
        test=np.where(row_dates==date)[0]
        if not len(train) or not len(test):
            continue

        m1=CatBoostClassifier(loss_function="MultiClass",**params).fit(X[train],y1[train])
        mb=CatBoostClassifier(loss_function="Logloss",**params).fit(X[train],yb[train])
        mo=CatBoostClassifier(loss_function="Logloss",**params).fit(X[train],yo[train])

        p1_raw=m1.predict_proba(X[test])
        p1=np.zeros((len(test),3))
        for col,cls in enumerate(m1.classes_):
            p1[:,int(cls)]=p1_raw[:,col]
        pb=mb.predict_proba(X[test])[:,1]
        po=mo.predict_proba(X[test])[:,1]

        folds.append({
            "date":date,
            "train_rows":len(train),
            "test_rows":len(test),
            "1x2_logloss":float(log_loss(y1[test],p1,labels=[0,1,2])),
            "btts_logloss":float(log_loss(yb[test],pb,labels=[0,1])),
            "over25_logloss":float(log_loss(yo[test],po,labels=[0,1])),
        })

        prior1=(np.bincount(y1[train],minlength=3)+1.0)
        prior1=prior1/prior1.sum()
        prior_b=(yb[train].sum()+1)/(len(train)+2)
        prior_o=(yo[train].sum()+1)/(len(train)+2)

        for pos,idx in enumerate(test):
            rec={
                "match_id":int(rows[idx]["match_id"]),
                "date":date,
                "actual_1x2":int(y1[idx]),
                "actual_btts":int(yb[idx]),
                "actual_over25":int(yo[idx]),
                "catboost_1x2":p1[pos].tolist(),
                "catboost_btts":float(pb[pos]),
                "catboost_over25":float(po[pos]),
                "rolling_prior_1x2":prior1.tolist(),
                "rolling_prior_btts":float(prior_b),
                "rolling_prior_over25":float(prior_o),
            }
            lh=(rows[idx].get("features") or {}).get("prematch_xg_home")
            la=(rows[idx].get("features") or {}).get("prematch_xg_away")
            if lh is not None and la is not None:
                pp1,ppb,ppo=_poisson_probability(float(lh),float(la))
                rec["poisson_1x2"]=pp1.tolist()
                rec["poisson_btts"]=ppb
                rec["poisson_over25"]=ppo
            predictions.append(rec)

    a1=np.array([r["actual_1x2"] for r in predictions])
    ab=np.array([r["actual_btts"] for r in predictions])
    ao=np.array([r["actual_over25"] for r in predictions])
    c1=np.array([r["catboost_1x2"] for r in predictions])
    cb=np.array([r["catboost_btts"] for r in predictions])
    co=np.array([r["catboost_over25"] for r in predictions])

    return {
        "research_version":RESEARCH_VERSION,
        "seed_dates":dates[:seed_date_blocks],
        "evaluation_dates":dates[seed_date_blocks:],
        "evaluation_rows":len(predictions),
        "core_feature_count":len(core),
        "folds":folds,
        "catboost":{
            "1x2_logloss":float(log_loss(a1,c1,labels=[0,1,2])),
            "1x2_accuracy":float(accuracy_score(a1,c1.argmax(axis=1))),
            "1x2_brier":_multiclass_brier(a1,c1),
            "btts_logloss":float(log_loss(ab,cb,labels=[0,1])),
            "btts_accuracy":float(accuracy_score(ab,cb>=0.5)),
            "btts_brier":float(brier_score_loss(ab,cb)),
            "over25_logloss":float(log_loss(ao,co,labels=[0,1])),
            "over25_accuracy":float(accuracy_score(ao,co>=0.5)),
            "over25_brier":float(brier_score_loss(ao,co)),
        },
        "predictions":predictions,
        "policy":{
            "shuffle":False,
            "date_block_prequential":True,
            "manual_mix_weights":False,
            "odds":False,
            "provider_potentials_core":False,
            "h2h_core":False,
            "final_oos":False,
        },
    }
