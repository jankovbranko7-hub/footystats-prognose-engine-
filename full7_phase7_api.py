"""Non-production API surface for the FULL-7 Phase-7 release candidate."""
from __future__ import annotations

import json
import hashlib
import hmac
import math
import os
import threading
import time
from pathlib import Path
from typing import Any, Mapping

from fastapi import APIRouter
from pydantic import BaseModel

from full7_phase7_decision import (
    FINAL_DECISION_SOURCE,
    FINAL_PHASE5_MANIFEST_SHA256,
    MANUAL_PERFORMANCE_GATES,
    PHASE5_CALIBRATION_DECISION_LOCK_SHA256,
    PHASE6_DECISION_LOCK_SHA256,
    PHASE6_MANIFEST_SHA256,
    REQUIRED_INTEGRITY_GATES,
    evaluate_phase7_decision,
)
from full7_phase7_features import extract_phase4_features
from full7_phase7_runtime import (
    Full7Phase7Runtime,
    RuntimeArtifactError,
    load_runtime_bundle,
)


FULL7_RELEASE_CANDIDATE_VERSION = "FULL7_FINAL_RC_1.0.0"
router = APIRouter()
_runtime_lock = threading.Lock()
_runtime_cache: Full7Phase7Runtime | None = None


class Phase7NormalizedRequest(BaseModel):
    home_id: int
    away_id: int
    sources: dict[str, Any]
    input_integrity: dict[str, Any]


def _read_pinned_manifest(
    path: Path | str, *, expected_sha256: str
) -> dict[str, Any]:
    manifest_path = Path(path)
    raw = manifest_path.read_bytes()
    actual = hashlib.sha256(raw).hexdigest()
    if actual != expected_sha256:
        raise RuntimeArtifactError(f"manifest_hash_mismatch:{actual}")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeArtifactError("manifest_decode_failed") from exc
    if not isinstance(value, dict) or not isinstance(value.get("artifacts"), dict):
        raise RuntimeArtifactError("manifest_schema_invalid")
    return value


def _validated_input_integrity(
    *,
    sources: Mapping[str, Any],
    home_id: int,
    away_id: int,
    proof: Any,
    hmac_key: bytes | None,
    decision_timestamp: float,
) -> bool:
    if (
        not isinstance(proof, Mapping)
        or not isinstance(hmac_key, bytes)
        or len(hmac_key) < 32
        or isinstance(decision_timestamp, bool)
    ):
        return False
    try:
        decision_time = float(decision_timestamp)
    except (TypeError, ValueError, OverflowError):
        return False
    if not math.isfinite(decision_time):
        return False
    signature = proof.get("collector_hmac_sha256")
    if not isinstance(signature, str) or len(signature) != 64:
        return False
    unsigned_proof = {
        key: value for key, value in proof.items() if key != "collector_hmac_sha256"
    }
    try:
        signed_message = json.dumps(
            unsigned_proof,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError, OverflowError):
        return False
    expected_signature = hmac.new(hmac_key, signed_message, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected_signature):
        return False
    if (
        proof.get("source_contract") != "FULL7_CP2_STRICT_PREMATCH_NORMALIZED_1.0"
        or proof.get("strict_pre_match") is not True
    ):
        return False
    if any(
        isinstance(proof.get(name), bool)
        for name in (
            "match_id",
            "home_id",
            "away_id",
            "source_max_timestamp",
            "kickoff_timestamp",
        )
    ):
        return False
    try:
        proof_home = int(proof["home_id"])
        proof_away = int(proof["away_id"])
        match_id = int(proof["match_id"])
        source_max = float(proof["source_max_timestamp"])
        kickoff = float(proof["kickoff_timestamp"])
        expected_sources_sha = str(proof["sources_sha256"])
    except (KeyError, TypeError, ValueError, OverflowError):
        return False
    if (
        proof_home != home_id
        or proof_away != away_id
        or home_id <= 0
        or away_id <= 0
        or home_id == away_id
        or match_id <= 0
        or not math.isfinite(source_max)
        or not math.isfinite(kickoff)
        or not source_max.is_integer()
        or not kickoff.is_integer()
        or source_max >= kickoff
    ):
        return False
    try:
        canonical_sources = json.dumps(
            sources,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError, OverflowError):
        return False
    if (
        len(expected_sources_sha) != 64
        or hashlib.sha256(canonical_sources).hexdigest() != expected_sources_sha
    ):
        return False
    required = ("match", "league", "form", "table", "player")
    if any(not isinstance(sources.get(name), Mapping) for name in required):
        return False
    match = sources["match"]
    if set(match) - {"found", "stored_postmatch", "prematch_optional", "identity"}:
        return False
    if (
        match.get("found") is not True
        or match.get("stored_postmatch") is not False
        or not isinstance(match.get("prematch_optional"), Mapping)
        or not isinstance(match.get("identity"), Mapping)
    ):
        return False
    identity = match["identity"]
    identity_fields = (
        (("homeID", "home_id"), home_id),
        (("awayID", "away_id"), away_id),
        (("match_id", "id"), match_id),
    )
    for keys, expected in identity_fields:
        present = [key for key in keys if key in identity]
        if not present:
            return False
        for key in present:
            try:
                if int(identity[key]) != expected:
                    return False
            except (TypeError, ValueError, OverflowError):
                return False
    try:
        identity_kickoff = int(identity["date_unix"])
    except (KeyError, TypeError, ValueError, OverflowError):
        return False
    if identity_kickoff != int(kickoff):
        return False

    league, form, table, player = (
        sources["league"],
        sources["form"],
        sources["table"],
        sources["player"],
    )
    try:
        if int(form["home_id"]) != home_id or int(form["away_id"]) != away_id:
            return False
        if int(form["kickoff_unix"]) != identity_kickoff:
            return False
    except (KeyError, TypeError, ValueError, OverflowError):
        return False
    if form.get("rule") != "date_unix < kickoff AND id != target":
        return False
    if any(not isinstance(form.get(side), Mapping) for side in ("home", "away")):
        return False
    embedded_timestamps: list[int] = []
    for side in ("home", "away"):
        source_matches = form[side].get("source_matches")
        if not isinstance(source_matches, list):
            return False
        for source in source_matches:
            if not isinstance(source, Mapping):
                return False
            try:
                source_match_id = int(source["match_id"])
                source_time = int(source["date_unix"])
            except (KeyError, TypeError, ValueError, OverflowError):
                return False
            if source_match_id == match_id or source_time >= identity_kickoff:
                return False
            embedded_timestamps.append(source_time)

    teams = league.get("teams_full_home_away")
    if not isinstance(teams, list):
        return False
    league_team_ids = set()
    for row in teams:
        if not isinstance(row, Mapping):
            continue
        value = row.get("id", row.get("team_id"))
        try:
            league_team_ids.add(int(value))
        except (TypeError, ValueError, OverflowError):
            continue
    if not {home_id, away_id}.issubset(league_team_ids):
        return False
    league_derived = league.get("league_aggregates_derived")
    if not isinstance(league_derived, Mapping):
        return False
    source_ids = league_derived.get("league_source_match_ids")
    if not isinstance(source_ids, list):
        return False
    try:
        if match_id in {int(value) for value in source_ids}:
            return False
        league_source_max = int(league_derived["league_source_max_timestamp"])
    except (KeyError, TypeError, ValueError, OverflowError):
        return False
    if league_source_max >= identity_kickoff:
        return False
    embedded_timestamps.append(league_source_max)
    if not embedded_timestamps or source_max != float(max(embedded_timestamps)):
        return False
    if decision_time < source_max or decision_time >= kickoff:
        return False

    if any(
        not isinstance(table.get(name), Mapping)
        for name in ("home_row", "away_row")
    ):
        return False
    try:
        table_home = int(table["home_row"].get("id", table["home_row"].get("team_id")))
        table_away = int(table["away_row"].get("id", table["away_row"].get("team_id")))
    except (TypeError, ValueError, OverflowError):
        return False
    if table_home != home_id or table_away != away_id:
        return False
    if not isinstance(player.get("players"), list):
        return False
    pagination = player.get("pagination")
    if not isinstance(pagination, Mapping) or pagination.get("pagination_complete") is not True:
        return False
    try:
        total_results = int(pagination["total_results"])
        loaded_rows = int(pagination["loaded_rows"])
        max_page = int(pagination["max_page"])
        loaded_pages = int(pagination["loaded_pages"])
    except (KeyError, TypeError, ValueError, OverflowError):
        return False
    if (total_results and loaded_rows != total_results) or (
        max_page and loaded_pages != max_page
    ):
        return False
    for row in player["players"]:
        if not isinstance(row, Mapping):
            return False
        try:
            club_id = int(row.get("club_team_id", row.get("team_id")))
        except (TypeError, ValueError, OverflowError):
            return False
        if club_id not in {home_id, away_id}:
            return False

    label_keys = {"actual_1x2", "actual_btts", "actual_over25", "hit_ou", "hit_btts"}
    forbidden_match = {
        "homeGoalCount", "awayGoalCount", "overallGoalCount", "totalGoalCount",
        "homeGoals", "awayGoals", "homeGoals_timings", "awayGoals_timings",
        "HTGoalCount", "ht_goals_team_a", "ht_goals_team_b", "winningTeam",
        "attendance", "team_a_shots", "team_b_shots", "team_a_possession",
        "team_b_possession", "totalCornerCount",
    } | label_keys

    def walk(value: Any):
        if isinstance(value, Mapping):
            for key, child in value.items():
                yield str(key)
                yield from walk(child)
        elif isinstance(value, list):
            for child in value:
                yield from walk(child)

    for source_name in required:
        for key in walk(sources[source_name]):
            if key in label_keys or "odd" in key.lower():
                return False
            if source_name == "match" and key in forbidden_match:
                return False
    return True


def _fail_closed(reason: str) -> dict[str, Any]:
    result = evaluate_phase7_decision(
        probabilities={"home": math.nan, "draw": 0.0, "away": 0.0, "btts_yes": 0.0},
        feature_coverage={"1X2": 0.0, "BTTS": 0.0},
        integrity_gates={name: False for name in REQUIRED_INTEGRITY_GATES},
    )
    result["fail_closed_reasons"] = sorted(
        set(result["fail_closed_reasons"] + [reason])
    )
    return result


def _load_configured_runtime() -> Full7Phase7Runtime:
    global _runtime_cache
    if _runtime_cache is not None:
        return _runtime_cache
    with _runtime_lock:
        if _runtime_cache is not None:
            return _runtime_cache
        bundle = Path(
            os.environ.get(
                "FULL7_PHASE7_BUNDLE_PATH",
                "artifacts/full7_phase7_rc/FULL7_FINAL_RC_BUNDLE.pkl.gz",
            )
        )
        manifest = Path(
            os.environ.get(
                "FULL7_PHASE7_MANIFEST_PATH",
                "artifacts/full7_phase7_rc/FULL7_FINAL_RC_MANIFEST.json",
            )
        )
        manifest_pin = os.environ.get("FULL7_PHASE7_MANIFEST_SHA256", "").strip()
        if len(manifest_pin) != 64 or any(
            char not in "0123456789abcdef" for char in manifest_pin
        ):
            raise RuntimeArtifactError("manifest_external_pin_missing")
        data = _read_pinned_manifest(manifest, expected_sha256=manifest_pin)
        expected = data["artifacts"][bundle.name]["sha256"]
        _runtime_cache, _metadata = load_runtime_bundle(bundle, expected_sha256=expected)
        return _runtime_cache


def predict_phase7_rc(
    *,
    sources: Any,
    home_id: int,
    away_id: int,
    input_integrity: Any,
    input_hmac_key: bytes | None = None,
    decision_timestamp: float | None = None,
    runtime: Full7Phase7Runtime | None = None,
) -> dict[str, Any]:
    """Predict from the exact normalized Phase-4 source contract, or fail closed."""
    if not isinstance(sources, Mapping) or isinstance(home_id, bool) or isinstance(away_id, bool):
        return _fail_closed("INPUT_NORMALIZATION_FAIL")
    try:
        normalized_home_id = int(home_id)
        normalized_away_id = int(away_id)
    except (TypeError, ValueError, OverflowError):
        return _fail_closed("INPUT_NORMALIZATION_FAIL")
    trusted_hmac_key = input_hmac_key
    if trusted_hmac_key is None:
        configured_key = os.environ.get("FULL7_PHASE7_INPUT_HMAC_KEY")
        trusted_hmac_key = configured_key.encode("utf-8") if configured_key else None
    trusted_decision_time = time.time() if decision_timestamp is None else decision_timestamp
    if not _validated_input_integrity(
        sources=sources,
        home_id=normalized_home_id,
        away_id=normalized_away_id,
        proof=input_integrity,
        hmac_key=trusted_hmac_key,
        decision_timestamp=trusted_decision_time,
    ):
        return _fail_closed("INPUT_INTEGRITY_FAIL")
    try:
        features, _groups = extract_phase4_features(
            sources, home_id=normalized_home_id, away_id=normalized_away_id
        )
        active_runtime = runtime or _load_configured_runtime()
        result = active_runtime.predict(
            features,
            input_integrity_verified=True,
            feature_schema_verified=True,
        )
        result["input_contract"] = "PHASE4_NORMALIZED_FEATURE_SOURCES"
        result["extracted_feature_count"] = len(features)
        return result
    except Exception as exc:
        result = _fail_closed("RUNTIME_OR_INPUT_INTEGRITY_FAIL")
        result["runtime_error"] = type(exc).__name__
        return result


@router.get("/api/full7/rc/engine-health")
def phase7_engine_health() -> dict[str, Any]:
    manifest_pin = os.environ.get("FULL7_PHASE7_MANIFEST_SHA256", "").strip()
    input_key = os.environ.get("FULL7_PHASE7_INPUT_HMAC_KEY", "")
    manifest_pin_configured = len(manifest_pin) == 64 and all(
        char in "0123456789abcdef" for char in manifest_pin
    )
    input_hmac_configured = len(input_key.encode("utf-8")) >= 32
    runtime_ready = manifest_pin_configured and input_hmac_configured
    return {
        "ok": runtime_ready,
        "code_status": "PASS_RELEASE_CANDIDATE",
        "runtime_ready": runtime_ready,
        "engine": "FOOTYSTATS_FULL7_FINAL_RC",
        "engine_version": FULL7_RELEASE_CANDIDATE_VERSION,
        "production_mounted": False,
        "main_changed": False,
        "input_integrity_mode": "HMAC_TRUSTED_STRICT_PREMATCH_CP2",
        "input_hmac_configured": input_hmac_configured,
        "manifest_pin_configured": manifest_pin_configured,
        "final_decision_source": FINAL_DECISION_SOURCE,
        "manual_performance_gates": MANUAL_PERFORMANCE_GATES,
        "legacy_v3_1_override_active": False,
        "o25_status": "HOLD",
        "o25_decision_rules_active": False,
        "model_lock_1x2": {"model": "GOAL_POISSON_LOCKED", "features": 298},
        "model_lock_btts": {"model": "GOAL_POISSON_LOCKED", "features": 209},
        "calibration_1x2": "MULTINOMIAL_LOGIT",
        "calibration_btts": "IDENTITY",
        "active_play_thresholds": {"HOME": 0.50, "AWAY": 0.50, "BTTS_YES": 0.55},
        "spielen_allowed_families": ["HOME", "AWAY", "BTTS_YES"],
        "frozen_hashes": {
            "PHASE5_CALIBRATION_DECISION_LOCK_SHA256": PHASE5_CALIBRATION_DECISION_LOCK_SHA256,
            "FINAL_PHASE5_MANIFEST_SHA256": FINAL_PHASE5_MANIFEST_SHA256,
            "PHASE6_DECISION_LOCK_SHA256": PHASE6_DECISION_LOCK_SHA256,
            "PHASE6_MANIFEST_SHA256": PHASE6_MANIFEST_SHA256,
        },
    }


@router.post("/api/full7/rc/predict-normalized")
def phase7_predict_normalized(request: Phase7NormalizedRequest) -> dict[str, Any]:
    return predict_phase7_rc(
        sources=request.sources,
        home_id=request.home_id,
        away_id=request.away_id,
        input_integrity=request.input_integrity,
    )
