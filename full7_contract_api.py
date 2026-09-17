"""FULL-7 architecture-contract API.

The preview routes remain available only in this standalone module. The stable
FULL-7 endpoints are still mounted by the application, but V2 release metadata
fails closed until a new untouched forward-OOS block authorizes merge/deploy.
Probability mode remains odds-free and all seven supported markets receive a
raw reliability/decision head before family coherence arbitration.
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

APP_VERSION = "FULL7_CONTRACT_PREVIEW_2.0"
PRODUCTION_VERSION = "FULL7_CONTRACT_V2_RC1"
DECISION_ARCHITECTURE = "SEVEN_MARKET_RAW_HEADS_THEN_COHERENCE"
RELEASE_STATUS = "BLOCKED_PENDING_V2_FORWARD_OOS"
RELEASE_AUTHORIZED = False
DECISION_CAPABLE_FAMILIES = ["1X2", "BTTS", "TOTALS"]
FAMILY_READINESS = {
    "1X2": "V2_FORWARD_OOS_REQUIRED",
    "BTTS": "V2_FORWARD_OOS_REQUIRED_HISTORICAL_BTTS_STRONGEST",
    "TOTALS": "V2_FORWARD_OOS_REQUIRED",
}
# Compatibility field: this now means release-authorized SPIELEN families,
# not decision-capable families. V2 structurally evaluates all three families.
SPIELEN_ALLOWED_FAMILIES: List[str] = []

router = APIRouter()
production_router = APIRouter()


def _complete_stage(stage: Any) -> None:
    if isinstance(stage, dict):
        for key in list(stage):
            stage[key] = True


def _production_release_view(decision: Mapping[str, Any]) -> Dict[str, Any]:
    """Expose V2 candidates without falsely authorizing them for production play.

    Inner DEVELOPMENT_ONLY / PENDING flags stay as fit provenance. All seven
    model decisions remain inspectable. Until the V2 release gate is authorized,
    raw/final SPIELEN states are candidates only and ``playable`` stays empty.
    """
    released = copy.deepcopy(dict(decision))
    released["status"] = RELEASE_STATUS
    released["release_authorized"] = RELEASE_AUTHORIZED
    released["decision_architecture"] = DECISION_ARCHITECTURE
    released["decision_capable_families"] = list(DECISION_CAPABLE_FAMILIES)
    released["family_readiness"] = dict(FAMILY_READINESS)
    released["spielen_allowed_families"] = list(SPIELEN_ALLOWED_FAMILIES)

    candidate_spielen = []
    blocked = []
    for market, row in (released.get("markets") or {}).items():
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
        blocked.append({
            **card,
            "release_block_reason": (
                "V2_FORWARD_OOS_RELEASE_NOT_AUTHORIZED"
                if row.get("decision") == "SPIELEN"
                else row.get("decision_reason")
            ),
        })

    released["candidate_spielen"] = candidate_spielen
    released["playable"] = candidate_spielen if RELEASE_AUTHORIZED else []
    released["blocked"] = blocked if not RELEASE_AUTHORIZED else [
        card for card in blocked if card.get("decision") != "SPIELEN"
    ]
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
        "model_contract_version": MODEL_FOUNDATION_VERSION,
        "model_bundle_sha256": MODEL_BUNDLE_SHA256,
        "decision_gate_version": DECISION_GATE_VERSION,
        "decision_architecture": DECISION_ARCHITECTURE,
        "expected_files": 7,
        "production_mounted": True,
        "markets": list(MARKETS),
        "all_markets_decision_enabled": True,
        "probability_mode_no_odds": True,
        "decision_capable_families": list(DECISION_CAPABLE_FAMILIES),
        "family_readiness": dict(FAMILY_READINESS),
        "spielen_allowed_families": list(SPIELEN_ALLOWED_FAMILIES),
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
            "release_authorized": RELEASE_AUTHORIZED,
            "decision_architecture": DECISION_ARCHITECTURE,
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
        },
    }


app = FastAPI(title="FULL-7 Architecture Contract Preview", version=APP_VERSION)
app.include_router(router)
