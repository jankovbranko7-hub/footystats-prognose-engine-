from __future__ import annotations

import base64
import hashlib
import json
import tarfile
import tempfile
from pathlib import Path

from full7_foundation import process_full7
from full7_gold_features import build_gold_features
from full7_contract_decision import build_decision_engine

EXPECTED_BUNDLE_SHA256 = "36c6b1592653c57d6f5bf275dff6c5533a3e30a7d1b01e917273ea2b0bd4f122"
PART_GLOB = "research/oos001_input/oos001.part*.b64"

ORDER = [
    "8558326_MatchDaten.json",
    "17148_LeagueDaten.json",
    "8558326_FormDaten.json",
    "8558326_TableDaten.json",
    "8558326_PlayerDaten.json",
    "8558326_RefereeDaten.json",
    "8558326_ManagerDaten.json",
]


def main() -> None:
    parts = sorted(Path(".").glob(PART_GLOB))
    if len(parts) != 8:
        raise RuntimeError(f"expected 8 OOS bundle parts, found {len(parts)}")

    encoded = "".join(path.read_bytes().decode("ascii") for path in parts)
    bundle = base64.b64decode(encoded, validate=True)
    actual_sha = hashlib.sha256(bundle).hexdigest()
    if actual_sha != EXPECTED_BUNDLE_SHA256:
        raise RuntimeError(f"OOS bundle SHA mismatch: {actual_sha}")

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        tar_path = tmp_path / "oos001.tar.gz"
        tar_path.write_bytes(bundle)
        with tarfile.open(tar_path, "r:gz") as tar:
            tar.extractall(tmp_path / "input")

        parsed = []
        file_hashes = {}
        for name in ORDER:
            path = tmp_path / "input" / name
            raw = path.read_bytes()
            file_hashes[name] = hashlib.sha256(raw).hexdigest()
            parsed.append({"name": name, "data": json.loads(raw.decode("utf-8-sig"))})

        processed = process_full7(parsed)
        if not processed.get("ok") or not processed.get("gold"):
            raise RuntimeError(json.dumps({
                "code": "FULL7_VALIDATION_FAILED",
                "stage": processed.get("stage"),
                "issues": processed.get("issues"),
            }, ensure_ascii=False))

        gold = processed["gold"]
        gold_features = build_gold_features(gold)
        decision = build_decision_engine(
            gold_features,
            validation_quality=gold.get("quality") or {},
        )

        evidence = decision["evidence"]
        selected_summary = {}
        for family, family_row in decision["families"].items():
            market = family_row["selected_market"]
            market_ev = evidence["market_evidence"][market]
            selected_summary[family] = {
                "selected_market": market,
                "base_probability": family_row["base_probability"],
                "evidence_adjusted_probability": family_row["evidence_adjusted_probability"],
                "reliability_score": family_row["reliability_score"],
                "decision": family_row["decision"],
                "decision_reason": family_row["decision_reason"],
                "thresholds": family_row["thresholds"],
                "confirm_count": market_ev["confirm_count"],
                "counter_count": market_ev["counter_count"],
                "neutral_count": market_ev["neutral_count"],
                "strongest_counter": market_ev["strongest_counter"],
                "robustness": market_ev["robustness"],
            }

        output = {
            "oos_id": "OOS_001_8558326",
            "status": "PREDICTION_FROZEN_BEFORE_RESULT_JOIN",
            "bundle_sha256": actual_sha,
            "file_sha256": file_hashes,
            "identity": gold.get("identity"),
            "quality": gold.get("quality"),
            "gold": {
                "feature_builder_version": gold_features.get("feature_builder_version"),
                "feature_count": gold_features.get("feature_count"),
                "available_block_count": gold_features.get("available_block_count"),
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
            "families": selected_summary,
            "markets": decision["markets"],
            "sample_security": decision["sample_security"],
            "data_quality_support": decision["data_quality_support"],
            "coherence": decision["coherence"],
            "contract_stage": decision["contract_stage"],
            "secondary_context": evidence["secondary_context"],
        }

        out_path = Path("research/oos001_output.json")
        out_path.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
        compact = json.dumps(output, separators=(",", ":"), ensure_ascii=False)
        print("OOS001_RESULT_JSON=" + compact)


if __name__ == "__main__":
    main()
