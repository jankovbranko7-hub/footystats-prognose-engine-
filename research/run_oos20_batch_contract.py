from __future__ import annotations

import base64
import hashlib
import json
import lzma
import os
from datetime import datetime, timezone
from pathlib import Path

from full7_contract_decision import build_decision_engine
from full7_contract_engine import MODEL_BUNDLE_SHA256

EXPECTED_BATCH_SHA256 = "25f5c9dd3e9fbaac151b6de2446741315a11c042699318ed486c4071369d2119"
PART_GLOB = "research/oos20_input/batch.part*.b64"
OUT_DIR = Path("research/oos20_output")

MARKETS = (
    "home_win", "draw", "away_win",
    "btts_yes", "btts_no", "over_2_5", "under_2_5",
)

def canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")

def main():
    parts = sorted(Path(".").glob(PART_GLOB))
    if len(parts) != 9:
        raise RuntimeError(f"expected 9 batch parts, found {len(parts)}")
    encoded = "".join(p.read_text(encoding="utf-8").strip() for p in parts)
    raw = lzma.decompress(base64.b64decode(encoded))
    actual = hashlib.sha256(raw).hexdigest()
    if actual != EXPECTED_BATCH_SHA256:
        raise RuntimeError(f"batch SHA mismatch: {actual}")
    batch = json.loads(raw.decode("utf-8"))
    if batch.get("result_joined"):
        raise RuntimeError("outcome blind batch unexpectedly has result_joined=true")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    summaries = []
    for item in batch["items"]:
        mid = int(item["match_id"])
        kickoff = int(item["kickoff_unix"])
        started = datetime.now(timezone.utc)
        started_unix = int(started.timestamp())
        if started_unix >= kickoff:
            summaries.append({
                "match_id": mid, "home": item["home"], "away": item["away"],
                "kickoff_unix": kickoff, "status": "MISSED_KICKOFF_NOT_OOS",
                "freeze_started_unix": started_unix,
            })
            continue

        decision = build_decision_engine(
            item["gold_features"],
            validation_quality=item.get("quality") or {},
        )
        frozen = datetime.now(timezone.utc)
        frozen_unix = int(frozen.timestamp())
        if frozen_unix >= kickoff:
            summaries.append({
                "match_id": mid, "home": item["home"], "away": item["away"],
                "kickoff_unix": kickoff, "status": "MISSED_KICKOFF_NOT_OOS",
                "freeze_started_unix": started_unix,
                "freeze_finished_unix": frozen_unix,
            })
            continue

        if set(decision["markets"]) != set(MARKETS):
            raise RuntimeError(f"seven-market contract failed for {mid}")

        payload = {
            "status": "PREDICTION_FROZEN_BEFORE_RESULT_JOIN",
            "match_id": mid,
            "home": item["home"],
            "away": item["away"],
            "kickoff_unix": kickoff,
            "source_group": item.get("source_group"),
            "runtime_commit": os.environ.get("GITHUB_SHA"),
            "model_bundle_sha256": MODEL_BUNDLE_SHA256,
            "input_file_sha256": item.get("file_sha256"),
            "gold": {
                "feature_builder_version": item["gold_features"].get("feature_builder_version"),
                "feature_count": item["gold_features"].get("feature_count"),
                "available_block_count": item["gold_features"].get("available_block_count"),
                "quality": item.get("quality"),
                "strict_pre_match_audit": item.get("audit"),
                "issues": item.get("issues"),
            },
            "probabilities": decision["probabilities"],
            "families": decision["families"],
            "markets": decision["markets"],
            "evidence": decision["evidence"],
            "sample_security": decision["sample_security"],
            "data_quality_support": decision["data_quality_support"],
            "coherence": decision["coherence"],
            "contract_stage": decision["contract_stage"],
            "secondary_context": decision["evidence"]["secondary_context"],
            "contract_flags": {
                "all_seven_markets_present": True,
                "complete_evidence_persisted": True,
                "result_joined": False,
                "frozen_before_kickoff": True,
            },
        }
        payload["prediction_payload_sha256"] = hashlib.sha256(canonical(payload)).hexdigest()
        payload["freeze_audit"] = {
            "frozen_before_result_join": True,
            "result_joined": False,
            "freeze_started_at_utc": started.isoformat(),
            "frozen_at_utc": frozen.isoformat(),
            "frozen_at_unix": frozen_unix,
            "kickoff_unix": kickoff,
            "workflow_run_id": os.environ.get("GITHUB_RUN_ID"),
            "workflow_head_sha": os.environ.get("GITHUB_SHA"),
        }
        out = OUT_DIR / f"FULL7_OOS_{mid}_FROZEN.json"
        out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        summaries.append({
            "match_id": mid, "home": item["home"], "away": item["away"],
            "kickoff_unix": kickoff,
            "status": payload["status"],
            "frozen_at_unix": frozen_unix,
            "prediction_payload_sha256": payload["prediction_payload_sha256"],
            "probabilities": payload["probabilities"],
            "decisions": {k: v["decision"] for k, v in payload["markets"].items()},
        })

    summary = {
        "batch_id": batch.get("batch_id"),
        "target_valid_matches": 20,
        "batch_sha256": actual,
        "model_bundle_sha256": MODEL_BUNDLE_SHA256,
        "workflow_head_sha": os.environ.get("GITHUB_SHA"),
        "result_joined": False,
        "items": summaries,
        "valid_frozen_count": sum(x["status"] == "PREDICTION_FROZEN_BEFORE_RESULT_JOIN" for x in summaries),
        "missed_count": sum(x["status"] == "MISSED_KICKOFF_NOT_OOS" for x in summaries),
    }
    (OUT_DIR / "FULL7_OOS20_BATCH_SUMMARY.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print("FULL7_OOS20_SUMMARY=" + json.dumps(summary, separators=(",", ":"), ensure_ascii=False))

if __name__ == "__main__":
    main()
