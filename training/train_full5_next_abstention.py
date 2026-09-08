#!/usr/bin/env python3
"""Train the final FULL-5 NEXT reliability/abstention policy.

The V0.4.3 probability core and the existing six-market ranking parameters are
read-only. Development-only ranking OOF predictions are reconstructed with the
frozen ranker specification. Only bootstrap dispersion and the second-level
reliability policy are fitted here.

The three action regions are learned with one-dimensional three-cluster
K-means on reliability probabilities.  K=3 is dictated by the product states
NO BET / BEOBACHTEN / SPIELEN; no performance cutoff is supplied by hand.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss
from sklearn.preprocessing import StandardScaler


REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from full5_next_ai import FEATURE_NAMES, MARKETS, candidate_features  # noqa: E402


RAW_POLICY_FEATURES = (
    "learned_score", "score_gap", "rank_stability", "rank_score_std",
    "rank_score_iqr", "core_probability", "family_margin",
    "baseline_lambda_home", "baseline_lambda_away",
    "match_prematch_xg_home", "match_prematch_xg_away", "match_prematch_xg_total",
    "match_ppg_home", "match_ppg_away",
    "league_matches_home", "league_matches_away",
    "league_ppg_home", "league_ppg_away",
    "league_btts_home", "league_btts_away",
    "league_over25_home", "league_over25_away",
    "league_first_half_btts_home", "league_first_half_btts_away",
    "league_first_half_goals_avg_home", "league_first_half_goals_avg_away",
    "league_second_half_goals_avg_home", "league_second_half_goals_avg_away",
    "league_fts_home", "league_fts_away", "league_cs_home", "league_cs_away",
    "form5_ppg_home", "form5_ppg_away", "form10_ppg_home", "form10_ppg_away",
    "form10_btts_home", "form10_btts_away",
    "form10_over25_home", "form10_over25_away",
    "table_ppg_home", "table_ppg_away",
    "player_contribution_per90_home", "player_contribution_per90_away",
    "player_depth_home", "player_depth_away",
    "robustness_stress_min", "robustness_stress_max", "robustness_stress_range",
)
POLICY_FEATURE_NAMES = RAW_POLICY_FEATURES + tuple(f"market_{market}" for market in MARKETS)
REGULARIZATION_GRID = (0.0003, 0.001, 0.003, 0.01, 0.03, 0.1)
RANK_BOOTSTRAPS = 80
POLICY_BOOTSTRAPS = 80
DEVELOPMENT_MATCHES = 160


def sha256_json(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def outer_ranking_splits() -> list[tuple[np.ndarray, np.ndarray]]:
    # Entirely inside the locked 160-match Development period.  The former
    # 87-match OOS block (indexes 160..246) is never used by this policy.
    return [
        (np.arange(0, 40 + fold * 30), np.arange(40 + fold * 30, 70 + fold * 30))
        for fold in range(4)
    ]


def outer_policy_splits() -> list[tuple[np.ndarray, np.ndarray]]:
    # The 120 input rows are themselves Development-only ranking OOF rows.
    return [
        (np.arange(0, 60 + fold * 30), np.arange(60 + fold * 30, 90 + fold * 30))
        for fold in range(2)
    ]


def inner_splits(count: int) -> list[tuple[np.ndarray, np.ndarray]]:
    block = max(12, count // 4)
    starts = (count - 2 * block, count - block)
    return [
        (np.arange(0, start), np.arange(start, min(start + block, count)))
        for start in starts if start >= 30
    ]


def actual_for(row: pd.Series, market: str) -> int:
    return int({
        "home_win": row.actual_1x2 == "HOME",
        "away_win": row.actual_1x2 == "AWAY",
        "btts_yes": row.actual_btts == "YES",
        "btts_no": row.actual_btts == "NO",
        "over_2_5": row.actual_ou25 == "OVER",
        "under_2_5": row.actual_ou25 == "UNDER",
    }[market])


def ranking_candidate_matrix(master: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for match_index, match in master.iterrows():
        for candidate in candidate_features(match.to_dict()):
            rows.append({
                "match_index": match_index,
                "market": candidate["market"],
                "core_probability": candidate["core_probability"],
                "correct": actual_for(match, candidate["market"]),
                **candidate["features"],
            })
    return pd.DataFrame(rows)


def fit_parameters(frame: pd.DataFrame, features: Iterable[str], target: str, indices: np.ndarray, c_value: float) -> dict[str, Any]:
    names = list(features)
    scaler = StandardScaler().fit(frame.iloc[indices][names])
    model = LogisticRegression(C=c_value, max_iter=5000, random_state=20260908).fit(
        scaler.transform(frame.iloc[indices][names]), frame.iloc[indices][target].astype(int)
    )
    return {
        "mean": scaler.mean_.tolist(), "scale": scaler.scale_.tolist(),
        "coefficient": model.coef_[0].tolist(), "intercept": float(model.intercept_[0]),
    }


def predict(parameters: dict[str, Any], frame: pd.DataFrame, features: Iterable[str]) -> np.ndarray:
    names = list(features)
    values = frame[names].to_numpy(float)
    mean = np.asarray(parameters["mean"], dtype=float)
    scale = np.asarray(parameters["scale"], dtype=float)
    coefficients = np.asarray(parameters["coefficient"], dtype=float)
    linear = ((values - mean) / np.where(scale > 0, scale, 1.0)) @ coefficients + float(parameters["intercept"])
    linear = np.clip(linear, -30, 30)
    return 1 / (1 + np.exp(-linear))


def ranking_oof_and_uncertainty(master: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    candidate_matrix = ranking_candidate_matrix(master)
    candidate_rows: list[pd.DataFrame] = []
    rows: list[dict[str, Any]] = []
    for fold, (train_matches, test_matches) in enumerate(outer_ranking_splits()):
        train_rows = candidate_matrix.index[candidate_matrix.match_index.isin(train_matches)].to_numpy()
        test = candidate_matrix[candidate_matrix.match_index.isin(test_matches)].copy()
        central = fit_parameters(candidate_matrix, FEATURE_NAMES, "correct", train_rows, 0.003)
        test["score"] = predict(central, test, FEATURE_NAMES)
        candidate_rows.append(test[["match_index", "market", "correct", "core_probability", *FEATURE_NAMES, "score"]])
        selected = (
            test.sort_values(["match_index", "score"], ascending=[True, False])
            .drop_duplicates("match_index").sort_values("match_index")
        )
        rng = np.random.default_rng(20260908 + fold)
        predictions: dict[int, list[tuple[str, float]]] = {int(i): [] for i in test_matches}
        for bootstrap in range(RANK_BOOTSTRAPS):
            sampled_matches = rng.choice(train_matches, len(train_matches), replace=True)
            sampled_rows = np.concatenate([
                candidate_matrix.index[candidate_matrix.match_index.eq(match_index)].to_numpy()
                for match_index in sampled_matches
            ])
            parameters = fit_parameters(candidate_matrix, FEATURE_NAMES, "correct", sampled_rows, 0.003)
            for match_index in test_matches:
                group = test[test.match_index.eq(match_index)].copy()
                group["bootstrap_score"] = predict(parameters, group, FEATURE_NAMES)
                winner = group.sort_values(["bootstrap_score", "core_probability"], ascending=[False, False]).iloc[0]
                chosen_market = selected.loc[selected.match_index.eq(match_index), "market"].iloc[0]
                chosen_score = float(group.loc[group.market.eq(chosen_market), "bootstrap_score"].iloc[0])
                predictions[int(match_index)].append((str(winner.market), chosen_score))
        for selected_row in selected.itertuples(index=False):
            values = predictions[int(selected_row.match_index)]
            scores = np.asarray([item[1] for item in values], dtype=float)
            rows.append({
                "match_index": int(selected_row.match_index), "market": str(selected_row.market),
                "rank_stability": sum(item[0] == selected_row.market for item in values) / len(values),
                "rank_score_mean": float(scores.mean()), "rank_score_std": float(scores.std(ddof=0)),
                "rank_score_q10": float(np.quantile(scores, 0.10)),
                "rank_score_q90": float(np.quantile(scores, 0.90)),
                "rank_score_iqr": float(np.quantile(scores, 0.75) - np.quantile(scores, 0.25)),
            })
    return (
        pd.concat(candidate_rows, ignore_index=True),
        pd.DataFrame(rows).sort_values("match_index").reset_index(drop=True),
    )


def replay_robustness(path: Path) -> dict[int, tuple[float, float, float]]:
    result: dict[int, tuple[float, float, float]] = {}
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            item = json.loads(line)
            diagnostics = ((item.get("result") or {}).get("diagnostics") or {})
            values = [float(value) for value in (diagnostics.get("stress_family_strength_pct") or {}).values() if value is not None]
            if values:
                result[int(item["match_id"])] = (min(values), max(values), max(values) - min(values))
    return result


def policy_matrix(master: pd.DataFrame, stored_candidates: pd.DataFrame, uncertainty: pd.DataFrame, robustness: dict[int, tuple[float, float, float]]) -> pd.DataFrame:
    selected = (
        stored_candidates.sort_values(["match_index", "score"], ascending=[True, False])
        .drop_duplicates("match_index").sort_values("match_index").reset_index(drop=True)
    )
    second_scores = (
        stored_candidates.sort_values(["match_index", "score"], ascending=[True, False])
        .groupby("match_index", sort=False)["score"]
        .apply(lambda values: float(values.iloc[1]))
    )
    selected["score_gap"] = selected.score - selected.match_index.map(second_scores)
    selected = selected.merge(uncertainty, on=["match_index", "market"], validate="one_to_one")
    rows: list[dict[str, Any]] = []
    for selected_row in selected.itertuples(index=False):
        raw = master.iloc[int(selected_row.match_index)]
        stress_min, stress_max, stress_range = robustness[int(raw.match_id)]
        candidate = candidate_features(raw.to_dict())[list(MARKETS).index(selected_row.market)]
        values: dict[str, Any] = {
            "match_index": int(selected_row.match_index), "match_id": int(raw.match_id),
            "kickoff_utc": raw.kickoff_utc, "market": selected_row.market,
            "correct": int(selected_row.correct), "learned_score": float(selected_row.score),
            "score_gap": float(selected_row.score_gap), "rank_stability": float(selected_row.rank_stability),
            "rank_score_std": float(selected_row.rank_score_std), "rank_score_iqr": float(selected_row.rank_score_iqr),
            "core_probability": float(selected_row.core_probability),
            "family_margin": float(candidate["features"]["family_margin"]),
            "baseline_lambda_home": raw.baseline_lambda_home, "baseline_lambda_away": raw.baseline_lambda_away,
            "robustness_stress_min": stress_min, "robustness_stress_max": stress_max,
            "robustness_stress_range": stress_range,
        }
        for name in RAW_POLICY_FEATURES:
            if name not in values:
                values[name] = raw[name]
        values.update({f"market_{market}": float(market == selected_row.market) for market in MARKETS})
        rows.append(values)
    frame = pd.DataFrame(rows)
    missing = frame[list(POLICY_FEATURE_NAMES)].isna().sum()
    if missing.any():
        raise ValueError("Missing policy inputs: " + missing[missing.gt(0)].to_dict().__repr__())
    return frame


def choose_c(frame: pd.DataFrame) -> tuple[float, list[dict[str, float]]]:
    audit: list[dict[str, float]] = []
    for c_value in REGULARIZATION_GRID:
        losses: list[float] = []
        for train_index, test_index in inner_splits(len(frame)):
            parameters = fit_parameters(frame, POLICY_FEATURE_NAMES, "correct", train_index, c_value)
            prediction = predict(parameters, frame.iloc[test_index], POLICY_FEATURE_NAMES)
            losses.append(log_loss(frame.iloc[test_index].correct, prediction, labels=[0, 1]))
        mean_loss = float(np.mean(losses))
        audit.append({"regularization_c": c_value, "inner_log_loss": mean_loss})
    chosen = min(audit, key=lambda row: (row["inner_log_loss"], row["regularization_c"]))
    return float(chosen["regularization_c"]), audit


def learned_boundaries(reliability: np.ndarray) -> dict[str, Any]:
    model = KMeans(n_clusters=3, n_init=20, random_state=20260908).fit(np.asarray(reliability).reshape(-1, 1))
    centres = sorted(float(value) for value in model.cluster_centers_[:, 0])
    return {
        "cluster_centres": centres,
        "learned_observe_boundary": (centres[0] + centres[1]) / 2,
        "learned_play_boundary": (centres[1] + centres[2]) / 2,
        "learning_method": "three_cluster_kmeans_on_trained_reliability; k=3 from the required product states",
    }


def action(probability: float, boundaries: dict[str, Any]) -> str:
    if probability >= boundaries["learned_play_boundary"]:
        return "SPIELEN"
    if probability >= boundaries["learned_observe_boundary"]:
        return "BEOBACHTEN"
    return "AUSLASSEN / KEIN BET"


def validate_policy(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, list[dict[str, Any]]]:
    predictions: list[dict[str, Any]] = []
    choices: list[dict[str, Any]] = []
    for fold, (train_index, test_index) in enumerate(outer_policy_splits()):
        train = frame.iloc[train_index]
        test = frame.iloc[test_index]
        c_value, audit = choose_c(train)
        parameters = fit_parameters(train, POLICY_FEATURE_NAMES, "correct", np.arange(len(train)), c_value)
        train_reliability = predict(parameters, train, POLICY_FEATURE_NAMES)
        boundaries = learned_boundaries(train_reliability)
        test_reliability = predict(parameters, test, POLICY_FEATURE_NAMES)
        choices.append({
            "fold": fold, "train_matches": len(train), "test_matches": len(test),
            "regularization_c": c_value, "inner_choices": audit, **boundaries,
        })
        for offset, (_, row) in enumerate(test.iterrows()):
            probability = float(test_reliability[offset])
            predictions.append({
                "fold": fold, "match_index": int(row.match_index), "match_id": int(row.match_id),
                "kickoff_utc": row.kickoff_utc, "market": row.market, "correct": int(row.correct),
                "reliability": probability, "decision": action(probability, boundaries),
                "learned_observe_boundary": boundaries["learned_observe_boundary"],
                "learned_play_boundary": boundaries["learned_play_boundary"],
            })
    oof = pd.DataFrame(predictions)
    fold_rows: list[dict[str, Any]] = []
    for fold, group in oof.groupby("fold"):
        plays = group[group.decision.eq("SPIELEN")]
        fold_rows.append({
            "fold": int(fold), "matches": len(group), "plays": len(plays),
            "hits": int(plays.correct.sum()),
            "hit_rate": float(plays.correct.mean()) if len(plays) else math.nan,
            "play_rate": len(plays) / len(group),
            "observe": int(group.decision.eq("BEOBACHTEN").sum()),
            "no_bet": int(group.decision.eq("AUSLASSEN / KEIN BET").sum()),
            "market_distribution": json.dumps(plays.market.value_counts().to_dict(), sort_keys=True),
        })
    return oof, pd.DataFrame(fold_rows), choices


def final_policy(frame: pd.DataFrame) -> dict[str, Any]:
    c_value, audit = choose_c(frame)
    central = fit_parameters(frame, POLICY_FEATURE_NAMES, "correct", np.arange(len(frame)), c_value)
    reliability = predict(central, frame, POLICY_FEATURE_NAMES)
    boundaries = learned_boundaries(reliability)
    rng = np.random.default_rng(20260908)
    bootstraps = []
    for seed in range(POLICY_BOOTSTRAPS):
        sampled = rng.choice(np.arange(len(frame)), len(frame), replace=True)
        bootstraps.append(fit_parameters(frame, POLICY_FEATURE_NAMES, "correct", sampled, c_value))
    return {
        "model_type": "ridge_logistic_reliability_with_learned_three_state_abstention",
        "feature_names": list(POLICY_FEATURE_NAMES), "regularization_c": c_value,
        "regularization_provenance": {
            "selection": "minimum chronological inner log loss", "candidate_grid": list(REGULARIZATION_GRID),
            "full_oof_inner_results": audit,
        },
        "central_model": central, "bootstrap_models": bootstraps,
        "boundaries": boundaries,
        "manual_performance_gates": [],
        "integrity_gates": ["STRICT_PREMATCH", "FIVE_FILES", "AUDIT", "LEAKAGE", "REQUIRED_INPUTS"],
        "final_decision_source": "TRAINED_AI_POLICY",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("matrix", type=Path)
    parser.add_argument("replay_jsonl", type=Path)
    parser.add_argument("--model", type=Path, default=REPO / "full5_next_ai_model.json")
    parser.add_argument("--output-dir", type=Path, default=REPO / "training" / "policy_validation")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    master = pd.read_csv(args.matrix, low_memory=False).sort_values(["kickoff_utc", "match_id"]).reset_index(drop=True)
    if len(master) != 247 or master.match_id.nunique() != 247:
        raise ValueError("Policy training requires the locked 247 unique matches")
    if not (master.strict_pre_match.eq(True).all() and master.result_verified.eq(True).all()):
        raise ValueError("Policy training matrix violates Strict/verified integrity")
    stored_candidates, uncertainty = ranking_oof_and_uncertainty(master)
    if len(stored_candidates) != 720 or stored_candidates.match_index.nunique() != 120:
        raise ValueError("Expected 720 candidate / 120 match Development-only ranking OOF rows")
    if stored_candidates.match_index.max() >= DEVELOPMENT_MATCHES:
        raise ValueError("Former 87-match OOS leaked into abstention-policy training")
    frame = policy_matrix(master, stored_candidates, uncertainty, replay_robustness(args.replay_jsonl))
    oof, time_stability, choices = validate_policy(frame)
    policy = final_policy(frame)

    plays = oof[oof.decision.eq("SPIELEN")]
    model = json.loads(args.model.read_text(encoding="utf-8"))
    ranking_hash_before = sha256_json({
        "feature_names": model["feature_names"], "central_model": model["central_model"],
        "bootstrap_models": model["bootstrap_models"],
    })
    model["version"] = "FULL-5-NEXT-AI-2.1.0"
    model["decision_policy"] = {
        "final_decision_source": "TRAINED_AI_POLICY", "manual_performance_gates": [],
        "integrity_gates": policy["integrity_gates"],
        "learned_observe_boundary": policy["boundaries"]["learned_observe_boundary"],
        "learned_play_boundary": policy["boundaries"]["learned_play_boundary"],
        "boundary_provenance": policy["boundaries"]["learning_method"],
    }
    model["abstention_policy"] = policy
    model["abstention_validation"] = {
        "method": "Development-only second-level expanding chronological grouped OOF on ranking-OOF rows; 60 initial + 2 disjoint 30-match tests",
        "matches": len(oof), "plays": len(plays), "hits": int(plays.correct.sum()),
        "hit_rate": float(plays.correct.mean()) if len(plays) else None,
        "play_rate": len(plays) / len(oof),
        "brier": brier_score_loss(oof.correct, oof.reliability),
        "log_loss": log_loss(oof.correct, oof.reliability, labels=[0, 1]),
        "time_blocks": time_stability.to_dict(orient="records"),
        "market_distribution": plays.market.value_counts().to_dict(),
        "development_population": DEVELOPMENT_MATCHES,
        "former_87_match_oos_rows_used": 0,
        "no_untouched_oos_claim": True,
    }
    model["validation"] = {
        "scope": "six-market ranking only; no final action-policy result",
        "method": model["validation"]["method"],
        "outer_matches": model["validation"]["outer_matches"],
        "rank_hits": model["validation"]["rank_hits"],
        "rank_hit_rate": model["validation"]["rank_hit_rate"],
        "historical_oos_not_untouched": True,
    }
    ranking_hash_after = sha256_json({
        "feature_names": model["feature_names"], "central_model": model["central_model"],
        "bootstrap_models": model["bootstrap_models"],
    })
    if ranking_hash_before != ranking_hash_after:
        raise RuntimeError("Frozen ranking parameters changed")

    args.model.write_text(json.dumps(model, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    uncertainty.to_csv(args.output_dir / "ranking_bootstrap_uncertainty.csv", index=False)
    frame.to_csv(args.output_dir / "policy_training_matrix.csv", index=False)
    oof.to_csv(args.output_dir / "policy_rolling_oof.csv", index=False)
    time_stability.to_csv(args.output_dir / "policy_time_stability.csv", index=False)
    (args.output_dir / "policy_model_choices.json").write_text(json.dumps(choices, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = {
        "version": model["version"], "ranking_hash_before": ranking_hash_before,
        "ranking_hash_after": ranking_hash_after, "policy_features": len(POLICY_FEATURE_NAMES),
        "rolling_oof": model["abstention_validation"], "final_boundaries": policy["boundaries"],
        "final_regularization_c": policy["regularization_c"],
    }
    (args.output_dir / "policy_validation_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
