"""Server-side FAST collection flow for the iOS FootyStats shortcut.

The iPhone only sends the selected match id and the user's FootyStats API key.
Render then collects the five canonical pre-match sources, constructs the same
five virtual JSON files used by the existing V0.5.0 engine, and runs analysis
in a background job. The API key is never stored in job state or output.

This module is transport/data-collection only. It does not alter the frozen
V0.4.3 FULL-5 probability core or the V0.5.0 decision policy.
"""
from __future__ import annotations

import asyncio
import copy
import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, Iterable, List, Tuple

from fastapi import BackgroundTasks, Form


FOOTYSTATS_BASE = "https://api.football-data-api.com"
JOB_TTL_SECONDS = 1800
JOB_MAX_COUNT = 32
JOB_POLL_MAX_WAIT_SECONDS = 25
HTTP_TIMEOUT_SECONDS = 30


def _dicts(obj: Any) -> Iterable[Dict[str, Any]]:
    if isinstance(obj, dict):
        yield obj
        for value in obj.values():
            yield from _dicts(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from _dicts(value)


def _to_int(value: Any) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _match_payload(response: Dict[str, Any]) -> Dict[str, Any]:
    data = response.get("data") if isinstance(response, dict) else None
    if isinstance(data, dict):
        return data
    for candidate in _dicts(response):
        if _to_int(candidate.get("id")) is not None and (
            _to_int(candidate.get("homeID")) is not None
            and _to_int(candidate.get("awayID")) is not None
        ):
            return candidate
    raise ValueError("Match Details enthalten keine gültige Match-/Team-Zuordnung.")


def _pager_max_page(response: Any) -> int:
    for candidate in _dicts(response):
        if "max_page" in candidate:
            value = _to_int(candidate.get("max_page"))
            if value and value > 0:
                return value
    return 1


def _api_get(endpoint: str, api_key: str, **params: Any) -> Dict[str, Any]:
    query = {"key": api_key}
    query.update({k: v for k, v in params.items() if v is not None})
    url = FOOTYSTATS_BASE + endpoint + "?" + urllib.parse.urlencode(query)
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "FootyStats-Prognose-Engine/0.5.0"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"FootyStats {endpoint} HTTP {exc.code}") from None
    except urllib.error.URLError as exc:
        raise RuntimeError(f"FootyStats {endpoint} Netzwerkfehler") from None
    except TimeoutError:
        raise RuntimeError(f"FootyStats {endpoint} Timeout") from None
    try:
        data = json.loads(raw.decode("utf-8"))
    except Exception:
        raise RuntimeError(f"FootyStats {endpoint} lieferte kein gültiges JSON") from None
    if not isinstance(data, dict):
        raise RuntimeError(f"FootyStats {endpoint} lieferte kein JSON-Objekt")
    if data.get("success") is False:
        message = str(data.get("message") or data.get("error") or "API request failed")
        raise RuntimeError(f"FootyStats {endpoint}: {message[:240]}")
    return data


def _fetch_paginated(endpoint: str, api_key: str, base_params: Dict[str, Any]) -> List[Dict[str, Any]]:
    first = _api_get(endpoint, api_key, **base_params, page=1)
    max_page = _pager_max_page(first)
    if max_page <= 1:
        return [first]
    pages: Dict[int, Dict[str, Any]] = {1: first}
    with ThreadPoolExecutor(max_workers=min(6, max_page - 1)) as pool:
        futures = {
            page: pool.submit(_api_get, endpoint, api_key, **base_params, page=page)
            for page in range(2, max_page + 1)
        }
        for page, future in futures.items():
            pages[page] = future.result()
    return [pages[page] for page in sorted(pages)]


def _filter_players(pages: List[Dict[str, Any]], home_id: int, away_id: int) -> Tuple[List[Dict[str, Any]], int, int]:
    wanted = {home_id, away_id}
    filtered_pages = copy.deepcopy(pages)
    before = 0
    after = 0
    for page in filtered_pages:
        rows = page.get("data") if isinstance(page, dict) else None
        if not isinstance(rows, list):
            continue
        before += len(rows)
        kept = []
        for player in rows:
            if not isinstance(player, dict):
                continue
            club_1 = _to_int(player.get("club_team_id"))
            club_2 = _to_int(player.get("club_team_2_id"))
            if club_1 in wanted or club_2 in wanted:
                kept.append(player)
        page["data"] = kept
        after += len(kept)
    return filtered_pages, before, after


def _strip_odds(obj: Any) -> int:
    removed = 0
    if isinstance(obj, dict):
        for key in list(obj.keys()):
            normalized = str(key).lower().replace("-", "_")
            if normalized == "odds" or normalized.startswith("odds_") or normalized == "odds_comparison":
                obj.pop(key, None)
                removed += 1
            else:
                removed += _strip_odds(obj.get(key))
    elif isinstance(obj, list):
        for value in obj:
            removed += _strip_odds(value)
    return removed


def _virtual_files(api_key: str, match_id: int) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    started = time.monotonic()
    captured_at = int(time.time())
    match_raw = _api_get("/match", api_key, match_id=match_id)
    match = _match_payload(match_raw)

    actual_match_id = _to_int(match.get("id"))
    home_id = _to_int(match.get("homeID"))
    away_id = _to_int(match.get("awayID"))
    season_id = _to_int(match.get("competition_id"))
    kickoff = _to_int(match.get("date_unix"))
    if None in {actual_match_id, home_id, away_id, season_id, kickoff}:
        raise ValueError("Match Details enthalten nicht alle Pflicht-IDs oder den Kickoff.")
    if int(actual_match_id) != int(match_id):
        raise ValueError("FootyStats Match-ID stimmt nicht mit der Auswahl überein.")
    if captured_at >= kickoff:
        raise ValueError("Das ausgewählte Spiel hat bereits begonnen; Strict Pre-Match ist nicht mehr möglich.")

    max_time = kickoff - 1
    with ThreadPoolExecutor(max_workers=6) as pool:
        league_future = pool.submit(_api_get, "/league-season", api_key, season_id=season_id, max_time=max_time)
        teams_future = pool.submit(
            _fetch_paginated,
            "/league-teams",
            api_key,
            {"season_id": season_id, "include": "stats", "max_time": max_time},
        )
        home_form_future = pool.submit(_api_get, "/lastx", api_key, team_id=home_id)
        away_form_future = pool.submit(_api_get, "/lastx", api_key, team_id=away_id)
        table_future = pool.submit(
            _api_get,
            "/league-tables",
            api_key,
            season_id=season_id,
            include="stats",
            max_time=max_time,
        )
        players_future = pool.submit(
            _fetch_paginated,
            "/league-players",
            api_key,
            {"season_id": season_id, "include": "stats", "max_time": max_time},
        )

        league_raw = league_future.result()
        team_pages = teams_future.result()
        home_form = home_form_future.result()
        away_form = away_form_future.result()
        table_raw = table_future.result()
        player_pages = players_future.result()

    player_pages, player_before, player_after = _filter_players(player_pages, home_id, away_id)
    match_for_analysis = copy.deepcopy(match_raw)
    odds_removed = _strip_odds(match_for_analysis)

    meta_common = {
        "captured_at_unix": captured_at,
        "kickoff_unix": kickoff,
    }
    parsed = [
        {
            "name": f"{match_id}_MatchDaten.json",
            "data": {
                "_footystats_meta": {
                    **meta_common,
                    "endpoint": "/match",
                    "match_id": match_id,
                    "temporal_mode": "PREMATCH_FIELD_WHITELIST",
                },
                "payload": match_for_analysis,
            },
        },
        {
            "name": f"{season_id}_LeagueDaten.json",
            "data": {
                "_footystats_meta": {
                    **meta_common,
                    "endpoint": "/league-season",
                    "team_endpoint": "/league-teams",
                    "season_id": season_id,
                    "max_time": max_time,
                    "temporal_mode": "STRICT_MAX_TIME",
                    "team_pagination_complete": True,
                },
                "payload": {"league": league_raw, "team_pages": team_pages},
            },
        },
        {
            "name": f"{match_id}_FormDaten.json",
            "data": {
                "_footystats_meta": {
                    **meta_common,
                    "endpoint": "/lastx",
                    "team_ids": [home_id, away_id],
                    "temporal_mode": "LIVE_CAPTURE_ONLY_NO_MAX_TIME",
                },
                "payload": {"home": home_form, "away": away_form},
            },
        },
        {
            "name": f"{match_id}_TableDaten.json",
            "data": {
                "_footystats_meta": {
                    **meta_common,
                    "endpoint": "/league-tables",
                    "season_id": season_id,
                    "max_time": max_time,
                    "temporal_mode": "STRICT_MAX_TIME",
                },
                "payload": table_raw,
            },
        },
        {
            "name": f"{match_id}_PlayerDaten.json",
            "data": {
                "_footystats_meta": {
                    **meta_common,
                    "endpoint": "/league-players",
                    "season_id": season_id,
                    "max_time": max_time,
                    "temporal_mode": "STRICT_MAX_TIME",
                    "pagination_complete": True,
                    "max_page": len(player_pages),
                },
                "payload": {"pages": player_pages},
            },
        },
    ]
    diagnostics = {
        "mode": "SERVER_SIDE_FAST",
        "match_id": match_id,
        "season_id": season_id,
        "home_id": home_id,
        "away_id": away_id,
        "kickoff_unix": kickoff,
        "max_time": max_time,
        "team_pages": len(team_pages),
        "player_pages": len(player_pages),
        "player_rows_before_filter": player_before,
        "player_rows_after_filter": player_after,
        "odds_fields_removed": odds_removed,
        "virtual_file_count": len(parsed),
        "collection_seconds": round(time.monotonic() - started, 3),
        "api_key_persisted": False,
    }
    return parsed, diagnostics


def apply_patch(legacy: Any, app: Any) -> Any:
    jobs: Dict[str, Dict[str, Any]] = {}
    jobs_lock = threading.Lock()

    def cleanup() -> None:
        now = time.time()
        with jobs_lock:
            expired = [job_id for job_id, job in jobs.items() if now - float(job.get("created_at_unix") or now) > JOB_TTL_SECONDS]
            for job_id in expired:
                jobs.pop(job_id, None)
            if len(jobs) > JOB_MAX_COUNT:
                ordered = sorted(jobs.items(), key=lambda item: float(item[1].get("created_at_unix") or 0))
                for job_id, _ in ordered[: max(0, len(jobs) - JOB_MAX_COUNT)]:
                    jobs.pop(job_id, None)

    def put(job_id: str, values: Dict[str, Any]) -> None:
        with jobs_lock:
            current = dict(jobs.get(job_id) or {})
            current.update(values)
            jobs[job_id] = current

    def get(job_id: str) -> Dict[str, Any] | None:
        with jobs_lock:
            value = jobs.get(job_id)
            return dict(value) if isinstance(value, dict) else None

    def run(job_id: str, api_key: str, match_id: int) -> None:
        put(job_id, {"status": "COLLECTING", "started_at_unix": int(time.time())})
        try:
            parsed, diagnostics = _virtual_files(api_key, match_id)
            put(job_id, {"status": "ANALYZING", "collection": diagnostics})
            result = legacy._analyze_bundle(parsed)
            if not isinstance(result, dict):
                raise RuntimeError("Die Analyse lieferte kein gültiges Ergebnisobjekt.")
            result["shortcut_fast"] = diagnostics
            put(
                job_id,
                {
                    "status": "DONE",
                    "finished_at_unix": int(time.time()),
                    "result": result,
                    "collection": diagnostics,
                },
            )
        except Exception as exc:
            put(
                job_id,
                {
                    "status": "ERROR",
                    "finished_at_unix": int(time.time()),
                    "error": str(exc),
                },
            )

    old_health = next((route.endpoint for route in app.router.routes if getattr(route, "path", None) == "/api/health"), None)
    app.router.routes = [
        route
        for route in app.router.routes
        if getattr(route, "path", None)
        not in {"/api/health", "/api/predict-shortcut-fast", "/api/predict-shortcut-fast-job/{job_id}"}
    ]

    def health() -> Dict[str, Any]:
        base = dict(old_health() if callable(old_health) else {})
        base.update(
            {
                "shortcut_fast_server_collection": True,
                "shortcut_fast_submit_endpoint": "/api/predict-shortcut-fast",
                "shortcut_fast_status_endpoint": "/api/predict-shortcut-fast-job/{job_id}",
                "shortcut_fast_virtual_files": 5,
                "shortcut_fast_api_key_persisted": False,
            }
        )
        return base

    async def submit(
        background_tasks: BackgroundTasks,
        match_id: int = Form(...),
        api_key: str = Form(...),
    ) -> Dict[str, Any]:
        cleanup()
        if match_id <= 0:
            return {"ok": False, "accepted": False, "error": "Ungültige Match-ID."}
        if not api_key or len(api_key.strip()) < 8:
            return {"ok": False, "accepted": False, "error": "FootyStats API-Key fehlt oder ist ungültig."}
        job_id = uuid.uuid4().hex
        created_at = int(time.time())
        put(job_id, {"job_id": job_id, "status": "QUEUED", "created_at_unix": created_at, "match_id": match_id})
        background_tasks.add_task(run, job_id, api_key.strip(), int(match_id))
        return {
            "ok": True,
            "accepted": True,
            "ready": False,
            "job_id": job_id,
            "job_status": "QUEUED",
            "match_id": int(match_id),
            "status_path": f"/api/predict-shortcut-fast-job/{job_id}",
        }

    async def status(job_id: str, wait_seconds: int = 0) -> Dict[str, Any]:
        cleanup()
        wait = max(0, min(int(wait_seconds or 0), JOB_POLL_MAX_WAIT_SECONDS))
        deadline = time.monotonic() + wait
        while True:
            job = get(job_id)
            if job is None:
                return {"ok": False, "ready": True, "job_id": job_id, "job_status": "NOT_FOUND", "error": "FAST-Job nicht gefunden oder abgelaufen."}
            state = str(job.get("status") or "UNKNOWN")
            if state == "DONE":
                payload = dict(job.get("result") or {})
                payload.update({"ready": True, "job_id": job_id, "job_status": "DONE"})
                return payload
            if state == "ERROR":
                return {
                    "ok": False,
                    "ready": True,
                    "job_id": job_id,
                    "job_status": "ERROR",
                    "phase": "FAST_SERVER_COLLECTION_OR_ANALYSIS_FAILED",
                    "decision": "ANALYSE NICHT MÖGLICH",
                    "error": job.get("error") or "Unbekannter FAST-Fehler.",
                }
            if time.monotonic() >= deadline:
                return {
                    "ok": True,
                    "ready": False,
                    "job_id": job_id,
                    "job_status": state,
                    "match_id": job.get("match_id"),
                    "collection": job.get("collection"),
                }
            await asyncio.sleep(0.5)

    app.add_api_route("/api/health", health, methods=["GET"])
    app.add_api_route("/api/predict-shortcut-fast", submit, methods=["POST"])
    app.add_api_route("/api/predict-shortcut-fast-job/{job_id}", status, methods=["GET"])
    return app
