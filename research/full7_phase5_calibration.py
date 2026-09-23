#!/usr/bin/env python3
"""FULL-7 Phase 5: calibration/reliability/stability only.

Hard constraints:
- Frozen Phase-4 model locks are immutable.
- OOS is never used for calibrator fit or selection.
- Calibrator decision lock is persisted before OOS predictions are loaded.
- No collection/API/network, no CP1/CP2/CP3/Phase-4 rebuild, no feature reselection.
"""
from __future__ import annotations

import gc
import hashlib
import json
import math
import shutil
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
from scipy.optimize import minimize_scalar
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression

from research.full7_phase4_continue import (
    DIRECT_VARIANTS,
    Phase4Error,
    _dev_folds,
    _fit_hgb,
    _fit_poisson_all,
    _metrics,
    _split_indices,
    _target_y,
    block_network,
)

PHASE5_VERSION = "FULL7_PHASE5_CALIBRATION_1.0"
EXPECTED_PHASE4_MANIFEST_SHA256 = "fd4d33b289602e09b7d6ad82565a83c310d444f20f517af687d255792e3f50b5"
EXPECTED_CRITICAL_HASHES = {
    "PHASE4_PHASE5_FREEZE.json": "5b0f73be407ee92c8af444551c5b8c0489d712f37f6dbe57b645e424d8df3c3b",
    "PHASE4_CALIBRATION_INPUT.jsonl.gz": "9fbac486cea8033f46c2b3eab5f2beb7d4ddac45184ce7c67c03ede46a4b0b83",
    "PHASE4_OOS_LOCK.json": "912dab54eca270b8da89e2245a0a1dc8fdfb308f57280e74cc60bcbed497d7cb",
    "PHASE4_LOCKED_OOS_RESULTS.json": "3d3d77b938a7120751ddc5b9021099bdbc9376e21f31997f826b8e38e304631c",
    "PHASE4_LOCKED_OOS_PREDICTIONS.npz": "d7dae8851a7e5b8b7fcc9de5c0aabaa358cced2e3e3cde46b571394247f04f30",
    "PHASE4_GROUP_ABLATIONS_DEVELOPMENT.json": "04a50fa86b9bb45ecce85c5cef51a115bec3b748ffcbab102352c59f526eb07b",
    "PHASE4_DEVELOPMENT_MODEL_COMPARISON.json": "66d54c3c09c1064490a1d28b3b468ac185f07b7fb5222f1edd3ca4e7720a566d",
    "PHASE4_FEATURE_SELECTION.json": "e6cd9a351ff4aedaa55b70421cb12f757c54d15beea0a51eb0e76a59b503d154",
    "PHASE4_V3_COVERAGE_DIAGNOSTIC_V2.json": "7b81d6c9b04826dcadafb90edb445c32f64b4ac2a39696ed2fe1bca1439c28de",
    "PHASE4_MODEL_RESEARCH.json": "1dbc1f07cc222a7aa2baba5e0bac040681b48f6eb2fbca0b36a6185033f7efe7",
}
MODEL_LOCKS = {
    "1X2": {"variant": "GOAL_POISSON_LOCKED", "feature_count": 298},
    "BTTS": {"variant": "GOAL_POISSON_LOCKED", "feature_count": 209},
    "O25": {"variant": "ENSEMBLE_HGB_POISSON_LOCKED", "feature_count": 240},
}
CALIBRATOR_CANDIDATES = {
    "1X2": ["IDENTITY", "TEMPERATURE_SCALING", "MULTINOMIAL_LOGIT"],
    "BTTS": ["IDENTITY", "PLATT", "BETA", "ISOTONIC"],
    "O25": ["IDENTITY", "PLATT", "BETA", "ISOTONIC"],
}
MIN_CALIBRATION_FIT_N = 1500
MIN_DEV_SEGMENT_N = 200
MIN_BIN_N = 50
TRAIN_FORWARD_FOLDS = 4
TRAIN_FORWARD_WARMUP_FRACTION = 0.40
BOOTSTRAP_REPS = 2000
BOOTSTRAP_BLOCK_DAYS = 7
SEED = 20260923
EPS = 1e-8

# Pre-OOS selection policy fixed before OOS application.
SELECTION_RULE = {
    "aggregate_logloss_max_worsening": 0.0005,
    "aggregate_brier_max_worsening": 0.00025,
    "segment_logloss_material_worsening": 0.0020,
    "aggregate_calibration_min_ece_improvement": 0.0010,
    "segment_calibration_min_improved_segments": 2,
    "segment_logloss_min_nonworse_segments": 2,
    "ranking": ["aggregate_logloss", "aggregate_brier", "aggregate_ece", "aggregate_mce"],
    "fallback": "IDENTITY",
}
PHASE6_READINESS_RULE = {
    "aggregate_logloss_better_than_rolling_prior": True,
    "aggregate_brier_better_than_rolling_prior": True,
    "minimum_folds_improving_both": 2,
    "block_bootstrap_logloss_95pct_upper_below_zero": True,
    "block_bootstrap_brier_95pct_upper_below_zero": True,
    "1x2_sum_to_one_required": True,
}


class Phase5Error(RuntimeError):
    pass


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _json_atomic(path: Path, obj: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def _canonical_sha(obj: Any) -> str:
    raw = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _validate_phase4(phase4: Path) -> dict[str, Any]:
    phase4 = Path(phase4)
    manifest = phase4 / "PHASE4_MANIFEST.json"
    if not manifest.is_file():
        raise Phase5Error("phase4_manifest_missing")
    actual_manifest = _sha256(manifest)
    if actual_manifest != EXPECTED_PHASE4_MANIFEST_SHA256:
        raise Phase5Error(f"phase4_manifest_hash_mismatch:{actual_manifest}")
    for name, expected in EXPECTED_CRITICAL_HASHES.items():
        path = phase4 / name
        if not path.is_file():
            raise Phase5Error(f"phase4_critical_missing:{name}")
        actual = _sha256(path)
        if actual != expected:
            raise Phase5Error(f"phase4_critical_hash_mismatch:{name}:{actual}")
    report = json.loads((phase4 / "PHASE4_MODEL_RESEARCH.json").read_text(encoding="utf-8"))
    if report.get("PHASE4_MODEL_RESEARCH") != "PASS":
        raise Phase5Error("phase4_not_pass")
    if report.get("V3_1_PAIRED_BASELINE_STATUS") != "INSUFFICIENT_SUPPORT":
        raise Phase5Error("v3_status_changed")
    if report.get("V3_COMPARISON_MODE") != "HISTORICAL_REFERENCE_ONLY":
        raise Phase5Error("v3_mode_changed")
    return {
        "phase4_manifest_sha256": actual_manifest,
        "critical_hashes": dict(EXPECTED_CRITICAL_HASHES),
    }


def _train_forward_folds(labels: Mapping[str, np.ndarray], train_idx: np.ndarray):
    dates = labels["dates"]
    unique_dates = sorted({str(dates[i]) for i in train_idx})
    if len(unique_dates) < 20:
        raise Phase5Error("train_dates_too_few_for_forward_oof")
    warmup_dates = max(5, int(len(unique_dates) * TRAIN_FORWARD_WARMUP_FRACTION))
    remaining = unique_dates[warmup_dates:]
    chunks = np.array_split(np.asarray(remaining, dtype=object), TRAIN_FORWARD_FOLDS)
    folds = []
    for n, chunk in enumerate(chunks, 1):
        if len(chunk) == 0:
            continue
        test_dates = set(str(x) for x in chunk.tolist())
        test = np.asarray([i for i in train_idx if str(dates[i]) in test_dates], dtype=int)
        start = int(test.min())
        tr = np.asarray([i for i in train_idx if i < start], dtype=int)
        if len(tr) < MIN_CALIBRATION_FIT_N or len(test) < 100:
            raise Phase5Error(f"train_forward_fold_support_low:{n}:{len(tr)}:{len(test)}")
        folds.append((tr, test, f"TRAIN_FWD{n}"))
    if len(folds) != TRAIN_FORWARD_FOLDS:
        raise Phase5Error("train_forward_fold_count_mismatch")
    return folds


def _locked_raw_prediction(
    X: np.ndarray,
    labels: Mapping[str, np.ndarray],
    meta: Mapping[str, Any],
    target: str,
    features: Sequence[str],
    variant: str,
    tr: np.ndarray,
    te: np.ndarray,
):
    feature_index = {name: i for i, name in enumerate(meta["feature_names"])}
    cols = [feature_index[name] for name in features]
    y = _target_y(labels, target)
    if variant == "GOAL_POISSON_LOCKED":
        p1, pb, po = _fit_poisson_all(X, labels, tr, te, cols)
        return {"1X2": p1, "BTTS": pb, "O25": po}[target]
    if variant == "ENSEMBLE_HGB_POISSON_LOCKED":
        hp = _fit_hgb(
            X,
            y,
            tr,
            te,
            cols,
            target,
            DIRECT_VARIANTS["HGB_REGULARIZED_CORE"]["params"],
        )
        p1, pb, po = _fit_poisson_all(X, labels, tr, te, cols)
        pp = {"1X2": p1, "BTTS": pb, "O25": po}[target]
        return (np.asarray(hp, dtype=float) + np.asarray(pp, dtype=float)) / 2.0
    raise Phase5Error(f"unexpected_locked_variant:{target}:{variant}")


def _generate_pre_oos_predictions(
    stage: Path,
    X: np.ndarray,
    labels: Mapping[str, np.ndarray],
    meta: Mapping[str, Any],
    ablation: Mapping[str, Any],
    dev_models: Mapping[str, Any],
    train_folds,
    dev_folds,
):
    outputs = {}
    fold_meta = {"train_forward": [], "development": []}
    for tr, te, name in train_folds:
        fold_meta["train_forward"].append(
            {"fold": name, "train_n": int(len(tr)), "test_n": int(len(te)),
             "test_start": str(labels["dates"][te[0]]), "test_end": str(labels["dates"][te[-1]])}
        )
    for tr, te, name in dev_folds:
        fold_meta["development"].append(
            {"fold": name, "train_n": int(len(tr)), "test_n": int(len(te)),
             "test_start": str(labels["dates"][te[0]]), "test_end": str(labels["dates"][te[-1]])}
        )
    _json_atomic(stage / "PHASE5_PREOOS_FOLDS.json", fold_meta)

    for target in ("1X2", "BTTS", "O25"):
        path = stage / f"PHASE5_PREOOS_{target}.npz"
        if path.is_file():
            outputs[target] = np.load(path)
            print(f"PHASE5_PREOOS_REUSE={target}", flush=True)
            continue

        locked = MODEL_LOCKS[target]
        if dev_models["targets"][target]["selected_for_oos"] != locked["variant"]:
            raise Phase5Error(f"phase4_variant_lock_changed:{target}")
        features = list(ablation["targets"][target]["locked_features"])
        if len(features) != locked["feature_count"]:
            raise Phase5Error(f"phase4_feature_count_lock_changed:{target}:{len(features)}")
        y = _target_y(labels, target)

        train_indices = []
        train_predictions = []
        train_fold_id = []
        for tr, te, name in train_folds:
            p = _locked_raw_prediction(X, labels, meta, target, features, locked["variant"], tr, te)
            train_indices.append(te)
            train_predictions.append(np.asarray(p, dtype=np.float64))
            train_fold_id.extend([name] * len(te))
            print(f"PHASE5_PREOOS_RAW={target}:{name}", flush=True)
            gc.collect()

        dev_indices = []
        dev_predictions = []
        dev_fold_id = []
        for tr, te, name in dev_folds:
            p = _locked_raw_prediction(X, labels, meta, target, features, locked["variant"], tr, te)
            dev_indices.append(te)
            dev_predictions.append(np.asarray(p, dtype=np.float64))
            dev_fold_id.extend([name] * len(te))
            print(f"PHASE5_PREOOS_RAW={target}:{name}", flush=True)
            gc.collect()

        train_i = np.concatenate(train_indices)
        dev_i = np.concatenate(dev_indices)
        train_p = np.concatenate(train_predictions, axis=0)
        dev_p = np.concatenate(dev_predictions, axis=0)
        np.savez_compressed(
            path,
            train_idx=train_i,
            train_y=y[train_i],
            train_pred=train_p,
            train_fold=np.asarray(train_fold_id, dtype="U16"),
            dev_idx=dev_i,
            dev_y=y[dev_i],
            dev_pred=dev_p,
            dev_fold=np.asarray(dev_fold_id, dtype="U16"),
        )
        outputs[target] = np.load(path)
        print(f"PHASE5_PREOOS_COMPLETE={target}", flush=True)
    return outputs


def _clip_binary(p):
    return np.clip(np.asarray(p, dtype=float), EPS, 1.0 - EPS)


def _clip_multi(p):
    x = np.clip(np.asarray(p, dtype=float), EPS, 1.0)
    x /= x.sum(axis=1, keepdims=True)
    return x


def _softmax(z):
    z = np.asarray(z, dtype=float)
    z = z - z.max(axis=1, keepdims=True)
    e = np.exp(z)
    return e / e.sum(axis=1, keepdims=True)


def _fit_calibrator(name: str, target: str, p, y):
    y = np.asarray(y, dtype=int)
    if len(y) < MIN_CALIBRATION_FIT_N and name != "IDENTITY":
        raise Phase5Error(f"calibrator_fit_support_low:{target}:{name}:{len(y)}")
    if name == "IDENTITY":
        return {"name": "IDENTITY"}

    if target != "1X2":
        p = _clip_binary(p)
        if len(np.unique(y)) != 2:
            raise Phase5Error(f"binary_calibrator_missing_class:{target}:{name}")
        if name == "PLATT":
            x = np.log(p / (1.0 - p)).reshape(-1, 1)
            m = LogisticRegression(C=1e6, solver="lbfgs", max_iter=3000, random_state=SEED)
            m.fit(x, y)
            return {"name": name, "coef": float(m.coef_[0, 0]), "intercept": float(m.intercept_[0])}
        if name == "BETA":
            x = np.column_stack([np.log(p), np.log1p(-p)])
            m = LogisticRegression(C=1e6, solver="lbfgs", max_iter=3000, random_state=SEED)
            m.fit(x, y)
            return {
                "name": name,
                "coef": [float(v) for v in m.coef_[0]],
                "intercept": float(m.intercept_[0]),
            }
        if name == "ISOTONIC":
            if len(np.unique(np.round(p, 8))) < 50:
                raise Phase5Error(f"isotonic_unique_probability_support_low:{target}")
            m = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
            m.fit(p, y)
            return {
                "name": name,
                "x_thresholds": [float(v) for v in m.X_thresholds_],
                "y_thresholds": [float(v) for v in m.y_thresholds_],
            }
        raise Phase5Error(f"unknown_binary_calibrator:{name}")

    p = _clip_multi(p)
    if set(np.unique(y).tolist()) != {0, 1, 2}:
        raise Phase5Error(f"multiclass_calibrator_missing_class:{name}")
    if name == "TEMPERATURE_SCALING":
        logp = np.log(p)

        def objective(t):
            q = _softmax(logp / float(t))
            return float(-np.mean(np.log(np.clip(q[np.arange(len(y)), y], EPS, 1.0))))

        res = minimize_scalar(objective, bounds=(0.25, 4.0), method="bounded", options={"xatol": 1e-8})
        if not res.success or not np.isfinite(res.x):
            raise Phase5Error("temperature_fit_failed")
        return {"name": name, "temperature": float(res.x)}
    if name == "MULTINOMIAL_LOGIT":
        x = np.log(p)
        m = LogisticRegression(C=10.0, solver="lbfgs", max_iter=3000, random_state=SEED)
        m.fit(x, y)
        return {
            "name": name,
            "classes": [int(v) for v in m.classes_],
            "coef": [[float(v) for v in row] for row in m.coef_],
            "intercept": [float(v) for v in m.intercept_],
        }
    raise Phase5Error(f"unknown_multiclass_calibrator:{name}")


def _apply_calibrator(params: Mapping[str, Any], target: str, p):
    name = params["name"]
    if name == "IDENTITY":
        return _clip_multi(p) if target == "1X2" else _clip_binary(p)

    if target != "1X2":
        p = _clip_binary(p)
        if name == "PLATT":
            z = params["coef"] * np.log(p / (1.0 - p)) + params["intercept"]
            return 1.0 / (1.0 + np.exp(-np.clip(z, -40.0, 40.0)))
        if name == "BETA":
            coef = np.asarray(params["coef"], dtype=float)
            x = np.column_stack([np.log(p), np.log1p(-p)])
            z = x @ coef + float(params["intercept"])
            return 1.0 / (1.0 + np.exp(-np.clip(z, -40.0, 40.0)))
        if name == "ISOTONIC":
            return np.clip(
                np.interp(
                    p,
                    np.asarray(params["x_thresholds"], dtype=float),
                    np.asarray(params["y_thresholds"], dtype=float),
                ),
                EPS,
                1.0 - EPS,
            )
        raise Phase5Error(f"unknown_binary_apply:{name}")

    p = _clip_multi(p)
    if name == "TEMPERATURE_SCALING":
        return _softmax(np.log(p) / float(params["temperature"]))
    if name == "MULTINOMIAL_LOGIT":
        x = np.log(p)
        coef = np.asarray(params["coef"], dtype=float)
        intercept = np.asarray(params["intercept"], dtype=float)
        scores = x @ coef.T + intercept
        q = _softmax(scores)
        classes = [int(v) for v in params["classes"]]
        if classes != [0, 1, 2]:
            aligned = np.zeros_like(q)
            for j, cls in enumerate(classes):
                aligned[:, cls] = q[:, j]
            q = aligned
        return q
    raise Phase5Error(f"unknown_multiclass_apply:{name}")


def _calibration_key(metrics: Mapping[str, Any], target: str):
    if target == "1X2":
        return float(metrics["toplabel_ece_10"]), float(metrics["toplabel_mce_10"])
    return float(metrics["ece_10"]), float(metrics["mce_10"])


def _selection_diagnostic(target: str, candidate: Mapping[str, Any], identity: Mapping[str, Any]):
    cm = candidate["aggregate_metrics"]
    im = identity["aggregate_metrics"]
    c_ece, c_mce = _calibration_key(cm, target)
    i_ece, i_mce = _calibration_key(im, target)
    seg_nonworse = 0
    seg_cal_better = 0
    seg_material_worse = 0
    for cseg, iseg in zip(candidate["segments"], identity["segments"]):
        if cseg["metrics"]["logloss"] <= iseg["metrics"]["logloss"] + 1e-12:
            seg_nonworse += 1
        if cseg["metrics"]["logloss"] > iseg["metrics"]["logloss"] + SELECTION_RULE["segment_logloss_material_worsening"]:
            seg_material_worse += 1
        ce, _ = _calibration_key(cseg["metrics"], target)
        ie, _ = _calibration_key(iseg["metrics"], target)
        if ce < ie:
            seg_cal_better += 1
    if candidate["name"] == "IDENTITY":
        eligible = True
        reasons = ["IDENTITY_FALLBACK_ALWAYS_ELIGIBLE"]
    else:
        checks = {
            "aggregate_logloss_nonmaterial": cm["logloss"] <= im["logloss"] + SELECTION_RULE["aggregate_logloss_max_worsening"],
            "aggregate_brier_nonmaterial": cm["brier"] <= im["brier"] + SELECTION_RULE["aggregate_brier_max_worsening"],
            "aggregate_calibration_improved": c_ece <= i_ece - SELECTION_RULE["aggregate_calibration_min_ece_improvement"],
            "segment_logloss_robust": seg_nonworse >= SELECTION_RULE["segment_logloss_min_nonworse_segments"],
            "segment_calibration_robust": seg_cal_better >= SELECTION_RULE["segment_calibration_min_improved_segments"],
            "no_multiple_material_logloss_failures": seg_material_worse <= 1,
        }
        eligible = all(checks.values())
        reasons = [f"{k}={v}" for k, v in checks.items()]
    return {
        "eligible": bool(eligible),
        "reasons": reasons,
        "delta_logloss_vs_identity": float(cm["logloss"] - im["logloss"]),
        "delta_brier_vs_identity": float(cm["brier"] - im["brier"]),
        "delta_ece_vs_identity": float(c_ece - i_ece),
        "delta_mce_vs_identity": float(c_mce - i_mce),
        "segments_logloss_nonworse": int(seg_nonworse),
        "segments_calibration_better": int(seg_cal_better),
        "segments_material_logloss_worse": int(seg_material_worse),
    }


def _select_calibrators(stage: Path, preoos: Mapping[str, Any]):
    out_path = stage / "PHASE5_CALIBRATOR_DEVELOPMENT_COMPARISON.json"
    if out_path.is_file():
        return json.loads(out_path.read_text(encoding="utf-8"))

    result = {
        "version": "FULL7_PHASE5_PREOOS_CALIBRATOR_SELECTION_1.0",
        "selection_rule": SELECTION_RULE,
        "oos_used_for_fit": False,
        "oos_used_for_selection": False,
        "targets": {},
    }
    for target in ("1X2", "BTTS", "O25"):
        data = preoos[target]
        train_pred = np.asarray(data["train_pred"], dtype=float)
        train_y = np.asarray(data["train_y"], dtype=int)
        dev_pred = np.asarray(data["dev_pred"], dtype=float)
        dev_y = np.asarray(data["dev_y"], dtype=int)
        dev_fold = np.asarray(data["dev_fold"]).astype(str)
        candidates = {}

        for candidate_name in CALIBRATOR_CANDIDATES[target]:
            fold_predictions = []
            fold_labels = []
            segment_results = []
            prior_pred_parts = [train_pred]
            prior_y_parts = [train_y]
            failed = None
            for fold_name in ("DEV1", "DEV2", "DEV3"):
                mask = dev_fold == fold_name
                if int(mask.sum()) < MIN_DEV_SEGMENT_N:
                    failed = f"segment_support_low:{fold_name}:{int(mask.sum())}"
                    break
                fit_p = np.concatenate(prior_pred_parts, axis=0)
                fit_y = np.concatenate(prior_y_parts, axis=0)
                try:
                    params = _fit_calibrator(candidate_name, target, fit_p, fit_y)
                    calibrated = _apply_calibrator(params, target, dev_pred[mask])
                except Exception as exc:
                    failed = f"{type(exc).__name__}:{exc}"
                    break
                metrics = _metrics(target, dev_y[mask], calibrated)
                segment_results.append({
                    "fold": fold_name,
                    "fit_n": int(len(fit_y)),
                    "evaluation_n": int(mask.sum()),
                    "metrics": metrics,
                    "parameter_sha256": _canonical_sha(params),
                })
                fold_predictions.append(np.asarray(calibrated))
                fold_labels.append(dev_y[mask])
                prior_pred_parts.append(dev_pred[mask])
                prior_y_parts.append(dev_y[mask])

            if failed is not None:
                candidates[candidate_name] = {"name": candidate_name, "status": "FAIL_CLOSED", "error": failed}
                continue
            aggregate_pred = np.concatenate(fold_predictions, axis=0)
            aggregate_y = np.concatenate(fold_labels, axis=0)
            candidates[candidate_name] = {
                "name": candidate_name,
                "status": "COMPLETE",
                "segments": segment_results,
                "aggregate_metrics": _metrics(target, aggregate_y, aggregate_pred),
            }

        identity = candidates["IDENTITY"]
        if identity.get("status") != "COMPLETE":
            raise Phase5Error(f"identity_calibrator_failed:{target}")
        eligible = []
        for name, candidate in candidates.items():
            if candidate.get("status") != "COMPLETE":
                candidate["selection_diagnostic"] = {"eligible": False, "reasons": ["FAIL_CLOSED"]}
                continue
            diagnostic = _selection_diagnostic(target, candidate, identity)
            candidate["selection_diagnostic"] = diagnostic
            if name != "IDENTITY" and diagnostic["eligible"]:
                eligible.append(name)

        if eligible:
            def rank_key(name):
                m = candidates[name]["aggregate_metrics"]
                ece, mce = _calibration_key(m, target)
                return (float(m["logloss"]), float(m["brier"]), float(ece), float(mce), name)
            selected = sorted(eligible, key=rank_key)[0]
            accepted = True
        else:
            selected = "IDENTITY"
            accepted = False

        # Final fit uses only out-of-sample/forward predictions from TRAIN + DEVELOPMENT.
        final_fit_pred = np.concatenate([train_pred, dev_pred], axis=0)
        final_fit_y = np.concatenate([train_y, dev_y], axis=0)
        final_params = _fit_calibrator(selected, target, final_fit_pred, final_fit_y)
        result["targets"][target] = {
            "model_lock": MODEL_LOCKS[target],
            "calibrator_candidates": CALIBRATOR_CANDIDATES[target],
            "candidates": candidates,
            "selected_calibrator": selected,
            "calibration_accepted": accepted,
            "calibration_fit_source": "TRAIN_FORWARD_OOF_PLUS_DEVELOPMENT_FORWARD_PREDICTIONS_ONLY",
            "calibration_selection_source": "DEV1_DEV2_DEV3_CHRONOLOGICAL_FORWARD_ONLY",
            "final_fit_n": int(len(final_fit_y)),
            "final_fit_prediction_rows_are_out_of_sample_from_base_model": True,
            "final_parameters": final_params,
            "final_parameters_sha256": _canonical_sha(final_params),
            "oos_used_for_fit": False,
            "oos_used_for_selection": False,
        }
        print(f"PHASE5_PREOOS_SELECTION={target}:{selected}:accepted={accepted}", flush=True)

    _json_atomic(out_path, result)
    return result


def _write_decision_lock(
    stage: Path,
    phase4_validation: Mapping[str, Any],
    selection: Mapping[str, Any],
    preoos: Mapping[str, Any],
):
    lock_path = stage / "PHASE5_CALIBRATION_DECISION_LOCK.json"
    sha_path = stage / "PHASE5_CALIBRATION_DECISION_LOCK.sha256"
    if lock_path.is_file() and sha_path.is_file():
        expected = sha_path.read_text(encoding="ascii").strip()
        actual = _sha256(lock_path)
        if expected != actual:
            raise Phase5Error("existing_phase5_lock_hash_mismatch")
        return json.loads(lock_path.read_text(encoding="utf-8")), actual

    targets = {}
    for target in ("1X2", "BTTS", "O25"):
        obj = selection["targets"][target]
        data = preoos[target]
        fit_ids = np.concatenate([np.asarray(data["train_idx"], dtype=np.int64), np.asarray(data["dev_idx"], dtype=np.int64)])
        targets[target] = {
            "model_lock": obj["model_lock"],
            "allowed_calibrators": obj["calibrator_candidates"],
            "selected_calibrator": obj["selected_calibrator"],
            "calibration_accepted": obj["calibration_accepted"],
            "fit_source": obj["calibration_fit_source"],
            "selection_source": obj["calibration_selection_source"],
            "fit_n": obj["final_fit_n"],
            "fit_row_indices_sha256": hashlib.sha256(fit_ids.tobytes()).hexdigest(),
            "final_parameters": obj["final_parameters"],
            "final_parameters_sha256": obj["final_parameters_sha256"],
            "oos_used_for_fit": False,
            "oos_used_for_selection": False,
        }

    payload = {
        "lock_version": "PHASE5_CALIBRATION_DECISION_LOCK_1.0",
        "created_at_utc": _utcnow(),
        "purpose": "Freeze calibrator selection and fitted parameters before any Phase-4 OOS prediction is loaded for Phase 5.",
        "phase4_manifest_sha256": phase4_validation["phase4_manifest_sha256"],
        "phase4_critical_hashes": phase4_validation["critical_hashes"],
        "model_locks": MODEL_LOCKS,
        "calibrator_candidates": CALIBRATOR_CANDIDATES,
        "fit_dataset": "CHRONOLOGICAL_PRE_OOS_FORWARD_PREDICTIONS_ONLY",
        "selection_dataset": "DEVELOPMENT_DEV1_DEV2_DEV3_ONLY",
        "selection_rule": SELECTION_RULE,
        "minimum_sample_rules": {
            "calibration_fit_min_n": MIN_CALIBRATION_FIT_N,
            "development_segment_min_n": MIN_DEV_SEGMENT_N,
            "reliability_bin_min_n": MIN_BIN_N,
            "isotonic_min_unique_probabilities": 50,
        },
        "fail_closed_rules": [
            "NO_OOS_IN_FIT",
            "NO_OOS_IN_SELECTION",
            "NO_IN_SAMPLE_BASE_MODEL_PREDICTIONS_FOR_CALIBRATOR_FIT",
            "NO_PHASE4_MODEL_CHANGE",
            "NO_FEATURE_RESELECTION",
            "NO_COLLECTION_OR_API",
            "IDENTITY_IF_NO_NONIDENTITY_CALIBRATOR_PASSES_PREOOS_ROBUSTNESS",
        ],
        "targets": targets,
        "V3_1_PAIRED_BASELINE_STATUS": "INSUFFICIENT_SUPPORT",
        "V3_COMPARISON_MODE": "HISTORICAL_REFERENCE_ONLY",
        "oos_used_for_fit": False,
        "oos_used_for_selection": False,
    }
    payload["lock_payload_sha256"] = _canonical_sha(payload)
    _json_atomic(lock_path, payload)
    file_sha = _sha256(lock_path)
    sha_path.write_text(file_sha + "\n", encoding="ascii")
    print("PHASE5_CALIBRATION_DECISION_LOCK_SHA256=" + file_sha, flush=True)
    print("PHASE5_OOS_APPLICATION_AUTHORIZED_BY_LOCK=true", flush=True)
    return payload, file_sha


def _reliability_binary(y, p):
    y = np.asarray(y, dtype=int)
    p = _clip_binary(p)
    bins = []
    for b in range(10):
        lo = b / 10.0
        hi = (b + 1) / 10.0
        mask = (p >= lo) & (p < hi if b < 9 else p <= hi)
        n = int(mask.sum())
        if n == 0:
            continue
        mean_p = float(p[mask].mean())
        rate = float(y[mask].mean())
        bins.append({
            "bin": b,
            "range": [lo, hi],
            "n": n,
            "mean_probability": mean_p,
            "actual_rate": rate,
            "absolute_calibration_error": abs(mean_p - rate),
            "thin_support": n < MIN_BIN_N,
            "high_probability_region": lo >= 0.60,
        })
    return bins


def _calibration_slope_intercept(y, p):
    y = np.asarray(y, dtype=int)
    p = _clip_binary(p)
    if len(np.unique(y)) != 2:
        return {"slope": None, "intercept": None, "status": "CLASS_SUPPORT_FAIL"}
    x = np.log(p / (1.0 - p)).reshape(-1, 1)
    m = LogisticRegression(C=1e6, solver="lbfgs", max_iter=3000, random_state=SEED)
    m.fit(x, y)
    return {"slope": float(m.coef_[0, 0]), "intercept": float(m.intercept_[0]), "status": "OK"}


def _probability_distribution(target, p):
    x = np.asarray(p, dtype=float)
    if target != "1X2":
        q = _clip_binary(x)
        return {
            "mean": float(q.mean()), "std": float(q.std()), "min": float(q.min()), "max": float(q.max()),
            "q01": float(np.quantile(q, 0.01)), "q05": float(np.quantile(q, 0.05)),
            "q25": float(np.quantile(q, 0.25)), "median": float(np.quantile(q, 0.5)),
            "q75": float(np.quantile(q, 0.75)), "q95": float(np.quantile(q, 0.95)), "q99": float(np.quantile(q, 0.99)),
            "extreme_counts": {
                "p_le_0_01": int((q <= 0.01).sum()), "p_le_0_05": int((q <= 0.05).sum()),
                "p_ge_0_95": int((q >= 0.95).sum()), "p_ge_0_99": int((q >= 0.99).sum()),
                "p_ge_0_70": int((q >= 0.70).sum()), "p_ge_0_80": int((q >= 0.80).sum()),
            },
        }
    q = _clip_multi(x)
    mx = q.max(axis=1)
    return {
        "class_mean": [float(v) for v in q.mean(axis=0)],
        "class_min": [float(v) for v in q.min(axis=0)],
        "class_max": [float(v) for v in q.max(axis=0)],
        "max_probability_quantiles": {
            "q50": float(np.quantile(mx, 0.5)), "q75": float(np.quantile(mx, 0.75)),
            "q90": float(np.quantile(mx, 0.9)), "q95": float(np.quantile(mx, 0.95)), "q99": float(np.quantile(mx, 0.99)),
        },
        "extreme_counts": {
            "max_p_ge_0_70": int((mx >= 0.70).sum()), "max_p_ge_0_80": int((mx >= 0.80).sum()),
            "max_p_ge_0_90": int((mx >= 0.90).sum()), "any_class_p_le_0_01": int((q <= 0.01).any(axis=1).sum()),
        },
    }


def _detail_metrics(target, y, p):
    base = _metrics(target, y, p)
    out = {
        "n": int(base["n"]),
        "logloss": float(base["logloss"]),
        "brier": float(base["brier"]),
        "accuracy": float(base["accuracy"]),
        "probability_distribution": _probability_distribution(target, p),
    }
    if target != "1X2":
        out["ece_10"] = float(base["ece_10"])
        out["mce_10"] = float(base["mce_10"])
        out["reliability_bins"] = _reliability_binary(y, p)
        out["calibration_slope_intercept"] = _calibration_slope_intercept(y, p)
    else:
        q = _clip_multi(p)
        out["toplabel_ece_10"] = float(base["toplabel_ece_10"])
        out["toplabel_mce_10"] = float(base["toplabel_mce_10"])
        out["toplabel_reliability_bins"] = base["toplabel_reliability_10"]
        classes = {"home": 0, "draw": 1, "away": 2}
        out["class_calibration"] = {}
        for name, cls in classes.items():
            yy = (np.asarray(y) == cls).astype(int)
            mm = _metrics("BTTS", yy, q[:, cls])
            out["class_calibration"][name] = {
                "ece_10": float(mm["ece_10"]),
                "mce_10": float(mm["mce_10"]),
                "reliability_bins": _reliability_binary(yy, q[:, cls]),
                "calibration_slope_intercept": _calibration_slope_intercept(yy, q[:, cls]),
            }
        sums = q.sum(axis=1)
        out["sum_to_one_coherence"] = {
            "max_abs_error": float(np.max(np.abs(sums - 1.0))),
            "violations_gt_1e_10": int((np.abs(sums - 1.0) > 1e-10).sum()),
            "all_finite": bool(np.isfinite(q).all()),
            "all_in_0_1": bool(((q >= 0.0) & (q <= 1.0)).all()),
        }
    return out


def _loss_vectors(target, y, p):
    y = np.asarray(y, dtype=int)
    if target == "1X2":
        q = _clip_multi(p)
        ll = -np.log(q[np.arange(len(y)), y])
        one = np.zeros_like(q)
        one[np.arange(len(y)), y] = 1.0
        br = np.sum((q - one) ** 2, axis=1)
        return ll, br
    q = _clip_binary(p)
    ll = -(y * np.log(q) + (1 - y) * np.log1p(-q))
    br = (q - y) ** 2
    return ll, br


def _bootstrap_delta(diff: np.ndarray, dates: Sequence[str]):
    diff = np.asarray(diff, dtype=float)
    ds = [date.fromisoformat(str(d)[:10]) for d in dates]
    first = min(ds)
    groups = defaultdict(list)
    for i, d in enumerate(ds):
        groups[(d - first).days // BOOTSTRAP_BLOCK_DAYS].append(i)
    blocks = [np.asarray(groups[k], dtype=int) for k in sorted(groups)]
    if len(blocks) < 10:
        raise Phase5Error(f"bootstrap_blocks_too_few:{len(blocks)}")
    rng = np.random.default_rng(SEED)
    reps = np.empty(BOOTSTRAP_REPS, dtype=float)
    for r in range(BOOTSTRAP_REPS):
        picks = rng.integers(0, len(blocks), size=len(blocks))
        total = 0.0
        count = 0
        for pick in picks:
            idx = blocks[int(pick)]
            total += float(diff[idx].sum())
            count += len(idx)
        reps[r] = total / count
    lo, hi = np.quantile(reps, [0.025, 0.975])
    point = float(diff.mean())
    if hi < 0:
        conclusion = "SUPPORTED_IMPROVEMENT"
    elif lo > 0:
        conclusion = "SUPPORTED_WORSENING"
    else:
        conclusion = "UNCERTAIN_CI_CROSSES_ZERO"
    return {
        "method": "PAIRED_CALENDAR_BLOCK_BOOTSTRAP",
        "block_days": BOOTSTRAP_BLOCK_DAYS,
        "blocks": len(blocks),
        "repetitions": BOOTSTRAP_REPS,
        "seed": SEED,
        "point_delta_model_minus_prior": point,
        "ci95": [float(lo), float(hi)],
        "bootstrap_probability_delta_lt_zero": float(np.mean(reps < 0.0)),
        "conclusion": conclusion,
    }


def _evaluate_oos_after_lock(
    stage: Path,
    phase4: Path,
    labels: Mapping[str, np.ndarray],
    splits: Mapping[str, Any],
    decision_lock: Mapping[str, Any],
    lock_sha: str,
):
    # This function is deliberately called only after decision lock is persisted.
    pred_file = phase4 / "PHASE4_LOCKED_OOS_PREDICTIONS.npz"
    if _sha256(pred_file) != EXPECTED_CRITICAL_HASHES["PHASE4_LOCKED_OOS_PREDICTIONS.npz"]:
        raise Phase5Error("oos_prediction_hash_changed_after_lock")
    raw = np.load(pred_file)
    _train, _dev, oos_folds = _split_indices(labels, splits)
    all_oos = np.concatenate([te for _tr, te, _name in oos_folds])
    results = {
        "version": "FULL7_PHASE5_OOS_EVALUATION_1.0",
        "decision_lock_sha256": lock_sha,
        "oos_used_for_fit": False,
        "oos_used_for_selection": False,
        "targets": {},
    }

    for target in ("1X2", "BTTS", "O25"):
        y = _target_y(labels, target)
        p_raw = np.asarray(raw[f"{target}_pred"], dtype=float)
        p_prior = np.asarray(raw[f"{target}_prior"], dtype=float)
        params = decision_lock["targets"][target]["final_parameters"]
        p_post = np.full_like(p_raw, np.nan, dtype=float)
        p_post[all_oos] = _apply_calibrator(params, target, p_raw[all_oos])

        folds = {}
        improving_both = 0
        for _tr, te, name in oos_folds:
            pre = _detail_metrics(target, y[te], p_raw[te])
            post = _detail_metrics(target, y[te], p_post[te])
            prior = _detail_metrics(target, y[te], p_prior[te])
            dll_pre = float(pre["logloss"] - prior["logloss"])
            dbr_pre = float(pre["brier"] - prior["brier"])
            dll_post = float(post["logloss"] - prior["logloss"])
            dbr_post = float(post["brier"] - prior["brier"])
            if dll_post < 0 and dbr_post < 0:
                improving_both += 1
            folds[name] = {
                "N": int(len(te)),
                "PRE_CALIBRATION_METRICS": pre,
                "POST_CALIBRATION_METRICS": post,
                "ROLLING_PRIOR_METRICS": prior,
                "ROLLING_PRIOR_PAIRED_COMPARISON": {
                    "pre_delta_logloss_model_minus_prior": dll_pre,
                    "pre_delta_brier_model_minus_prior": dbr_pre,
                    "post_delta_logloss_model_minus_prior": dll_post,
                    "post_delta_brier_model_minus_prior": dbr_post,
                    "post_direction": "IMPROVED_BOTH" if dll_post < 0 and dbr_post < 0 else "MIXED_OR_WORSE",
                },
            }

        pre_all = _detail_metrics(target, y[all_oos], p_raw[all_oos])
        post_all = _detail_metrics(target, y[all_oos], p_post[all_oos])
        prior_all = _detail_metrics(target, y[all_oos], p_prior[all_oos])

        pre_ll, pre_br = _loss_vectors(target, y[all_oos], p_raw[all_oos])
        post_ll, post_br = _loss_vectors(target, y[all_oos], p_post[all_oos])
        prior_ll, prior_br = _loss_vectors(target, y[all_oos], p_prior[all_oos])
        dates = [str(labels["dates"][i]) for i in all_oos]
        uncertainty = {
            "pre_vs_prior_logloss": _bootstrap_delta(pre_ll - prior_ll, dates),
            "pre_vs_prior_brier": _bootstrap_delta(pre_br - prior_br, dates),
            "post_vs_prior_logloss": _bootstrap_delta(post_ll - prior_ll, dates),
            "post_vs_prior_brier": _bootstrap_delta(post_br - prior_br, dates),
        }

        coherence_ok = True
        if target == "1X2":
            coherence_ok = (
                post_all["sum_to_one_coherence"]["violations_gt_1e_10"] == 0
                and post_all["sum_to_one_coherence"]["all_finite"]
                and post_all["sum_to_one_coherence"]["all_in_0_1"]
            )

        ready = (
            post_all["logloss"] < prior_all["logloss"]
            and post_all["brier"] < prior_all["brier"]
            and improving_both >= PHASE6_READINESS_RULE["minimum_folds_improving_both"]
            and uncertainty["post_vs_prior_logloss"]["ci95"][1] < 0
            and uncertainty["post_vs_prior_brier"]["ci95"][1] < 0
            and coherence_ok
        )
        results["targets"][target] = {
            "MODEL_LOCK": MODEL_LOCKS[target],
            "CALIBRATOR_CANDIDATES": CALIBRATOR_CANDIDATES[target],
            "SELECTED_CALIBRATOR": decision_lock["targets"][target]["selected_calibrator"],
            "CALIBRATION_FIT_SOURCE": decision_lock["targets"][target]["fit_source"],
            "CALIBRATION_SELECTION_SOURCE": decision_lock["targets"][target]["selection_source"],
            "OOS_USED_FOR_FIT": False,
            "OOS_USED_FOR_SELECTION": False,
            "CALIBRATION_ACCEPTED": bool(decision_lock["targets"][target]["calibration_accepted"]),
            "OOS1_METRICS": folds["OOS1"],
            "OOS2_METRICS": folds["OOS2"],
            "OOS3_METRICS": folds["OOS3"],
            "AGGREGATE_OOS_METRICS": {
                "N": int(len(all_oos)),
                "PRE_CALIBRATION_METRICS": pre_all,
                "POST_CALIBRATION_METRICS": post_all,
                "ROLLING_PRIOR_METRICS": prior_all,
                "ROLLING_PRIOR_PAIRED_COMPARISON": {
                    "pre_delta_logloss_model_minus_prior": float(pre_all["logloss"] - prior_all["logloss"]),
                    "pre_delta_brier_model_minus_prior": float(pre_all["brier"] - prior_all["brier"]),
                    "post_delta_logloss_model_minus_prior": float(post_all["logloss"] - prior_all["logloss"]),
                    "post_delta_brier_model_minus_prior": float(post_all["brier"] - prior_all["brier"]),
                },
            },
            "OOS_FOLD_STABILITY": {
                "folds_improving_both_post_vs_prior": int(improving_both),
                "required_for_phase6_ready": PHASE6_READINESS_RULE["minimum_folds_improving_both"],
                "all_three_improve_both": improving_both == 3,
            },
            "UNCERTAINTY_RESULT": uncertainty,
            "1X2_COHERENCE_CHECK": post_all.get("sum_to_one_coherence") if target == "1X2" else "NOT_APPLICABLE",
            "PHASE6_READY": bool(ready),
        }
        print(
            "PHASE5_OOS_COMPLETE="
            + target
            + ":selected="
            + str(results["targets"][target]["SELECTED_CALIBRATOR"])
            + ":phase6_ready="
            + str(bool(ready)).lower(),
            flush=True,
        )
    return results


def _manifest(stage: Path):
    artifacts = {}
    for path in sorted(p for p in stage.iterdir() if p.is_file() and p.name != "PHASE5_MANIFEST.json"):
        artifacts[path.name] = {"bytes": path.stat().st_size, "sha256": _sha256(path)}
    obj = {"schema": "FULL7_PHASE5_MANIFEST_1.0", "created_at_utc": _utcnow(), "artifacts": artifacts}
    _json_atomic(stage / "PHASE5_MANIFEST.json", obj)
    return obj


def run_phase5(phase4_dir: Path, output_dir: Path):
    phase4 = Path(phase4_dir)
    output = Path(output_dir)
    if output.is_dir() and (output / "PHASE5_CALIBRATION_REPORT.json").is_file():
        report = json.loads((output / "PHASE5_CALIBRATION_REPORT.json").read_text(encoding="utf-8"))
        if report.get("PHASE5_CALIBRATION") == "PASS":
            print("PHASE5_REUSE_PASS", flush=True)
            return report

    validation = _validate_phase4(phase4)
    stage = output.parent / ".phase5.stage"
    stage.mkdir(parents=True, exist_ok=True)

    # Frozen Phase-4 matrix is read-only and reused; never rebuilt.
    matrix = phase4 / "PHASE4_MATRIX.npy"
    labels_path = phase4 / "PHASE4_LABELS.npz"
    meta_path = phase4 / "PHASE4_MATRIX_METADATA.json"
    ablation_path = phase4 / "PHASE4_GROUP_ABLATIONS_DEVELOPMENT.json"
    dev_models_path = phase4 / "PHASE4_DEVELOPMENT_MODEL_COMPARISON.json"
    splits_path = phase4 / "PHASE4_SPLITS.json"
    for p in (matrix, labels_path, meta_path, ablation_path, dev_models_path, splits_path):
        if not p.is_file():
            raise Phase5Error(f"phase4_required_artifact_missing:{p.name}")

    X = np.load(matrix, mmap_mode="r")
    npz = np.load(labels_path)
    labels = {k: npz[k] for k in ("match_ids", "dates", "y1", "yb", "yo", "yh", "ya")}
    if len(labels["match_ids"]) != 16137:
        raise Phase5Error("phase4_match_count_changed")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    ablation = json.loads(ablation_path.read_text(encoding="utf-8"))
    dev_models = json.loads(dev_models_path.read_text(encoding="utf-8"))
    splits = json.loads(splits_path.read_text(encoding="utf-8"))
    train, dev, _oos = _split_indices(labels, splits)
    train_folds = _train_forward_folds(labels, train)
    dev_folds = _dev_folds(labels, train, dev)

    print("PHASE5_PREOOS_CALIBRATION_START", flush=True)
    preoos = _generate_pre_oos_predictions(stage, X, labels, meta, ablation, dev_models, train_folds, dev_folds)
    selection = _select_calibrators(stage, preoos)

    # Mandatory barrier: lock is fully written and hashed before OOS predictions are loaded below.
    decision_lock, lock_sha = _write_decision_lock(stage, validation, selection, preoos)

    oos_results = _evaluate_oos_after_lock(stage, phase4, labels, splits, decision_lock, lock_sha)

    report = {
        "PHASE5_CALIBRATION": "PASS",
        "status": "COMPLETE",
        "phase5_version": PHASE5_VERSION,
        "completed_at_utc": _utcnow(),
        "phase4_manifest_sha256": validation["phase4_manifest_sha256"],
        "PHASE5_CALIBRATION_DECISION_LOCK_SHA256": lock_sha,
        "OOS_USED_FOR_FIT": False,
        "OOS_USED_FOR_SELECTION": False,
        "V3_1_PAIRED_BASELINE_STATUS": "INSUFFICIENT_SUPPORT",
        "V3_COMPARISON_MODE": "HISTORICAL_REFERENCE_ONLY",
        "H2H": "UNAVAILABLE_IN_FROZEN_FULL7_PHASE4_INPUT",
        "Provider_Potentials": "UNAVAILABLE_IN_FROZEN_FULL7_PHASE4_INPUT",
        "phase4_model_locks_unchanged": MODEL_LOCKS,
        "phase4_feature_results_mutated": False,
        "collection_performed": False,
        "api_calls_performed": False,
        "phase4_rebuilt": False,
        "targets": oos_results["targets"],
        "phase6_readiness_rule": PHASE6_READINESS_RULE,
        "production_release_allowed": False,
        "decision_gates_developed": False,
        "threshold_optimization_performed": False,
        "next_action": "STOP_FOR_STEERING_REVIEW_BEFORE_PHASE6",
    }
    _json_atomic(stage / "PHASE5_CALIBRATION_REPORT.json", report)

    lines = [
        "FULL-7 PHASE 5 CALIBRATION",
        f"PHASE5_CALIBRATION = {report['PHASE5_CALIBRATION']}",
        f"PHASE5_CALIBRATION_DECISION_LOCK_SHA256 = {lock_sha}",
        "OOS_USED_FOR_FIT = false",
        "OOS_USED_FOR_SELECTION = false",
        "",
    ]
    for target in ("1X2", "BTTS", "O25"):
        t = report["targets"][target]
        agg = t["AGGREGATE_OOS_METRICS"]
        lines += [
            f"[{target}]",
            f"MODEL_LOCK = {json.dumps(t['MODEL_LOCK'], sort_keys=True)}",
            f"SELECTED_CALIBRATOR = {t['SELECTED_CALIBRATOR']}",
            f"CALIBRATION_ACCEPTED = {str(t['CALIBRATION_ACCEPTED']).lower()}",
            f"PRE_LOGLOSS = {agg['PRE_CALIBRATION_METRICS']['logloss']:.12f}",
            f"POST_LOGLOSS = {agg['POST_CALIBRATION_METRICS']['logloss']:.12f}",
            f"PRE_BRIER = {agg['PRE_CALIBRATION_METRICS']['brier']:.12f}",
            f"POST_BRIER = {agg['POST_CALIBRATION_METRICS']['brier']:.12f}",
            f"PHASE6_READY = {str(t['PHASE6_READY']).lower()}",
            "",
        ]
    (stage / "PHASE5_CALIBRATION_REPORT.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    manifest = _manifest(stage)

    if output.exists():
        raise Phase5Error("phase5_output_appeared_before_publish")
    stage.rename(output)
    manifest_sha = _sha256(output / "PHASE5_MANIFEST.json")
    print("PHASE5_CALIBRATION=PASS", flush=True)
    print("PHASE5_MANIFEST_SHA256=" + manifest_sha, flush=True)
    print(
        "PHASE5_FINAL="
        + json.dumps(
            {
                "decision_lock_sha256": lock_sha,
                "manifest_sha256": manifest_sha,
                "targets": {
                    t: {
                        "selected_calibrator": report["targets"][t]["SELECTED_CALIBRATOR"],
                        "calibration_accepted": report["targets"][t]["CALIBRATION_ACCEPTED"],
                        "phase6_ready": report["targets"][t]["PHASE6_READY"],
                        "aggregate": report["targets"][t]["AGGREGATE_OOS_METRICS"],
                        "fold_stability": report["targets"][t]["OOS_FOLD_STABILITY"],
                        "uncertainty": report["targets"][t]["UNCERTAINTY_RESULT"],
                    }
                    for t in ("1X2", "BTTS", "O25")
                },
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return report


def run_phase5_offline(phase4_dir: Path, output_dir: Path):
    with block_network():
        return run_phase5(phase4_dir, output_dir)
