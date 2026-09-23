#!/usr/bin/env python3
"""FULL-7 Phase 6 — PRE-OOS decision research and one-shot locked OOS evaluation.

This module is intentionally NOT wired into the service runner. It is a research
artifact that must be invoked explicitly against the frozen Phase-4/Phase-5
artifact tree. It never runs CP1-CP5, never collects data, never calls an API,
and never changes production.

Hard barrier:
1) PRE-OOS research reads only Phase-5 forward/OOF predictions + Phase-4 matrix
   quality metadata + the pre-OOS Phase-5 calibration decision lock.
2) PHASE6_DECISION_LOCK is written and hashed.
3) Only then are Phase-4 OOS predictions/labels opened exactly once for
   evaluation. OOS cannot alter any Phase-6 rule.

O25/U25 is hard-HOLD and has no threshold/gate research path in this module.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from research.full7_phase5_calibration import (
    _apply_calibrator,
    _calibration_slope_intercept,
    _sha256,
)

PHASE6_VERSION = "FULL7_PHASE6_DECISION_RESEARCH_1.0"

EXPECTED_PHASE4_MANIFEST_SHA256 = "fd4d33b289602e09b7d6ad82565a83c310d444f20f517af687d255792e3f50b5"
EXPECTED_PHASE5_DECISION_LOCK_SHA256 = "cb48662360cd66b4e7daaf84ff47294c04d8bb7983e3da9cceecc30207984a99"
EXPECTED_PHASE5_MANIFEST_SHA256 = "189057b6bc81c0e86b1eb1eb7d131e9592c320dd01f7a4ccaaf9b46ae885ab1a"

MODEL_LOCKS = {
    "1X2": {"model": "GOAL_POISSON_LOCKED", "features": 298, "calibrator": "MULTINOMIAL_LOGIT"},
    "BTTS": {"model": "GOAL_POISSON_LOCKED", "features": 209, "calibrator": "IDENTITY"},
    "O25": {"model": "ENSEMBLE_HGB_POISSON_LOCKED", "features": 240, "status": "HOLD"},
}
O25_HOLD = True

CLASS_INFO = {
    "HOME": {"target": "1X2", "class_index": 0},
    "DRAW": {"target": "1X2", "class_index": 1},
    "AWAY": {"target": "1X2", "class_index": 2},
    "BTTS_YES": {"target": "BTTS", "positive": True},
    "BTTS_NO": {"target": "BTTS", "positive": False},
}

# Candidate grids are fixed in source; they are not learned from OOS.
PLAY_THRESHOLDS_1X2 = tuple(round(0.50 + 0.025 * i, 3) for i in range(13))  # 0.50..0.80
WATCH_THRESHOLDS_1X2 = tuple(round(0.40 + 0.025 * i, 3) for i in range(13))  # 0.40..0.70
PLAY_THRESHOLDS_BTTS = tuple(round(0.55 + 0.025 * i, 3) for i in range(11))  # 0.55..0.80
WATCH_THRESHOLDS_BTTS = tuple(round(0.50 + 0.025 * i, 3) for i in range(9))   # 0.50..0.70
MARGIN_THRESHOLDS_1X2 = (0.0, 0.05, 0.10, 0.15)
BIN_WIDTH = 0.05

# Play support / reliability rules. These are source constants, not OOS tuned.
PLAY_RULE = {
    "min_train_forward_n": 150,
    "min_dev_total_n": 180,
    "min_dev_segment_n": 30,
    "min_dev_segments_with_min_n": 3,
    "max_train_calibration_gap": 0.08,
    "max_aggregate_calibration_gap": 0.05,
    "max_segment_calibration_gap": 0.10,
    "min_segments_calibration_ok": 2,
    "max_wilson95_width": 0.18,
    "min_segments_prediction_inside_wilson95": 2,
    "max_aggregate_slope_deviation": 0.30,  # slope in [0.70, 1.30]
    "max_abs_aggregate_intercept": 0.20,
    "bin_min_total_n": 40,
    "bin_min_segment_n": 8,
    "bin_min_supported_segments": 2,
    "max_overconfidence_segment_gap": 0.10,
}
WATCH_RULE = {
    "min_train_forward_n": 80,
    "min_dev_total_n": 100,
    "min_dev_segment_n": 20,
    "min_dev_segments_with_min_n": 2,
    "max_train_calibration_gap": 0.12,
    "max_aggregate_calibration_gap": 0.08,
    "max_segment_calibration_gap": 0.15,
    "min_segments_calibration_ok": 2,
    "max_wilson95_width": 0.28,
    "min_segments_prediction_inside_wilson95": 1,
    "max_aggregate_slope_deviation": 0.40,
    "max_abs_aggregate_intercept": 0.30,
    "bin_min_total_n": 25,
    "bin_min_segment_n": 5,
    "bin_min_supported_segments": 2,
    "max_overconfidence_segment_gap": 0.16,
}
OOS_PHASE7_READINESS_RULE = {
    "min_play_n_aggregate": 100,
    "min_play_n_fold": 10,
    "min_folds_with_play_support": 2,
    "max_aggregate_calibration_gap": 0.08,
    "max_supported_fold_calibration_gap": 0.15,
    "max_wilson95_width": 0.20,
}
QUALITY_TRAIN_QUANTILE = 0.01
EPS = 1e-8


class Phase6Error(RuntimeError):
    pass


def _json_atomic(path: Path, obj: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def _canonical_sha(obj: Any) -> str:
    raw = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _manifest_hash(path: Path, expected: str, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise Phase6Error(f"{label}_missing")
    actual = _sha256(path)
    if actual != expected:
        raise Phase6Error(f"{label}_hash_mismatch:{actual}")
    return json.loads(path.read_text(encoding="utf-8"))


def _artifact_hash_from_manifest(manifest: Mapping[str, Any], name: str) -> str | None:
    item = (manifest.get("artifacts") or {}).get(name)
    if isinstance(item, Mapping):
        value = item.get("sha256")
        return str(value) if value else None
    return None


def _require_manifest_artifact(root: Path, manifest: Mapping[str, Any], name: str) -> Path:
    path = root / name
    if not path.is_file():
        raise Phase6Error(f"artifact_missing:{name}")
    expected = _artifact_hash_from_manifest(manifest, name)
    if expected is None:
        raise Phase6Error(f"artifact_hash_missing_from_manifest:{name}")
    actual = _sha256(path)
    if actual != expected:
        raise Phase6Error(f"artifact_hash_mismatch:{name}:{actual}")
    return path


def _wilson95(successes: int, n: int) -> dict[str, Any]:
    if n <= 0:
        return {"lower": None, "upper": None, "width": None}
    z = 1.959963984540054
    phat = successes / n
    denom = 1.0 + z * z / n
    center = (phat + z * z / (2.0 * n)) / denom
    half = z * math.sqrt((phat * (1.0 - phat) + z * z / (4.0 * n)) / n) / denom
    lo = max(0.0, center - half)
    hi = min(1.0, center + half)
    return {"lower": lo, "upper": hi, "width": hi - lo}


def _binary_metrics(y: np.ndarray, p: np.ndarray) -> dict[str, Any]:
    y = np.asarray(y, dtype=int)
    p = np.clip(np.asarray(p, dtype=float), 1e-7, 1.0 - 1e-7)
    n = int(len(y))
    if n == 0:
        return {
            "n": 0, "correct": 0, "wrong": 0, "hit_rate": None,
            "mean_probability": None, "observed_rate": None, "calibration_gap": None,
            "logloss": None, "brier": None, "wilson95": _wilson95(0, 0),
        }
    hits = int(y.sum())
    mean_p = float(p.mean())
    rate = float(y.mean())
    ll = float(np.mean(-(y * np.log(p) + (1 - y) * np.log(1.0 - p))))
    br = float(np.mean((p - y) ** 2))
    return {
        "n": n,
        "correct": hits,
        "wrong": n - hits,
        "hit_rate": rate,
        "mean_probability": mean_p,
        "observed_rate": rate,
        "calibration_gap": abs(mean_p - rate),
        "signed_calibration_error_pred_minus_observed": mean_p - rate,
        "logloss": ll,
        "brier": br,
        "wilson95": _wilson95(hits, n),
    }


def _fixed_bins(y: np.ndarray, p: np.ndarray, width: float = BIN_WIDTH) -> list[dict[str, Any]]:
    y = np.asarray(y, dtype=int)
    p = np.asarray(p, dtype=float)
    out = []
    count = int(round(1.0 / width))
    for b in range(count):
        lo = b * width
        hi = min(1.0, (b + 1) * width)
        mask = (p >= lo) & (p < hi if b < count - 1 else p <= hi)
        n = int(mask.sum())
        if n == 0:
            continue
        m = _binary_metrics(y[mask], p[mask])
        out.append({
            "bin": b, "range": [lo, hi], "n": n,
            "mean_probability": m["mean_probability"],
            "observed_rate": m["observed_rate"],
            "absolute_calibration_error": m["calibration_gap"],
        })
    return out


def _zone_metrics(y: np.ndarray, p: np.ndarray, fold: np.ndarray, mask: np.ndarray) -> dict[str, Any]:
    y = np.asarray(y, dtype=int)
    p = np.asarray(p, dtype=float)
    fold = np.asarray(fold).astype(str)
    mask = np.asarray(mask, dtype=bool)
    aggregate = _binary_metrics(y[mask], p[mask])
    segments = {}
    for name in sorted(set(fold.tolist())):
        sm = mask & (fold == name)
        segments[name] = _binary_metrics(y[sm], p[sm])
    return {
        "aggregate": aggregate,
        "segments": segments,
        "reliability_bins_005": _fixed_bins(y[mask], p[mask]),
    }


def _global_calibration(y: np.ndarray, p: np.ndarray) -> dict[str, Any]:
    return _calibration_slope_intercept(np.asarray(y, dtype=int), np.asarray(p, dtype=float))


def _direction_arrays(
    direction: str,
    pred: np.ndarray,
    y: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Return direction probability, binary outcome, preferred-direction mask, margin."""
    if direction in ("HOME", "DRAW", "AWAY"):
        class_index = CLASS_INFO[direction]["class_index"]
        q = np.asarray(pred, dtype=float)
        if q.ndim != 2 or q.shape[1] != 3:
            raise Phase6Error(f"1x2_prediction_shape_invalid:{direction}:{q.shape}")
        probs = q[:, class_index]
        yy = (np.asarray(y, dtype=int) == class_index).astype(int)
        top = np.argmax(q, axis=1)
        preferred = top == class_index
        sorted_q = np.sort(q, axis=1)
        margin = sorted_q[:, -1] - sorted_q[:, -2]
        return probs, yy, preferred, margin
    q = np.asarray(pred, dtype=float).reshape(-1)
    yy_yes = np.asarray(y, dtype=int).reshape(-1)
    if direction == "BTTS_YES":
        return q, yy_yes, q >= 0.5, np.abs(q - 0.5) * 2.0
    if direction == "BTTS_NO":
        return 1.0 - q, 1 - yy_yes, q < 0.5, np.abs(q - 0.5) * 2.0
    raise Phase6Error(f"unknown_direction:{direction}")


def _feature_quality(
    X: np.ndarray,
    row_idx: np.ndarray,
    feature_cols: np.ndarray,
) -> np.ndarray:
    if len(feature_cols) == 0:
        raise Phase6Error("no_locked_feature_columns")
    values = np.asarray(X[np.ix_(np.asarray(row_idx, dtype=int), feature_cols)], dtype=np.float32)
    return np.isfinite(values).mean(axis=1)


def _quality_floor(train_quality: np.ndarray) -> float:
    if len(train_quality) < 100:
        raise Phase6Error("quality_reference_too_small")
    q = float(np.quantile(np.asarray(train_quality, dtype=float), QUALITY_TRAIN_QUANTILE))
    return max(0.0, min(1.0, q))


def _supported_ceiling(
    p: np.ndarray,
    fold: np.ndarray,
    base_mask: np.ndarray,
    threshold: float,
    rule: Mapping[str, Any],
) -> tuple[float | None, list[dict[str, Any]]]:
    """Highest contiguous 0.05 bin supported from threshold upward.

    Once a bin is unsupported, higher bins are considered extrapolation for PLAY/WATCH
    even if a still-higher bin happens to contain a few observations.
    """
    p = np.asarray(p, dtype=float)
    fold = np.asarray(fold).astype(str)
    base_mask = np.asarray(base_mask, dtype=bool)
    start_bin = int(math.floor(threshold / BIN_WIDTH + 1e-12))
    max_bin = int(round(1.0 / BIN_WIDTH)) - 1
    diagnostics = []
    ceiling = None
    for b in range(start_bin, max_bin + 1):
        lo = b * BIN_WIDTH
        hi = min(1.0, (b + 1) * BIN_WIDTH)
        bm = base_mask & (p >= lo) & (p < hi if b < max_bin else p <= hi)
        total = int(bm.sum())
        segment_counts = {name: int((bm & (fold == name)).sum()) for name in sorted(set(fold.tolist()))}
        supported_segments = sum(
            n >= int(rule["bin_min_segment_n"]) for n in segment_counts.values()
        )
        supported = (
            total >= int(rule["bin_min_total_n"])
            and supported_segments >= int(rule["bin_min_supported_segments"])
        )
        diagnostics.append({
            "range": [lo, hi],
            "n": total,
            "segment_n": segment_counts,
            "supported_segments": supported_segments,
            "supported": supported,
        })
        if not supported:
            break
        ceiling = hi
    return ceiling, diagnostics


def _evaluate_candidate(
    direction: str,
    threshold: float,
    margin_threshold: float,
    train: Mapping[str, np.ndarray],
    dev: Mapping[str, np.ndarray],
    quality_floor: float,
    rule: Mapping[str, Any],
) -> dict[str, Any]:
    train_p, train_y, train_pref, train_margin = _direction_arrays(direction, train["pred"], train["y"])
    dev_p, dev_y, dev_pref, dev_margin = _direction_arrays(direction, dev["pred"], dev["y"])

    train_base = (
        train_pref
        & (train["quality"] >= quality_floor)
        & np.isfinite(train_p)
        & (train_p >= threshold)
        & (train_margin >= margin_threshold)
    )
    dev_base = (
        dev_pref
        & (dev["quality"] >= quality_floor)
        & np.isfinite(dev_p)
        & (dev_p >= threshold)
        & (dev_margin >= margin_threshold)
    )

    ceiling, bin_support = _supported_ceiling(
        dev_p, dev["fold"], dev_base, threshold, rule
    )
    if ceiling is None:
        return {
            "direction": direction,
            "threshold": threshold,
            "margin_threshold": margin_threshold,
            "status": "FAIL_CLOSED",
            "reasons": ["PROBABILITY_BIN_SUPPORT_FAIL"],
            "supported_probability_ceiling": None,
            "bin_support": bin_support,
        }

    # Avoid unsupported upper-tail extrapolation.
    train_mask = train_base & (train_p <= ceiling + 1e-12)
    dev_mask = dev_base & (dev_p <= ceiling + 1e-12)
    train_metrics = _zone_metrics(train_y, train_p, train["fold"], train_mask)
    dev_metrics = _zone_metrics(dev_y, dev_p, dev["fold"], dev_mask)
    global_cal = _global_calibration(dev_y, dev_p)

    agg = dev_metrics["aggregate"]
    segments = dev_metrics["segments"]
    seg_min_n = sum(v["n"] >= int(rule["min_dev_segment_n"]) for v in segments.values())
    seg_cal_ok = sum(
        v["n"] >= int(rule["min_dev_segment_n"])
        and v["calibration_gap"] is not None
        and v["calibration_gap"] <= float(rule["max_segment_calibration_gap"])
        for v in segments.values()
    )
    seg_inside_ci = sum(
        v["n"] >= int(rule["min_dev_segment_n"])
        and v["mean_probability"] is not None
        and v["wilson95"]["lower"] is not None
        and v["wilson95"]["lower"] <= v["mean_probability"] <= v["wilson95"]["upper"]
        for v in segments.values()
    )
    severe_overconfidence = [
        name for name, v in segments.items()
        if v["n"] >= int(rule["min_dev_segment_n"])
        and v["signed_calibration_error_pred_minus_observed"] is not None
        and v["signed_calibration_error_pred_minus_observed"] > float(rule["max_overconfidence_segment_gap"])
    ]

    slope = global_cal.get("slope")
    intercept = global_cal.get("intercept")
    checks = {
        "train_forward_support": train_metrics["aggregate"]["n"] >= int(rule["min_train_forward_n"]),
        "dev_total_support": agg["n"] >= int(rule["min_dev_total_n"]),
        "dev_segment_support": seg_min_n >= int(rule["min_dev_segments_with_min_n"]),
        "train_calibration": (
            train_metrics["aggregate"]["calibration_gap"] is not None
            and train_metrics["aggregate"]["calibration_gap"] <= float(rule["max_train_calibration_gap"])
        ),
        "aggregate_calibration": (
            agg["calibration_gap"] is not None
            and agg["calibration_gap"] <= float(rule["max_aggregate_calibration_gap"])
        ),
        "segment_calibration": seg_cal_ok >= int(rule["min_segments_calibration_ok"]),
        "wilson_width": (
            agg["wilson95"]["width"] is not None
            and agg["wilson95"]["width"] <= float(rule["max_wilson95_width"])
        ),
        "predicted_mean_inside_wilson": seg_inside_ci >= int(rule["min_segments_prediction_inside_wilson95"]),
        "global_slope": (
            slope is not None and abs(float(slope) - 1.0) <= float(rule["max_aggregate_slope_deviation"])
        ),
        "global_intercept": (
            intercept is not None and abs(float(intercept)) <= float(rule["max_abs_aggregate_intercept"])
        ),
        "no_severe_overconfidence_segment": not severe_overconfidence,
        "probability_bin_support": ceiling is not None,
    }
    passed = all(checks.values())
    return {
        "direction": direction,
        "threshold": threshold,
        "margin_threshold": margin_threshold,
        "status": "PASS" if passed else "FAIL_CLOSED",
        "checks": checks,
        "failed_checks": sorted(k for k, v in checks.items() if not v),
        "supported_probability_ceiling": ceiling,
        "bin_support": bin_support,
        "train_forward_metrics": train_metrics,
        "development_metrics": dev_metrics,
        "global_development_calibration_slope_intercept": global_cal,
        "development_eligible_prediction_n": int(dev_pref.sum()),
        "development_zone_coverage_all_rows": float(dev_mask.mean()),
        "development_zone_coverage_preferred_direction": (
            float(dev_mask.sum() / dev_pref.sum()) if int(dev_pref.sum()) else 0.0
        ),
        "severe_overconfidence_segments": severe_overconfidence,
    }


def _candidate_grid(direction: str, tier: str) -> tuple[Sequence[float], Sequence[float]]:
    if direction in ("HOME", "DRAW", "AWAY"):
        thresholds = PLAY_THRESHOLDS_1X2 if tier == "PLAY" else WATCH_THRESHOLDS_1X2
        return thresholds, MARGIN_THRESHOLDS_1X2
    thresholds = PLAY_THRESHOLDS_BTTS if tier == "PLAY" else WATCH_THRESHOLDS_BTTS
    return thresholds, (0.0,)


def _choose_candidate(
    direction: str,
    tier: str,
    train: Mapping[str, np.ndarray],
    dev: Mapping[str, np.ndarray],
    quality_floor: float,
) -> dict[str, Any]:
    rule = PLAY_RULE if tier == "PLAY" else WATCH_RULE
    thresholds, margins = _candidate_grid(direction, tier)
    candidates = []
    for threshold in thresholds:
        for margin in margins:
            candidates.append(
                _evaluate_candidate(direction, threshold, margin, train, dev, quality_floor, rule)
            )
    passing = [c for c in candidates if c["status"] == "PASS"]
    if not passing:
        return {
            "tier": tier,
            "direction": direction,
            "selected": None,
            "candidate_count": len(candidates),
            "passing_count": 0,
            "candidates": candidates,
        }

    # No hit-rate chasing:
    # 1) prefer no margin complexity where a robust rule exists,
    # 2) maximize robust coverage,
    # 3) lower calibration gap,
    # 4) lower logloss.
    no_margin = [c for c in passing if abs(float(c["margin_threshold"])) < 1e-12]
    pool = no_margin if no_margin else passing
    pool.sort(
        key=lambda c: (
            -float(c["development_zone_coverage_all_rows"]),
            float(c["development_metrics"]["aggregate"]["calibration_gap"]),
            float(c["development_metrics"]["aggregate"]["logloss"]),
            float(c["threshold"]),
            float(c["margin_threshold"]),
        )
    )
    selected = pool[0]
    return {
        "tier": tier,
        "direction": direction,
        "selected": selected,
        "candidate_count": len(candidates),
        "passing_count": len(passing),
        "selection_principle": (
            "NO_MARGIN_IF_ROBUST_THEN_MAX_COVERAGE_THEN_CALIBRATION_THEN_LOGLOSS;"
            "HIT_RATE_IS_NOT_A_RANKING_TERM"
        ),
        "candidates": candidates,
    }


def _prepare_pre_oos(
    phase4: Path,
    phase5: Path,
) -> tuple[dict[str, Any], dict[str, Any], np.ndarray, dict[str, Any]]:
    """Read PRE-OOS-only artifacts. OOS prediction/label files are forbidden here."""
    p4_manifest = _manifest_hash(
        phase4 / "PHASE4_MANIFEST.json",
        EXPECTED_PHASE4_MANIFEST_SHA256,
        "phase4_manifest",
    )
    p5_manifest = _manifest_hash(
        phase5 / "PHASE5_MANIFEST.json",
        EXPECTED_PHASE5_MANIFEST_SHA256,
        "phase5_manifest",
    )

    lock_path = phase5 / "PHASE5_CALIBRATION_DECISION_LOCK.json"
    if _sha256(lock_path) != EXPECTED_PHASE5_DECISION_LOCK_SHA256:
        raise Phase6Error("phase5_calibration_decision_lock_hash_mismatch")
    phase5_lock = json.loads(lock_path.read_text(encoding="utf-8"))
    if phase5_lock.get("oos_used_for_fit") is not False or phase5_lock.get("oos_used_for_selection") is not False:
        raise Phase6Error("phase5_lock_oos_contamination_flag")

    # Hard readiness assertions from frozen acceptance.
    if phase5_lock["targets"]["1X2"]["selected_calibrator"] != "MULTINOMIAL_LOGIT":
        raise Phase6Error("1x2_calibrator_lock_changed")
    if phase5_lock["targets"]["BTTS"]["selected_calibrator"] != "IDENTITY":
        raise Phase6Error("btts_calibrator_lock_changed")

    preoos_paths = {}
    for target in ("1X2", "BTTS"):
        name = f"PHASE5_PREOOS_{target}.npz"
        preoos_paths[target] = _require_manifest_artifact(phase5, p5_manifest, name)

    matrix_path = _require_manifest_artifact(phase4, p4_manifest, "PHASE4_MATRIX.npy")
    metadata_path = _require_manifest_artifact(phase4, p4_manifest, "PHASE4_MATRIX_METADATA.json")
    ablation_path = _require_manifest_artifact(
        phase4, p4_manifest, "PHASE4_GROUP_ABLATIONS_DEVELOPMENT.json"
    )

    X = np.load(matrix_path, mmap_mode="r")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    ablation = json.loads(ablation_path.read_text(encoding="utf-8"))
    feature_index = {name: i for i, name in enumerate(metadata["feature_names"])}

    data = {}
    for target in ("1X2", "BTTS"):
        npz = np.load(preoos_paths[target])
        locked_features = list(ablation["targets"][target]["locked_features"])
        if len(locked_features) != MODEL_LOCKS[target]["features"]:
            raise Phase6Error(f"locked_feature_count_changed:{target}:{len(locked_features)}")
        cols = np.asarray([feature_index[n] for n in locked_features], dtype=int)

        train_idx = np.asarray(npz["train_idx"], dtype=int)
        dev_idx = np.asarray(npz["dev_idx"], dtype=int)
        train_pred_raw = np.asarray(npz["train_pred"], dtype=float)
        dev_pred_raw = np.asarray(npz["dev_pred"], dtype=float)
        params = phase5_lock["targets"][target]["final_parameters"]
        train_pred = _apply_calibrator(params, target, train_pred_raw)
        dev_pred = _apply_calibrator(params, target, dev_pred_raw)

        train_quality = _feature_quality(X, train_idx, cols)
        dev_quality = _feature_quality(X, dev_idx, cols)
        qfloor = _quality_floor(train_quality)

        data[target] = {
            "train": {
                "idx": train_idx,
                "y": np.asarray(npz["train_y"], dtype=int),
                "pred": train_pred,
                "fold": np.asarray(npz["train_fold"]).astype(str),
                "quality": train_quality,
            },
            "dev": {
                "idx": dev_idx,
                "y": np.asarray(npz["dev_y"], dtype=int),
                "pred": dev_pred,
                "fold": np.asarray(npz["dev_fold"]).astype(str),
                "quality": dev_quality,
            },
            "quality_floor": qfloor,
            "locked_feature_count": len(locked_features),
            "preoos_file_sha256": _sha256(preoos_paths[target]),
        }

    provenance = {
        "phase4_manifest_sha256": EXPECTED_PHASE4_MANIFEST_SHA256,
        "phase5_manifest_sha256": EXPECTED_PHASE5_MANIFEST_SHA256,
        "phase5_calibration_decision_lock_sha256": EXPECTED_PHASE5_DECISION_LOCK_SHA256,
        "oos_artifacts_opened_before_phase6_lock": False,
    }
    return data, phase5_lock, X, provenance


def _research_rules(phase4: Path, phase5: Path, stage: Path) -> dict[str, Any]:
    data, phase5_lock, _X, provenance = _prepare_pre_oos(phase4, phase5)
    research = {
        "version": "FULL7_PHASE6_PREOOS_DECISION_RESEARCH_1.0",
        "OOS_USED_FOR_THRESHOLD_SELECTION": False,
        "OOS_USED_FOR_GATE_SELECTION": False,
        "O25_STATUS": "HOLD",
        "O25_PHASE6_READY": False,
        "rules": {"PLAY": PLAY_RULE, "WATCH": WATCH_RULE},
        "candidate_grids": {
            "1X2_PLAY": PLAY_THRESHOLDS_1X2,
            "1X2_WATCH": WATCH_THRESHOLDS_1X2,
            "BTTS_PLAY": PLAY_THRESHOLDS_BTTS,
            "BTTS_WATCH": WATCH_THRESHOLDS_BTTS,
            "1X2_MARGIN": MARGIN_THRESHOLDS_1X2,
        },
        "directions": {},
        "provenance": provenance,
    }
    for direction in ("HOME", "DRAW", "AWAY", "BTTS_YES", "BTTS_NO"):
        target = CLASS_INFO[direction]["target"]
        target_data = data[target]
        play = _choose_candidate(
            direction, "PLAY", target_data["train"], target_data["dev"], target_data["quality_floor"]
        )
        watch = _choose_candidate(
            direction, "WATCH", target_data["train"], target_data["dev"], target_data["quality_floor"]
        )
        research["directions"][direction] = {
            "target": target,
            "model_lock": MODEL_LOCKS[target],
            "quality_floor_train_q01": target_data["quality_floor"],
            "locked_feature_count": target_data["locked_feature_count"],
            "PLAY_RESEARCH": play,
            "WATCH_RESEARCH": watch,
            "PLAY_AVAILABLE": play["selected"] is not None,
            "WATCH_AVAILABLE": watch["selected"] is not None,
        }

    _json_atomic(stage / "PHASE6_PREOOS_DECISION_RESEARCH.json", research)
    return research


def _compact_selected(selected: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if selected is None:
        return None
    return {
        "threshold": selected["threshold"],
        "margin_threshold": selected["margin_threshold"],
        "supported_probability_ceiling": selected["supported_probability_ceiling"],
        "development_metrics": selected["development_metrics"],
        "train_forward_metrics": selected["train_forward_metrics"],
        "global_development_calibration_slope_intercept": selected[
            "global_development_calibration_slope_intercept"
        ],
        "bin_support": selected["bin_support"],
        "checks": selected["checks"],
    }


def _build_phase6_lock(
    stage: Path,
    research: Mapping[str, Any],
) -> tuple[dict[str, Any], str]:
    lock_path = stage / "PHASE6_DECISION_LOCK.json"
    sha_path = stage / "PHASE6_DECISION_LOCK.sha256"
    if lock_path.exists() or sha_path.exists():
        raise Phase6Error("phase6_lock_already_exists_fail_closed")

    directions = {}
    for direction, obj in research["directions"].items():
        play = obj["PLAY_RESEARCH"]["selected"]
        watch = obj["WATCH_RESEARCH"]["selected"]
        directions[direction] = {
            "target": obj["target"],
            "model": MODEL_LOCKS[obj["target"]]["model"],
            "calibrator": MODEL_LOCKS[obj["target"]]["calibrator"],
            "prediction_column": (
                {"HOME": "p_home_calibrated", "DRAW": "p_draw_calibrated", "AWAY": "p_away_calibrated"}[direction]
                if direction in ("HOME", "DRAW", "AWAY")
                else ("p_btts_yes_identity" if direction == "BTTS_YES" else "1_minus_p_btts_yes_identity")
            ),
            "PLAY": _compact_selected(play),
            "WATCH": _compact_selected(watch),
            "PLAY_AVAILABLE": play is not None,
            "WATCH_AVAILABLE": watch is not None,
            "AUSLASSEN_RULES": [
                "NOT_MODEL_PREFERRED_DIRECTION",
                "PROBABILITY_BELOW_WATCH_ZONE",
                "ROW_FEATURE_COVERAGE_BELOW_PREOOS_TRAIN_Q01",
                "PROBABILITY_OUTSIDE_SUPPORTED_PREOOS_RANGE",
                "PREDICTION_NOT_FINITE",
                "MODEL_INPUT_INTEGRITY_FAIL",
                "PREDICTION_COHERENCE_FAIL",
                "OTHER_FAIL_CLOSED",
            ],
            "quality_floor_train_q01": obj["quality_floor_train_q01"],
        }

    lock = {
        "lock_version": "PHASE6_DECISION_LOCK_1.0",
        "phase5_calibration_decision_lock_sha256": EXPECTED_PHASE5_DECISION_LOCK_SHA256,
        "phase5_manifest_sha256": EXPECTED_PHASE5_MANIFEST_SHA256,
        "phase4_manifest_sha256": EXPECTED_PHASE4_MANIFEST_SHA256,
        "market_readiness": {
            "1X2": {"status": "READY", **MODEL_LOCKS["1X2"]},
            "BTTS": {"status": "READY", **MODEL_LOCKS["BTTS"]},
            "O25": {"status": "HOLD", **MODEL_LOCKS["O25"]},
        },
        "O25_HOLD": True,
        "O25_PHASE6_READY": False,
        "O25_REASON": (
            "PRE-OOS Isotonic calibrator violated final Phase-5 calibration compliance; "
            "no alternative calibrator may be selected after OOS."
        ),
        "directions": directions,
        "minimum_support": {"PLAY": PLAY_RULE, "WATCH": WATCH_RULE},
        "reliability_requirements": {
            "fixed_probability_bin_width": BIN_WIDTH,
            "calibration_gap_limits": {
                "PLAY": PLAY_RULE["max_aggregate_calibration_gap"],
                "WATCH": WATCH_RULE["max_aggregate_calibration_gap"],
            },
            "slope_intercept_rules": {
                "PLAY": {
                    "slope_range": [
                        1.0 - PLAY_RULE["max_aggregate_slope_deviation"],
                        1.0 + PLAY_RULE["max_aggregate_slope_deviation"],
                    ],
                    "max_abs_intercept": PLAY_RULE["max_abs_aggregate_intercept"],
                },
                "WATCH": {
                    "slope_range": [
                        1.0 - WATCH_RULE["max_aggregate_slope_deviation"],
                        1.0 + WATCH_RULE["max_aggregate_slope_deviation"],
                    ],
                    "max_abs_intercept": WATCH_RULE["max_abs_aggregate_intercept"],
                },
            },
        },
        "temporal_robustness_rule": (
            "PLAY requires support in all three DEV segments, calibration support in >=2/3, "
            "and no severe overconfidence segment; WATCH requires support/calibration in >=2/3."
        ),
        "fail_closed_rules": [
            "NO_OOS_IN_THRESHOLD_OR_GATE_SELECTION",
            "NO_O25_THRESHOLD_RESEARCH",
            "NO_V3_1_THRESHOLD_CARRYOVER",
            "NO_ODDS_OR_VALUE",
            "NO_POST_LOCK_RULE_CHANGE",
            "NO_UNSUPPORTED_HIGH_PROBABILITY_EXTRAPOLATION",
            "NO_PLAY_IF_EMPIRICAL_SUPPORT_OR_CALIBRATION_OR_INTEGRITY_GATE_FAILS",
        ],
        "historical_reference_only": {
            "V3_1_1X2_PLAY_THRESHOLD": 0.71,
            "V3_1_BTTS_PLAY_THRESHOLD": 0.605,
            "used_for_full7_rule_selection": False,
        },
        "OOS_USED_FOR_THRESHOLD_SELECTION": False,
        "OOS_USED_FOR_GATE_SELECTION": False,
        "phase7_readiness_evaluation_rule": OOS_PHASE7_READINESS_RULE,
    }
    lock["rules_payload_sha256"] = _canonical_sha(lock)
    _json_atomic(lock_path, lock)
    sha = _sha256(lock_path)
    sha_path.write_text(sha + "\n", encoding="ascii")
    print("PHASE6_DECISION_LOCK_SHA256=" + sha, flush=True)
    return lock, sha


def _load_post_lock_oos(
    phase4: Path,
    phase5: Path,
    lock_sha: str,
) -> tuple[dict[str, Any], np.ndarray, dict[str, Any], Mapping[str, Any]]:
    """OOS barrier: this function must never be called before PHASE6 lock exists."""
    lock_path = phase5.parent / "phase6" / "PHASE6_DECISION_LOCK.json"
    # When running in stage the caller verifies its own stage lock; this path check
    # is only a defense-in-depth hint and is not relied on for correctness.

    p4_manifest = _manifest_hash(
        phase4 / "PHASE4_MANIFEST.json",
        EXPECTED_PHASE4_MANIFEST_SHA256,
        "phase4_manifest_post_lock",
    )
    labels_path = _require_manifest_artifact(phase4, p4_manifest, "PHASE4_LABELS.npz")
    pred_path = _require_manifest_artifact(phase4, p4_manifest, "PHASE4_LOCKED_OOS_PREDICTIONS.npz")
    splits_path = _require_manifest_artifact(phase4, p4_manifest, "PHASE4_SPLITS.json")
    matrix_path = _require_manifest_artifact(phase4, p4_manifest, "PHASE4_MATRIX.npy")
    metadata_path = _require_manifest_artifact(phase4, p4_manifest, "PHASE4_MATRIX_METADATA.json")
    ablation_path = _require_manifest_artifact(phase4, p4_manifest, "PHASE4_GROUP_ABLATIONS_DEVELOPMENT.json")

    labels_npz = np.load(labels_path)
    labels = {k: labels_npz[k] for k in ("match_ids", "dates", "y1", "yb", "yo", "yh", "ya")}
    preds = np.load(pred_path)
    splits = json.loads(splits_path.read_text(encoding="utf-8"))
    X = np.load(matrix_path, mmap_mode="r")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    ablation = json.loads(ablation_path.read_text(encoding="utf-8"))

    phase5_lock = json.loads((phase5 / "PHASE5_CALIBRATION_DECISION_LOCK.json").read_text(encoding="utf-8"))
    return labels, X, {"preds": preds, "splits": splits, "metadata": metadata, "ablation": ablation}, phase5_lock


def _oos_indices(labels: Mapping[str, np.ndarray], splits: Mapping[str, Any]) -> dict[str, np.ndarray]:
    # Exact frozen Phase-4 split schema:
    # splits["oos_folds"] = [{"fold": 1, "test_start_date": ..., "test_end_date": ...}, ...]
    dates = np.asarray(labels["dates"]).astype(str)
    rows = splits.get("oos_folds")
    if not isinstance(rows, list) or len(rows) != 3:
        raise Phase6Error("oos_fold_schema_changed")
    out = {}
    for meta in rows:
        try:
            fold_num = int(meta["fold"])
            start = str(meta["test_start_date"])
            end = str(meta["test_end_date"])
        except Exception as exc:
            raise Phase6Error(f"oos_fold_schema_invalid:{exc}") from exc
        name = f"OOS{fold_num}"
        mask = (dates >= start) & (dates <= end)
        idx = np.where(mask)[0]
        if len(idx) == 0:
            raise Phase6Error(f"oos_split_empty:{name}")
        out[name] = idx
    if set(out) != {"OOS1", "OOS2", "OOS3"}:
        raise Phase6Error(f"oos_fold_labels_changed:{sorted(out)}")
    return out


def _rule_for_direction(lock: Mapping[str, Any], direction: str) -> Mapping[str, Any]:
    return lock["directions"][direction]


def _classify_rows(
    direction: str,
    pred: np.ndarray,
    y: np.ndarray,
    quality: np.ndarray,
    rule: Mapping[str, Any],
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    p, yy, preferred, margin = _direction_arrays(direction, pred, y)
    n = len(p)
    decision = np.full(n, "AUSLASSEN", dtype="U12")
    reason = np.full(n, "LOW_PROBABILITY_OR_NOT_PREFERRED", dtype="U64")

    finite = np.isfinite(p)
    quality_ok = np.asarray(quality, dtype=float) >= float(rule["quality_floor_train_q01"])
    coherent = finite & (p >= 0.0) & (p <= 1.0)
    base_ok = preferred & finite & quality_ok & coherent
    reason[preferred & ~finite] = "PREDICTION_NOT_FINITE"
    reason[preferred & finite & ~quality_ok] = "DATA_QUALITY_FAIL"
    reason[preferred & finite & quality_ok & ~coherent] = "COHERENCE_FAIL"

    watch = rule.get("WATCH")
    play = rule.get("PLAY")
    if watch is not None:
        wm = (
            base_ok
            & (p >= float(watch["threshold"]))
            & (margin >= float(watch["margin_threshold"]))
            & (p <= float(watch["supported_probability_ceiling"]) + 1e-12)
        )
        decision[wm] = "BEOBACHTEN"
        reason[wm] = "WATCH_GATES_PASS"
        extreme = (
            base_ok
            & (p >= float(watch["threshold"]))
            & (p > float(watch["supported_probability_ceiling"]) + 1e-12)
        )
        reason[extreme] = "EXTREME_EXTRAPOLATION_GUARD"

    if play is not None:
        pm = (
            base_ok
            & (p >= float(play["threshold"]))
            & (margin >= float(play["margin_threshold"]))
            & (p <= float(play["supported_probability_ceiling"]) + 1e-12)
        )
        decision[pm] = "SPIELEN"
        reason[pm] = "ALL_PLAY_GATES_PASS"

    return p, yy, decision, reason


def _decision_eval(
    direction: str,
    p: np.ndarray,
    y: np.ndarray,
    decision: np.ndarray,
    preferred: np.ndarray,
) -> dict[str, Any]:
    play = decision == "SPIELEN"
    watch = decision == "BEOBACHTEN"
    skip = decision == "AUSLASSEN"
    play_metrics = _binary_metrics(y[play], p[play])
    pred_n = int(preferred.sum())
    return {
        "predictions": pred_n,
        "SPIELEN": int(play.sum()),
        "BEOBACHTEN": int(watch.sum()),
        "AUSLASSEN": int(skip.sum()),
        "SPIELEN_COVERAGE_ALL_MATCHES": float(play.mean()),
        "SPIELEN_COVERAGE_PREDICTIONS": float(play.sum() / pred_n) if pred_n else 0.0,
        "SPIELEN_METRICS": play_metrics,
    }


def _phase7_direction_ready(folds: Mapping[str, Any], aggregate: Mapping[str, Any]) -> bool:
    rule = OOS_PHASE7_READINESS_RULE
    agg = aggregate["SPIELEN_METRICS"]
    if agg["n"] < rule["min_play_n_aggregate"]:
        return False
    if agg["calibration_gap"] is None or agg["calibration_gap"] > rule["max_aggregate_calibration_gap"]:
        return False
    if agg["wilson95"]["width"] is None or agg["wilson95"]["width"] > rule["max_wilson95_width"]:
        return False
    supported = 0
    for obj in folds.values():
        m = obj["SPIELEN_METRICS"]
        if m["n"] >= rule["min_play_n_fold"]:
            if m["calibration_gap"] is None or m["calibration_gap"] > rule["max_supported_fold_calibration_gap"]:
                continue
            supported += 1
    return supported >= rule["min_folds_with_play_support"]


def _evaluate_oos_once(
    stage: Path,
    phase4: Path,
    phase5: Path,
    lock: Mapping[str, Any],
    lock_sha: str,
) -> dict[str, Any]:
    # Mandatory barrier check immediately before opening any OOS artifact.
    lock_path = stage / "PHASE6_DECISION_LOCK.json"
    if not lock_path.is_file() or _sha256(lock_path) != lock_sha:
        raise Phase6Error("phase6_lock_not_persisted_before_oos")

    labels, X, ctx, phase5_lock = _load_post_lock_oos(phase4, phase5, lock_sha)
    folds = _oos_indices(labels, ctx["splits"])
    all_oos = np.concatenate([folds["OOS1"], folds["OOS2"], folds["OOS3"]])

    feature_index = {name: i for i, name in enumerate(ctx["metadata"]["feature_names"])}
    target_cols = {}
    for target in ("1X2", "BTTS"):
        features = ctx["ablation"]["targets"][target]["locked_features"]
        target_cols[target] = np.asarray([feature_index[n] for n in features], dtype=int)

    raw_1x2 = np.asarray(ctx["preds"]["1X2_pred"], dtype=float)
    raw_btts = np.asarray(ctx["preds"]["BTTS_pred"], dtype=float)
    cal_1x2 = np.full_like(raw_1x2, np.nan, dtype=float)
    cal_btts = np.full_like(raw_btts, np.nan, dtype=float)
    cal_1x2[all_oos] = _apply_calibrator(
        phase5_lock["targets"]["1X2"]["final_parameters"], "1X2", raw_1x2[all_oos]
    )
    cal_btts[all_oos] = _apply_calibrator(
        phase5_lock["targets"]["BTTS"]["final_parameters"], "BTTS", raw_btts[all_oos]
    )

    results = {
        "version": "FULL7_PHASE6_LOCKED_OOS_EVALUATION_1.0",
        "PHASE6_DECISION_LOCK_SHA256": lock_sha,
        "OOS_USED_FOR_THRESHOLD_SELECTION": False,
        "OOS_USED_FOR_GATE_SELECTION": False,
        "directions": {},
    }

    for direction in ("HOME", "DRAW", "AWAY", "BTTS_YES", "BTTS_NO"):
        target = CLASS_INFO[direction]["target"]
        pred_all = cal_1x2 if target == "1X2" else cal_btts
        y_all = labels["y1"] if target == "1X2" else labels["yb"]
        rule = _rule_for_direction(lock, direction)

        fold_results = {}
        for fold_name, idx in folds.items():
            quality = _feature_quality(X, idx, target_cols[target])
            p, yy, preferred, _margin = _direction_arrays(direction, pred_all[idx], y_all[idx])
            p2, yy2, decision, reasons = _classify_rows(
                direction, pred_all[idx], y_all[idx], quality, rule
            )
            obj = _decision_eval(direction, p2, yy2, decision, preferred)
            obj["reason_counts"] = {
                str(k): int(v) for k, v in zip(*np.unique(reasons, return_counts=True))
            }
            fold_results[fold_name] = obj

        quality = _feature_quality(X, all_oos, target_cols[target])
        p, yy, preferred, _margin = _direction_arrays(direction, pred_all[all_oos], y_all[all_oos])
        p2, yy2, decision, reasons = _classify_rows(
            direction, pred_all[all_oos], y_all[all_oos], quality, rule
        )
        aggregate = _decision_eval(direction, p2, yy2, decision, preferred)
        aggregate["reason_counts"] = {
            str(k): int(v) for k, v in zip(*np.unique(reasons, return_counts=True))
        }
        phase7_ready = bool(rule.get("PLAY_AVAILABLE")) and _phase7_direction_ready(fold_results, aggregate)
        results["directions"][direction] = {
            "OOS1": fold_results["OOS1"],
            "OOS2": fold_results["OOS2"],
            "OOS3": fold_results["OOS3"],
            "ALL": aggregate,
            "TEMPORAL_STABILITY": {
                "play_hit_rates": {
                    k: v["SPIELEN_METRICS"]["hit_rate"] for k, v in fold_results.items()
                },
                "play_calibration_gaps": {
                    k: v["SPIELEN_METRICS"]["calibration_gap"] for k, v in fold_results.items()
                },
            },
            "PHASE7_READY": phase7_ready,
        }
    return results


def _market_status(oos: Mapping[str, Any], directions: Sequence[str]) -> tuple[str, bool]:
    play_rules = [oos["directions"][d]["ALL"]["SPIELEN"] for d in directions]
    ready = [oos["directions"][d]["PHASE7_READY"] for d in directions]
    if any(n > 0 for n in play_rules):
        return "PASS", any(ready)
    return "FAIL", False


def _write_final_report(
    stage: Path,
    research: Mapping[str, Any],
    lock: Mapping[str, Any],
    lock_sha: str,
    oos: Mapping[str, Any],
) -> dict[str, Any]:
    status_1x2, ready_1x2 = _market_status(oos, ("HOME", "DRAW", "AWAY"))
    status_btts, ready_btts = _market_status(oos, ("BTTS_YES", "BTTS_NO"))

    report = {
        "PHASE6_DECISION_RESEARCH": "PARTIAL_PASS",
        "status": "COMPLETE",
        "PHASE6_DECISION_LOCK_SHA256": lock_sha,
        "OOS_USED_FOR_THRESHOLD_SELECTION": False,
        "OOS_USED_FOR_GATE_SELECTION": False,
        "1X2_PHASE6_STATUS": status_1x2,
        "BTTS_PHASE6_STATUS": status_btts,
        "O25_PHASE6_STATUS": "HOLD",
        "O25_STATUS": "HOLD",
        "O25_PHASE6_READY": False,
        "PHASE7_READY": {
            "1X2": ready_1x2,
            "BTTS": ready_btts,
            "O25": False,
            "directions": {
                d: oos["directions"][d]["PHASE7_READY"]
                for d in ("HOME", "DRAW", "AWAY", "BTTS_YES", "BTTS_NO")
            },
        },
        "MARKET_READINESS_LOCK": {
            "1X2": MODEL_LOCKS["1X2"],
            "BTTS": MODEL_LOCKS["BTTS"],
            "O25": MODEL_LOCKS["O25"],
        },
        "PREOOS_DECISION_RESEARCH": research,
        "DECISION_LOCK": lock,
        "LOCKED_OOS_EVALUATION": oos,
        "V3_1_THRESHOLDS": {
            "status": "HISTORICAL_REFERENCE_ONLY",
            "1X2_PLAY": 0.71,
            "BTTS_PLAY": 0.605,
            "used_for_selection": False,
        },
        "ODDS_USED": False,
        "PRODUCTION_CHANGED": False,
        "MAIN_CHANGED": False,
        "O25_REPAIRED_IN_PHASE6": False,
        "next_action": "STOP_FOR_STEERING_REVIEW",
    }
    _json_atomic(stage / "PHASE6_DECISION_RESEARCH_REPORT.json", report)

    lines = [
        "FULL-7 PHASE 6 DECISION RESEARCH",
        "PHASE6_DECISION_RESEARCH = PARTIAL_PASS",
        f"PHASE6_DECISION_LOCK_SHA256 = {lock_sha}",
        f"1X2_PHASE6_STATUS = {status_1x2}",
        f"BTTS_PHASE6_STATUS = {status_btts}",
        "O25_PHASE6_STATUS = HOLD",
        "OOS_USED_FOR_THRESHOLD_SELECTION = false",
        "OOS_USED_FOR_GATE_SELECTION = false",
        "",
    ]
    for d in ("HOME", "DRAW", "AWAY", "BTTS_YES", "BTTS_NO"):
        rule = lock["directions"][d]
        ev = oos["directions"][d]["ALL"]
        lines += [
            f"[{d}]",
            f"PLAY_AVAILABLE_PREOOS = {str(rule['PLAY_AVAILABLE']).lower()}",
            f"PLAY_THRESHOLD = {None if rule['PLAY'] is None else rule['PLAY']['threshold']}",
            f"WATCH_THRESHOLD = {None if rule['WATCH'] is None else rule['WATCH']['threshold']}",
            f"OOS_PLAY_N = {ev['SPIELEN']}",
            f"OOS_PLAY_HIT_RATE = {ev['SPIELEN_METRICS']['hit_rate']}",
            f"OOS_PLAY_CALIBRATION_GAP = {ev['SPIELEN_METRICS']['calibration_gap']}",
            f"PHASE7_READY = {str(oos['directions'][d]['PHASE7_READY']).lower()}",
            "",
        ]
    (stage / "PHASE6_DECISION_RESEARCH_REPORT.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report


def _write_manifest(stage: Path) -> dict[str, Any]:
    artifacts = {}
    for path in sorted(p for p in stage.iterdir() if p.is_file() and p.name != "PHASE6_MANIFEST.json"):
        artifacts[path.name] = {"bytes": path.stat().st_size, "sha256": _sha256(path)}
    manifest = {"schema": "FULL7_PHASE6_MANIFEST_1.0", "artifacts": artifacts}
    _json_atomic(stage / "PHASE6_MANIFEST.json", manifest)
    return manifest


def run_phase6(root: Path) -> dict[str, Any]:
    root = Path(root)
    phase4 = root / "phase4"
    phase5 = root / "phase5"
    output = root / "phase6"
    if output.exists():
        raise Phase6Error("phase6_output_exists_fail_closed")

    stage = root / ".phase6.stage"
    if stage.exists():
        raise Phase6Error("phase6_stage_exists_requires_manual_integrity_inspection")
    stage.mkdir(parents=False, exist_ok=False)

    # PRE-OOS only. No Phase-4 OOS prediction or label file may be opened here.
    research = _research_rules(phase4, phase5, stage)

    # Immutable decision lock is persisted BEFORE OOS artifacts are opened.
    lock, lock_sha = _build_phase6_lock(stage, research)

    # Exactly one locked OOS application.
    oos = _evaluate_oos_once(stage, phase4, phase5, lock, lock_sha)
    _json_atomic(stage / "PHASE6_LOCKED_OOS_EVALUATION.json", oos)

    report = _write_final_report(stage, research, lock, lock_sha, oos)
    _write_manifest(stage)

    stage.rename(output)
    print("PHASE6_DECISION_RESEARCH=PARTIAL_PASS", flush=True)
    print("PHASE6_DECISION_LOCK_SHA256=" + lock_sha, flush=True)
    print("PHASE6_MANIFEST_SHA256=" + _sha256(output / "PHASE6_MANIFEST.json"), flush=True)
    print("PHASE6_STOP_BEFORE_PRODUCTION=true", flush=True)
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root",
        default="/var/data/full7/audit/full7_phase2_phase3",
        help="Frozen audit artifact root containing phase4/ and phase5/",
    )
    args = parser.parse_args()
    run_phase6(Path(args.root))


if __name__ == "__main__":
    main()
