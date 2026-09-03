from __future__ import annotations

import concurrent.futures as _futures

from fastapi import Query
from fastapi.responses import JSONResponse

import app as _app_module
from app import app
from forebet_auto import ForebetAutoError
import forebet_auto_v5 as _forebet_v5

# The iPhone final POST must finish before Shortcuts aborts the request. The
# Forebet repair can perform up to three sequential external attempts (actor,
# date-page browser, same-day fallback), so keep each attempt tightly bounded.
_forebet_v5._FAST_APIFY_API_TIMEOUT = 5
_forebet_v5._FAST_APIFY_SOCKET_TIMEOUT = 6

from forebet_auto_v5 import build_snapshot, debug_match, health
from forebet_debug import debug_pages


# Hard wall-clock budget for the complete server-side Forebet repair. Per-call
# network timeouts alone are not enough because actor/browser/fallback can run
# sequentially. The final iOS POST must always return a saveable JSON archive.
_IOS_REPAIR_TOTAL_TIMEOUT_SECONDS = 8
_REPAIR_EXECUTOR = _futures.ThreadPoolExecutor(
    max_workers=2,
    thread_name_prefix="forebet-ios-repair",
)
_ORIGINAL_REPAIR = _app_module._repair_forebet_from_match_data


def _bounded_repair_forebet_from_match_data(match_data, forebet_data):
    future = _REPAIR_EXECUTOR.submit(_ORIGINAL_REPAIR, match_data, forebet_data)
    try:
        return future.result(timeout=_IOS_REPAIR_TOTAL_TIMEOUT_SECONDS)
    except _futures.TimeoutError:
        match = _app_module.mf(match_data)
        match_id = int(match.get("match_id") or 0)
        home = str(match.get("home_name") or "").strip()
        away = str(match.get("away_name") or "").strip()
        match_date = _app_module._forebet_match_date(match_data)
        return {
            "ok": False,
            "schema": "forebet-auto-error-v1",
            "phase": "FOREBET_SERVER_REPAIR_TIMEOUT",
            "error": (
                "Forebet-Reparatur überschritt das iOS-Laufzeitbudget von "
                f"{_IOS_REPAIR_TOTAL_TIMEOUT_SECONDS} Sekunden. "
                "Die FootyStats-Analyse wird trotzdem als gemeinsame Datei gespeichert."
            ),
            "match_id": match_id,
            "home": home,
            "away": away,
            "match_date": match_date,
            "source_url": "https://www.forebet.com/",
            "odds_used": False,
        }, True


# selected_analysis_file() resolves this global at request time, so replacing it
# here bounds the existing endpoint without changing the signed AEA1 Shortcut.
_app_module._repair_forebet_from_match_data = _bounded_repair_forebet_from_match_data


@app.get("/api/forebet-auto/health")
def forebet_auto_health():
    result = dict(health())
    result["ios_repair_total_timeout_seconds"] = _IOS_REPAIR_TOTAL_TIMEOUT_SECONDS
    return result


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


@app.get("/api/forebet-auto/export")
def forebet_auto_export(
    match_id: int = Query(..., ge=1),
    home: str = Query(default=""),
    away: str = Query(default=""),
    date: str | None = Query(default=None),
    force: bool = Query(default=False),
):
    """Always return JSON; final analysis can repair identity from MatchDaten."""
    home = (home or "").strip()
    away = (away or "").strip()
    if not home or not away:
        return {
            "ok": False,
            "schema": "forebet-auto-error-v1",
            "phase": "FOREBET_IDENTITY_DEFERRED",
            "error": "Teamnamen fehlen im Auswahlobjekt; Render ergänzt sie im finalen Analyse-Request aus MatchDaten.",
            "match_id": match_id,
            "home": home,
            "away": away,
            "match_date": date,
            "source_url": "https://www.forebet.com/",
            "odds_used": False,
        }
    try:
        result = build_snapshot(match_id=match_id, home=home, away=away, date=date, force=force)
        return {"ok": True, **result}
    except ForebetAutoError as exc:
        return {
            "ok": False,
            "schema": "forebet-auto-error-v1",
            "phase": "FOREBET_UNAVAILABLE",
            "error": str(exc),
            "match_id": match_id,
            "home": home,
            "away": away,
            "match_date": date,
            "source_url": "https://www.forebet.com/",
            "odds_used": False,
        }
