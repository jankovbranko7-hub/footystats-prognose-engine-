"""V1-owned compatibility adapter for the copied decision core.

No production V0.4.x module is imported. The adapter exposes the same patch surface
needed by the V1-owned probability-core seed while using V1's own Dixon-Coles code.
"""
from __future__ import annotations
from typing import Any, Dict
import v1_decision_core
from v1_score_core import dixon_coles, RHO

VERSION="V1"


def _replace_strings(value: Any) -> Any:
    if isinstance(value,dict): return {k:_replace_strings(v) for k,v in value.items()}
    if isinstance(value,list): return [_replace_strings(v) for v in value]
    if isinstance(value,str):
        return value.replace("0.4.1","V1").replace("V0.4.1","V1")
    return value


def apply_patch(legacy: Any) -> Any:
    legacy.poisson=dixon_coles
    app=v1_decision_core.apply_patch(legacy)
    predict_prev=legacy.predict
    attach_prev=legacy._attach_supplemental
    protocol_prev=legacy.elite_protocol_report

    def predict_v1(match: Any, league: Any) -> Dict[str,Any]:
        out=_replace_strings(predict_prev(match,league)); out["model_version"]="V1"
        method=dict(out.get("method") or {}); method.update({"score_distribution":"Dixon-Coles","dixon_coles_rho":RHO,"engine_line":"V1"}); out["method"]=method
        return out
    def protocol_v1(result:Dict[str,Any],report:Dict[str,Any])->Dict[str,Any]:
        out=_replace_strings(protocol_prev(result,report)); out["version"]="V1 / Dixon-Coles + V1 Decision Core"; out["score_model"]={"distribution":"Dixon-Coles","rho":RHO,"owner":"V1"}; return out
    def attach_v1(result:Dict[str,Any],report:Dict[str,Any],source_files:Dict[str,str])->Dict[str,Any]:
        out=_replace_strings(attach_prev(result,report,source_files)); out["model_version"]="V1"; return out
    legacy.predict=predict_v1; legacy.elite_protocol_report=protocol_v1; legacy._attach_supplemental=attach_v1
    legacy.app.version="V1"; legacy.app.title="FootyStats V1"
    return app
