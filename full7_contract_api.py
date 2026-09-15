"""Development-only FULL-7 architecture-contract preview API.

This module is intentionally NOT mounted by production app.py.
It executes the complete saved architecture contract on exactly seven uploaded
FootyStats pre-match files and returns probabilities, evidence and decisions for
all seven markets.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

from fastapi import APIRouter, FastAPI, File, HTTPException, UploadFile

from full7_foundation import process_full7
from full7_gold_features import build_gold_features
from full7_contract_decision import (
    DECISION_GATE_VERSION,
    build_decision_engine,
)

APP_VERSION = "FULL7_CONTRACT_PREVIEW_1.0"

router = APIRouter()


async def _read_json(file: UploadFile) -> Dict[str, Any]:
    raw = await file.read()
    if not raw:
        raise HTTPException(
            status_code=422,
            detail={"code": "EMPTY_FILE", "filename": file.filename},
        )
    try:
        parsed = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "INVALID_JSON",
                "filename": file.filename,
                "message": str(exc),
            },
        ) from exc
    if not isinstance(parsed, dict):
        raise HTTPException(
            status_code=422,
            detail={"code": "INVALID_JSON_ROOT", "filename": file.filename},
        )
    return {"name": file.filename or "unnamed.json", "data": parsed}


@router.get("/api/full7/contract-preview/health")
def health() -> Dict[str, Any]:
    return {
        "ok": True,
        "development_only": True,
        "production_mounted": False,
        "version": APP_VERSION,
        "decision_gate_version": DECISION_GATE_VERSION,
        "expected_files": 7,
        "markets": [
            "home_win", "draw", "away_win",
            "btts_yes", "btts_no", "over_2_5", "under_2_5",
        ],
        "new_untouched_oos_required": True,
    }


@router.post("/api/full7/contract-preview")
async def contract_preview(
    match_file: UploadFile = File(...),
    league_file: UploadFile = File(...),
    form_file: UploadFile = File(...),
    table_file: UploadFile = File(...),
    player_file: UploadFile = File(...),
    referee_file: UploadFile = File(...),
    manager_file: UploadFile = File(...),
) -> Dict[str, Any]:
    uploads: List[UploadFile] = [
        match_file, league_file, form_file, table_file,
        player_file, referee_file, manager_file,
    ]
    parsed = [await _read_json(file) for file in uploads]

    processed = process_full7(parsed)
    if not processed.get("ok") or not processed.get("gold"):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "FULL7_VALIDATION_FAILED",
                "stage": processed.get("stage"),
                "issues": processed.get("issues"),
            },
        )

    gold = processed["gold"]
    gold_features = build_gold_features(gold)
    decision = build_decision_engine(
        gold_features,
        validation_quality=gold.get("quality") or {},
    )

    return {
        "ok": True,
        "development_only": True,
        "production_mounted": False,
        "identity": gold.get("identity"),
        "quality": gold.get("quality"),
        "gold": {
            "feature_builder_version": gold_features.get("feature_builder_version"),
            "feature_count": gold_features.get("feature_count"),
            "available_block_count": gold_features.get("available_block_count"),
            "policies": gold_features.get("policies"),
        },
        "contract_engine": decision,
    }


app = FastAPI(title="FULL-7 Architecture Contract Preview", version=APP_VERSION)
app.include_router(router)
