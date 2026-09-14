"""Development-only FULL-7 validation API.

This module is intentionally not imported by production app.py.
It validates seven uploaded FootyStats JSON files and returns the Bronze/Silver/Gold audit.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

from fastapi import FastAPI, File, HTTPException, UploadFile

from full7_foundation import process_full7

APP_VERSION = "0.1.0-full7-validation"
app = FastAPI(title="FootyStats FULL-7 Validation", version=APP_VERSION)


async def _load_json(file: UploadFile) -> Dict[str, Any]:
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=422, detail={"code": "EMPTY_FILE", "filename": file.filename})
    try:
        parsed = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "INVALID_JSON", "filename": file.filename, "message": str(exc)},
        ) from exc
    if not isinstance(parsed, dict):
        raise HTTPException(
            status_code=422,
            detail={"code": "INVALID_JSON_ROOT", "filename": file.filename},
        )
    return {"name": file.filename or "unnamed.json", "data": parsed}


async def validate_uploads(files: List[UploadFile]) -> Dict[str, Any]:
    parsed = [await _load_json(file) for file in files]
    result = process_full7(parsed)
    # Gold contains the source payloads and can be large. The validation endpoint returns
    # only audit/lineage readiness. A later model endpoint may consume Gold internally.
    if result.get("gold"):
        gold = result["gold"]
        result["gold"] = {
            "identity": gold.get("identity"),
            "quality": gold.get("quality"),
            "lineage": gold.get("lineage"),
            "namespaces_present": sorted((gold.get("namespaces") or {}).keys()),
        }
    return result


@app.get("/api/full7/health")
def full7_health() -> Dict[str, Any]:
    return {
        "ok": True,
        "development_only": True,
        "version": APP_VERSION,
        "expected_files": 7,
        "production_wired": False,
    }


@app.post("/api/full7/validate")
async def full7_validate(
    match_file: UploadFile = File(...),
    league_file: UploadFile = File(...),
    form_file: UploadFile = File(...),
    table_file: UploadFile = File(...),
    player_file: UploadFile = File(...),
    referee_file: UploadFile = File(...),
    manager_file: UploadFile = File(...),
) -> Dict[str, Any]:
    return await validate_uploads([
        match_file,
        league_file,
        form_file,
        table_file,
        player_file,
        referee_file,
        manager_file,
    ])
