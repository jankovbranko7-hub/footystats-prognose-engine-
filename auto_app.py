from __future__ import annotations

from fastapi import Query
from fastapi.responses import JSONResponse

from app import app
from forebet_auto import ForebetAutoError
from forebet_auto_v3 import build_snapshot, debug_match, health
from forebet_debug import debug_pages


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
