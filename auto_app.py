from __future__ import annotations

from fastapi import Query
from fastapi.responses import JSONResponse

import app as core_app
from app import app
from elite_fusion import attach_forebet_elite
from forebet_auto import ForebetAutoError
from forebet_auto_final import build_snapshot, debug_match, health
from forebet_auto_v6_debug import debug_direct
from forebet_debug import debug_pages

# Keep the fully working Luzern/Vaduz AUTO data-acquisition path unchanged.
# Only replace the existing v0.6.0 fusion function in this test service with
# the reliability-weighted Elite fusion.
core_app._attach_forebet_ensemble = attach_forebet_elite
app.version = "0.6.1-elite-fusion"
core_app.INDEX_HTML = (
    core_app.INDEX_HTML
    .replace("FootyStats + Forebet Super Analyse v0.6.0", "FootyStats + Forebet Elite Fusion v0.6.1")
    .replace("FootyStats-V5.5-Kern + Forebet-Konsensmodell", "FootyStats-V5.5-Kern + datenqualitätsgewichtete Forebet-Fusion")
)


@app.get("/api/elite-fusion/health")
def elite_fusion_health():
    return {
        "ok": True,
        "active": True,
        "version": "0.6.1-elite-fusion",
        "method": "reliability-weighted-log-pool",
        "equal_weight_50_50": False,
        "odds_used": False,
        "stable_v0_4_0_untouched": True,
        "forebet_acquisition": "known-good-3a1d12f",
    }


@app.get("/api/forebet-auto/health")
def forebet_auto_health():
    return health()


@app.get("/api/forebet-auto/debug-pages")
def forebet_auto_debug_pages(
    date: str | None = Query(default=None),
    force: bool = Query(default=False),
):
    try:
        return debug_pages(date=date, force=force)
    except ForebetAutoError as exc:
        return JSONResponse(
            status_code=422,
            content={
                "ok": False,
                "phase": "FOREBET_BROWSER_DEBUG_FAILED",
                "error": str(exc),
                "date": date,
            },
        )


@app.get("/api/forebet-auto/debug-direct")
def forebet_auto_debug_direct(
    home: str = Query(..., min_length=1),
    away: str = Query(..., min_length=1),
    date: str | None = Query(default=None),
):
    try:
        return debug_direct(home=home, away=away, date=date)
    except ForebetAutoError as exc:
        return JSONResponse(
            status_code=422,
            content={
                "ok": False,
                "phase": "FOREBET_DIRECT_DEBUG_FAILED",
                "error": str(exc),
                "home": home,
                "away": away,
                "date": date,
            },
        )


@app.get("/api/forebet-auto/debug")
def forebet_auto_debug(
    home: str = Query(..., min_length=1),
    away: str = Query(..., min_length=1),
    date: str | None = Query(default=None),
    force: bool = Query(default=False),
):
    try:
        return debug_match(home=home, away=away, date=date, force=force)
    except ForebetAutoError as exc:
        return JSONResponse(
            status_code=422,
            content={
                "ok": False,
                "phase": "FOREBET_AUTO_DEBUG_FAILED",
                "error": str(exc),
                "home": home,
                "away": away,
            },
        )


@app.get("/api/forebet-auto")
def forebet_auto(
    match_id: int = Query(..., ge=1),
    home: str = Query(..., min_length=1),
    away: str = Query(..., min_length=1),
    date: str | None = Query(default=None),
    force: bool = Query(default=False),
):
    try:
        return build_snapshot(match_id=match_id, home=home, away=away, date=date, force=force)
    except ForebetAutoError as exc:
        return JSONResponse(
            status_code=422,
            content={
                "ok": False,
                "phase": "FOREBET_AUTO_FAILED",
                "error": str(exc),
                "match_id": match_id,
                "home": home,
                "away": away,
            },
        )
