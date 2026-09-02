from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List, Optional, Tuple

LABEL = {
    "home_win": "Sieg Heim",
    "away_win": "Sieg Auswärts",
    "btts_yes": "BTTS Yes",
    "btts_no": "BTTS No",
    "over_2_5": "Over 2,5",
    "under_2_5": "Under 2,5",
}

ALLOWED = ["home_win", "away_win", "btts_yes", "btts_no", "over_2_5", "under_2_5"]


def _num(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip().replace(",", ".").replace("%", ""))
    except Exception:
        return None


def _bounded_probability(value: float) -> float:
    return max(1e-6, min(1.0 - 1e-6, float(value)))


def _weighted_binary_log_pool(first: float, second: float, first_weight: float) -> float:
    p = _bounded_probability(first)
    q = _bounded_probability(second)
    w = max(0.0, min(1.0, float(first_weight)))
    log_odds = w * math.log(p / (1.0 - p)) + (1.0 - w) * math.log(q / (1.0 - q))
    return 1.0 / (1.0 + math.exp(-log_odds))


def _weighted_multiclass_log_pool(
    first_model: Dict[str, float],
    second_model: Dict[str, float],
    keys: Iterable[str],
    first_weight: float,
) -> Dict[str, float]:
    w = max(0.0, min(1.0, float(first_weight)))
    raw = {
        key: (_bounded_probability(first_model[key]) ** w)
        * (_bounded_probability(second_model[key]) ** (1.0 - w))
        for key in keys
    }
    total = sum(raw.values())
    return {key: value / total for key, value in raw.items()}


def _quality_value(value: Any, mapping: Dict[str, float], default: float) -> float:
    text = str(value or "").upper()
    for marker, score in mapping.items():
        if marker in text:
            return score
    return default


def _footystats_reliability(result: Dict[str, Any]) -> Dict[str, Any]:
    diagnostics = result.get("diagnostics") or {}
    samples = result.get("samples") or {}
    protocol = diagnostics.get("elite_protocol") or {}
    gates = protocol.get("gates") or {}

    quality = _quality_value(
        diagnostics.get("data_quality"),
        {"HOCH": 0.95, "MITTEL": 0.82, "NIEDRIG": 0.60},
        0.72,
    )
    sample = _quality_value(
        samples.get("security") or diagnostics.get("sample_security"),
        {"HOCH": 0.95, "MITTEL": 0.82, "NIEDRIG": 0.60},
        0.70,
    )
    robustness = _quality_value(
        diagnostics.get("robustness_status"),
        {
            "NICHT BESTANDEN": 0.55,
            "INSTABIL": 0.55,
            "EINGESCHRÄNKT": 0.74,
            "STABIL": 0.86,
            "BESTANDEN": 0.95,
        },
        0.70,
    )
    rvu = _quality_value(
        diagnostics.get("result_vs_underlying"),
        {
            "STARK WIDERSPRÜCHLICH": 0.50,
            "TEILWEISE WIDERSPRÜCHLICH": 0.64,
            "TEILWEISE KONSISTENT": 0.84,
            "KONSISTENT": 0.95,
            "NICHT PRÜFBAR": 0.65,
        },
        0.70,
    )
    multi_block = _quality_value(
        gates.get("multi_block_confirmation"),
        {"NICHT BESTANDEN": 0.60, "EINGESCHRÄNKT": 0.80, "BESTANDEN": 0.95},
        0.75,
    )

    score = 0.25 * quality + 0.20 * sample + 0.20 * robustness + 0.20 * rvu + 0.15 * multi_block
    return {
        "score": round(max(0.50, min(0.97, score)), 4),
        "components": {
            "data_quality": round(quality, 3),
            "sample_security": round(sample, 3),
            "robustness": round(robustness, 3),
            "result_vs_underlying": round(rvu, 3),
            "multi_block": round(multi_block, 3),
        },
    }


def _score_tuple(forebet: Dict[str, Any]) -> Optional[Tuple[int, int]]:
    score = str(forebet.get("predicted_score") or "").strip().replace(":", "-")
    if "-" not in score:
        return None
    left, right = score.split("-", 1)
    try:
        return int(left.strip()), int(right.strip())
    except Exception:
        return None


def _forebet_internal_coherence(forebet: Dict[str, Any]) -> Dict[str, float]:
    probabilities = forebet.get("probabilities") or {}
    score = _score_tuple(forebet)
    avg = _num(forebet.get("average_goals"))

    one_x_two = 1.0
    btts = 1.0
    ou = 1.0
    if score is not None:
        hs, aas = score
        predicted_side = "home_win" if hs > aas else ("away_win" if aas > hs else "draw")
        p_top = max(("home_win", "draw", "away_win"), key=lambda key: probabilities.get(key, 0.0))
        if predicted_side != p_top:
            one_x_two = 0.88

        btts_yes = probabilities.get("btts_yes")
        score_btts_yes = hs > 0 and aas > 0
        if btts_yes is not None:
            if btts_yes >= 0.60 and not score_btts_yes:
                btts = 0.85
            elif btts_yes <= 0.40 and score_btts_yes:
                btts = 0.85

        over = probabilities.get("over_2_5")
        score_over = hs + aas >= 3
        if over is not None:
            if over >= 0.60 and not score_over:
                ou = 0.85
            elif over <= 0.40 and score_over:
                ou = 0.85

        if avg is not None:
            delta = abs((hs + aas) - avg)
            if delta > 1.75:
                ou *= 0.90
                btts *= 0.95
            elif delta <= 1.0:
                ou *= 1.03
                btts *= 1.02

    if avg is not None:
        over = probabilities.get("over_2_5")
        if over is not None:
            if over >= 0.60 and avg < 2.45:
                ou *= 0.88
            elif over <= 0.40 and avg > 2.75:
                ou *= 0.88

    return {
        "1x2": round(max(0.75, min(1.05, one_x_two)), 3),
        "btts": round(max(0.75, min(1.05, btts)), 3),
        "ou": round(max(0.75, min(1.05, ou)), 3),
    }


def _weights(result: Dict[str, Any], forebet: Dict[str, Any]) -> Dict[str, Any]:
    fs = _footystats_reliability(result)
    forebet_base = 0.55
    coherence = _forebet_internal_coherence(forebet)
    output: Dict[str, Any] = {}
    for family in ("1x2", "btts", "ou"):
        fs_evidence = fs["score"]
        fb_evidence = forebet_base * coherence[family]
        fs_weight = fs_evidence / (fs_evidence + fb_evidence)
        fs_weight = max(0.50, min(0.70, fs_weight))
        output[family] = {
            "footystats": round(fs_weight, 4),
            "forebet": round(1.0 - fs_weight, 4),
            "forebet_internal_coherence": coherence[family],
        }
    output["footystats_reliability"] = fs
    output["forebet_uncalibrated_prior"] = forebet_base
    return output


def _score_supports_market(forebet: Dict[str, Any], market: str) -> str:
    score = _score_tuple(forebet)
    if score is None:
        return "NICHT PRÜFBAR"
    home, away = score
    if market == "home_win":
        return "JA" if home > away else "NEIN"
    if market == "away_win":
        return "JA" if away > home else "NEIN"
    if market == "btts_yes":
        return "JA" if home > 0 and away > 0 else "NEIN"
    if market == "btts_no":
        return "JA" if home == 0 or away == 0 else "NEIN"
    if market == "over_2_5":
        return "JA" if home + away >= 3 else "NEIN"
    if market == "under_2_5":
        return "JA" if home + away <= 2 else "NEIN"
    return "NICHT PRÜFBAR"


def _goal_environment(result: Dict[str, Any], forebet: Dict[str, Any]) -> Dict[str, Any]:
    fs_total = _num((result.get("expected_goals") or {}).get("total"))
    fb_total = _num(forebet.get("average_goals"))
    if fs_total is None or fb_total is None:
        return {"status": "NICHT PRÜFBAR", "footystats_xg_total": fs_total, "forebet_average_goals": fb_total}
    difference = abs(fs_total - fb_total)
    status = "HOCH" if difference <= 0.50 else ("MITTEL" if difference <= 1.00 else "NIEDRIG")
    return {
        "status": status,
        "footystats_xg_total": round(fs_total, 3),
        "forebet_average_goals": round(fb_total, 3),
        "difference_goals": round(difference, 3),
    }


def _consensus_for_market(fs: float, fb: float) -> Dict[str, Any]:
    diff = abs(fs - fb)
    min_support = min(fs, fb)
    same_direction = (fs >= 0.50) == (fb >= 0.50)
    if same_direction and min_support >= 0.60 and diff <= 0.08:
        status = "HOCH"
    elif same_direction and min_support >= 0.55 and diff <= 0.15:
        status = "MITTEL"
    else:
        status = "NIEDRIG"
    return {
        "status": status,
        "difference_pp": round(diff * 100, 1),
        "both_models_ge_60": min_support >= 0.60,
        "same_direction": same_direction,
    }


def _severe_guardrail_failure(result: Dict[str, Any]) -> List[str]:
    diagnostics = result.get("diagnostics") or {}
    protocol = diagnostics.get("elite_protocol") or {}
    gates = protocol.get("gates") or {}
    reasons: List[str] = []

    quality = str(diagnostics.get("data_quality") or "")
    sample = str((result.get("samples") or {}).get("security") or diagnostics.get("sample_security") or "")
    rvu = str(diagnostics.get("result_vs_underlying") or "")
    robustness = str(diagnostics.get("robustness_status") or "")
    multi = str(gates.get("multi_block_confirmation") or "")

    if "NIEDRIG" in quality:
        reasons.append("FootyStats-Datenqualität niedrig")
    if "NIEDRIG" in sample:
        reasons.append("Venue-Stichprobe niedrig")
    if "STARK WIDERSPRÜCHLICH" in rvu:
        reasons.append("Result-vs-Underlying stark widersprüchlich")
    if diagnostics.get("single_point_of_failure"):
        reasons.append("Single Point of Failure im FootyStats-Robustheitstest")
    if "NICHT BESTANDEN" in robustness or "INSTABIL" in robustness:
        reasons.append("FootyStats-Robustheit nicht bestanden")
    if multi and "NICHT BESTANDEN" in multi:
        reasons.append("Multi-Block-Bestätigung nicht bestanden")
    coherence = gates.get("coherence")
    if isinstance(coherence, dict) and coherence.get("passed") is False:
        reasons.append("Wahrscheinlichkeits-Kohärenz nicht bestanden")
    return reasons


def attach_forebet_elite(result: Dict[str, Any], forebet: Dict[str, Any]) -> Dict[str, Any]:
    if not result.get("ok"):
        return result

    result = dict(result)
    fs_prob = {key: float(value) for key, value in (result.get("probabilities") or {}).items()}
    fb_prob = {key: float(value) for key, value in (forebet.get("probabilities") or {}).items()}
    required = {"home_win", "draw", "away_win", "btts_yes", "btts_no", "over_2_5", "under_2_5"}
    if not required.issubset(fs_prob) or not required.issubset(fb_prob):
        raise ValueError("FootyStats oder Forebet enthält nicht alle benötigten Markt-Wahrscheinlichkeiten.")

    weight_info = _weights(result, forebet)
    w_1x2 = weight_info["1x2"]["footystats"]
    w_btts = weight_info["btts"]["footystats"]
    w_ou = weight_info["ou"]["footystats"]

    fused = _weighted_multiclass_log_pool(fs_prob, fb_prob, ("home_win", "draw", "away_win"), w_1x2)
    fused["btts_yes"] = _weighted_binary_log_pool(fs_prob["btts_yes"], fb_prob["btts_yes"], w_btts)
    fused["btts_no"] = 1.0 - fused["btts_yes"]
    fused["over_2_5"] = _weighted_binary_log_pool(fs_prob["over_2_5"], fb_prob["over_2_5"], w_ou)
    fused["under_2_5"] = 1.0 - fused["over_2_5"]

    ranking = sorted(((key, fused[key]) for key in ALLOWED), key=lambda item: item[1], reverse=True)
    fused_top, fused_probability = ranking[0]
    fs_top = max(ALLOWED, key=lambda key: fs_prob[key])
    fb_top = max(ALLOWED, key=lambda key: fb_prob[key])

    comparison = []
    market_consensus = {}
    for key in ALLOWED:
        family = "1x2" if key in {"home_win", "away_win"} else ("btts" if key.startswith("btts") else "ou")
        consensus = _consensus_for_market(fs_prob[key], fb_prob[key])
        market_consensus[key] = consensus
        comparison.append({
            "key": key,
            "label": LABEL[key],
            "footystats_probability_pct": round(fs_prob[key] * 100, 1),
            "forebet_probability_pct": round(fb_prob[key] * 100, 1),
            "combined_probability_pct": round(fused[key] * 100, 1),
            "difference_pp": consensus["difference_pp"],
            "consensus": consensus["status"],
            "footystats_weight_pct": round(weight_info[family]["footystats"] * 100, 1),
            "forebet_weight_pct": round(weight_info[family]["forebet"] * 100, 1),
        })

    top_consensus = market_consensus[fused_top]
    score_support = _score_supports_market(forebet, fused_top)
    goal_environment = _goal_environment(result, forebet)
    hard_failures = _severe_guardrail_failure(result)
    play_blockers = list(hard_failures)

    if fused_probability < 0.65:
        play_blockers.append("gemeinsame Wahrscheinlichkeit unter 65 %")
    if top_consensus["status"] != "HOCH":
        play_blockers.append("kein hoher FootyStats/Forebet-Konsens im Top-Markt")
    if score_support == "NEIN":
        play_blockers.append("Forebet-Ergebnistipp widerspricht dem gemeinsamen Top-Markt")
    if fused_top in {"over_2_5", "under_2_5", "btts_yes", "btts_no"} and goal_environment.get("status") == "NIEDRIG":
        play_blockers.append("Tor-Umfeld zwischen FootyStats-xG und Forebet deutlich uneinig")

    if fused_probability < 0.60 or top_consensus["difference_pp"] >= 18.0 or "Result-vs-Underlying stark widersprüchlich" in hard_failures:
        final_decision = "AUSLASSEN"
    elif not play_blockers:
        final_decision = "SPIELEN"
    else:
        final_decision = "BEOBACHTEN"

    footystats_snapshot = {
        "version": result.get("model_version") or "0.4.0",
        "probabilities": fs_prob,
        "markets": list(result.get("markets") or []),
        "strongest_market": dict(result.get("strongest_market") or {}),
        "decision_after_guardrails": result.get("decision"),
        "expected_goals": result.get("expected_goals"),
    }

    result["footystats_model"] = footystats_snapshot
    result["forebet_model"] = forebet
    result["probabilities"] = fused
    result["markets"] = [
        {"rank": index + 1, "key": key, "label": LABEL[key], "probability_pct": round(probability * 100, 1)}
        for index, (key, probability) in enumerate(ranking)
    ]
    result["strongest_market"] = {
        "key": fused_top,
        "label": LABEL[fused_top],
        "probability_pct": round(fused_probability * 100, 1),
    }
    result["second_market"] = {
        "key": ranking[1][0],
        "label": LABEL[ranking[1][0]],
        "probability_pct": round(ranking[1][1] * 100, 1),
    }
    result["decision_before_forebet_ensemble"] = result.get("decision")
    result["decision"] = final_decision
    result["ensemble"] = {
        "active": True,
        "method": "datenqualitätsgewichteter logarithmischer Opinion-Pool",
        "weights": weight_info,
        "backtested_weights": False,
        "weighting_note": "Die Gewichte sind transparente Engineering-Priors aus FootyStats-Datenqualität/Robustheit und Forebet-interner Konsistenz; sie sind noch nicht ergebnisbasiert backtest-kalibriert.",
        "market_comparison": comparison,
        "market_consensus": market_consensus,
        "footystats_top_market": fs_top,
        "forebet_top_market": fb_top,
        "combined_top_market": fused_top,
        "top_market_agreement": fs_top == fb_top == fused_top,
        "top_market_difference_pp": top_consensus["difference_pp"],
        "agreement_status": top_consensus["status"],
        "forebet_score_supports_top_market": score_support,
        "goal_environment": goal_environment,
        "play_blockers": play_blockers,
        "decision_rule": "SPIELEN erst ab 65 % gemeinsam, hohem Konsens, ohne schwere FootyStats-Guardrail-Fehler und ohne Widerspruch des Forebet-Ergebnistipps; ab 18 PP Modell-Differenz wird ausgelassen.",
        "double_counting_control": "Forebet-Ergebnistipp und Ø-Tore sind nur Kohärenzdiagnostik und werden nicht als zusätzliche unabhängige Stimmen gewichtet.",
    }
    result["method"] = {
        **dict(result.get("method") or {}),
        "forebet_ensemble": True,
        "opinion_pool": "reliability-weighted log pool",
        "odds_used": False,
        "forebet_score_double_counted": False,
    }
    result["model_version"] = "0.6.1-elite-fusion"
    result["notes"] = list(result.get("notes") or []) + [
        "Forebet beeinflusst alle sechs Märkte, aber nicht mehr blind 50/50.",
        "FootyStats-Gewicht folgt Datenqualität, Stichprobe, Robustheit, Result-vs-Underlying und Multi-Block-Abdeckung.",
        "Forebet bleibt bis zu einem echten Backtest ein unkalibriertes externes Modell und kann FootyStats deshalb nicht dominieren.",
        "Forebet-Ergebnistipp und Ø-Tore werden nur zur Kohärenzprüfung genutzt, um Doppelzählung zu vermeiden.",
        "Odds werden vollständig ignoriert.",
    ]
    return result
