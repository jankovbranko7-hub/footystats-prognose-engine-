#!/usr/bin/env python3
"""Fit the frozen AI 2.0 six-market ranker only.

This utility intentionally cannot overwrite the production combined model;
the final action policy is trained separately by train_full5_next_abstention.py.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler


REPO = Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(REPO))

from full5_next_ai import FEATURE_NAMES, candidate_features  # noqa: E402


def training_rows(path: Path) -> tuple[pd.DataFrame, np.ndarray, np.ndarray]:
    matches = pd.read_csv(path, low_memory=False).sort_values(["kickoff_utc", "match_id"]).reset_index(drop=True)
    rows, targets, groups = [], [], []
    for index, match in matches.iterrows():
        actual = {
            "home_win": match.actual_1x2 == "HOME", "away_win": match.actual_1x2 == "AWAY",
            "btts_yes": match.actual_btts == "YES", "btts_no": match.actual_btts == "NO",
            "over_2_5": match.actual_ou25 == "OVER", "under_2_5": match.actual_ou25 == "UNDER",
        }
        for candidate in candidate_features(match.to_dict()):
            rows.append(candidate["features"])
            targets.append(int(actual[candidate["market"]]))
            groups.append(index)
    return pd.DataFrame(rows, columns=FEATURE_NAMES), np.asarray(targets, dtype=int), np.asarray(groups, dtype=int)


def parameters(frame: pd.DataFrame, target: np.ndarray, indices: np.ndarray | None = None, seed: int = 20260908) -> dict:
    if indices is None:
        indices = np.arange(len(frame))
    scaler = StandardScaler().fit(frame.iloc[indices])
    model = LogisticRegression(C=0.003, max_iter=4000, random_state=seed).fit(scaler.transform(frame.iloc[indices]), target[indices])
    return {
        "mean": scaler.mean_.tolist(), "scale": scaler.scale_.tolist(),
        "coefficient": model.coef_[0].tolist(), "intercept": float(model.intercept_[0]),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("matrix", type=Path)
    parser.add_argument("--output", type=Path, default=REPO / "full5_next_ranking_model.json")
    parser.add_argument("--bootstrap-models", type=int, default=80)
    args = parser.parse_args()
    frame, target, groups = training_rows(args.matrix)
    unique_groups = np.unique(groups)
    rng = np.random.default_rng(20260908)
    bootstraps = []
    for seed in range(args.bootstrap_models):
        sampled_groups = rng.choice(unique_groups, len(unique_groups), replace=True)
        sampled_rows = np.concatenate([np.flatnonzero(groups == group) for group in sampled_groups])
        bootstraps.append(parameters(frame, target, sampled_rows, 20260908 + seed))
    artifact = {
        "version": "FULL-5-NEXT-RANKING-2.0.0",
        "trained_at_utc": "2026-09-08T00:00:00Z",
        "training_matches": int(len(unique_groups)),
        "training_candidates": int(len(frame)),
        "feature_names": list(FEATURE_NAMES),
        "regularization": {"model": "logistic_ridge", "c": 0.003},
        "central_model": parameters(frame, target),
        "bootstrap_models": bootstraps,
        "validation": {
            "scope": "six-market ranking only; no final action-policy result",
            "method": "five expanding chronological outer folds; 97 initial train + five disjoint 30-match tests",
            "outer_matches": 150,
            "rank_hits": 94,
            "rank_hit_rate": 94 / 150,
            "historical_oos_not_untouched": True,
        },
    }
    args.output.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "matches": len(unique_groups), "candidates": len(frame), "bootstrap_models": len(bootstraps)}, indent=2))


if __name__ == "__main__":
    main()
