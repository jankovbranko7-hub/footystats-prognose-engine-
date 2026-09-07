"""Standalone V1 Dixon-Coles score distribution.

This module is owned by V1 and does not import any V0.4.x engine.
"""
from __future__ import annotations
import math
from typing import Dict

RHO = -0.25
VERSION = "V1"


def dixon_coles(home_lambda: float, away_lambda: float, cap: int = 10) -> Dict[str, float]:
    hl=float(home_lambda); al=float(away_lambda)
    if not (math.isfinite(hl) and math.isfinite(al)) or hl <= 0 or al <= 0:
        raise ValueError("Dixon-Coles benötigt positive endliche Lambdas.")
    ph=[math.exp(-hl)*hl**i/math.factorial(i) for i in range(cap+1)]
    pa=[math.exp(-al)*al**j/math.factorial(j) for j in range(cap+1)]
    def tau(i,j):
        if i==0 and j==0:return 1.0-hl*al*RHO
        if i==0 and j==1:return 1.0+hl*RHO
        if i==1 and j==0:return 1.0+al*RHO
        if i==1 and j==1:return 1.0-RHO
        return 1.0
    cells=[]; mass=0.0
    for i,px in enumerate(ph):
        for j,py in enumerate(pa):
            q=px*py*tau(i,j)
            if q < 0: raise ValueError("Dixon-Coles rho erzeugt negative Score-Wahrscheinlichkeit.")
            cells.append((i,j,q)); mass += q
    if mass <= 0: raise ValueError("Dixon-Coles Scoregrid hat keine positive Masse.")
    hw=dr=aw=btts=o25=0.0
    for i,j,raw in cells:
        q=raw/mass
        if i>j: hw+=q
        elif i==j: dr+=q
        else: aw+=q
        if i and j: btts+=q
        if i+j>=3: o25+=q
    return {"home_win":hw,"draw":dr,"away_win":aw,"btts_yes":btts,"btts_no":1.0-btts,"over_2_5":o25,"under_2_5":1.0-o25}
