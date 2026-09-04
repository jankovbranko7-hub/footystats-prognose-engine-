"""V0.4.3 FULL-5 production parameter lock.

Keeps the V0.4.2 hybrid lambda as the base, applies the selectively validated
FULL-5 regularized Poisson layer, then uses the unchanged Dixon-Coles grid.
The separate experimental Elite-Lambda correction is intentionally NOT used.
"""
from __future__ import annotations
from typing import Any, Dict

import v043_engine as engine

VERSION = "0.4.3"
FULL5_ALPHA = 3.0

# Refit on all 137 strict pre-match archives (274 team-side rows) after
# competition-grouped nested CV selected alpha=3 as the modal/median setting.
engine.FULL5_ALPHA = FULL5_ALPHA
engine.FULL5_MEAN = [0.3597050204326385, 0.5, 1.4796715328467154, 1.336824817518248, 1.336824817518248, 1.4708394160583942, 1.3833576642335765, 1.4868248175182481, 1.4537956204379563, 95.2359489051095, 47.78631386861314, 12.90978102189781, 4.384051094890511, 0.34442362939773496, 0.08748175182481752, 0.03302919708029195, 1.4927007299270072, 1.3974452554744525, 1.4631386861313869, 4.529963503649635, 1.4513868613138685, 1.4043795620437958, 0.005802919708029196, -0.014233576642335764, 0.0032846715328467197, 0.04740875912408761, 0.029999999999999995, 0.013138686131386863, 1.3585401459854014, 1.3585401459854014, 11.218978102189782, 11.218978102189782, 1.3834051094890512, 1.4538321167883212, 0.13156204379562045, 0.09215693430656935, 98.99270072992701, 0.13156204379562045, 0.09215693430656935, 98.99270072992701]
engine.FULL5_SCALE = [0.2537271686379997, 0.5, 0.47854962764997294, 1.017502197116014, 1.017502197116014, 0.4812791158480532, 0.9978976275129648, 0.4946175164298908, 1.07622558307924, 20.469128241351484, 15.923365512954563, 4.754244429773673, 2.0443229237005136, 0.12258901834199282, 0.9009588614942196, 0.9428385193659015, 0.29090847796895114, 0.5180966417713164, 0.5799499749692959, 1.1767828524752115, 0.2510697767953675, 0.4850868856087425, 0.17927340533411096, 0.4194821670913384, 0.3991187546031719, 0.8596304167221717, 0.18287844473159012, 0.408811258406289, 1.0560334199989712, 1.0560334199989712, 6.423287159533431, 6.423287159533431, 0.9978865989447173, 1.076096931903313, 0.06926183909590466, 0.05514474158891393, 3.2799130982901414, 0.06926183909590466, 0.05514474158891393, 3.2799130982901414]
engine.FULL5_COEF = [0.029321263872944918, 0.016807821059201474, 0.017518846246883667, 0.022893946636247078, 0.0008056228033539791, 0.014589043691197618, 0.002475805287896291, 0.02502735781213671, 0.008828195843686465, 0.021325156439372186, -0.0077096251099305945, 0.022687170877703923, 0.007564249624516097, -0.0026647526049011845, 0.0050510650600018, 0.0030523141400370054, 0.03107624959894226, -0.008441580865262475, 0.034752040947524564, 0.024871673748488837, 0.032238209316503334, 0.020445010155219136, -0.0159610468889025, -0.00152279841492525, 0.03409539710597407, 0.010062825406572194, -0.003134611022987816, -0.0022680482321938045, 0.022644445232523708, -0.0011254692534697212, -0.029622748139290587, -0.02123740928643949, 0.0024773370732830836, 0.00885589340010667, 0.006391664348285519, 0.021974088392828925, 0.008452149321463648, 0.007716044387547451, -0.0007183149050051366, 0.0089266104667745]
engine.FULL5_INTERCEPT = 0.44827477453213127

if not (
    len(engine.FULL5_FEATURES)
    == len(engine.FULL5_MEAN)
    == len(engine.FULL5_SCALE)
    == len(engine.FULL5_COEF)
    == engine.FEATURE_COUNT
):
    raise RuntimeError("V0.4.3 FULL-5 production parameter lengths are inconsistent.")


def apply_patch(legacy: Any) -> Any:
    app = engine.apply_patch(legacy)

    predict_candidate = legacy.predict

    def predict_production(match: Any, league: Any) -> Dict[str, Any]:
        out = predict_candidate(match, league)
        if isinstance(out, dict):
            out["model_version"] = VERSION
            method = dict(out.get("method") or {})
            method["release_status"] = "production"
            method["full5_alpha"] = FULL5_ALPHA
            method["elite_lambda_correction"] = False
            out["method"] = method
            notes = list(out.get("notes") or [])
            notes = [
                str(n).replace(
                    "V0.4.3 FULL-5 Kandidat aktiv",
                    "V0.4.3 FULL-5 Produktion aktiv",
                )
                for n in notes
            ]
            out["notes"] = notes
        return out

    legacy.predict = predict_production

    legacy.app.router.routes = [
        route
        for route in legacy.app.router.routes
        if getattr(route, "path", None) != "/api/health"
    ]

    def health() -> Dict[str, Any]:
        return {
            "ok": True,
            "version": VERSION,
            "engine": "five-source-full5-regularized-dixon-coles",
            "rho": engine.v042_engine.RHO,
            "full5_features": engine.FEATURE_COUNT,
            "alpha": FULL5_ALPHA,
            "production": True,
            "candidate": False,
            "baseline": "v0.4.2",
            "elite_lambda_correction": False,
        }

    legacy.app.add_api_route("/api/health", health, methods=["GET"])
    legacy.app.version = VERSION
    legacy.app.title = "FootyStats Prognose Engine V0.4.3 FULL-5 Production"
    return app
