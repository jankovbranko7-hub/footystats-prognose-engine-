import math
import hashlib

import numpy as np
import pytest

from full7_phase7_runtime import (
    Full7Phase7Runtime,
    RuntimeArtifactError,
    apply_multinomial_logit,
    load_runtime_bundle,
    poisson_market_probabilities,
    serialize_runtime_bundle,
    vectorize_locked_features,
)


class ConstantRegressor:
    def __init__(self, value):
        self.value = value

    def predict(self, matrix):
        return np.full(len(matrix), self.value, dtype=float)


def test_multinomial_logit_calibration_is_finite_and_coherent():
    params = {
        "name": "MULTINOMIAL_LOGIT",
        "classes": [0, 1, 2],
        "coef": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
        "intercept": [0.0, 0.0, 0.0],
    }
    calibrated = apply_multinomial_logit([0.55, 0.25, 0.20], params)
    assert all(math.isfinite(value) and 0.0 <= value <= 1.0 for value in calibrated)
    assert sum(calibrated) == pytest.approx(1.0, abs=1e-12)


def test_poisson_market_probabilities_are_coherent():
    probabilities = poisson_market_probabilities(1.6, 1.1)
    assert sum(probabilities["1X2"]) == pytest.approx(1.0, abs=1e-12)
    assert probabilities["btts_no"] == pytest.approx(1.0 - probabilities["btts_yes"])
    assert 0.0 <= probabilities["btts_yes"] <= 1.0


def test_vectorizer_preserves_missing_values_without_imputation():
    vector, coverage = vectorize_locked_features(
        {"a": 1.0, "c": 3.0},
        ["a", "b", "c"],
        expected_count=3,
    )
    assert vector[0] == 1.0
    assert np.isnan(vector[1])
    assert vector[2] == 3.0
    assert coverage == pytest.approx(2 / 3)


def test_vectorizer_rejects_feature_count_mismatch():
    with pytest.raises(RuntimeArtifactError, match="feature_count_mismatch"):
        vectorize_locked_features({"a": 1.0}, ["a"], expected_count=2)


def test_vectorizer_rejects_duplicate_locked_feature_names():
    with pytest.raises(RuntimeArtifactError, match="duplicate_locked_feature"):
        vectorize_locked_features({"a": 1.0}, ["a", "a"], expected_count=2)


def test_vectorizer_treats_nan_and_inf_as_missing_not_replacements():
    vector, coverage = vectorize_locked_features(
        {"a": math.nan, "b": math.inf, "c": 4.0},
        ["a", "b", "c"],
        expected_count=3,
    )
    assert np.isnan(vector[0]) and np.isnan(vector[1])
    assert coverage == pytest.approx(1 / 3)


def test_runtime_integrates_two_locked_goal_poisson_models_and_calibration():
    calibrator = {
        "name": "MULTINOMIAL_LOGIT",
        "classes": [0, 1, 2],
        "coef": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
        "intercept": [0.0, 0.0, 0.0],
    }
    runtime = Full7Phase7Runtime(
        models={
            "1X2_HOME": ConstantRegressor(1.6),
            "1X2_AWAY": ConstantRegressor(0.9),
            "BTTS_HOME": ConstantRegressor(1.5),
            "BTTS_AWAY": ConstantRegressor(1.2),
        },
        feature_names={"1X2": ["a", "b"], "BTTS": ["a", "c"]},
        calibrator_1x2=calibrator,
        expected_feature_counts={"1X2": 2, "BTTS": 2},
        coverage_floors={"1X2": 0.5, "BTTS": 0.5},
        frozen_gate_attestations_verified=True,
        model_artifact_integrity_verified=True,
    )
    result = runtime.predict(
        {"a": 1.0, "b": 2.0, "c": 3.0},
        input_integrity_verified=True,
        feature_schema_verified=True,
    )
    probabilities = result["probabilities"]
    assert sum(probabilities[key] for key in ("home", "draw", "away")) == pytest.approx(1.0)
    assert probabilities["btts_no"] == pytest.approx(1.0 - probabilities["btts_yes"])
    assert result["model_lock_1x2"] == "GOAL_POISSON_LOCKED"
    assert result["model_lock_btts"] == "GOAL_POISSON_LOCKED"
    assert result["calibration_1x2"] == "MULTINOMIAL_LOGIT"
    assert result["calibration_btts"] == "IDENTITY"


def test_runtime_model_nonfinite_prediction_fails_closed():
    calibrator = {
        "name": "MULTINOMIAL_LOGIT",
        "classes": [0, 1, 2],
        "coef": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
        "intercept": [0.0, 0.0, 0.0],
    }
    runtime = Full7Phase7Runtime(
        models={
            "1X2_HOME": ConstantRegressor(math.nan),
            "1X2_AWAY": ConstantRegressor(0.9),
            "BTTS_HOME": ConstantRegressor(1.5),
            "BTTS_AWAY": ConstantRegressor(1.2),
        },
        feature_names={"1X2": ["a"], "BTTS": ["a"]},
        calibrator_1x2=calibrator,
        expected_feature_counts={"1X2": 1, "BTTS": 1},
        coverage_floors={"1X2": 0.5, "BTTS": 0.5},
        frozen_gate_attestations_verified=True,
        model_artifact_integrity_verified=True,
    )
    result = runtime.predict(
        {"a": 1.0}, input_integrity_verified=True, feature_schema_verified=True
    )
    assert "MODEL_RUNTIME_FAIL" in result["fail_closed_reasons"]
    assert result["directions"]["HOME"]["decision"] == "AUSLASSEN"


def _bundle_payload():
    return {
        "schema": "FULL7_PHASE7_RUNTIME_BUNDLE_1.0",
        "release_candidate_version": "FULL7_FINAL_RC_1.0.0",
        "frozen_hashes": {
            "phase5_calibration_decision_lock_sha256": "cb48662360cd66b4e7daaf84ff47294c04d8bb7983e3da9cceecc30207984a99",
            "phase5_manifest_sha256": "189057b6bc81c0e86b1eb1eb7d131e9592c320dd01f7a4ccaaf9b46ae885ab1a",
            "phase6_decision_lock_sha256": "627f581e0e3a11c099166abdc792566a7a8fb5e8d252e748fc8e43457813829e",
            "phase6_manifest_sha256": "dff0689bfa2c81bb7c7c9f0b1ce9beeb4dd3bcbd6de4779ee205d86dbe15cca4",
        },
        "models": {
            "1X2_HOME": ConstantRegressor(1.6),
            "1X2_AWAY": ConstantRegressor(0.9),
            "BTTS_HOME": ConstantRegressor(1.5),
            "BTTS_AWAY": ConstantRegressor(1.2),
        },
        "feature_names": {"1X2": [f"x{i}" for i in range(298)], "BTTS": [f"x{i}" for i in range(209)]},
        "calibrator_1x2": {
            "name": "MULTINOMIAL_LOGIT",
            "classes": [0, 1, 2],
            "coef": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
            "intercept": [0.0, 0.0, 0.0],
        },
        "calibrator_btts": {"name": "IDENTITY"},
        "o25_status": "HOLD",
        "o25_runtime_active": False,
        "legacy_v3_1_override_active": False,
        "fit_provenance": {"oos_rows_used_for_fit": 0},
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


def test_verified_runtime_bundle_round_trip(tmp_path):
    raw = serialize_runtime_bundle(_bundle_payload())
    path = tmp_path / "bundle.pkl.gz"
    path.write_bytes(raw)
    expected = hashlib.sha256(raw).hexdigest()
    runtime, metadata = load_runtime_bundle(path, expected_sha256=expected)
    result = runtime.predict(
        {f"x{i}": 1.0 for i in range(298)},
        input_integrity_verified=True,
        feature_schema_verified=True,
    )
    assert metadata["release_candidate_version"] == "FULL7_FINAL_RC_1.0.0"
    assert result["o25_status"] == "HOLD"


def test_runtime_bundle_rejects_hash_mismatch(tmp_path):
    path = tmp_path / "bundle.pkl.gz"
    path.write_bytes(serialize_runtime_bundle(_bundle_payload()))
    with pytest.raises(RuntimeArtifactError, match="bundle_hash_mismatch"):
        load_runtime_bundle(path, expected_sha256="0" * 64)


def test_runtime_bundle_rejects_o25_activation(tmp_path):
    payload = _bundle_payload()
    payload["o25_runtime_active"] = True
    raw = serialize_runtime_bundle(payload)
    path = tmp_path / "bundle.pkl.gz"
    path.write_bytes(raw)
    with pytest.raises(RuntimeArtifactError, match="o25_runtime_active"):
        load_runtime_bundle(path, expected_sha256=hashlib.sha256(raw).hexdigest())


def test_runtime_fails_closed_without_dynamic_and_frozen_integrity_proofs():
    payload = _bundle_payload()
    runtime = Full7Phase7Runtime(
        models=payload["models"],
        feature_names=payload["feature_names"],
        calibrator_1x2=payload["calibrator_1x2"],
    )
    result = runtime.predict({f"x{i}": 1.0 for i in range(298)})
    assert result["directions"]["HOME"]["decision"] == "AUSLASSEN"
    assert result["integrity_gates"]["input_integrity"] is False
    assert result["integrity_gates"]["model_integrity"] is False
    assert result["integrity_gates"]["train_forward_support"] is False
