from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import tarfile
from datetime import datetime, timezone
from pathlib import Path

from full7_foundation import process_full7
from full7_gold_features import build_gold_features
from full7_contract_decision import build_decision_engine
from full7_contract_engine import MODEL_BUNDLE_SHA256

EXPECTED_ARCHIVE_SHA256 = "3ee4c4382c0a2c57ab2f8c0be37cf71ed362bc520c7e5b711634c990e21810aa"
PART_GLOB = "research/oos20_input_batchB/raw.part*.b64"
EXPECTED_PARTS = 5
EXPECTED_MATCH_IDS = (8570349, 8570376, 8420411, 8554518)
OUT_DIR = Path("research/oos20_output_batchB")
MARKETS = (
    "home_win", "draw", "away_win",
    "btts_yes", "btts_no", "over_2_5", "under_2_5",
)

def canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")

def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()

def load_archive():
    parts = sorted(Path(".").glob(PART_GLOB))
    if len(parts) != EXPECTED_PARTS:
        raise RuntimeError(f"expected {EXPECTED_PARTS} Batch-B parts, found {len(parts)}")
    encoded = "".join(p.read_text(encoding="utf-8").strip() for p in parts)
    archive = base64.b64decode(encoded, validate=True)
    actual = sha(archive)
    if actual != EXPECTED_ARCHIVE_SHA256:
        raise RuntimeError(f"Batch-B archive SHA mismatch: {actual}")
    return archive, actual

def read_tar_json(tf: tarfile.TarFile, name: str):
    member = tf.getmember(name)
    if not member.isfile():
        raise RuntimeError(f"not a regular file: {name}")
    fh = tf.extractfile(member)
    if fh is None:
        raise RuntimeError(f"cannot read: {name}")
    raw = fh.read()
    return raw, json.loads(raw.decode("utf-8-sig"))

def fixture_names(match_data):
    payload = match_data.get("payload", match_data)
    row = payload.get("data", payload) if isinstance(payload, dict) else {}
    if not isinstance(row, dict):
        row = {}
    return (
        str(row.get("home_name") or row.get("homeName") or row.get("home_name_clean") or ""),
        str(row.get("away_name") or row.get("awayName") or row.get("away_name_clean") or ""),
    )

def main():
    archive, archive_sha = load_archive()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    summaries = []

    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:xz") as tf:
        for member in tf.getmembers():
            path = Path(member.name)
            if path.is_absolute() or ".." in path.parts:
                raise RuntimeError(f"unsafe tar path: {member.name}")

        _, manifest = read_tar_json(tf, "manifest.json")
        mids = tuple(int(x) for x in manifest.get("match_ids", []))
        if set(mids) != set(EXPECTED_MATCH_IDS) or len(mids) != len(EXPECTED_MATCH_IDS):
            raise RuntimeError(f"unexpected Batch-B match IDs: {mids}")

        for mid in EXPECTED_MATCH_IDS:
            started = datetime.now(timezone.utc)
            started_unix = int(started.timestamp())
            files_meta = manifest["matches"][str(mid)]
            parsed = []
            file_hashes = {}
            match_obj = None

            for role in ("MatchDaten","LeagueDaten","FormDaten","TableDaten","PlayerDaten","RefereeDaten","ManagerDaten"):
                meta = files_meta[role]
                raw, obj = read_tar_json(tf, meta["arcname"])
                actual_file_sha = sha(raw)
                if actual_file_sha != meta["sha256"]:
                    raise RuntimeError(f"file SHA mismatch mid={mid} role={role}")
                file_hashes[meta["source"]] = actual_file_sha
                parsed.append({"name": meta["source"], "data": obj})
                if role == "MatchDaten":
                    match_obj = obj

            if match_obj is None:
                raise RuntimeError(f"missing match object for {mid}")
            match_meta = match_obj.get("_footystats_meta") or {}
            kickoff = int(match_meta["kickoff_unix"])
            home, away = fixture_names(match_obj)

            if started_unix >= kickoff:
                summaries.append({
                    "match_id": mid, "home": home, "away": away,
                    "kickoff_unix": kickoff,
                    "status": "MISSED_KICKOFF_NOT_OOS",
                    "freeze_started_unix": started_unix,
                })
                continue

            processed = process_full7(parsed)
            if not processed.get("ok") or not processed.get("gold"):
                raise RuntimeError(json.dumps({
                    "code": "FULL7_VALIDATION_FAILED",
                    "match_id": mid,
                    "stage": processed.get("stage"),
                    "issues": processed.get("issues"),
                }, ensure_ascii=False))

            gold = processed["gold"]
            identity = gold.get("identity") or {}
            if int(identity.get("match_id") or -1) != mid:
                raise RuntimeError(f"identity mismatch for {mid}: {identity}")

            gold_features = build_gold_features(gold)
            decision = build_decision_engine(
                gold_features,
                validation_quality=gold.get("quality") or {},
            )
            frozen = datetime.now(timezone.utc)
            frozen_unix = int(frozen.timestamp())
            if frozen_unix >= kickoff:
                summaries.append({
                    "match_id": mid, "home": home, "away": away,
                    "kickoff_unix": kickoff,
                    "status": "MISSED_KICKOFF_NOT_OOS",
                    "freeze_started_unix": started_unix,
                    "freeze_finished_unix": frozen_unix,
                })
                continue

            if set(decision["markets"]) != set(MARKETS):
                raise RuntimeError(f"seven-market contract failed for {mid}")

            evidence = decision["evidence"]
            output = {
                "status": "PREDICTION_FROZEN_BEFORE_RESULT_JOIN",
                "match_id": mid,
                "home": home,
                "away": away,
                "kickoff_unix": kickoff,
                "archive_sha256": archive_sha,
                "file_sha256": file_hashes,
                "identity": identity,
                "quality": gold.get("quality"),
                "runtime_commit": os.environ.get("GITHUB_SHA"),
                "model_bundle_sha256": MODEL_BUNDLE_SHA256,
                "gold": {
                    "feature_builder_version": gold_features.get("feature_builder_version"),
                    "feature_count": gold_features.get("feature_count"),
                    "available_block_count": gold_features.get("available_block_count"),
                    "strict_pre_match_audit": processed.get("audit"),
                    "issues": processed.get("issues"),
                },
                "probabilities": decision["probabilities"],
                "model_support": {
                    "catboost": evidence["probability_layer"]["model_support"]["catboost"],
                    "goal_model": evidence["probability_layer"]["model_support"]["goal_model"],
                    "goal_parameters": evidence["probability_layer"]["model_support"]["goal_parameters"],
                    "ensemble": evidence["probability_layer"]["ensemble"],
                    "calibrated": evidence["probability_layer"]["calibrated"],
                    "ensemble_policy": evidence["probability_layer"]["ensemble_policy"],
                    "calibration_policy": evidence["probability_layer"]["calibration_policy"],
                },
                "families": decision["families"],
                "markets": decision["markets"],
                "evidence": evidence,
                "sample_security": decision["sample_security"],
                "data_quality_support": decision["data_quality_support"],
                "coherence": decision["coherence"],
                "contract_stage": decision["contract_stage"],
                "secondary_context": evidence["secondary_context"],
                "contract_flags": {
                    "all_seven_markets_present": True,
                    "complete_evidence_persisted": True,
                    "result_joined": False,
                    "frozen_before_kickoff": True,
                    "no_odds_policy": bool(gold_features.get("policies", {}).get("no_odds")),
                },
            }
            prediction_basis = dict(output)
            output["prediction_payload_sha256"] = hashlib.sha256(canonical(prediction_basis)).hexdigest()
            output["freeze_audit"] = {
                "frozen_before_result_join": True,
                "result_joined": False,
                "freeze_started_at_utc": started.isoformat(),
                "frozen_at_utc": frozen.isoformat(),
                "frozen_at_unix": frozen_unix,
                "kickoff_unix": kickoff,
                "workflow_run_id": os.environ.get("GITHUB_RUN_ID"),
                "workflow_head_sha": os.environ.get("GITHUB_SHA"),
            }

            out_path = OUT_DIR / f"FULL7_OOS_{mid}_FROZEN.json"
            out_path.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
            summaries.append({
                "match_id": mid, "home": home, "away": away,
                "kickoff_unix": kickoff,
                "status": output["status"],
                "frozen_at_unix": frozen_unix,
                "seconds_before_kickoff": kickoff - frozen_unix,
                "prediction_payload_sha256": output["prediction_payload_sha256"],
                "probabilities": output["probabilities"],
                "decisions": {k: v["decision"] for k, v in output["markets"].items()},
                "feature_count": gold_features.get("feature_count"),
                "available_block_count": gold_features.get("available_block_count"),
            })

    summary = {
        "schema_version": "FULL7_OOS20_BATCH_B_FREEZE_1.0",
        "target_valid_matches": 20,
        "archive_sha256": archive_sha,
        "model_bundle_sha256": MODEL_BUNDLE_SHA256,
        "workflow_head_sha": os.environ.get("GITHUB_SHA"),
        "result_joined": False,
        "items": summaries,
        "valid_frozen_count": sum(x["status"] == "PREDICTION_FROZEN_BEFORE_RESULT_JOIN" for x in summaries),
        "missed_count": sum(x["status"] == "MISSED_KICKOFF_NOT_OOS" for x in summaries),
    }
    (OUT_DIR / "FULL7_OOS20_BATCH_B_SUMMARY.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print("FULL7_OOS20_BATCH_B_SUMMARY=" + json.dumps(summary, separators=(",", ":"), ensure_ascii=False))

if __name__ == "__main__":
    main()
