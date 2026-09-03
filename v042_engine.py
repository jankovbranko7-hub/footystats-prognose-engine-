"""V0.4.2 production: V0.4.1 hybrid lambda engine + Dixon-Coles scoregrid.

This release changes only the score-distribution layer. The five-source V0.4.1
lambda construction, evidence blocks and decision gates stay unchanged so the
137-match validation isolates the effect of Dixon-Coles.
"""
from __future__ import annotations

import math
from typing import Any, Dict

import v041_engine

VERSION = "0.4.2"
RHO = -0.25


def dixon_coles(hl: float, al: float, cap: int = 10) -> Dict[str, float]:
    """Dixon-Coles low-score correction on an independent Poisson scoregrid."""
    hl = float(hl); al = float(al)
    if not (math.isfinite(hl) and math.isfinite(al)) or hl <= 0 or al <= 0:
        raise ValueError("Dixon-Coles benötigt positive endliche Lambdas.")

    ph = [math.exp(-hl) * hl ** i / math.factorial(i) for i in range(cap + 1)]
    pa = [math.exp(-al) * al ** j / math.factorial(j) for j in range(cap + 1)]

    def tau(i: int, j: int) -> float:
        if i == 0 and j == 0:
            return 1.0 - hl * al * RHO
        if i == 0 and j == 1:
            return 1.0 + hl * RHO
        if i == 1 and j == 0:
            return 1.0 + al * RHO
        if i == 1 and j == 1:
            return 1.0 - RHO
        return 1.0

    cells = []
    mass = 0.0
    for i, px in enumerate(ph):
        for j, py in enumerate(pa):
            q = px * py * tau(i, j)
            if q < 0:
                raise ValueError("Dixon-Coles rho erzeugt negative Score-Wahrscheinlichkeit.")
            cells.append((i, j, q)); mass += q
    if mass <= 0:
        raise ValueError("Dixon-Coles Scoregrid hat keine positive Masse.")

    hw = dr = aw = btts = o25 = 0.0
    for i, j, raw in cells:
        q = raw / mass
        if i > j: hw += q
        elif i == j: dr += q
        else: aw += q
        if i and j: btts += q
        if i + j >= 3: o25 += q

    return {
        "home_win": hw,
        "draw": dr,
        "away_win": aw,
        "btts_yes": btts,
        "btts_no": 1.0 - btts,
        "over_2_5": o25,
        "under_2_5": 1.0 - o25,
    }


def _replace_strings(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _replace_strings(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_replace_strings(v) for v in value]
    if isinstance(value, str):
        return (value.replace("0.4.1", VERSION)
                     .replace("V0.4.1", "V0.4.2")
                     .replace("Hybrid-Poisson-Core", "Hybrid-Lambda + Dixon-Coles-Core")
                     .replace("Hybrid-Core + Five-Source Decision Engine", "Hybrid-Lambda + Dixon-Coles + Five-Source Decision Engine"))
    return value


def apply_patch(legacy: Any) -> Any:
    # V0.4.1 resolves legacy.poisson at prediction time, so swapping this one
    # function changes both the main scoregrid and every removal-stress grid.
    legacy.poisson = dixon_coles
    app = v041_engine.apply_patch(legacy)

    predict_v041 = legacy.predict
    attach_v041 = legacy._attach_supplemental
    protocol_v041 = legacy.elite_protocol_report

    def predict_v042(match: Any, league: Any) -> Dict[str, Any]:
        out = _replace_strings(predict_v041(match, league))
        out["model_version"] = VERSION
        method = dict(out.get("method") or {})
        method.update({
            "score_distribution": "Dixon-Coles",
            "dixon_coles_rho": RHO,
            "dixon_coles_low_score_correction": True,
            "release_status": "production",
        })
        out["method"] = method
        model = (((out.get("expected_goals") or {}).get("league_relative_model")) or {})
        if isinstance(model, dict):
            model["dixon_coles_fitted"] = True
            model["dixon_coles_rho"] = RHO
            model["method"] = "V0.4.2 hybrid lambdas + Dixon-Coles scoregrid"
        out.setdefault("notes", [])
        out["notes"] = [n for n in out["notes"] if "V0.4.1" not in str(n)] + [
            "V0.4.2 Dixon-Coles Produktion aktiv; Lambda-Core und Five-Source Gates entsprechen V0.4.1.",
            f"Dixon-Coles rho={RHO:.2f}; Low-Score-Zellen 0:0, 0:1, 1:0, 1:1 werden korrigiert.",
        ]
        return out

    def protocol_v042(result: Dict[str, Any], report: Dict[str, Any]) -> Dict[str, Any]:
        out = _replace_strings(protocol_v041(result, report))
        out["version"] = "0.4.2 / Hybrid-Lambda + Dixon-Coles + Five-Source Decision Engine"
        out["score_model"] = {"distribution": "Dixon-Coles", "rho": RHO, "base_lambdas": "V0.4.1 hybrid"}
        return out

    def attach_v042(result: Dict[str, Any], report: Dict[str, Any], source_files: Dict[str, str]) -> Dict[str, Any]:
        out = _replace_strings(attach_v041(result, report, source_files))
        out["model_version"] = VERSION
        return out

    legacy.predict = predict_v042
    legacy.elite_protocol_report = protocol_v042
    legacy._attach_supplemental = attach_v042
    legacy.app.version = VERSION
    legacy.app.title = "FootyStats Prognose Engine V0.4.2 Dixon-Coles"
    legacy.INDEX_HTML = legacy.INDEX_HTML.replace("FootyStats Prognose Engine v0.4.1", "FootyStats Prognose Engine v0.4.2 Dixon-Coles")
    legacy.INDEX_HTML = legacy.INDEX_HTML.replace("V0.4.1 Hybrid-Core", "V0.4.2 Dixon-Coles")

    legacy.app.router.routes = [route for route in legacy.app.router.routes if getattr(route, "path", None) != "/api/health"]
    def health() -> Dict[str, Any]:
        return {"ok": True, "version": VERSION, "engine": "five-source-hybrid-dixon-coles", "rho": RHO, "production": True, "backup": "v0.4.1"}
    legacy.app.add_api_route("/api/health", health, methods=["GET"])
    return app
