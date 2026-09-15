from __future__ import annotations

import math
from typing import Dict, Iterable, List, Mapping, Sequence, Tuple


MAX_GOALS = 12


def _poisson(lam: float, k: int) -> float:
    lam=max(0.03,min(8.0,float(lam)))
    return math.exp(-lam)*(lam**k)/math.factorial(k)


def dixon_coles_tau(home_goals:int,away_goals:int,lambda_home:float,lambda_away:float,rho:float)->float:
    lh=max(0.03,float(lambda_home))
    la=max(0.03,float(lambda_away))
    if home_goals==0 and away_goals==0:
        return 1.0-lh*la*rho
    if home_goals==0 and away_goals==1:
        return 1.0+lh*rho
    if home_goals==1 and away_goals==0:
        return 1.0+la*rho
    if home_goals==1 and away_goals==1:
        return 1.0-rho
    return 1.0


def score_matrix(lambda_home:float,lambda_away:float,rho:float=0.0,max_goals:int=MAX_GOALS)->List[List[float]]:
    lh=max(0.03,min(8.0,float(lambda_home)))
    la=max(0.03,min(8.0,float(lambda_away)))
    matrix=[]
    total=0.0
    for h in range(max_goals+1):
        row=[]
        for a in range(max_goals+1):
            p=_poisson(lh,h)*_poisson(la,a)
            p*=dixon_coles_tau(h,a,lh,la,float(rho))
            p=max(1e-15,p)
            row.append(p)
            total+=p
        matrix.append(row)
    return [[p/total for p in row] for row in matrix]


def market_probabilities(lambda_home:float,lambda_away:float,rho:float=0.0,max_goals:int=MAX_GOALS)->Dict[str,float]:
    m=score_matrix(lambda_home,lambda_away,rho,max_goals)
    home=sum(m[h][a] for h in range(max_goals+1) for a in range(max_goals+1) if h>a)
    draw=sum(m[g][g] for g in range(max_goals+1))
    away=sum(m[h][a] for h in range(max_goals+1) for a in range(max_goals+1) if h<a)
    btts_yes=sum(m[h][a] for h in range(1,max_goals+1) for a in range(1,max_goals+1))
    over25=sum(m[h][a] for h in range(max_goals+1) for a in range(max_goals+1) if h+a>=3)
    return {
        "home_win":home,
        "draw":draw,
        "away_win":away,
        "btts_yes":btts_yes,
        "btts_no":1.0-btts_yes,
        "over_2_5":over25,
        "under_2_5":1.0-over25,
    }


def score_nll(home_goals:int,away_goals:int,lambda_home:float,lambda_away:float,rho:float)->float:
    m=score_matrix(lambda_home,lambda_away,rho)
    h=min(MAX_GOALS,max(0,int(home_goals)))
    a=min(MAX_GOALS,max(0,int(away_goals)))
    return -math.log(max(1e-15,m[h][a]))


def learn_rho(
    actual_scores:Sequence[Tuple[int,int]],
    lambdas:Sequence[Tuple[float,float]],
    candidates:Iterable[float]|None=None,
)->Dict[str,float]:
    if len(actual_scores)!=len(lambdas) or not actual_scores:
        raise ValueError("actual_scores and lambdas must be non-empty and aligned")
    if candidates is None:
        candidates=[-0.30+i*0.025 for i in range(17)]
    best_rho=0.0
    best_nll=float("inf")
    for rho in candidates:
        nll=sum(
            score_nll(h,a,lh,la,float(rho))
            for (h,a),(lh,la) in zip(actual_scores,lambdas)
        )/len(actual_scores)
        if nll<best_nll:
            best_nll=nll
            best_rho=float(rho)
    return {"rho":best_rho,"mean_score_nll":best_nll,"n":len(actual_scores)}
