"""Development-only FULL-7 validation API.

This module is intentionally not imported by production app.py.
It validates seven uploaded FootyStats JSON files and returns the Bronze/Silver/Gold audit.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

from fastapi import FastAPI, File, HTTPException, UploadFile

from full7_foundation import process_full7, inventory_gold
from full7_gold_features import build_gold_features
from full7_signal_groups import audit_signal_groups
from full7_feature_sets import build_feature_sets
from full7_market_feature_sets import build_market_feature_sets

APP_VERSION = "0.4.0-full7-validation"
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
        registry = inventory_gold(gold)
        gold_features = build_gold_features(gold)
        signal_groups = audit_signal_groups(gold_features)
        feature_sets = build_feature_sets(gold_features)
        market_sets = build_market_feature_sets(feature_sets.get("core_probability") or [])
        result["market_feature_sets"] = {
            "market_feature_set_version": market_sets.get("market_feature_set_version"),
            "feature_counts": market_sets.get("feature_counts"),
            "family_counts": market_sets.get("family_counts"),
            "policy": market_sets.get("policy"),
            "research_readiness": {
                "1X2": "DEVELOPMENT_CANDIDATE_STRONG",
                "BTTS": "DEVELOPMENT_CANDIDATE_NEEDS_NEW_OOS",
                "TOTALS": "HOLD_NO_INCREMENTAL_SIGNAL_YET",
                "production_recommendation": False,
            },
        }
        result["signal_groups"] = {
            "signal_group_version": signal_groups.get("signal_group_version"),
            "feature_count": signal_groups.get("feature_count"),
            "assigned_feature_count": signal_groups.get("assigned_feature_count"),
            "unassigned_feature_count": signal_groups.get("unassigned_feature_count"),
            "forbidden_odds_feature_count": signal_groups.get("forbidden_odds_feature_count"),
            "available_group_count": signal_groups.get("available_group_count"),
            "available_evidence_cluster_count": signal_groups.get("available_evidence_cluster_count"),
            "available_evidence_clusters": signal_groups.get("available_evidence_clusters"),
            "groups": signal_groups.get("groups"),
            "policy": signal_groups.get("policy"),
        }
        result["gold_features"] = {
            "feature_builder_version": gold_features.get("feature_builder_version"),
            "feature_count": gold_features.get("feature_count"),
            "available_block_count": gold_features.get("available_block_count"),
            "blocks": [
                {
                    "name": block.get("name"),
                    "available": block.get("available"),
                    "feature_count": block.get("feature_count"),
                    "notes": block.get("notes"),
                }
                for block in gold_features.get("blocks", [])
            ],
            "policies": gold_features.get("policies"),
        }
        result["feature_registry"] = {
            "registry_version": registry.get("registry_version"),
            "field_count": registry.get("field_count"),
            "status_counts": registry.get("status_counts"),
            "family_counts": registry.get("family_counts"),
            "source_counts": registry.get("source_counts"),
            "redundancy_group_count": registry.get("redundancy_group_count"),
            "redundancy_groups_with_multiple_fields": registry.get("redundancy_groups_with_multiple_fields"),
            "review_required_count": registry.get("review_required_count"),
            "model_candidate_count": registry.get("model_candidate_count"),
            "blocked_or_nonpredictive_count": registry.get("blocked_or_nonpredictive_count"),
            "activation_policy": registry.get("activation_policy"),
            "evidence_policy": registry.get("evidence_policy"),
        }
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
        "market_model_readiness": {
            "1X2": "DEVELOPMENT_CANDIDATE_STRONG",
            "BTTS": "DEVELOPMENT_CANDIDATE_NEEDS_NEW_OOS",
            "TOTALS": "HOLD_NO_INCREMENTAL_SIGNAL_YET",
        },
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
