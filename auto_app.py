from __future__ import annotations

from fastapi import Query, Request
from fastapi.responses import JSONResponse

import app as core_app
from app import app
from elite_fusion import attach_forebet_elite
from forebet_auto import ForebetAutoError
from forebet_auto_final import build_snapshot, debug_match, health
from forebet_auto_v6_debug import debug_direct
from forebet_debug import debug_pages
from forebet_html_ingest import (
    locate_match_url_from_html,
    parse_fixture,
    parse_match_html,
    self_test as html_ingest_self_test,
)

# Keep the stable FootyStats v0.4.0 engine untouched. This test service only
# adds the Elite fusion plus the Forebet acquisition/ingest layer.
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
        "forebet_acquisition": "iphone-html-ingest",
    }


@app.get("/api/forebet-auto/health")
def forebet_auto_health():
    result = dict(health())
    result.update({
        "iphone_html_ingest": True,
        "iphone_fetch_required": True,
        "server_forebet_fetch_required": False,
    })
    return result


@app.get("/api/forebet-auto/ingest-health")
def forebet_ingest_health():
    try:
        test = html_ingest_self_test()
        return {
            "ok": True,
            "iphone_html_ingest": True,
            "locate_endpoint": "/api/forebet-auto/locate-from-html",
            "parse_endpoint": "/api/forebet-auto/parse-match-html",
            "dundee_fixture_test": test["dundee"]["predicted_score"],
            "luzern_fixture_test": test["luzern"]["predicted_score"],
        }
    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content={"ok": False, "phase": "FOREBET_HTML_INGEST_SELF_TEST_FAILED", "error": str(exc)},
        )


@app.post("/api/forebet-auto/locate-from-html")
async def forebet_locate_from_html(
    request: Request,
    fixture: str = Query(..., min_length=3),
    date: str | None = Query(default=None),
):
    try:
        home, away = parse_fixture(fixture)
        body = await request.body()
        source_url = locate_match_url_from_html(body, home=home, away=away, date=date)
        return {
            "ok": True,
            "fixture": fixture,
            "home": home,
            "away": away,
            "date": date,
            "source_url": source_url,
        }
    except ForebetAutoError as exc:
        return JSONResponse(
            status_code=422,
            content={
                "ok": False,
                "phase": "FOREBET_HTML_LOCATE_FAILED",
                "error": str(exc),
                "fixture": fixture,
                "date": date,
            },
        )


@app.post("/api/forebet-auto/parse-match-html")
async def forebet_parse_match_html(
    request: Request,
    match_id: int = Query(..., ge=1),
    fixture: str = Query(..., min_length=3),
    date: str | None = Query(default=None),
    source_url: str = Query(..., min_length=20),
):
    try:
        home, away = parse_fixture(fixture)
        body = await request.body()
        return parse_match_html(
            body,
            match_id=match_id,
            home=home,
            away=away,
            date=date,
            source_url=source_url,
        )
    except ForebetAutoError as exc:
        return JSONResponse(
            status_code=422,
            content={
                "ok": False,
                "phase": "FOREBET_HTML_PARSE_FAILED",
                "error": str(exc),
                "match_id": match_id,
                "fixture": fixture,
                "date": date,
                "source_url": source_url,
            },
        )


# Legacy server-fetch diagnostics remain available but are no longer used by
# the iPhone Shortcut. This lets us diagnose Forebet outages without coupling
# the working six-file flow to Render/Apify/Jina network behaviour.
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
