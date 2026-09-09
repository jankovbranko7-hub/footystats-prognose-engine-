"""Asynchronous iOS Shortcut upload flow for FootyStats V0.5.0.

This patch only changes transport/orchestration for the five uploaded JSON files.
It does not alter the frozen V0.4.3 FULL-5 probability core, market probabilities,
or the V0.5.0 decision logic.
"""
from __future__ import annotations

import asyncio
import json
import threading
import time
import uuid
from typing import Any, Dict, Iterable, List, Tuple

from fastapi import BackgroundTasks, File, UploadFile


JOB_TTL_SECONDS = 1800
JOB_MAX_COUNT = 32
JOB_POLL_MAX_WAIT_SECONDS = 25


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


def _match_team_ids(parsed: List[Dict[str, Any]]) -> Tuple[int | None, int | None]:
    for item in parsed:
        if "matchdaten" not in str(item.get("name") or "").lower():
            continue
        for candidate in _dicts(item.get("data")):
            home = _to_int(candidate.get("homeID", candidate.get("home_id")))
            away = _to_int(candidate.get("awayID", candidate.get("away_id")))
            if home is not None and away is not None:
                return home, away
    return None, None


def _strip_odds(obj: Any) -> int:
    """Remove odds-only keys from the in-memory analysis copy; return removed count."""
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


def _filter_player_pages(data: Any, home_id: int | None, away_id: int | None) -> Tuple[int, int]:
    """Keep only target-team players in the in-memory PlayerDaten analysis copy."""
    if home_id is None or away_id is None or not isinstance(data, dict):
        return 0, 0
    payload = data.get("payload")
    if not isinstance(payload, dict):
        return 0, 0
    pages = payload.get("pages")
    if not isinstance(pages, list):
        return 0, 0

    wanted = {home_id, away_id}
    before = 0
    after = 0
    for page in pages:
        if not isinstance(page, dict) or not isinstance(page.get("data"), list):
            continue
        rows = page.get("data") or []
        before += len(rows)
        filtered = []
        for player in rows:
            if not isinstance(player, dict):
                continue
            club_1 = _to_int(player.get("club_team_id"))
            club_2 = _to_int(player.get("club_team_2_id"))
            if club_1 in wanted or club_2 in wanted:
                filtered.append(player)
        page["data"] = filtered
        after += len(filtered)
    return before, after


def apply_patch(legacy: Any, app: Any) -> Any:
    jobs: Dict[str, Dict[str, Any]] = {}
    jobs_lock = threading.Lock()

    def _cleanup_jobs() -> None:
        now = time.time()
        with jobs_lock:
            expired = [
                job_id
                for job_id, job in jobs.items()
                if now - float(job.get("created_at_unix") or now) > JOB_TTL_SECONDS
            ]
            for job_id in expired:
                jobs.pop(job_id, None)
            if len(jobs) > JOB_MAX_COUNT:
                ordered = sorted(
                    jobs.items(),
                    key=lambda item: float(item[1].get("created_at_unix") or 0),
                )
                for job_id, _ in ordered[: max(0, len(jobs) - JOB_MAX_COUNT)]:
                    jobs.pop(job_id, None)

    def _put_job(job_id: str, values: Dict[str, Any]) -> None:
        with jobs_lock:
            current = dict(jobs.get(job_id) or {})
            current.update(values)
            jobs[job_id] = current

    def _get_job(job_id: str) -> Dict[str, Any] | None:
        with jobs_lock:
            job = jobs.get(job_id)
            return dict(job) if isinstance(job, dict) else None

    def _run_job(
        job_id: str,
        blobs: List[Tuple[str, bytes]],
        received: Dict[str, str],
    ) -> None:
        _put_job(job_id, {"status": "RUNNING", "started_at_unix": int(time.time())})
        try:
            parsed: List[Dict[str, Any]] = []
            for filename, raw in blobs:
                data = json.loads(raw.decode("utf-8"))
                parsed.append({"name": filename, "data": data})

            home_id, away_id = _match_team_ids(parsed)
            player_before = 0
            player_after = 0
            odds_removed = 0
            for item in parsed:
                lower_name = str(item.get("name") or "").lower()
                if "playerdaten" in lower_name:
                    player_before, player_after = _filter_player_pages(item.get("data"), home_id, away_id)
                elif "matchdaten" in lower_name:
                    odds_removed += _strip_odds(item.get("data"))

            _put_job(
                job_id,
                {
                    "transport_optimization": {
                        "home_id": home_id,
                        "away_id": away_id,
                        "player_rows_before": player_before,
                        "player_rows_after": player_after,
                        "odds_fields_removed": odds_removed,
                    }
                },
            )

            result = legacy._analyze_bundle(parsed)
            if not isinstance(result, dict):
                result = {
                    "ok": False,
                    "decision": "ANALYSE NICHT MÖGLICH",
                    "phase": "ASYNC_RESULT_INVALID",
                    "error": "Die Analyse lieferte kein gültiges Ergebnisobjekt.",
                }

            _put_job(
                job_id,
                {
                    "status": "DONE",
                    "finished_at_unix": int(time.time()),
                    "result": result,
                    "received": received,
                },
            )
        except Exception as exc:
            _put_job(
                job_id,
                {
                    "status": "ERROR",
                    "finished_at_unix": int(time.time()),
                    "error": str(exc),
                    "received": received,
                },
            )

    old_health = next(
        (route.endpoint for route in app.router.routes if getattr(route, "path", None) == "/api/health"),
        None,
    )

    app.router.routes = [
        route
        for route in app.router.routes
        if getattr(route, "path", None)
        not in {
            "/api/health",
            "/api/predict-shortcut-v1-1-async",
            "/api/predict-shortcut-v1-1-job/{job_id}",
        }
    ]

    def health() -> Dict[str, Any]:
        base = dict(old_health() if callable(old_health) else {})
        base.update(
            {
                "shortcut_async_transport": True,
                "shortcut_async_upload_endpoint": "/api/predict-shortcut-v1-1-async",
                "shortcut_async_status_endpoint": "/api/predict-shortcut-v1-1-job/{job_id}",
                "shortcut_async_long_poll_max_seconds": JOB_POLL_MAX_WAIT_SECONDS,
                "shortcut_async_job_ttl_seconds": JOB_TTL_SECONDS,
                "shortcut_async_player_prefilter": True,
                "shortcut_async_odds_strip": True,
            }
        )
        return base

    async def predict_shortcut_v1_1_async(
        background_tasks: BackgroundTasks,
        match_file: UploadFile = File(...),
        league_file: UploadFile = File(...),
        form_file: UploadFile = File(...),
        table_file: UploadFile = File(...),
        player_file: UploadFile = File(...),
    ) -> Dict[str, Any]:
        """Accept the five files, return a job id immediately, analyze afterwards."""
        _cleanup_jobs()
        ordered = [
            ("match_file", match_file, "MatchDaten.json"),
            ("league_file", league_file, "LeagueDaten.json"),
            ("form_file", form_file, "FormDaten.json"),
            ("table_file", table_file, "TableDaten.json"),
            ("player_file", player_file, "PlayerDaten.json"),
        ]

        blobs: List[Tuple[str, bytes]] = []
        received: Dict[str, str] = {}
        errors: List[Dict[str, str]] = []
        total_bytes = 0

        for field_name, upload, fallback_name in ordered:
            filename = upload.filename or fallback_name
            received[field_name] = filename
            try:
                raw = await upload.read()
                if not raw:
                    raise ValueError("empty upload")
                total_bytes += len(raw)
                blobs.append((filename, raw))
            except Exception as exc:
                errors.append({"field": field_name, "name": filename, "error": str(exc)})

        if errors:
            return {
                "ok": False,
                "accepted": False,
                "phase": "ASYNC_UPLOAD_READ_FAILED",
                "decision": "ANALYSE NICHT MÖGLICH",
                "error": "Mindestens eine der fünf Shortcut-Dateien konnte nicht übernommen werden.",
                "received": received,
                "files": errors,
            }

        job_id = uuid.uuid4().hex
        created_at = int(time.time())
        _put_job(
            job_id,
            {
                "job_id": job_id,
                "status": "QUEUED",
                "created_at_unix": created_at,
                "received": received,
                "file_count": len(blobs),
                "total_bytes": total_bytes,
            },
        )
        background_tasks.add_task(_run_job, job_id, blobs, received)

        return {
            "ok": True,
            "accepted": True,
            "ready": False,
            "job_id": job_id,
            "job_status": "QUEUED",
            "file_count": len(blobs),
            "total_bytes": total_bytes,
            "status_path": f"/api/predict-shortcut-v1-1-job/{job_id}",
        }

    async def predict_shortcut_v1_1_job(job_id: str, wait_seconds: int = 0) -> Dict[str, Any]:
        """Long-poll a job for up to 25 seconds and return the analysis when ready."""
        _cleanup_jobs()
        wait = max(0, min(int(wait_seconds or 0), JOB_POLL_MAX_WAIT_SECONDS))
        deadline = time.monotonic() + wait

        while True:
            job = _get_job(job_id)
            if job is None:
                return {
                    "ok": False,
                    "ready": True,
                    "job_id": job_id,
                    "job_status": "NOT_FOUND",
                    "error": "Shortcut-Job nicht gefunden oder abgelaufen.",
                }

            status = str(job.get("status") or "UNKNOWN")
            if status == "DONE":
                result = job.get("result")
                payload = dict(result) if isinstance(result, dict) else {"ok": False}
                payload["ready"] = True
                payload["job_id"] = job_id
                payload["job_status"] = "DONE"
                payload["async_transport"] = {
                    "mode": "UPLOAD_THEN_LONG_POLL",
                    "created_at_unix": job.get("created_at_unix"),
                    "started_at_unix": job.get("started_at_unix"),
                    "finished_at_unix": job.get("finished_at_unix"),
                    "received": job.get("received"),
                    "file_count": job.get("file_count"),
                    "total_bytes": job.get("total_bytes"),
                    "optimization": job.get("transport_optimization"),
                }
                return payload

            if status == "ERROR":
                return {
                    "ok": False,
                    "ready": True,
                    "job_id": job_id,
                    "job_status": "ERROR",
                    "phase": "ASYNC_ANALYSIS_FAILED",
                    "decision": "ANALYSE NICHT MÖGLICH",
                    "error": job.get("error") or "Unbekannter Analysefehler.",
                    "received": job.get("received"),
                    "optimization": job.get("transport_optimization"),
                }

            if time.monotonic() >= deadline:
                return {
                    "ok": True,
                    "ready": False,
                    "job_id": job_id,
                    "job_status": status,
                    "created_at_unix": job.get("created_at_unix"),
                    "started_at_unix": job.get("started_at_unix"),
                    "optimization": job.get("transport_optimization"),
                }

            await asyncio.sleep(0.5)

    app.add_api_route("/api/health", health, methods=["GET"])
    app.add_api_route(
        "/api/predict-shortcut-v1-1-async",
        predict_shortcut_v1_1_async,
        methods=["POST"],
    )
    app.add_api_route(
        "/api/predict-shortcut-v1-1-job/{job_id}",
        predict_shortcut_v1_1_job,
        methods=["GET"],
    )
    return app
