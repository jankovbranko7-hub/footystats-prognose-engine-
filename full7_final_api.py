"""Production FULL-7 Gated 1.0 prediction API.

Consumes exactly seven FootyStats pre-match files, validates Bronze/Silver/Gold,
builds the frozen Gold feature vector and returns coherent probabilities plus the
selective BTTS decision gate. 1X2 and Totals remain probability-only.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

from fastapi import APIRouter, File, HTTPException, UploadFile

from full7_foundation import process_full7
from full7_gold_features import build_gold_features
from full7_signal_groups import audit_signal_groups
from full7_final_engine import (
    BTTS_GATE_VERSION,
    ENGINE_VERSION,
    MODEL_CONTRACT_VERSION,
    READINESS,
    predict_gold_features,
)

router = APIRouter()


async def _read_json(file: UploadFile) -> Dict[str, Any]:
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
        raise HTTPException(status_code=422, detail={"code": "INVALID_JSON_ROOT", "filename": file.filename})
    return {"name": file.filename or "unnamed.json", "data": parsed}


@router.get("/api/full7/engine-health")
def full7_engine_health() -> Dict[str, Any]:
    return {
        "ok": True,
        "engine": "FOOTYSTATS_FULL7_GATED",
        "engine_version": ENGINE_VERSION,
        "model_contract_version": MODEL_CONTRACT_VERSION,
        "decision_gate_version": BTTS_GATE_VERSION,
        "expected_files": 7,
        "production_wired": True,
        "family_readiness": dict(READINESS),
        "recommendation_family": "BTTS",
        "non_btts_recommendation": False,
    }


@router.post("/api/full7/predict")
async def full7_predict(
    match_file: UploadFile = File(...),
    league_file: UploadFile = File(...),
    form_file: UploadFile = File(...),
    table_file: UploadFile = File(...),
    player_file: UploadFile = File(...),
    referee_file: UploadFile = File(...),
    manager_file: UploadFile = File(...),
) -> Dict[str, Any]:
    uploads: List[UploadFile] = [
        match_file, league_file, form_file, table_file, player_file, referee_file, manager_file
    ]
    parsed = [await _read_json(file) for file in uploads]
    result = process_full7(parsed)
    if not result.get("ok") or not result.get("gold"):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "FULL7_VALIDATION_FAILED",
                "stage": result.get("stage"),
                "issues": result.get("issues"),
            },
        )

    gold = result["gold"]
    gold_features = build_gold_features(gold)
    signal_groups = audit_signal_groups(gold_features)
    prediction = predict_gold_features(gold_features)

    return {
        "ok": True,
        "identity": gold.get("identity"),
        "quality": gold.get("quality"),
        "engine": prediction,
        "feature_audit": {
            "gold_builder_version": gold_features.get("feature_builder_version"),
            "gold_feature_count": gold_features.get("feature_count"),
            "available_block_count": gold_features.get("available_block_count"),
            "available_evidence_cluster_count": signal_groups.get("available_evidence_cluster_count"),
            "available_evidence_clusters": signal_groups.get("available_evidence_clusters"),
            "forbidden_odds_feature_count": signal_groups.get("forbidden_odds_feature_count"),
        },
    }
