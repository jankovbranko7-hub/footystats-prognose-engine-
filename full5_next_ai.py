"""Trained six-market ranker for FULL-5 NEXT.

This module is deliberately independent from the V0.4.3 probability core.  It
turns the seven frozen core probabilities plus leakage-safe summaries from the
five uploaded FootyStats files into six comparable correctness scores.
"""
from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Sequence


MODEL_PATH = Path(__file__).with_name("full5_next_ai_model.json")
MARKETS = ("home_win", "away_win", "btts_yes", "btts_no", "over_2_5", "under_2_5")
LABELS = {
    "home_win": "Sieg Heim", "away_win": "Sieg Auswärts",
    "btts_yes": "BTTS Yes", "btts_no": "BTTS No",
    "over_2_5": "Over 2,5", "under_2_5": "Under 2,5",
}
BASE_FEATURES = (
    "core_logit", "family_strength", "family_margin", "match_score", "league_score",
    "form_score", "table_score", "player_score", "first_half_score", "zero_goal_score",
    "sample_quality", "player_depth",
)
FEATURE_NAMES = BASE_FEATURES + tuple(f"market_{market}" for market in MARKETS)
POLICY_RAW_FEATURES = (
    "learned_score", "score_gap", "rank_stability", "rank_score_std",
    "rank_score_iqr", "core_probability", "family_margin",
    "baseline_lambda_home", "baseline_lambda_away",
    "match_prematch_xg_home", "match_prematch_xg_away", "match_prematch_xg_total",
    "match_ppg_home", "match_ppg_away", "league_matches_home", "league_matches_away",
    "league_ppg_home", "league_ppg_away", "league_btts_home", "league_btts_away",
    "league_over25_home", "league_over25_away",
    "league_first_half_btts_home", "league_first_half_btts_away",
    "league_first_half_goals_avg_home", "league_first_half_goals_avg_away",
    "league_second_half_goals_avg_home", "league_second_half_goals_avg_away",
    "league_fts_home", "league_fts_away", "league_cs_home", "league_cs_away",
    "form5_ppg_home", "form5_ppg_away", "form10_ppg_home", "form10_ppg_away",
    "form10_btts_home", "form10_btts_away", "form10_over25_home", "form10_over25_away",
    "table_ppg_home", "table_ppg_away",
    "player_contribution_per90_home", "player_contribution_per90_away",
    "player_depth_home", "player_depth_away",
    "robustness_stress_min", "robustness_stress_max", "robustness_stress_range",
)
POLICY_FEATURE_NAMES = POLICY_RAW_FEATURES + tuple(f"market_{market}" for market in MARKETS)


def _num(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def _required(value: Any, name: str) -> float:
    result = _num(value)
    if result is None:
        raise ValueError(f"FULL-5 NEXT AI input missing: {name}")
    return result


def _clip_probability(value: float) -> float:
    return max(1e-6, min(1 - 1e-6, float(value)))


def _mean(left: Any, right: Any, name: str) -> float:
    return (_required(left, name + "_home") + _required(right, name + "_away")) / 2


def _status(score: float, positive: float, negative: float) -> tuple[int, int]:
    return int(score >= positive), int(score <= negative)


def _iter_page_data(content: Any) -> Iterable[Mapping[str, Any]]:
    if not isinstance(content, Mapping):
        return
    for key, pages in content.items():
        if not str(key).lower().startswith("pages") or not isinstance(pages, list):
            continue
        for page in pages:
            if isinstance(page, Mapping):
                for item in page.get("data") or []:
                    if isinstance(item, Mapping):
                        yield item


def _source(parsed_files: Sequence[Mapping[str, Any]], source: str) -> Any:
    for item in parsed_files:
        name = str(item.get("name") or item.get("filename") or "").lower()
        if f"{source}daten" in name or name.endswith(f"{source}.json"):
            return item.get("data")
    return None


def _league_team(content: Any, team_id: Any) -> Mapping[str, Any]:
    candidates = [item for item in _iter_page_data(content) if str(item.get("id")) == str(team_id) and isinstance(item.get("stats"), Mapping)]
    return max(candidates, key=lambda item: len(item.get("stats") or {}), default={})


def _league_stat(team: Mapping[str, Any], base: str, venue: str) -> float | None:
    stats = team.get("stats") or {}
    for container in (stats, stats.get("additional_info") or {}):
        for key in (f"{base}_{venue}", base):
            result = _num(container.get(key))
            if result is not None:
                return result
    return None


def _flat_inputs(row: Mapping[str, Any]) -> Dict[str, float]:
    names = (
        "baseline_home_win", "baseline_draw", "baseline_away_win", "baseline_btts_yes", "baseline_btts_no",
        "baseline_over_2_5", "baseline_under_2_5", "match_prematch_xg_home", "match_prematch_xg_away",
        "match_prematch_xg_total", "match_ppg_diff", "league_ppg_diff", "league_btts_mean",
        "league_over25_mean", "league_first_half_btts_mean", "league_first_half_goals_avg_mean",
        "league_second_half_goals_avg_mean", "btts_zero_goal_support", "form5_ppg_diff", "form10_ppg_diff",
        "form10_btts_mean", "form10_over25_mean", "table_ppg_diff", "player_contribution_per90_home",
        "player_contribution_per90_away", "player_depth_min", "league_matches_mean",
    )
    return {name: _required(row.get(name), name) for name in names}


def _live_inputs(result: Mapping[str, Any], parsed_files: Sequence[Mapping[str, Any]]) -> Dict[str, float]:
    probabilities = result.get("probabilities") or {}
    match = (result.get("audit") or {}).get("match") or {}
    coverage = ((result.get("diagnostics") or {}).get("supplemental_inputs") or {}).get("coverage") or {}
    form = coverage.get("form") or {}
    table = coverage.get("table") or {}
    player = coverage.get("player") or {}
    home_form, away_form = form.get("home") or {}, form.get("away") or {}
    home_table, away_table = table.get("home") or {}, table.get("away") or {}
    home_player, away_player = player.get("home") or {}, player.get("away") or {}
    home5 = (home_form.get("windows") or {}).get("5") or home_form.get("recent_5") or {}
    away5 = (away_form.get("windows") or {}).get("5") or away_form.get("recent_5") or {}
    home10 = (home_form.get("windows") or {}).get("10") or home_form.get("reference") or {}
    away10 = (away_form.get("windows") or {}).get("10") or away_form.get("reference") or {}

    league = _source(parsed_files, "league")
    home_team = _league_team(league, match.get("home_id"))
    away_team = _league_team(league, match.get("away_id"))
    league_ppg_home = _required(_league_stat(home_team, "seasonPPG", "home"), "league_ppg_home")
    league_ppg_away = _required(_league_stat(away_team, "seasonPPG", "away"), "league_ppg_away")
    league_btts_home = _required(_league_stat(home_team, "seasonBTTSPercentage", "home"), "league_btts_home")
    league_btts_away = _required(_league_stat(away_team, "seasonBTTSPercentage", "away"), "league_btts_away")
    league_over_home = _required(_league_stat(home_team, "seasonOver25Percentage", "home"), "league_over25_home")
    league_over_away = _required(_league_stat(away_team, "seasonOver25Percentage", "away"), "league_over25_away")
    first_btts_home = _required(_league_stat(home_team, "seasonBTTSPercentageHT", "home"), "league_first_half_btts_home")
    first_btts_away = _required(_league_stat(away_team, "seasonBTTSPercentageHT", "away"), "league_first_half_btts_away")
    first_goals_home = _required(_league_stat(home_team, "AVGHT", "home"), "league_first_half_goals_home")
    first_goals_away = _required(_league_stat(away_team, "AVGHT", "away"), "league_first_half_goals_away")
    second_goals_home = _required(_league_stat(home_team, "AVG_2hg", "home"), "league_second_half_goals_home")
    second_goals_away = _required(_league_stat(away_team, "AVG_2hg", "away"), "league_second_half_goals_away")
    fts_home = _required(_league_stat(home_team, "seasonFTSPercentage", "home"), "league_fts_home")
    fts_away = _required(_league_stat(away_team, "seasonFTSPercentage", "away"), "league_fts_away")
    cs_home = _required(_league_stat(home_team, "seasonCSPercentage", "home"), "league_cs_home")
    cs_away = _required(_league_stat(away_team, "seasonCSPercentage", "away"), "league_cs_away")
    zero_pressure = ((fts_home + cs_away) / 2 + (fts_away + cs_home) / 2) / 2
    samples = result.get("samples") or {}
    league_matches_home = _required(samples.get("home_venue"), "home_venue_sample")
    league_matches_away = _required(samples.get("away_venue"), "away_venue_sample")
    league_matches_mean = (league_matches_home + league_matches_away) / 2
    player_depth_home = _required(home_player.get("players_found"), "player_depth_home")
    player_depth_away = _required(away_player.get("players_found"), "player_depth_away")
    depth_min = min(player_depth_home, player_depth_away)
    contribution_home = _required(home_player.get("goals_per_90"), "player_goals_home") + _required(home_player.get("assists_per_90"), "player_assists_home")
    contribution_away = _required(away_player.get("goals_per_90"), "player_goals_away") + _required(away_player.get("assists_per_90"), "player_assists_away")
    expected = result.get("expected_goals") or {}

    return {
        "baseline_home_win": _required(probabilities.get("home_win"), "home_win"),
        "baseline_draw": _required(probabilities.get("draw"), "draw"),
        "baseline_away_win": _required(probabilities.get("away_win"), "away_win"),
        "baseline_btts_yes": _required(probabilities.get("btts_yes"), "btts_yes"),
        "baseline_btts_no": _required(probabilities.get("btts_no"), "btts_no"),
        "baseline_over_2_5": _required(probabilities.get("over_2_5"), "over_2_5"),
        "baseline_under_2_5": _required(probabilities.get("under_2_5"), "under_2_5"),
        "match_prematch_xg_home": _required(match.get("home_prematch_xg"), "match_prematch_xg_home"),
        "match_prematch_xg_away": _required(match.get("away_prematch_xg"), "match_prematch_xg_away"),
        "match_prematch_xg_total": _required(match.get("total_prematch_xg"), "match_prematch_xg_total"),
        "baseline_lambda_home": _required(expected.get("home"), "baseline_lambda_home"),
        "baseline_lambda_away": _required(expected.get("away"), "baseline_lambda_away"),
        "match_ppg_home": _required(match.get("pre_match_home_ppg"), "match_ppg_home"),
        "match_ppg_away": _required(match.get("pre_match_away_ppg"), "match_ppg_away"),
        "match_ppg_diff": _required(match.get("pre_match_home_ppg"), "match_ppg_home") - _required(match.get("pre_match_away_ppg"), "match_ppg_away"),
        "league_matches_home": league_matches_home,
        "league_matches_away": league_matches_away,
        "league_ppg_home": league_ppg_home,
        "league_ppg_away": league_ppg_away,
        "league_ppg_diff": league_ppg_home - league_ppg_away,
        "league_btts_home": league_btts_home,
        "league_btts_away": league_btts_away,
        "league_btts_mean": (league_btts_home + league_btts_away) / 2,
        "league_over25_home": league_over_home,
        "league_over25_away": league_over_away,
        "league_over25_mean": (league_over_home + league_over_away) / 2,
        "league_first_half_btts_home": first_btts_home,
        "league_first_half_btts_away": first_btts_away,
        "league_first_half_btts_mean": (first_btts_home + first_btts_away) / 2,
        "league_first_half_goals_avg_home": first_goals_home,
        "league_first_half_goals_avg_away": first_goals_away,
        "league_first_half_goals_avg_mean": (first_goals_home + first_goals_away) / 2,
        "league_second_half_goals_avg_home": second_goals_home,
        "league_second_half_goals_avg_away": second_goals_away,
        "league_second_half_goals_avg_mean": (second_goals_home + second_goals_away) / 2,
        "league_fts_home": fts_home, "league_fts_away": fts_away,
        "league_cs_home": cs_home, "league_cs_away": cs_away,
        "btts_zero_goal_support": 100 - zero_pressure,
        "form5_ppg_home": _required(home5.get("ppg"), "form5_ppg_home"),
        "form5_ppg_away": _required(away5.get("ppg"), "form5_ppg_away"),
        "form5_ppg_diff": _required(home5.get("ppg"), "form5_ppg_home") - _required(away5.get("ppg"), "form5_ppg_away"),
        "form10_ppg_home": _required(home10.get("ppg"), "form10_ppg_home"),
        "form10_ppg_away": _required(away10.get("ppg"), "form10_ppg_away"),
        "form10_ppg_diff": _required(home10.get("ppg"), "form10_ppg_home") - _required(away10.get("ppg"), "form10_ppg_away"),
        "form10_btts_home": _required(home10.get("btts_pct"), "form10_btts_home"),
        "form10_btts_away": _required(away10.get("btts_pct"), "form10_btts_away"),
        "form10_btts_mean": _mean(home10.get("btts_pct"), away10.get("btts_pct"), "form10_btts"),
        "form10_over25_home": _required(home10.get("over_25_pct"), "form10_over25_home"),
        "form10_over25_away": _required(away10.get("over_25_pct"), "form10_over25_away"),
        "form10_over25_mean": _mean(home10.get("over_25_pct"), away10.get("over_25_pct"), "form10_over25"),
        "table_ppg_home": _required(home_table.get("ppg"), "table_ppg_home"),
        "table_ppg_away": _required(away_table.get("ppg"), "table_ppg_away"),
        "table_ppg_diff": _required(home_table.get("ppg"), "table_ppg_home") - _required(away_table.get("ppg"), "table_ppg_away"),
        "player_contribution_per90_home": contribution_home,
        "player_contribution_per90_away": contribution_away,
        "player_depth_home": player_depth_home,
        "player_depth_away": player_depth_away,
        "player_depth_min": depth_min,
        "league_matches_mean": league_matches_mean,
    }


def candidate_features(inputs: Mapping[str, Any]) -> list[Dict[str, Any]]:
    data = _flat_inputs(inputs)
    probabilities = {
        "home_win": data["baseline_home_win"], "away_win": data["baseline_away_win"],
        "btts_yes": data["baseline_btts_yes"], "btts_no": data["baseline_btts_no"],
        "over_2_5": data["baseline_over_2_5"], "under_2_5": data["baseline_under_2_5"],
    }
    sample_quality = 0.6 * min(1.0, data["league_matches_mean"] / 10) + 0.4 * min(1.0, data["player_depth_min"] / 22)
    rows = []
    for market in MARKETS:
        probability = probabilities[market]
        family = "1X2" if market in {"home_win", "away_win"} else "BTTS" if market.startswith("btts") else "O/U"
        direction = 1 if market in {"home_win", "btts_yes", "over_2_5"} else -1
        if family == "1X2":
            family_strength = max(0.0, (probability - 1 / 3) / (2 / 3)) if probability >= data["baseline_draw"] else 0.0
            family_margin = probability - max(data["baseline_draw"], data["baseline_away_win"] if market == "home_win" else data["baseline_home_win"])
            match_score = direction * data["match_ppg_diff"]
            league_score = direction * data["league_ppg_diff"]
            form_score = direction * (0.75 * data["form10_ppg_diff"] + 0.25 * data["form5_ppg_diff"])
            table_score = direction * data["table_ppg_diff"]
            player_score = first_half_score = zero_goal_score = 0.0
            match_confirm, match_counter = _status(match_score, 0.35, -0.35)
            form_confirm, form_counter = _status(form_score, 0.25, -0.25)
            table_confirm, table_counter = _status(table_score, 0.35, -0.35)
            player_confirm = player_counter = 0
            applicable = ("UNDERLYING", "MATCH", "FORM", "TABLE")
        elif family == "BTTS":
            family_strength = max(0.0, 2 * probability - 1)
            family_margin = 2 * probability - 1
            minimum_xg = min(data["match_prematch_xg_home"], data["match_prematch_xg_away"])
            match_score = minimum_xg if direction == 1 else -minimum_xg
            league_score = data["league_btts_mean"] / 100 if direction == 1 else 1 - data["league_btts_mean"] / 100
            form_score = data["form10_btts_mean"] / 100 if direction == 1 else 1 - data["form10_btts_mean"] / 100
            first_half_score = data["league_first_half_btts_mean"] / 100 if direction == 1 else 1 - data["league_first_half_btts_mean"] / 100
            zero_goal_score = data["btts_zero_goal_support"] / 100 if direction == 1 else 1 - data["btts_zero_goal_support"] / 100
            table_score = player_score = 0.0
            match_confirm, match_counter = _status(minimum_xg, 1.0, 0.7) if direction == 1 else _status(-minimum_xg, -0.7, -1.0)
            form_confirm, form_counter = _status(form_score, 0.60, 0.40)
            table_confirm = table_counter = player_confirm = player_counter = 0
            applicable = ("UNDERLYING", "MATCH", "FORM")
        else:
            family_strength = max(0.0, 2 * probability - 1)
            family_margin = 2 * probability - 1
            total_xg = data["match_prematch_xg_total"]
            intensity = data["player_contribution_per90_home"] + data["player_contribution_per90_away"]
            match_score = direction * total_xg
            league_score = data["league_over25_mean"] / 100 if direction == 1 else 1 - data["league_over25_mean"] / 100
            form_score = data["form10_over25_mean"] / 100 if direction == 1 else 1 - data["form10_over25_mean"] / 100
            player_score = direction * intensity
            first_half_score = direction * (data["league_first_half_goals_avg_mean"] + data["league_second_half_goals_avg_mean"])
            table_score = zero_goal_score = 0.0
            if direction == 1:
                match_confirm, match_counter = _status(total_xg, 2.8, 2.2)
                player_confirm, player_counter = _status(intensity, 0.50, 0.32)
            else:
                match_confirm, match_counter = _status(-total_xg, -2.2, -2.8)
                player_confirm, player_counter = _status(-intensity, -0.32, -0.50)
            form_confirm, form_counter = _status(form_score, 0.60, 0.40)
            table_confirm = table_counter = 0
            applicable = ("UNDERLYING", "MATCH", "FORM", "PLAYER")
        block_state = {
            "UNDERLYING": (int(family_strength > 0), 0),
            "MATCH": (match_confirm, match_counter),
            "FORM": (form_confirm, form_counter),
            "TABLE": (table_confirm, table_counter),
            "PLAYER": (player_confirm, player_counter),
        }
        confirming_blocks = [name for name in applicable if block_state[name][0]]
        counter_blocks = [name for name in applicable if block_state[name][1]]
        confirmations = len(confirming_blocks)
        counters = len(counter_blocks)
        feature_values = {
            "core_logit": math.log(_clip_probability(probability) / (1 - _clip_probability(probability))),
            "family_strength": family_strength, "family_margin": family_margin,
            "match_score": match_score, "league_score": league_score, "form_score": form_score,
            "table_score": table_score, "player_score": player_score,
            "first_half_score": first_half_score, "zero_goal_score": zero_goal_score,
            "sample_quality": sample_quality, "player_depth": data["player_depth_min"] / 22,
        }
        feature_values.update({f"market_{key}": float(key == market) for key in MARKETS})
        rows.append({
            "market": market, "label": LABELS[market], "family": family,
            "core_probability": probability, "features": feature_values,
            "confirmations": confirmations, "applicable_blocks": len(applicable),
            "applicable_block_names": list(applicable), "confirmation_ratio": confirmations / len(applicable),
            "confirming_blocks": confirming_blocks, "counter_blocks": counter_blocks,
            "counters": counters, "sample_quality": sample_quality,
        })
    return rows


@lru_cache(maxsize=1)
def load_model() -> Dict[str, Any]:
    with MODEL_PATH.open(encoding="utf-8") as handle:
        model = json.load(handle)
    if tuple(model.get("feature_names") or ()) != FEATURE_NAMES:
        raise RuntimeError("FULL-5 NEXT AI model feature contract mismatch")
    return model


def _predict(parameters: Mapping[str, Any], features: Mapping[str, float]) -> float:
    return _predict_named(parameters, features, FEATURE_NAMES)


def _predict_named(parameters: Mapping[str, Any], features: Mapping[str, float], names: Sequence[str]) -> float:
    linear = float(parameters["intercept"])
    for index, name in enumerate(names):
        scale = float(parameters["scale"][index])
        value = (float(features[name]) - float(parameters["mean"][index])) / (scale if scale > 0 else 1.0)
        linear += float(parameters["coefficient"][index]) * value
    linear = max(-30.0, min(30.0, linear))
    return 1 / (1 + math.exp(-linear))


def _quantile(values: Sequence[float], quantile: float) -> float:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        raise ValueError("Cannot calculate an empty bootstrap quantile")
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] * (upper - position) + ordered[upper] * (position - lower)


def rank_markets(result: Mapping[str, Any], parsed_files: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    inputs = _live_inputs(result, parsed_files)
    candidates = candidate_features(inputs)
    model = load_model()
    for candidate in candidates:
        candidate["learned_score"] = _predict(model["central_model"], candidate["features"])
    selected = max(candidates, key=lambda item: (item["learned_score"], item["core_probability"]))
    second = sorted(candidates, key=lambda item: item["learned_score"], reverse=True)[1]
    bootstrap_winners = []
    selected_bootstrap_scores = []
    for parameters in model.get("bootstrap_models") or []:
        scored = [(candidate, _predict(parameters, candidate["features"])) for candidate in candidates]
        bootstrap_winners.append(max(scored, key=lambda item: item[1])[0]["market"])
        selected_bootstrap_scores.append(next(score for candidate, score in scored if candidate["market"] == selected["market"]))
    rank_stability = bootstrap_winners.count(selected["market"]) / len(bootstrap_winners) if bootstrap_winners else 1.0
    selected["score_gap"] = selected["learned_score"] - second["learned_score"]
    selected["rank_stability"] = rank_stability
    selected["rank_score_mean"] = sum(selected_bootstrap_scores) / len(selected_bootstrap_scores)
    selected["rank_score_std"] = math.sqrt(sum((value - selected["rank_score_mean"]) ** 2 for value in selected_bootstrap_scores) / len(selected_bootstrap_scores))
    selected["rank_score_q10"] = _quantile(selected_bootstrap_scores, 0.10)
    selected["rank_score_q90"] = _quantile(selected_bootstrap_scores, 0.90)
    selected["rank_score_iqr"] = _quantile(selected_bootstrap_scores, 0.75) - _quantile(selected_bootstrap_scores, 0.25)
    selected_features = dict(selected["features"])
    for candidate in candidates:
        candidate.pop("features")
    return {
        "selected": selected, "second": second, "candidates": candidates,
        "selected_rank_features": selected_features, "live_inputs": inputs, "model": model,
    }


def policy_features(result: Mapping[str, Any], ranking: Mapping[str, Any]) -> Dict[str, float]:
    model = ranking["model"]
    policy = model.get("abstention_policy") or {}
    if tuple(policy.get("feature_names") or ()) != POLICY_FEATURE_NAMES:
        raise RuntimeError("FULL-5 NEXT abstention feature contract mismatch")
    selected = ranking["selected"]
    inputs = ranking["live_inputs"]
    rank_features = ranking["selected_rank_features"]
    stress = ((result.get("diagnostics") or {}).get("stress_family_strength_pct") or {})
    stress_values = [_required(value, "robustness_stress") for value in stress.values()]
    if not stress_values:
        raise ValueError("FULL-5 NEXT AI input missing: robustness_stress")
    values: Dict[str, float] = {
        "learned_score": _required(selected.get("learned_score"), "learned_score"),
        "score_gap": _required(selected.get("score_gap"), "score_gap"),
        "rank_stability": _required(selected.get("rank_stability"), "rank_stability"),
        "rank_score_std": _required(selected.get("rank_score_std"), "rank_score_std"),
        "rank_score_iqr": _required(selected.get("rank_score_iqr"), "rank_score_iqr"),
        "core_probability": _required(selected.get("core_probability"), "core_probability"),
        "family_margin": _required(rank_features.get("family_margin"), "family_margin"),
        "robustness_stress_min": min(stress_values),
        "robustness_stress_max": max(stress_values),
        "robustness_stress_range": max(stress_values) - min(stress_values),
    }
    for name in POLICY_RAW_FEATURES:
        if name not in values:
            values[name] = _required(inputs.get(name), name)
    market = str(selected["market"])
    values.update({f"market_{name}": float(name == market) for name in MARKETS})
    return values


def apply_abstention_policy(result: Mapping[str, Any], ranking: Mapping[str, Any]) -> Dict[str, Any]:
    model = ranking["model"]
    policy = model.get("abstention_policy") or {}
    features = policy_features(result, ranking)
    central = _predict_named(policy["central_model"], features, POLICY_FEATURE_NAMES)
    bootstrap = [
        _predict_named(parameters, features, POLICY_FEATURE_NAMES)
        for parameters in policy.get("bootstrap_models") or []
    ]
    boundaries = policy.get("boundaries") or {}
    observe_boundary = _required(boundaries.get("learned_observe_boundary"), "learned_observe_boundary")
    play_boundary = _required(boundaries.get("learned_play_boundary"), "learned_play_boundary")
    decision = (
        "SPIELEN" if central >= play_boundary else
        "BEOBACHTEN" if central >= observe_boundary else
        "AUSLASSEN / KEIN BET"
    )
    mean = sum(bootstrap) / len(bootstrap) if bootstrap else central
    dispersion = math.sqrt(sum((value - mean) ** 2 for value in bootstrap) / len(bootstrap)) if bootstrap else 0.0
    return {
        "decision": decision, "reliability": central,
        "reliability_bootstrap_mean": mean, "reliability_uncertainty": dispersion,
        "reliability_q10": _quantile(bootstrap, 0.10) if bootstrap else central,
        "reliability_q90": _quantile(bootstrap, 0.90) if bootstrap else central,
        "learned_observe_boundary": observe_boundary, "learned_play_boundary": play_boundary,
        "boundary_provenance": boundaries.get("learning_method"),
        "final_decision_source": "TRAINED_AI_POLICY",
        "manual_performance_gates": "NONE",
        "integrity_gates": list(policy.get("integrity_gates") or []),
    }
