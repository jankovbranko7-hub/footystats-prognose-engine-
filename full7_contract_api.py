"""FULL-7 architecture-contract API.

The preview routes remain available only in this standalone module. The
``production_router`` exposes the validated contract engine on the stable
production FULL-7 endpoints and consumes exactly seven FootyStats pre-match
files. Probability mode remains odds-free and every supported market receives
probability, evidence and a final decision.
"""
from __future__ import annotations

import copy
import json
from typing import Any, Dict, List, Mapping, Sequence, Tuple

from fastapi import APIRouter, FastAPI, File, HTTPException, UploadFile

from full7_foundation import process_full7
from full7_gold_features import build_gold_features
from full7_contract_decision import (
    DECISION_GATE_VERSION,
    build_decision_engine,
)
from full7_contract_engine import (
    MARKETS,
    MODEL_BUNDLE_SHA256,
    MODEL_FOUNDATION_VERSION,
)

APP_VERSION = "FULL7_CONTRACT_PREVIEW_1.0"
PRODUCTION_VERSION = "FULL7_CONTRACT_1.0.0"
RELEASE_STATUS = "PRODUCTION_RELEASED_OOS_VALIDATED"

router = APIRouter()
production_router = APIRouter()


def _complete_stage(stage: Any) -> None:
    if isinstance(stage, dict):
        for key in list(stage):
            stage[key] = True


def _production_release_view(decision: Mapping[str, Any]) -> Dict[str, Any]:
    """Return production-facing release metadata without changing model logic.

    The underlying contract components retain their development provenance. Once
    the final Forward-OOS/release gates have passed, the production API must not
    expose the pre-release PENDING/DEVELOPMENT_ONLY state as the live engine
    state. Only release metadata is changed here; probabilities, evidence values,
    thresholds, gates and decisions are preserved byte-for-byte in meaning.
    """
    released = copy.deepcopy(dict(decision))
    released["status"] = RELEASE_STATUS
    _complete_stage(released.get("contract_stage"))

    evidence = released.get("evidence")
    if isinstance(evidence, dict):
        evidence["status"] = RELEASE_STATUS
        probability_layer = evidence.get("probability_layer")
        if isinstance(probability_layer, dict):
            probability_layer["status"] = RELEASE_STATUS
            _complete_stage(probability_layer.get("contract_stage"))
            model_support = probability_layer.get("model_support")
            if isinstance(model_support, dict):
                model_support["status"] = RELEASE_STATUS
                _complete_stage(model_support.get("contract_stage"))
    return released


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


async def _execute_contract(
    uploads: Sequence[UploadFile],
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
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
    if set(decision.get("markets") or {}) != set(MARKETS):
        raise HTTPException(
            status_code=500,
            detail={"code": "FULL7_SEVEN_MARKET_CONTRACT_FAILED"},
        )
    return processed, gold, gold_features, decision


@router.get("/api/full7/contract-preview/health")
def health() -> Dict[str, Any]:
    return {
        "ok": True,
        "development_only": True,
        "production_mounted": False,
        "version": APP_VERSION,
        "decision_gate_version": DECISION_GATE_VERSION,
        "expected_files": 7,
        "markets": list(MARKETS),
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
    _, gold, gold_features, decision = await _execute_contract(uploads)

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


@production_router.get("/api/full7/engine-health")
def production_health() -> Dict[str, Any]:
    return {
        "ok": True,
        "engine": "FOOTYSTATS_FULL7_CONTRACT",
        "engine_version": PRODUCTION_VERSION,
        "release_status": RELEASE_STATUS,
        "model_contract_version": MODEL_FOUNDATION_VERSION,
        "model_bundle_sha256": MODEL_BUNDLE_SHA256,
        "decision_gate_version": DECISION_GATE_VERSION,
        "expected_files": 7,
        "production_mounted": True,
        "markets": list(MARKETS),
        "all_markets_decision_enabled": True,
        "probability_mode_no_odds": True,
    }


@production_router.post("/api/full7/predict")
async def production_predict(
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
    processed, gold, gold_features, decision = await _execute_contract(uploads)
    released_decision = _production_release_view(decision)

    return {
        "ok": True,
        "identity": gold.get("identity"),
        "quality": gold.get("quality"),
        "engine": released_decision,
        "feature_audit": {
            "gold_builder_version": gold_features.get("feature_builder_version"),
            "gold_feature_count": gold_features.get("feature_count"),
            "available_block_count": gold_features.get("available_block_count"),
            "policies": gold_features.get("policies"),
            "strict_pre_match_audit": processed.get("audit"),
            "issues": processed.get("issues"),
        },
        "contract": {
            "engine_version": PRODUCTION_VERSION,
            "release_status": RELEASE_STATUS,
            "model_contract_version": MODEL_FOUNDATION_VERSION,
            "model_bundle_sha256": MODEL_BUNDLE_SHA256,
            "decision_gate_version": DECISION_GATE_VERSION,
            "expected_files": 7,
            "markets": list(MARKETS),
            "all_markets_decision_enabled": True,
            "probability_mode_no_odds": True,
        },
    }


app = FastAPI(title="FULL-7 Architecture Contract Preview", version=APP_VERSION)
app.include_router(router)
