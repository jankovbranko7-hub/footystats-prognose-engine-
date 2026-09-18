"""FULL-7 architecture-contract API.

The preview routes remain available for the V2 contract diagnostics. The stable
FULL-7 production endpoints are mounted by the application and use the V3.1
live-compatible meta layer for final decisions. V3.1 was authorized explicitly
for production after historical walk-forward validation; new prospective V3 OOS
validation remains false and is exposed as provenance rather than rewritten.
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
from full7_v3_live import (
    DECISION_SOURCE as V3_DECISION_SOURCE,
    ENGINE_VERSION as V3_ENGINE_VERSION,
    HISTORICAL_TRAINING_ROWS as V3_HISTORICAL_TRAINING_ROWS,
    HISTORICAL_WALK_FORWARD_OOS_ROWS as V3_HISTORICAL_WALK_FORWARD_OOS_ROWS,
    MODEL_SHA256 as V3_MODEL_SHA256,
    NEW_PROSPECTIVE_FORWARD_OOS_VALIDATED as V3_NEW_PROSPECTIVE_OOS_VALIDATED,
    PLAY_THRESHOLDS as V3_PLAY_THRESHOLDS,
    predict_v3_live,
)

APP_VERSION = "FULL7_CONTRACT_PREVIEW_3.1"
PRODUCTION_VERSION = V3_ENGINE_VERSION
DECISION_ARCHITECTURE = "SEVEN_MARKET_RAW_HEADS_THEN_COHERENCE"
PRODUCTION_DECISION_ARCHITECTURE = "V3_LIVE_META_FAMILY_MODELS_WITH_V2_DIAGNOSTIC_CORE"
RELEASE_STATUS = "LIVE_USER_AUTHORIZED_HISTORICAL_WALK_FORWARD"
RELEASE_AUTHORIZED = True
PRODUCTION_AUTHORIZATION_BASIS = "USER_EXPLICIT_2026-09-18"
DECISION_CAPABLE_FAMILIES = ["1X2", "BTTS", "TOTALS"]
FAMILY_READINESS = {
    "1X2": "LIVE_HISTORICAL_WALK_FORWARD_PLAY_GATE",
    "BTTS": "LIVE_HISTORICAL_WALK_FORWARD_PLAY_GATE",
    "TOTALS": "LIVE_HISTORICAL_WALK_FORWARD_PLAY_GATE",
}
# User explicitly authorized live operation without waiting for new prospective
# V3 result collection. This does not rewrite prospective validation provenance.
SPIELEN_ALLOWED_FAMILIES: List[str] = list(DECISION_CAPABLE_FAMILIES)

router = APIRouter()
production_router = APIRouter()


def _complete_stage(stage: Any) -> None:
    if isinstance(stage, dict):
        for key in list(stage):
            stage[key] = True


def _production_release_view(
    decision: Mapping[str, Any],
    v3: Mapping[str, Any],
) -> Dict[str, Any]:
    """Expose V3.1 as final production decision while preserving V2 diagnostics."""
    released = copy.deepcopy(dict(decision))
    released["v2_reference"] = {
        "status": decision.get("status"),
        "decision_gate_version": decision.get("decision_gate_version"),
        "probabilities": copy.deepcopy(decision.get("probabilities") or {}),
        "families": copy.deepcopy(decision.get("families") or {}),
        "purpose": "DIAGNOSTIC_REFERENCE_ONLY",
    }
    released["status"] = RELEASE_STATUS
    released["release_authorized"] = RELEASE_AUTHORIZED
    released["production_authorization_basis"] = PRODUCTION_AUTHORIZATION_BASIS
    released["decision_architecture"] = PRODUCTION_DECISION_ARCHITECTURE
    released["decision_source"] = V3_DECISION_SOURCE
    released["decision_capable_families"] = list(DECISION_CAPABLE_FAMILIES)
    released["family_readiness"] = dict(FAMILY_READINESS)
    released["spielen_allowed_families"] = list(SPIELEN_ALLOWED_FAMILIES)
    released["historical_training_rows"] = V3_HISTORICAL_TRAINING_ROWS
    released["historical_walk_forward_oos_rows"] = V3_HISTORICAL_WALK_FORWARD_OOS_ROWS
    released["new_prospective_forward_oos_validated"] = V3_NEW_PROSPECTIVE_OOS_VALIDATED
    released["v3_model_sha256"] = dict(V3_MODEL_SHA256)
    released["play_thresholds"] = dict(V3_PLAY_THRESHOLDS)

    if not v3.get("supported"):
        fail_closed = {}
        for market in MARKETS:
            v2_row = (decision.get("markets") or {}).get(market) or {}
            fail_closed[market] = {
                "market": market,
                "family": v2_row.get("family"),
                "selected_in_family": False,
                "probability": v2_row.get("probability"),
                "probability_source": "V2_DIAGNOSTIC_ONLY",
                "raw_reliability_score": None,
                "raw_decision": "AUSLASSEN",
                "raw_decision_reason": "V3_INPUTS_INCOMPLETE_FAIL_CLOSED",
                "reliability_score": None,
                "decision": "AUSLASSEN",
                "decision_reason": "V3_INPUTS_INCOMPLETE_FAIL_CLOSED",
                "data_quality_support": False,
            }
        released["probabilities"] = {}
        released["families"] = {}
        released["markets"] = fail_closed
        released["candidate_spielen"] = []
        released["playable"] = []
        released["blocked"] = [{
            "release_block_reason": "V3_INPUTS_INCOMPLETE_FAIL_CLOSED",
            "missing_inputs": list(v3.get("missing_inputs") or []),
        }]
        released["v3_supported"] = False
        return released

    released["v3_supported"] = True
    released["probabilities"] = copy.deepcopy(v3.get("probabilities") or {})
    released["families"] = copy.deepcopy(v3.get("families") or {})
    released["markets"] = copy.deepcopy(v3.get("markets") or {})
    released["validation_provenance"] = copy.deepcopy(v3.get("validation_provenance") or {})
    released["feature_policy"] = copy.deepcopy(v3.get("feature_policy") or {})
    released["league"] = v3.get("league")
    released["league_known_in_training"] = v3.get("league_known_in_training")

    candidate_spielen = []
    blocked = []
    for market, row in released["markets"].items():
        card = {
            "market": market,
            "family": row.get("family"),
            "probability": row.get("probability"),
            "raw_reliability_score": row.get("raw_reliability_score"),
            "raw_decision": row.get("raw_decision"),
            "decision": row.get("decision"),
            "reason": row.get("decision_reason"),
        }
        if row.get("decision") == "SPIELEN":
            candidate_spielen.append(card)
        else:
            blocked.append({
                **card,
                "release_block_reason": row.get("decision_reason"),
            })

    released["candidate_spielen"] = candidate_spielen
    released["playable"] = candidate_spielen
    released["blocked"] = blocked
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
    if not all(
        (decision["markets"][market].get("raw_reliability_score") is not None)
        and decision["markets"][market].get("raw_decision")
        for market in MARKETS
    ):
        raise HTTPException(
            status_code=500,
            detail={"code": "FULL7_SEVEN_RAW_HEADS_CONTRACT_FAILED"},
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
        "decision_architecture": DECISION_ARCHITECTURE,
        "expected_files": 7,
        "markets": list(MARKETS),
        "decision_capable_families": list(DECISION_CAPABLE_FAMILIES),
        "new_untouched_oos_required": True,
        "release_authorized": False,
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
        "release_authorized": False,
        "decision_architecture": DECISION_ARCHITECTURE,
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
        "release_authorized": RELEASE_AUTHORIZED,
        "spielen_release_authorized": RELEASE_AUTHORIZED,
        "production_authorization_basis": PRODUCTION_AUTHORIZATION_BASIS,
        "decision_source": V3_DECISION_SOURCE,
        "model_contract_version": MODEL_FOUNDATION_VERSION,
        "model_bundle_sha256": MODEL_BUNDLE_SHA256,
        "v3_model_sha256": dict(V3_MODEL_SHA256),
        "decision_gate_version": DECISION_GATE_VERSION,
        "decision_architecture": PRODUCTION_DECISION_ARCHITECTURE,
        "expected_files": 7,
        "production_mounted": True,
        "markets": list(MARKETS),
        "all_markets_decision_enabled": True,
        "probability_mode_no_odds": True,
        "decision_capable_families": list(DECISION_CAPABLE_FAMILIES),
        "family_readiness": dict(FAMILY_READINESS),
        "spielen_allowed_families": list(SPIELEN_ALLOWED_FAMILIES),
        "play_thresholds": dict(V3_PLAY_THRESHOLDS),
        "historical_training_rows": V3_HISTORICAL_TRAINING_ROWS,
        "historical_walk_forward_oos_rows": V3_HISTORICAL_WALK_FORWARD_OOS_ROWS,
        "new_prospective_forward_oos_validated": V3_NEW_PROSPECTIVE_OOS_VALIDATED,
        "live_feature_policy": "SEVEN_FILE_GOLD_PREMATCH_ONLY",
        "max_spielen_family": None,
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
    v3 = predict_v3_live(gold, gold_features)
    released_decision = _production_release_view(decision, v3)

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
            "release_authorized": RELEASE_AUTHORIZED,
            "production_authorization_basis": PRODUCTION_AUTHORIZATION_BASIS,
            "decision_source": V3_DECISION_SOURCE,
            "decision_architecture": PRODUCTION_DECISION_ARCHITECTURE,
            "model_contract_version": MODEL_FOUNDATION_VERSION,
            "model_bundle_sha256": MODEL_BUNDLE_SHA256,
            "decision_gate_version": DECISION_GATE_VERSION,
            "expected_files": 7,
            "markets": list(MARKETS),
            "all_markets_decision_enabled": True,
            "probability_mode_no_odds": True,
            "decision_capable_families": list(DECISION_CAPABLE_FAMILIES),
            "family_readiness": dict(FAMILY_READINESS),
            "spielen_allowed_families": list(SPIELEN_ALLOWED_FAMILIES),
            "play_thresholds": dict(V3_PLAY_THRESHOLDS),
            "historical_training_rows": V3_HISTORICAL_TRAINING_ROWS,
            "historical_walk_forward_oos_rows": V3_HISTORICAL_WALK_FORWARD_OOS_ROWS,
            "new_prospective_forward_oos_validated": V3_NEW_PROSPECTIVE_OOS_VALIDATED,
            "v3_model_sha256": dict(V3_MODEL_SHA256),
        },
    }


app = FastAPI(title="FULL-7 Architecture Contract Preview", version=APP_VERSION)
app.include_router(router)
