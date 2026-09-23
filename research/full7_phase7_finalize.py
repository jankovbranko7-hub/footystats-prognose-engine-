#!/usr/bin/env python3
"""FULL-7 Phase 7 frozen-artifact audit and release-candidate builder."""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any, Mapping

import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor

from full7_phase7_runtime import (
    BUNDLE_SCHEMA,
    Full7Phase7Runtime,
    load_runtime_bundle,
    serialize_runtime_bundle,
)


RELEASE_CANDIDATE_VERSION = "FULL7_FINAL_RC_1.0.0"
EXPECTED_PHASE4_MANIFEST_SHA256 = (
    "fd4d33b289602e09b7d6ad82565a83c310d444f20f517af687d255792e3f50b5"
)
EXPECTED_PHASE5_LOCK_SHA256 = (
    "cb48662360cd66b4e7daaf84ff47294c04d8bb7983e3da9cceecc30207984a99"
)
EXPECTED_PHASE5_MANIFEST_SHA256 = (
    "189057b6bc81c0e86b1eb1eb7d131e9592c320dd01f7a4ccaaf9b46ae885ab1a"
)
EXPECTED_PHASE6_LOCK_SHA256 = (
    "627f581e0e3a11c099166abdc792566a7a8fb5e8d252e748fc8e43457813829e"
)
EXPECTED_PHASE6_MANIFEST_SHA256 = (
    "dff0689bfa2c81bb7c7c9f0b1ce9beeb4dd3bcbd6de4779ee205d86dbe15cca4"
)
EXPECTED_PREOOS_SHA256 = {
    "PHASE5_PREOOS_1X2.npz": "a0802348c84b4728c355013b28d98f43d23e294d5ddb06c40db7685f747a5137",
    "PHASE5_PREOOS_BTTS.npz": "b797ff8d77fbc84bb431084c243639b18b4095d0bf77f42c21b100f2a21587b3",
}
POISSON_PARAMS = {
    "max_iter": 180,
    "learning_rate": 0.04,
    "max_leaf_nodes": 15,
    "min_samples_leaf": 60,
    "l2_regularization": 5.0,
    "loss": "poisson",
    "early_stopping": False,
    "max_bins": 63,
}
FROZEN_RULE_CHECKS = {
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
}


class Phase7Error(RuntimeError):
    pass


def final_fit_indices(
    labels: Mapping[str, Any], splits: Mapping[str, Any]
) -> dict[str, Any]:
    """Resolve the frozen chronological fit partition without opening OOS outputs."""
    dates = np.asarray(labels["dates"]).astype(str)
    train_end = str(splits["train_end_date"])
    development_end = str(splits["development_end_date"])
    train = np.flatnonzero(dates <= train_end).astype(np.int64)
    development = np.flatnonzero(
        (dates > train_end) & (dates <= development_end)
    ).astype(np.int64)
    oos_parts = []
    for fold in splits.get("oos_folds", []):
        start = str(fold["test_start_date"])
        end = str(fold["test_end_date"])
        oos_parts.append(np.flatnonzero((dates >= start) & (dates <= end)))
    oos = (
        np.unique(np.concatenate(oos_parts)).astype(np.int64)
        if oos_parts
        else np.empty(0, dtype=np.int64)
    )
    fit = np.unique(np.concatenate([train, development])).astype(np.int64)
    overlap = np.intersect1d(fit, oos)
    if overlap.size:
        raise Phase7Error(f"fit_oos_overlap:{overlap.size}")
    if not train.size or not development.size or not oos.size:
        raise Phase7Error("chronological_partition_incomplete")
    return {
        "train_indices": train,
        "development_indices": development,
        "fit_indices": fit,
        "oos_indices": oos,
        "train_rows": int(train.size),
        "development_rows": int(development.size),
        "fit_rows": int(fit.size),
        "oos_rows": int(oos.size),
        "oos_rows_used_for_fit": 0,
    }


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def audit_manifest(path: Path, *, expected_manifest_sha256: str) -> dict[str, Any]:
    manifest_path = Path(path)
    if not manifest_path.is_file():
        raise Phase7Error(f"manifest_missing:{manifest_path}")
    actual_manifest_sha = sha256(manifest_path)
    if actual_manifest_sha != expected_manifest_sha256:
        raise Phase7Error(f"manifest_hash_mismatch:{actual_manifest_sha}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict) or not artifacts:
        raise Phase7Error("manifest_artifacts_missing")
    verified = {}
    for name, metadata in sorted(artifacts.items()):
        artifact = manifest_path.parent / name
        if not artifact.is_file():
            raise Phase7Error(f"artifact_missing:{name}")
        actual_sha = sha256(artifact)
        if actual_sha != metadata.get("sha256"):
            raise Phase7Error(f"artifact_hash_mismatch:{name}:{actual_sha}")
        expected_bytes = int(metadata.get("bytes", -1))
        if artifact.stat().st_size != expected_bytes:
            raise Phase7Error(f"artifact_size_mismatch:{name}")
        verified[name] = {"bytes": expected_bytes, "sha256": actual_sha}
    return {
        "manifest": str(manifest_path),
        "manifest_sha256": actual_manifest_sha,
        "artifact_count": len(verified),
        "all_artifacts_verified": True,
        "artifacts": verified,
    }


def _close(actual: Any, expected: float, tolerance: float = 5e-5) -> bool:
    try:
        return math.isclose(float(actual), expected, rel_tol=0.0, abs_tol=tolerance)
    except (TypeError, ValueError):
        return False


def _direction_rule(
    directions: Mapping[str, Any],
    direction: str,
    *,
    play: tuple[float, float] | None,
    watch: tuple[float, float] | None,
    quality: float | None = None,
) -> None:
    row = directions.get(direction)
    if not isinstance(row, Mapping):
        raise Phase7Error(f"direction_missing:{direction}")
    if (row.get("PLAY_AVAILABLE") is True) != (play is not None):
        raise Phase7Error(f"play_availability_mismatch:{direction}")
    if (row.get("WATCH_AVAILABLE") is True) != (watch is not None):
        raise Phase7Error(f"watch_availability_mismatch:{direction}")
    for tier, expected in (("PLAY", play), ("WATCH", watch)):
        rule = row.get(tier)
        if expected is None:
            if rule is not None:
                raise Phase7Error(f"disabled_rule_present:{direction}:{tier}")
            continue
        if not isinstance(rule, Mapping):
            raise Phase7Error(f"rule_missing:{direction}:{tier}")
        if not _close(rule.get("threshold"), expected[0], tolerance=1e-12):
            raise Phase7Error(f"threshold_mismatch:{direction}:{tier}")
        if not _close(rule.get("supported_probability_ceiling"), expected[1], tolerance=1e-12):
            raise Phase7Error(f"ceiling_mismatch:{direction}:{tier}")
        if tier == "PLAY" and not _close(rule.get("margin_threshold", 0.0), 0.0, tolerance=1e-12):
            raise Phase7Error(f"margin_mismatch:{direction}:{tier}")
        checks = rule.get("checks")
        if not isinstance(checks, Mapping):
            raise Phase7Error(f"frozen_gate_attestation_missing:{direction}:{tier}")
        if not FROZEN_RULE_CHECKS.issubset(checks) or not all(
            checks.get(name) is True for name in FROZEN_RULE_CHECKS
        ):
            raise Phase7Error(f"frozen_gate_attestation_fail:{direction}:{tier}")
    if quality is not None and not _close(row.get("quality_floor_train_q01"), quality):
        raise Phase7Error(f"quality_floor_mismatch:{direction}")


def audit_phase6_semantics(lock: Mapping[str, Any]) -> dict[str, Any]:
    if lock.get("O25_HOLD") is not True or lock.get("O25_PHASE6_READY") is not False:
        raise Phase7Error("o25_not_hold")
    if lock.get("OOS_USED_FOR_THRESHOLD_SELECTION") is not False:
        raise Phase7Error("oos_used_for_threshold_selection")
    if lock.get("OOS_USED_FOR_GATE_SELECTION") is not False:
        raise Phase7Error("oos_used_for_gate_selection")
    readiness = lock.get("market_readiness") or {}
    expected_models = {
        "1X2": ("READY", "GOAL_POISSON_LOCKED", 298, "MULTINOMIAL_LOGIT"),
        "BTTS": ("READY", "GOAL_POISSON_LOCKED", 209, "IDENTITY"),
        "O25": ("HOLD", "ENSEMBLE_HGB_POISSON_LOCKED", 240, None),
    }
    for target, (status, model, features, calibrator) in expected_models.items():
        row = readiness.get(target) or {}
        if row.get("status") != status or row.get("model") != model or int(row.get("features", -1)) != features:
            raise Phase7Error(f"model_lock_mismatch:{target}")
        if calibrator is not None and row.get("calibrator") != calibrator:
            raise Phase7Error(f"calibrator_lock_mismatch:{target}")
    directions = lock.get("directions") or {}
    _direction_rule(directions, "HOME", play=(0.50, 0.80), watch=(0.40, 0.85), quality=0.97775)
    _direction_rule(directions, "DRAW", play=None, watch=None)
    _direction_rule(directions, "AWAY", play=(0.50, 0.65), watch=(0.40, 0.70), quality=0.97775)
    _direction_rule(directions, "BTTS_YES", play=(0.55, 0.70), watch=(0.50, 0.70), quality=0.98086)
    _direction_rule(directions, "BTTS_NO", play=None, watch=(0.50, 0.60))
    legacy = lock.get("historical_reference_only") or {}
    if legacy.get("used_for_full7_rule_selection") is not False:
        raise Phase7Error("legacy_v3_reference_active")
    return {
        "status": "PASS",
        "oos_used_for_threshold_selection": False,
        "oos_used_for_gate_selection": False,
        "legacy_v3_1_override_active": False,
        "o25_runtime_active": False,
        "directions": ["HOME", "DRAW", "AWAY", "BTTS_YES", "BTTS_NO"],
    }


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Phase7Error(f"json_read_failed:{path}") from exc
    if not isinstance(value, dict):
        raise Phase7Error(f"json_object_required:{path}")
    return value


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _verify_hash_receipt(path: Path, expected: str) -> None:
    if not path.is_file() or path.read_text(encoding="ascii").strip() != expected:
        raise Phase7Error(f"hash_receipt_mismatch:{path.name}")


def audit_frozen_tree(root: Path) -> dict[str, Any]:
    """Verify every published Phase-4/5/6 artifact and all four user locks."""
    root = Path(root)
    phase4, phase5, phase6 = root / "phase4", root / "phase5", root / "phase6"
    receipts = {
        "phase4": audit_manifest(
            phase4 / "PHASE4_MANIFEST.json",
            expected_manifest_sha256=EXPECTED_PHASE4_MANIFEST_SHA256,
        ),
        "phase5": audit_manifest(
            phase5 / "PHASE5_MANIFEST.json",
            expected_manifest_sha256=EXPECTED_PHASE5_MANIFEST_SHA256,
        ),
        "phase6": audit_manifest(
            phase6 / "PHASE6_MANIFEST.json",
            expected_manifest_sha256=EXPECTED_PHASE6_MANIFEST_SHA256,
        ),
    }
    lock5_path = phase5 / "PHASE5_CALIBRATION_DECISION_LOCK.json"
    lock6_path = phase6 / "PHASE6_DECISION_LOCK.json"
    if sha256(lock5_path) != EXPECTED_PHASE5_LOCK_SHA256:
        raise Phase7Error("phase5_decision_lock_hash_mismatch")
    if sha256(lock6_path) != EXPECTED_PHASE6_LOCK_SHA256:
        raise Phase7Error("phase6_decision_lock_hash_mismatch")
    _verify_hash_receipt(
        phase5 / "PHASE5_CALIBRATION_DECISION_LOCK.sha256",
        EXPECTED_PHASE5_LOCK_SHA256,
    )
    _verify_hash_receipt(
        phase6 / "PHASE6_DECISION_LOCK.sha256", EXPECTED_PHASE6_LOCK_SHA256
    )
    for name, expected in EXPECTED_PREOOS_SHA256.items():
        if sha256(phase5 / name) != expected:
            raise Phase7Error(f"phase5_preoos_hash_mismatch:{name}")

    lock5 = _read_json(lock5_path)
    if lock5.get("oos_used_for_fit") is not False or lock5.get("oos_used_for_selection") is not False:
        raise Phase7Error("phase5_oos_contamination_flag")
    expectations = {
        "1X2": ("GOAL_POISSON_LOCKED", 298, "MULTINOMIAL_LOGIT"),
        "BTTS": ("GOAL_POISSON_LOCKED", 209, "IDENTITY"),
    }
    for target, (variant, count, calibrator) in expectations.items():
        row = (lock5.get("targets") or {}).get(target) or {}
        model = row.get("model_lock") or {}
        if model.get("variant") != variant or int(model.get("feature_count", -1)) != count:
            raise Phase7Error(f"phase5_model_lock_mismatch:{target}")
        if row.get("selected_calibrator") != calibrator:
            raise Phase7Error(f"phase5_calibrator_mismatch:{target}")
        if row.get("oos_used_for_fit") is not False or row.get("oos_used_for_selection") is not False:
            raise Phase7Error(f"phase5_target_oos_contamination:{target}")
    lock6 = _read_json(lock6_path)
    semantic = audit_phase6_semantics(lock6)
    return {
        "status": "PASS",
        "all_frozen_artifacts_verified": True,
        "manifests": receipts,
        "locks": {
            "phase5_calibration_decision_lock_sha256": EXPECTED_PHASE5_LOCK_SHA256,
            "phase5_manifest_sha256": EXPECTED_PHASE5_MANIFEST_SHA256,
            "phase6_decision_lock_sha256": EXPECTED_PHASE6_LOCK_SHA256,
            "phase6_manifest_sha256": EXPECTED_PHASE6_MANIFEST_SHA256,
        },
        "phase6_semantic_audit": semantic,
        "phase5_lock": lock5,
        "phase6_lock": lock6,
    }


def _fit_goal_models(
    matrix: np.ndarray,
    labels: Mapping[str, np.ndarray],
    fit_indices: np.ndarray,
    columns: np.ndarray,
) -> tuple[HistGradientBoostingRegressor, HistGradientBoostingRegressor]:
    x_fit = np.asarray(matrix[np.ix_(fit_indices, columns)], dtype=np.float32)
    models = []
    for label, seed in (("yh", 42), ("ya", 43)):
        model = HistGradientBoostingRegressor(random_state=seed, **POISSON_PARAMS)
        model.fit(x_fit, np.asarray(labels[label])[fit_indices])
        models.append(model)
    return models[0], models[1]


def _fit_index_sha256(indices: np.ndarray) -> str:
    return hashlib.sha256(np.asarray(indices, dtype=np.int64).tobytes()).hexdigest()


def _shadow_comparison(
    *,
    runtime: Full7Phase7Runtime,
    matrix: np.ndarray,
    v3_matrix: np.ndarray,
    leagues: np.ndarray,
    development_indices: np.ndarray,
    feature_names: Mapping[str, list[str]],
    columns: Mapping[str, np.ndarray],
    limit: int = 100,
) -> dict[str, Any]:
    """Compare decisions only; labels and performance never enter this audit."""
    from full7_v3_live import (
        NUMERIC_FEATURES,
        PLAY_THRESHOLDS,
        _MODELS,
        _predict_family,
        _state,
    )

    rows = []
    for index in development_indices:
        v3_values = np.asarray(v3_matrix[int(index)], dtype=float)
        league = str(leagues[int(index)])
        if len(v3_values) != len(NUMERIC_FEATURES) or not np.isfinite(v3_values).all() or not league:
            continue
        features: dict[str, float] = {}
        for target, names in feature_names.items():
            values = np.asarray(matrix[int(index), columns[target]], dtype=float)
            features.update(
                {name: float(value) for name, value in zip(names, values) if math.isfinite(float(value))}
            )
        final = runtime.predict(
            features,
            input_integrity_verified=True,
            feature_schema_verified=True,
        )
        record = {name: float(value) for name, value in zip(NUMERIC_FEATURES, v3_values)}
        record["liga"] = league
        league_known = league in set(_MODELS["1X2"]["league_categories"])
        v3_decisions = {}
        for family in ("1X2", "BTTS", "TOTALS"):
            probabilities = _predict_family(family, record)
            direction, probability = max(probabilities.items(), key=lambda item: item[1])
            state, _reason = _state(probability, family, league_known=league_known)
            v3_decisions[family] = {
                "direction": direction,
                "decision": state,
                "probability": probability,
                "historical_play_threshold": PLAY_THRESHOLDS[family],
            }
        final_1x2 = max(
            (final["directions"][name] for name in ("HOME", "DRAW", "AWAY")),
            key=lambda item: (-1 if item["probability"] is None else item["probability"]),
        )
        final_btts = max(
            (final["directions"][name] for name in ("BTTS_YES", "BTTS_NO")),
            key=lambda item: (-1 if item["probability"] is None else item["probability"]),
        )
        new_decisions = {
            "1X2": {"direction": final_1x2["direction"], "decision": final_1x2["decision"]},
            "BTTS": {"direction": final_btts["direction"], "decision": final_btts["decision"]},
            "TOTALS": {"direction": "O25/U25", "decision": "HOLD"},
        }
        rows.append(
            {
                "matrix_row": int(index),
                "v3_1": v3_decisions,
                "full7_rc": new_decisions,
                "different": {
                    family: v3_decisions[family]["decision"] != new_decisions[family]["decision"]
                    for family in ("1X2", "BTTS", "TOTALS")
                },
            }
        )
        if len(rows) >= limit:
            break
    if not rows:
        return {
            "status": "NOT_TECHNICALLY_POSSIBLE_NO_COMPLETE_IDENTICAL_INPUTS",
            "rules_changed_from_shadow": False,
            "labels_used": False,
        }
    return {
        "status": "COMPLETE_REFERENCE_ONLY",
        "input_partition": "DEVELOPMENT",
        "identical_input_rows": len(rows),
        "labels_used": False,
        "performance_selection_performed": False,
        "rules_changed_from_shadow": False,
        "differences": {
            family: sum(int(row["different"][family]) for row in rows)
            for family in ("1X2", "BTTS", "TOTALS")
        },
        "rows": rows,
    }


def _report_text(report: Mapping[str, Any]) -> str:
    ordered = (
        "FULL7_FINAL_ENGINE_STATUS",
        "FULL7_RELEASE_CANDIDATE_VERSION",
        "MODEL_LOCK_1X2",
        "MODEL_LOCK_BTTS",
        "CALIBRATION_1X2",
        "CALIBRATION_BTTS",
        "FINAL_DECISION_SOURCE",
        "HOME_RULE",
        "DRAW_RULE",
        "AWAY_RULE",
        "BTTS_YES_RULE",
        "BTTS_NO_RULE",
        "O25_STATUS",
        "MANUAL_PERFORMANCE_GATES",
        "INTEGRITY_GATES",
        "FINAL_DECISION_DEPENDENCY_AUDIT",
        "REGRESSION_TESTS",
        "FROZEN_ARTIFACT_HASH_AUDIT",
        "LEGACY_V3_1_OVERRIDE_AUDIT",
        "O25_HOLD_AUDIT",
        "PRODUCTION_CHANGED",
        "MAIN_CHANGED",
        "RELEASE_CANDIDATE_COMMIT",
        "READY_FOR_EXPLICIT_PRODUCTION_APPROVAL",
    )
    return "\n".join(
        f"{key} = {json.dumps(report.get(key), ensure_ascii=False, sort_keys=True)}"
        for key in ordered
    ) + "\n"


def build_release_candidate(root: Path, output: Path) -> dict[str, Any]:
    """Build the final runtime artifact without reading OOS predictions or labels."""
    root, output = Path(root), Path(output)
    if output.exists():
        raise Phase7Error("phase7_output_exists_fail_closed")
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = output.parent / f".{output.name}.stage"
    if stage.exists():
        raise Phase7Error("phase7_stage_exists_requires_manual_audit")

    audit = audit_frozen_tree(root)
    phase4 = root / "phase4"
    metadata = _read_json(phase4 / "PHASE4_MATRIX_METADATA.json")
    ablation = _read_json(phase4 / "PHASE4_GROUP_ABLATIONS_DEVELOPMENT.json")
    splits = _read_json(phase4 / "PHASE4_SPLITS.json")
    with np.load(phase4 / "PHASE4_LABELS.npz") as npz:
        labels = {
            name: np.asarray(npz[name])
            for name in ("dates", "leagues", "yh", "ya")
        }
    partition = final_fit_indices(labels, splits)
    matrix = np.load(phase4 / "PHASE4_MATRIX.npy", mmap_mode="r")
    feature_index = {name: index for index, name in enumerate(metadata["feature_names"])}
    feature_names = {
        target: list(ablation["targets"][target]["locked_features"])
        for target in ("1X2", "BTTS")
    }
    if len(feature_names["1X2"]) != 298 or len(feature_names["BTTS"]) != 209:
        raise Phase7Error("locked_feature_count_mismatch")
    try:
        columns = {
            target: np.asarray([feature_index[name] for name in names], dtype=np.int64)
            for target, names in feature_names.items()
        }
    except KeyError as exc:
        raise Phase7Error(f"locked_feature_missing_from_matrix:{exc.args[0]}") from exc

    fit = partition["fit_indices"]
    one_home, one_away = _fit_goal_models(matrix, labels, fit, columns["1X2"])
    btts_home, btts_away = _fit_goal_models(matrix, labels, fit, columns["BTTS"])
    models = {
        "1X2_HOME": one_home,
        "1X2_AWAY": one_away,
        "BTTS_HOME": btts_home,
        "BTTS_AWAY": btts_away,
    }
    lock5 = audit["phase5_lock"]
    calibrator_1x2 = lock5["targets"]["1X2"]["final_parameters"]
    calibrator_btts = lock5["targets"]["BTTS"]["final_parameters"]
    if calibrator_1x2.get("name") != "MULTINOMIAL_LOGIT":
        raise Phase7Error("1x2_final_calibrator_changed")
    if calibrator_btts != {"name": "IDENTITY"}:
        raise Phase7Error("btts_final_calibrator_changed")

    payload = {
        "schema": BUNDLE_SCHEMA,
        "release_candidate_version": RELEASE_CANDIDATE_VERSION,
        "frozen_hashes": audit["locks"],
        "models": models,
        "feature_names": feature_names,
        "calibrator_1x2": calibrator_1x2,
        "calibrator_btts": calibrator_btts,
        "o25_status": "HOLD",
        "o25_runtime_active": False,
        "legacy_v3_1_override_active": False,
        "fit_provenance": {
            "dataset": "FROZEN_PHASE4_TRAIN_PLUS_DEVELOPMENT_ONLY",
            "train_rows": partition["train_rows"],
            "development_rows": partition["development_rows"],
            "fit_rows": partition["fit_rows"],
            "oos_rows_available_but_unopened_for_fit": partition["oos_rows"],
            "oos_rows_used_for_fit": 0,
            "fit_row_indices_sha256": _fit_index_sha256(fit),
            "model_parameters": POISSON_PARAMS,
            "random_states": {"HOME_GOALS": 42, "AWAY_GOALS": 43},
        },
        "dependency_audit": {
            "final_decision_module": "full7_phase7_decision",
            "legacy_v3_1_imported_by_runtime": False,
            "legacy_thresholds_active": False,
            "totals_model_present": False,
            "o25_calibrator_present": False,
            "input_integrity_mode": "HMAC_TRUSTED_STRICT_PREMATCH_CP2",
            "manifest_requires_external_sha256_pin": True,
        },
    }
    bundle = serialize_runtime_bundle(payload)
    bundle_sha = hashlib.sha256(bundle).hexdigest()

    # Load the exact hash-pinned serialized artifact before any PASS report.
    stage.mkdir(parents=False, exist_ok=False)
    bundle_path = stage / "FULL7_FINAL_RC_BUNDLE.pkl.gz"
    bundle_path.write_bytes(bundle)
    runtime, _bundle_metadata = load_runtime_bundle(
        bundle_path, expected_sha256=bundle_sha
    )
    canary_index = int(partition["development_indices"][-1])
    canary_features = {}
    for target, names in feature_names.items():
        row = np.asarray(matrix[canary_index, columns[target]], dtype=float)
        canary_features.update(
            {name: float(value) for name, value in zip(names, row) if math.isfinite(float(value))}
        )
    canary = runtime.predict(
        canary_features,
        input_integrity_verified=True,
        feature_schema_verified=True,
    )
    if canary.get("runtime_error") or not all(canary["coherence"].values()):
        raise Phase7Error("real_model_canary_failed")
    shadow = _shadow_comparison(
        runtime=runtime,
        matrix=matrix,
        v3_matrix=np.load(phase4 / "PHASE4_V3_MATRIX.npy", mmap_mode="r"),
        leagues=labels["leagues"],
        development_indices=partition["development_indices"],
        feature_names=feature_names,
        columns=columns,
    )

    report = {
        "FULL7_FINAL_ENGINE_STATUS": "PASS_RELEASE_CANDIDATE",
        "FULL7_RELEASE_CANDIDATE_VERSION": RELEASE_CANDIDATE_VERSION,
        "MODEL_LOCK_1X2": "GOAL_POISSON_LOCKED / 298",
        "MODEL_LOCK_BTTS": "GOAL_POISSON_LOCKED / 209",
        "CALIBRATION_1X2": "MULTINOMIAL_LOGIT",
        "CALIBRATION_BTTS": "IDENTITY",
        "FINAL_DECISION_SOURCE": f"PHASE6_DECISION_LOCK_SHA256:{EXPECTED_PHASE6_LOCK_SHA256}",
        "HOME_RULE": "TOP1; SPIELEN 0.50..0.80; BEOBACHTEN 0.40..0.85; coverage>=0.97775; all gates",
        "DRAW_RULE": "AUSLASSEN_ONLY",
        "AWAY_RULE": "TOP1; SPIELEN 0.50..0.65; BEOBACHTEN 0.40..0.70; coverage>=0.97775; all gates",
        "BTTS_YES_RULE": "SPIELEN 0.55..0.70; BEOBACHTEN 0.50..0.70; coverage>=0.98086; all gates",
        "BTTS_NO_RULE": "SPIELEN disabled; BEOBACHTEN 0.50..0.60",
        "O25_STATUS": "HOLD / NICHT_FREIGEGEBEN",
        "MANUAL_PERFORMANCE_GATES": "DISABLED; frozen Phase-6 gates are authoritative",
        "INTEGRITY_GATES": sorted(FROZEN_RULE_CHECKS | {"hmac_trusted_strict_prematch_input", "model_artifact_sha256", "manifest_external_sha256_pin", "coherence", "feature_coverage"}),
        "FINAL_DECISION_DEPENDENCY_AUDIT": payload["dependency_audit"],
        "REGRESSION_TESTS": {"REAL_MODEL_SERIALIZATION_CANARY": "PASS", "LOCAL_SUITE": "PENDING_SOURCE_CHECKOUT"},
        "FROZEN_ARTIFACT_HASH_AUDIT": "PASS",
        "LEGACY_V3_1_OVERRIDE_AUDIT": "PASS_INACTIVE",
        "O25_HOLD_AUDIT": "PASS_NO_RUNTIME_NO_CALIBRATOR_NO_RULES",
        "PRODUCTION_CHANGED": False,
        "MAIN_CHANGED": False,
        "RELEASE_CANDIDATE_COMMIT": os.environ.get("RENDER_GIT_COMMIT", "NOT_EXPOSED_IN_BUILD"),
        "READY_FOR_EXPLICIT_PRODUCTION_APPROVAL": True,
        "bundle_sha256": bundle_sha,
        "bundle_bytes": len(bundle),
        "fit_provenance": payload["fit_provenance"],
        "real_model_canary": {
            "matrix_row": canary_index,
            "coherence": canary["coherence"],
            "directions": {key: value["decision"] for key, value in canary["directions"].items()},
        },
        "shadow_comparison": {
            key: value for key, value in shadow.items() if key != "rows"
        },
    }

    _write_json(stage / "FROZEN_ARTIFACT_HASH_AUDIT.json", {
        key: value for key, value in audit.items() if key not in {"phase5_lock", "phase6_lock"}
    })
    _write_json(stage / "FINAL_DECISION_DEPENDENCY_AUDIT.json", payload["dependency_audit"])
    _write_json(stage / "SHADOW_COMPARISON_V3_1_VS_FULL7_RC.json", shadow)
    _write_json(stage / "FULL7_FINAL_AUDIT.json", report)
    (stage / "FULL7_FINAL_AUDIT.txt").write_text(_report_text(report), encoding="utf-8")
    artifacts = {
        path.name: {"bytes": path.stat().st_size, "sha256": sha256(path)}
        for path in sorted(stage.iterdir())
        if path.is_file()
    }
    _write_json(stage / "FULL7_FINAL_RC_MANIFEST.json", {
        "schema": "FULL7_FINAL_RC_MANIFEST_1.0",
        "release_candidate_version": RELEASE_CANDIDATE_VERSION,
        "artifacts": artifacts,
    })
    output.parent.mkdir(parents=True, exist_ok=True)
    stage.rename(output)

    # Recheck the four immutable roots after publication; any mutation is fatal.
    after = {
        "phase4_manifest_sha256": sha256(root / "phase4/PHASE4_MANIFEST.json"),
        "phase5_manifest_sha256": sha256(root / "phase5/PHASE5_MANIFEST.json"),
        "phase5_lock_sha256": sha256(root / "phase5/PHASE5_CALIBRATION_DECISION_LOCK.json"),
        "phase6_manifest_sha256": sha256(root / "phase6/PHASE6_MANIFEST.json"),
        "phase6_lock_sha256": sha256(root / "phase6/PHASE6_DECISION_LOCK.json"),
    }
    expected_after = {
        "phase4_manifest_sha256": EXPECTED_PHASE4_MANIFEST_SHA256,
        "phase5_manifest_sha256": EXPECTED_PHASE5_MANIFEST_SHA256,
        "phase5_lock_sha256": EXPECTED_PHASE5_LOCK_SHA256,
        "phase6_manifest_sha256": EXPECTED_PHASE6_MANIFEST_SHA256,
        "phase6_lock_sha256": EXPECTED_PHASE6_LOCK_SHA256,
    }
    if after != expected_after:
        raise Phase7Error("frozen_root_changed_during_phase7")
    return report


def emit_bundle_parts(output: Path, *, chunk_chars: int = 32_000) -> None:
    import base64

    raw = (Path(output) / "FULL7_FINAL_RC_BUNDLE.pkl.gz").read_bytes()
    encoded = base64.b64encode(raw).decode("ascii")
    count = math.ceil(len(encoded) / chunk_chars)
    for index in range(count):
        part = encoded[index * chunk_chars : (index + 1) * chunk_chars]
        print(f"PHASE7_BUNDLE_PART={index + 1:04d}/{count:04d}:{part}", flush=True)
