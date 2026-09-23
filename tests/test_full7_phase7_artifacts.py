import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from research.full7_phase7_finalize import (
    Phase7Error,
    audit_manifest,
    audit_phase6_semantics,
    final_fit_indices,
)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_manifest_audit_verifies_every_member_and_detects_tampering(tmp_path):
    artifact = tmp_path / "LOCK.json"
    artifact.write_text('{"status":"frozen"}\n', encoding="utf-8")
    manifest = tmp_path / "MANIFEST.json"
    manifest.write_text(
        json.dumps({"artifacts": {artifact.name: {"bytes": artifact.stat().st_size, "sha256": sha(artifact)}}}),
        encoding="utf-8",
    )
    receipt = audit_manifest(manifest, expected_manifest_sha256=sha(manifest))
    assert receipt["artifact_count"] == 1
    assert receipt["all_artifacts_verified"] is True

    artifact.write_text('{"status":"changed"}\n', encoding="utf-8")
    with pytest.raises(Phase7Error, match="artifact_hash_mismatch"):
        audit_manifest(manifest, expected_manifest_sha256=sha(manifest))


def test_phase6_semantic_audit_accepts_only_locked_release_directions():
    lock = {
        "O25_HOLD": True,
        "O25_PHASE6_READY": False,
        "OOS_USED_FOR_THRESHOLD_SELECTION": False,
        "OOS_USED_FOR_GATE_SELECTION": False,
        "market_readiness": {
            "1X2": {"status": "READY", "model": "GOAL_POISSON_LOCKED", "features": 298, "calibrator": "MULTINOMIAL_LOGIT"},
            "BTTS": {"status": "READY", "model": "GOAL_POISSON_LOCKED", "features": 209, "calibrator": "IDENTITY"},
            "O25": {"status": "HOLD", "model": "ENSEMBLE_HGB_POISSON_LOCKED", "features": 240},
        },
        "directions": {
            "HOME": {"PLAY_AVAILABLE": True, "WATCH_AVAILABLE": True, "quality_floor_train_q01": 0.97775, "PLAY": {"threshold": 0.50, "supported_probability_ceiling": 0.80, "margin_threshold": 0.0}, "WATCH": {"threshold": 0.40, "supported_probability_ceiling": 0.85}},
            "DRAW": {"PLAY_AVAILABLE": False, "WATCH_AVAILABLE": False, "PLAY": None, "WATCH": None},
            "AWAY": {"PLAY_AVAILABLE": True, "WATCH_AVAILABLE": True, "quality_floor_train_q01": 0.97775, "PLAY": {"threshold": 0.50, "supported_probability_ceiling": 0.65, "margin_threshold": 0.0}, "WATCH": {"threshold": 0.40, "supported_probability_ceiling": 0.70}},
            "BTTS_YES": {"PLAY_AVAILABLE": True, "WATCH_AVAILABLE": True, "quality_floor_train_q01": 0.98086, "PLAY": {"threshold": 0.55, "supported_probability_ceiling": 0.70, "margin_threshold": 0.0}, "WATCH": {"threshold": 0.50, "supported_probability_ceiling": 0.70}},
            "BTTS_NO": {"PLAY_AVAILABLE": False, "WATCH_AVAILABLE": True, "PLAY": None, "WATCH": {"threshold": 0.50, "supported_probability_ceiling": 0.60}},
        },
        "historical_reference_only": {
            "V3_1_1X2_PLAY_THRESHOLD": 0.71,
            "V3_1_BTTS_PLAY_THRESHOLD": 0.605,
            "used_for_full7_rule_selection": False,
        },
    }
    frozen_checks = {
        name: True
        for name in (
            "train_forward_support",
            "dev_total_support",
            "dev_segment_support",
            "train_calibration",
            "aggregate_calibration",
            "segment_calibration",
            "wilson_width",
            "predicted_mean_inside_wilson",
            "global_slope",
            "global_intercept",
            "no_severe_overconfidence_segment",
            "probability_bin_support",
        )
    }
    for row in lock["directions"].values():
        for tier in ("PLAY", "WATCH"):
            if row.get(tier) is not None:
                row[tier]["checks"] = frozen_checks
    receipt = audit_phase6_semantics(lock)
    assert receipt["status"] == "PASS"
    assert receipt["legacy_v3_1_override_active"] is False
    assert receipt["o25_runtime_active"] is False


def test_phase6_semantic_audit_rejects_o25_activation():
    lock = {
        "O25_HOLD": False,
        "O25_PHASE6_READY": True,
        "OOS_USED_FOR_THRESHOLD_SELECTION": False,
        "OOS_USED_FOR_GATE_SELECTION": False,
        "market_readiness": {},
        "directions": {},
    }
    with pytest.raises(Phase7Error, match="o25_not_hold"):
        audit_phase6_semantics(lock)


def test_final_fit_indices_are_train_plus_development_and_exclude_oos():
    labels = {
        "dates": np.asarray(
            ["2024-01-01", "2024-02-01", "2024-03-01", "2024-04-01"],
            dtype="U10",
        )
    }
    splits = {
        "train_end_date": "2024-02-01",
        "development_end_date": "2024-03-01",
        "oos_folds": [
            {
                "fold": 1,
                "test_start_date": "2024-04-01",
                "test_end_date": "2024-04-01",
            }
        ],
    }
    receipt = final_fit_indices(labels, splits)
    assert receipt["fit_indices"].tolist() == [0, 1, 2]
    assert receipt["oos_indices"].tolist() == [3]
    assert receipt["oos_rows_used_for_fit"] == 0


def test_final_fit_indices_fail_closed_on_overlap():
    labels = {"dates": np.asarray(["2024-01-01", "2024-02-01"], dtype="U10")}
    splits = {
        "train_end_date": "2024-01-01",
        "development_end_date": "2024-02-01",
        "oos_folds": [
            {
                "fold": 1,
                "test_start_date": "2024-02-01",
                "test_end_date": "2024-02-01",
            }
        ],
    }
    with pytest.raises(Phase7Error, match="fit_oos_overlap"):
        final_fit_indices(labels, splits)
