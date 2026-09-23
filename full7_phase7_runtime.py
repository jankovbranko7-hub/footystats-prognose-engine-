"""Numerical primitives and locked-feature validation for FULL-7 Phase 7."""
from __future__ import annotations

import gzip
import hashlib
import math
import pickle
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from full7_phase7_decision import (
    FINAL_PHASE5_MANIFEST_SHA256,
    PHASE5_CALIBRATION_DECISION_LOCK_SHA256,
    PHASE6_DECISION_LOCK_SHA256,
    PHASE6_MANIFEST_SHA256,
    REQUIRED_INTEGRITY_GATES,
    evaluate_phase7_decision,
)


class RuntimeArtifactError(RuntimeError):
    pass


BUNDLE_SCHEMA = "FULL7_PHASE7_RUNTIME_BUNDLE_1.0"


def serialize_runtime_bundle(payload: Mapping[str, Any]) -> bytes:
    """Serialize a trusted RC payload deterministically for hashing and transport."""
    return gzip.compress(pickle.dumps(dict(payload), protocol=5), compresslevel=9, mtime=0)


def load_runtime_bundle(
    path: Path | str, *, expected_sha256: str
) -> tuple["Full7Phase7Runtime", dict[str, Any]]:
    """Load only the exact hash-pinned FULL-7 RC artifact, then validate its locks."""
    bundle_path = Path(path)
    raw = bundle_path.read_bytes()
    actual_sha = hashlib.sha256(raw).hexdigest()
    if actual_sha != expected_sha256:
        raise RuntimeArtifactError(f"bundle_hash_mismatch:{actual_sha}")
    try:
        payload = pickle.loads(gzip.decompress(raw))
    except Exception as exc:
        raise RuntimeArtifactError("bundle_decode_failed") from exc
    if not isinstance(payload, Mapping) or payload.get("schema") != BUNDLE_SCHEMA:
        raise RuntimeArtifactError("bundle_schema_mismatch")
    if payload.get("release_candidate_version") != "FULL7_FINAL_RC_1.0.0":
        raise RuntimeArtifactError("bundle_release_version_mismatch")
    frozen = payload.get("frozen_hashes")
    expected_frozen = {
        "phase5_calibration_decision_lock_sha256": PHASE5_CALIBRATION_DECISION_LOCK_SHA256,
        "phase5_manifest_sha256": FINAL_PHASE5_MANIFEST_SHA256,
        "phase6_decision_lock_sha256": PHASE6_DECISION_LOCK_SHA256,
        "phase6_manifest_sha256": PHASE6_MANIFEST_SHA256,
    }
    if not isinstance(frozen, Mapping) or any(
        frozen.get(name) != value for name, value in expected_frozen.items()
    ):
        raise RuntimeArtifactError("bundle_frozen_hash_mismatch")
    if payload.get("o25_status") != "HOLD" or payload.get("o25_runtime_active") is not False:
        raise RuntimeArtifactError("o25_runtime_active")
    if payload.get("legacy_v3_1_override_active") is not False:
        raise RuntimeArtifactError("legacy_v3_1_override_active")
    dependency = payload.get("dependency_audit") or {}
    if (
        dependency.get("final_decision_module") != "full7_phase7_decision"
        or dependency.get("legacy_v3_1_imported_by_runtime") is not False
        or dependency.get("legacy_thresholds_active") is not False
        or dependency.get("totals_model_present") is not False
        or dependency.get("o25_calibrator_present") is not False
        or dependency.get("input_integrity_mode")
        != "HMAC_TRUSTED_STRICT_PREMATCH_CP2"
        or dependency.get("manifest_requires_external_sha256_pin") is not True
    ):
        raise RuntimeArtifactError("bundle_dependency_audit_failed")
    if (payload.get("fit_provenance") or {}).get("oos_rows_used_for_fit") != 0:
        raise RuntimeArtifactError("oos_fit_contamination")
    calibrator_btts = payload.get("calibrator_btts") or {}
    if calibrator_btts.get("name") != "IDENTITY":
        raise RuntimeArtifactError("btts_calibrator_not_identity")
    calibrator_1x2 = payload.get("calibrator_1x2") or {}
    if calibrator_1x2.get("name") != "MULTINOMIAL_LOGIT":
        raise RuntimeArtifactError("1x2_calibrator_not_multinomial_logit")
    runtime = Full7Phase7Runtime(
        models=payload.get("models") or {},
        feature_names=payload.get("feature_names") or {},
        calibrator_1x2=calibrator_1x2,
        frozen_gate_attestations_verified=True,
        model_artifact_integrity_verified=True,
    )
    metadata = {
        key: value
        for key, value in payload.items()
        if key not in {"models", "feature_names", "calibrator_1x2", "calibrator_btts"}
    }
    metadata["bundle_sha256"] = actual_sha
    return runtime, metadata


def _finite(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def vectorize_locked_features(
    features: Mapping[str, Any],
    locked_names: Sequence[str],
    *,
    expected_count: int,
) -> tuple[np.ndarray, float]:
    names = list(locked_names)
    if len(names) != expected_count:
        raise RuntimeArtifactError(
            f"feature_count_mismatch:{len(names)}!={expected_count}"
        )
    if len(set(names)) != len(names):
        raise RuntimeArtifactError("duplicate_locked_feature")
    vector = np.full(len(names), np.nan, dtype=np.float32)
    present = 0
    for index, name in enumerate(names):
        value = _finite(features.get(name))
        if value is not None:
            vector[index] = value
            present += 1
    return vector, present / len(names) if names else 0.0


def _softmax(values: np.ndarray) -> np.ndarray:
    shifted = values - np.max(values)
    exp = np.exp(shifted)
    total = float(exp.sum())
    if not math.isfinite(total) or total <= 0.0:
        raise RuntimeArtifactError("calibration_softmax_invalid")
    return exp / total


def apply_multinomial_logit(
    probabilities: Sequence[float],
    parameters: Mapping[str, Any],
) -> list[float]:
    if parameters.get("name") != "MULTINOMIAL_LOGIT":
        raise RuntimeArtifactError("1x2_calibrator_not_multinomial_logit")
    raw = np.asarray(probabilities, dtype=float)
    if raw.shape != (3,) or not np.isfinite(raw).all() or (raw <= 0.0).any():
        raise RuntimeArtifactError("1x2_raw_probability_invalid")
    raw = np.clip(raw, 1e-7, 1.0)
    raw /= raw.sum()
    coef = np.asarray(parameters.get("coef"), dtype=float)
    intercept = np.asarray(parameters.get("intercept"), dtype=float)
    classes = [int(value) for value in parameters.get("classes", [])]
    if coef.shape != (3, 3) or intercept.shape != (3,) or sorted(classes) != [0, 1, 2]:
        raise RuntimeArtifactError("1x2_calibrator_shape_invalid")
    calibrated = _softmax(np.log(raw) @ coef.T + intercept)
    aligned = np.zeros(3, dtype=float)
    for column, cls in enumerate(classes):
        aligned[cls] = calibrated[column]
    return [float(value) for value in aligned]


def poisson_market_probabilities(lambda_home: float, lambda_away: float) -> dict[str, Any]:
    lh = _finite(lambda_home)
    la = _finite(lambda_away)
    if lh is None or la is None:
        raise RuntimeArtifactError("goal_lambda_not_finite")
    lh = min(8.0, max(0.03, lh))
    la = min(8.0, max(0.03, la))
    factorial = [math.factorial(index) for index in range(13)]
    home = np.asarray(
        [math.exp(-lh) * lh**index / factorial[index] for index in range(13)],
        dtype=float,
    )
    away = np.asarray(
        [math.exp(-la) * la**index / factorial[index] for index in range(13)],
        dtype=float,
    )
    matrix = np.outer(home, away)
    total = float(matrix.sum())
    if not math.isfinite(total) or total <= 0.0:
        raise RuntimeArtifactError("poisson_score_matrix_invalid")
    matrix /= total
    one_x_two = [
        float(np.tril(matrix, -1).sum()),
        float(np.trace(matrix)),
        float(np.triu(matrix, 1).sum()),
    ]
    btts_yes = float(matrix[1:, 1:].sum())
    return {
        "lambda_home": lh,
        "lambda_away": la,
        "1X2": one_x_two,
        "btts_yes": btts_yes,
        "btts_no": 1.0 - btts_yes,
    }


class Full7Phase7Runtime:
    """Run the two locked Goal-Poisson heads and the frozen calibrators."""

    REQUIRED_MODELS = ("1X2_HOME", "1X2_AWAY", "BTTS_HOME", "BTTS_AWAY")

    def __init__(
        self,
        *,
        models: Mapping[str, Any],
        feature_names: Mapping[str, Sequence[str]],
        calibrator_1x2: Mapping[str, Any],
        expected_feature_counts: Mapping[str, int] | None = None,
        coverage_floors: Mapping[str, float] | None = None,
        frozen_gate_attestations_verified: bool = False,
        model_artifact_integrity_verified: bool = False,
    ) -> None:
        missing = [name for name in self.REQUIRED_MODELS if name not in models]
        if missing:
            raise RuntimeArtifactError(f"model_artifact_missing:{','.join(missing)}")
        self.models = dict(models)
        self.feature_names = {key: list(value) for key, value in feature_names.items()}
        self.calibrator_1x2 = dict(calibrator_1x2)
        self.expected_feature_counts = dict(
            expected_feature_counts or {"1X2": 298, "BTTS": 209}
        )
        self.coverage_floors = dict(
            coverage_floors or {"1X2": 0.97775, "BTTS": 0.98086}
        )
        self.frozen_gate_attestations_verified = (
            frozen_gate_attestations_verified is True
        )
        self.model_artifact_integrity_verified = (
            model_artifact_integrity_verified is True
        )
        for family, expected in self.expected_feature_counts.items():
            names = self.feature_names.get(family, [])
            if len(names) != int(expected):
                raise RuntimeArtifactError(
                    f"feature_count_mismatch:{family}:{len(names)}!={expected}"
                )
        for name, model in self.models.items():
            family = "1X2" if name.startswith("1X2_") else "BTTS"
            observed = getattr(model, "n_features_in_", None)
            if observed is not None and int(observed) != int(
                self.expected_feature_counts[family]
            ):
                raise RuntimeArtifactError(f"model_feature_schema_mismatch:{name}")

    @staticmethod
    def _predict_lambda(model: Any, vector: np.ndarray) -> float:
        prediction = np.asarray(model.predict(vector.reshape(1, -1)), dtype=float).reshape(-1)
        if prediction.shape != (1,) or not math.isfinite(float(prediction[0])):
            raise RuntimeArtifactError("goal_model_prediction_not_finite")
        return min(8.0, max(0.03, float(prediction[0])))

    def predict(
        self,
        features: Mapping[str, Any],
        *,
        input_integrity_verified: bool = False,
        feature_schema_verified: bool = False,
    ) -> dict[str, Any]:
        try:
            x1, coverage_1x2 = vectorize_locked_features(
                features,
                self.feature_names.get("1X2", ()),
                expected_count=int(self.expected_feature_counts["1X2"]),
            )
            xb, coverage_btts = vectorize_locked_features(
                features,
                self.feature_names.get("BTTS", ()),
                expected_count=int(self.expected_feature_counts["BTTS"]),
            )
            raw_1x2 = poisson_market_probabilities(
                self._predict_lambda(self.models["1X2_HOME"], x1),
                self._predict_lambda(self.models["1X2_AWAY"], x1),
            )
            raw_btts = poisson_market_probabilities(
                self._predict_lambda(self.models["BTTS_HOME"], xb),
                self._predict_lambda(self.models["BTTS_AWAY"], xb),
            )
            calibrated_1x2 = apply_multinomial_logit(
                raw_1x2["1X2"], self.calibrator_1x2
            )
            static_gate_names = (
                "train_forward_support",
                "development_support",
                "chronological_segment_support",
                "calibration_gap",
                "calibration_slope_intercept",
                "wilson_uncertainty",
                "probability_bin_support",
            )
            gates = {
                name: self.frozen_gate_attestations_verified
                for name in static_gate_names
            }
            gates["input_integrity"] = input_integrity_verified is True
            gates["model_integrity"] = self.model_artifact_integrity_verified
            gates["feature_schema"] = feature_schema_verified is True
            decision = evaluate_phase7_decision(
                probabilities={
                    "home": calibrated_1x2[0],
                    "draw": calibrated_1x2[1],
                    "away": calibrated_1x2[2],
                    "btts_yes": raw_btts["btts_yes"],
                },
                feature_coverage={"1X2": coverage_1x2, "BTTS": coverage_btts},
                integrity_gates=gates,
            )
            decision.update(
                {
                    "model_lock_1x2": "GOAL_POISSON_LOCKED",
                    "model_lock_btts": "GOAL_POISSON_LOCKED",
                    "calibration_1x2": "MULTINOMIAL_LOGIT",
                    "calibration_btts": "IDENTITY",
                    "feature_coverage": {"1X2": coverage_1x2, "BTTS": coverage_btts},
                    "goal_models": {
                        "1X2": {
                            "lambda_home": raw_1x2["lambda_home"],
                            "lambda_away": raw_1x2["lambda_away"],
                        },
                        "BTTS": {
                            "lambda_home": raw_btts["lambda_home"],
                            "lambda_away": raw_btts["lambda_away"],
                        },
                    },
                }
            )
            return decision
        except Exception as exc:
            failed = evaluate_phase7_decision(
                probabilities={"home": math.nan, "draw": 0.0, "away": 0.0, "btts_yes": 0.0},
                feature_coverage={"1X2": 0.0, "BTTS": 0.0},
                integrity_gates={name: False for name in REQUIRED_INTEGRITY_GATES},
            )
            failed["fail_closed_reasons"] = sorted(
                set(failed["fail_closed_reasons"] + ["MODEL_RUNTIME_FAIL"])
            )
            failed["runtime_error"] = type(exc).__name__
            failed["model_lock_1x2"] = "GOAL_POISSON_LOCKED"
            failed["model_lock_btts"] = "GOAL_POISSON_LOCKED"
            failed["calibration_1x2"] = "MULTINOMIAL_LOGIT"
            failed["calibration_btts"] = "IDENTITY"
            return failed
