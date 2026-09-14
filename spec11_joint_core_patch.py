"""Joint Outcome Core for SPEC v1.1 / Engine v1.1.6.

This patch fuses the complete five-source pre-match evidence into one coherent
score distribution. Every available MATCH, LEAGUE, FORM, TABLE and PLAYER block
updates the normalized score matrix without inventing missing values.
"""
from __future__ import annotations

import math
import time
from typing import Any, Dict, List, Tuple

import spec11_cross_market_normalization_patch as current
import spec11_native_engine as native

ENGINE_NAME = "FOOTYSTATS_SPEC_V1_1_FULL5_JOINT_OUTCOME"
ENGINE_VERSION = "1.1.6-full5-joint-outcome"
MARKETS = ("home_win", "draw", "away_win", "btts_yes", "btts_no", "over_2_5", "under_2_5")
LABELS = {
    "home_win": "Sieg Heim", "draw": "Unentschieden", "away_win": "Sieg Auswärts",
    "btts_yes": "BTTS Yes", "btts_no": "BTTS No",
    "over_2_5": "Over 2,5", "under_2_5": "Under 2,5",
}
CALIBRATION = {
    "over_2_5": (48, 63),
    "btts_yes": (115, 194),
    "under_2_5": (12, 20),
}


def _num(value: Any):
    return native._num(value)


def _stats(team: Dict[str, Any]) -> Dict[str, Any]:
    stats = (team or {}).get("stats")
    return stats if isinstance(stats, dict) else (team or {})


def _metric(team: Dict[str, Any], name: str, split: str):
    return _num(_stats(team).get(f"{name}_{split}"))


def _matches(team: Dict[str, Any], split: str):
    return _metric(team, "seasonMatchesPlayed", split)


def _league_rows(teams: List[Dict[str, Any]], name: str, split: str) -> List[Tuple[float, float]]:
    rows = []
    for team in teams:
        value, exposure = _metric(team, name, split), _matches(team, split)
        if value is not None and exposure is not None and value >= 0 and exposure > 0:
            rows.append((float(value), float(exposure)))
    return rows


def _weighted_mean(rows: List[Tuple[float, float]]) -> float:
    total = sum(weight for _, weight in rows)
    if len(rows) < 2 or total <= 0:
        raise ValueError("Zu wenige Liga-Zeilen für Joint-Core Partial Pooling.")
    return sum(value * weight for value, weight in rows) / total


def empirical_bayes_rate(value: float, exposure: float, rows: List[Tuple[float, float]]) -> Dict[str, float]:
    if value is None or exposure is None or value < 0 or exposure <= 0:
        raise ValueError("Venue-xG oder zugehörige Stichprobe fehlt.")
    mean = _weighted_mean(rows)
    total = sum(weight for _, weight in rows)
    variance = sum(weight * (row_value - mean) ** 2 for row_value, weight in rows) / total
    if variance <= 1e-10:
        posterior, prior_exposure, reliability = mean, 0.0, 1.0
    else:
        prior_shape = mean * mean / variance
        prior_exposure = mean / variance
        posterior = (exposure * value + prior_shape) / (exposure + prior_exposure)
        reliability = exposure / (exposure + prior_exposure)
    return {
        "raw": float(value), "matches": float(exposure), "league_mean": float(mean),
        "variance": float(variance), "prior_exposure": float(prior_exposure),
        "reliability": float(reliability), "shrunk": float(posterior),
    }


def _component(teams, team, metric, split):
    rows = _league_rows(teams, metric, split)
    return empirical_bayes_rate(_metric(team, metric, split), _matches(team, split), rows)


def joint_lambdas(match: Dict[str, Any], teams: List[Dict[str, Any]], home_team: Dict[str, Any], away_team: Dict[str, Any]):
    components = {
        "home_attack": _component(teams, home_team, "xg_for_avg", "home"),
        "away_defence": _component(teams, away_team, "xg_against_avg", "away"),
        "away_attack": _component(teams, away_team, "xg_for_avg", "away"),
        "home_defence": _component(teams, home_team, "xg_against_avg", "home"),
    }
    ha, ad = components["home_attack"]["shrunk"], components["away_defence"]["shrunk"]
    aa, hd = components["away_attack"]["shrunk"], components["home_defence"]["shrunk"]
    variants = {
        "attack": (ha, aa),
        "geometric": (math.sqrt(ha * ad), math.sqrt(aa * hd)),
        "arithmetic": ((ha + ad) / 2.0, (aa + hd) / 2.0),
        "harmonic": (2.0 / (1.0 / ha + 1.0 / ad), 2.0 / (1.0 / aa + 1.0 / hd)),
    }
    total_anchor = _num(match.get("total_xg_prematch"))
    anchored = total_anchor is not None and total_anchor > 0
    lambdas = {}
    for name, (home_strength, away_strength) in variants.items():
        total = total_anchor if anchored else home_strength + away_strength
        home_lambda = total * home_strength / (home_strength + away_strength)
        lambdas[name] = (max(0.05, home_lambda), max(0.05, total - home_lambda))
    return lambdas, components, {"value": total_anchor, "used": anchored}


def score_probabilities(home_lambda: float, away_lambda: float, cap: int = 14) -> Dict[str, float]:
    home = [math.exp(-home_lambda) * home_lambda ** i / math.factorial(i) for i in range(cap + 1)]
    away = [math.exp(-away_lambda) * away_lambda ** j / math.factorial(j) for j in range(cap + 1)]
    mass = sum(home) * sum(away)
    result = {market: 0.0 for market in MARKETS}
    for i, hp in enumerate(home):
        for j, ap in enumerate(away):
            probability = hp * ap / mass
            if i > j:
                result["home_win"] += probability
            elif i == j:
                result["draw"] += probability
            else:
                result["away_win"] += probability
            if i > 0 and j > 0:
                result["btts_yes"] += probability
            if i + j >= 3:
                result["over_2_5"] += probability
    result["btts_no"] = 1.0 - result["btts_yes"]
    result["under_2_5"] = 1.0 - result["over_2_5"]
    return result


CENTRAL_EVIDENCE_SOURCES = ("MATCH", "LEAGUE", "FORM", "TABLE", "PLAYER")
_STATUS_VALUE = {
    native.SUPPORT: 1.0,
    native.CONTRADICT: -1.0,
    native.NEUTRAL: 0.0,
}


def full5_evidence_tilts(evidence: Dict[str, Any]):
    """Convert every available central source into coherent score-matrix tilts.

    Each source contributes at most one averaged vote per market. Dividing by
    the five expected sources makes missing data reduce impact continuously and
    prevents sources with more raw fields from dominating.
    """
    market_rows = {row.get("key"): row for row in evidence.get("markets", [])}
    market_scores: Dict[str, float] = {}
    source_audit: Dict[str, Any] = {}

    for market in MARKETS:
        signals = market_rows.get(market, {}).get("signals") or []
        by_source: Dict[str, List[float]] = {source: [] for source in CENTRAL_EVIDENCE_SOURCES}
        for signal in signals:
            source = signal.get("source")
            value = _STATUS_VALUE.get(signal.get("status"))
            if source in by_source and value is not None:
                by_source[source].append(value)

        per_source = {
            source: (sum(values) / len(values))
            for source, values in by_source.items()
            if values
        }
        # Five-source denominator is intentional: unavailable sources contribute
        # no invented value and reduce the evidence impact rather than becoming 0-strength.
        score = sum(per_source.values()) / len(CENTRAL_EVIDENCE_SOURCES)
        market_scores[market] = score
        source_audit[market] = {
            "per_source": {source: round(value, 8) for source, value in per_source.items()},
            "available_sources": sorted(per_source),
            "available_source_count": len(per_source),
            "five_source_score": round(score, 8),
        }

    result_mean = sum(market_scores[m] for m in ("home_win", "draw", "away_win")) / 3.0
    btts_contrast = (market_scores["btts_yes"] - market_scores["btts_no"]) / 2.0
    goals_contrast = (market_scores["over_2_5"] - market_scores["under_2_5"]) / 2.0
    theta = {
        "home_win": market_scores["home_win"] - result_mean,
        "draw": market_scores["draw"] - result_mean,
        "away_win": market_scores["away_win"] - result_mean,
        "btts_yes": btts_contrast,
        "btts_no": -btts_contrast,
        "over_2_5": goals_contrast,
        "under_2_5": -goals_contrast,
    }
    return theta, {
        "sources": list(CENTRAL_EVIDENCE_SOURCES),
        "market_scores": {key: round(value, 8) for key, value in market_scores.items()},
        "source_detail": source_audit,
        "method": "ONE_AVERAGED_VOTE_PER_SOURCE_THEN_EXPONENTIAL_SCORE_MATRIX_TILT",
        "missing_policy": "NO_IMPUTATION; missing source lowers five-source evidence magnitude",
    }


def tilted_score_probabilities(home_lambda: float, away_lambda: float, theta: Dict[str, float], cap: int = 14):
    """Exponentially tilt score states, preserving one normalized joint distribution."""
    home = [math.exp(-home_lambda) * home_lambda ** i / math.factorial(i) for i in range(cap + 1)]
    away = [math.exp(-away_lambda) * away_lambda ** j / math.factorial(j) for j in range(cap + 1)]
    weighted: List[Tuple[int, int, float]] = []
    for i, hp in enumerate(home):
        for j, ap in enumerate(away):
            result_market = "home_win" if i > j else ("draw" if i == j else "away_win")
            btts_market = "btts_yes" if i > 0 and j > 0 else "btts_no"
            goals_market = "over_2_5" if i + j >= 3 else "under_2_5"
            log_tilt = theta[result_market] + theta[btts_market] + theta[goals_market]
            weighted.append((i, j, hp * ap * math.exp(log_tilt)))

    mass = sum(value for _, _, value in weighted)
    result = {market: 0.0 for market in MARKETS}
    for i, j, value in weighted:
        probability = value / mass
        if i > j:
            result["home_win"] += probability
        elif i == j:
            result["draw"] += probability
        else:
            result["away_win"] += probability
        if i > 0 and j > 0:
            result["btts_yes"] += probability
        if i + j >= 3:
            result["over_2_5"] += probability
    result["btts_no"] = 1.0 - result["btts_yes"]
    result["under_2_5"] = 1.0 - result["over_2_5"]
    return result


def average_markets(variant_probabilities: Dict[str, Dict[str, float]]) -> Dict[str, float]:
    return {
        market: sum(row[market] for row in variant_probabilities.values()) / len(variant_probabilities)
        for market in MARKETS
    }


def wilson_lower(hits: int, trials: int, z: float = 1.95996398454) -> float:
    p = hits / trials
    denominator = 1.0 + z * z / trials
    return (p + z * z / (2.0 * trials) - z * math.sqrt(p * (1.0 - p) / trials + z * z / (4.0 * trials * trials))) / denominator


def conservative_market_ranking():
    rows = []
    for market, (hits, trials) in CALIBRATION.items():
        rows.append({
            "market": market, "hits": hits, "trials": trials,
            "hit_rate": hits / trials, "wilson_lower_95": wilson_lower(hits, trials),
        })
    return sorted(rows, key=lambda row: row["wilson_lower_95"], reverse=True)


def uncertainty_action(selected_market: str):
    ranking = conservative_market_ranking()
    calibrated = {row["market"] for row in ranking}
    if selected_market == ranking[0]["market"]:
        return "SPIELEN", "Höchster konservativer marktbezogener OOF-Rang; keine manuelle Wahrscheinlichkeitsschwelle."
    if selected_market in calibrated:
        return "BEOBACHTEN", "Historisch OOF-kalibriert, aber nicht stärkster konservativer Marktrang."
    return "AUSLASSEN", "Für diesen Joint-Rang-1-Markt fehlt eine historische OOF-Auswahlbasis."


def apply_patch(legacy: Any) -> Any:
    app = current.apply_patch(legacy)
    base_analyze = legacy._analyze_bundle

    def analyze_joint(parsed_files: List[Dict[str, Any]]) -> Dict[str, Any]:
        evidence = base_analyze(parsed_files)
        if not isinstance(evidence, dict) or not evidence.get("ok"):
            return evidence

        pair = native._pair(parsed_files)
        files, match, identity = pair["files"], pair["match"], pair["identity"]
        teams = native._league_team_rows(files["league"]["data"])
        home_team = native._team_by_id(teams, identity["home_id"])
        away_team = native._team_by_id(teams, identity["away_id"])
        if home_team is None or away_team is None:
            return {
                "ok": False, "phase": "JOINT_CORE_TEAM_PAIRING_FAILED",
                "error": "Joint-Core kann die beiden Zielteams nicht eindeutig der Liga zuordnen.",
                "fallback_used": False,
            }

        try:
            lambdas, components, total_anchor = joint_lambdas(match, teams, home_team, away_team)
        except ValueError as exc:
            return {
                "ok": False, "phase": "JOINT_CORE_INPUT_FAILED", "error": str(exc),
                "fallback_used": False, "evidence_diagnostic": evidence,
            }

        base_variants = {name: score_probabilities(*values) for name, values in lambdas.items()}
        base_probabilities = average_markets(base_variants)
        evidence_tilts, evidence_fusion = full5_evidence_tilts(evidence)
        variants = {
            name: tilted_score_probabilities(*values, evidence_tilts)
            for name, values in lambdas.items()
        }
        probabilities = average_markets(variants)
        selected = max(MARKETS, key=lambda market: probabilities[market])
        action, action_reason = uncertainty_action(selected)
        ranked = sorted(
            [{"key": market, "label": LABELS[market], "probability": probabilities[market]} for market in MARKETS],
            key=lambda row: row["probability"], reverse=True,
        )
        for rank, row in enumerate(ranked, 1):
            row["rank"] = rank

        diagnostic_market = next((row for row in evidence.get("markets", []) if row.get("key") == selected), {})
        strongest = dict(diagnostic_market)
        strongest.update({
            "key": selected, "label": LABELS[selected],
            "joint_probability": round(probabilities[selected], 8),
            "clear_lead": action == "SPIELEN", "decision_action": action,
        })

        result = dict(evidence)
        result.update({
            "engine": ENGINE_NAME,
            "engine_version": ENGINE_VERSION,
            "analysis_type": "SPEC_V1_1_FULL5_JOINT_OUTCOME",
            "decision": action,
            "recommendation": LABELS[selected] if action != "AUSLASSEN" else "KEIN BET",
            "recommendation_reason": f"{LABELS[selected]} ist Rang 1 der gemeinsamen Ergebnismatrix. {action_reason}",
            "strongest_market": strongest,
            "joint_outcome": {
                "selected_market": selected,
                "selected_label": LABELS[selected],
                "action": action,
                "action_reason": action_reason,
                "probabilities": {key: round(value, 8) for key, value in probabilities.items()},
                "base_probabilities_before_full5": {
                    key: round(value, 8) for key, value in base_probabilities.items()
                },
                "full5_evidence_tilts": {
                    key: round(value, 8) for key, value in evidence_tilts.items()
                },
                "full5_evidence_fusion": evidence_fusion,
                "ranked_markets": ranked,
                "variant_lambdas": {
                    name: {"home": round(values[0], 8), "away": round(values[1], 8)}
                    for name, values in lambdas.items()
                },
                "variant_probabilities": variants,
                "partial_pooling": components,
                "total_xg_anchor": total_anchor,
                "calibration_ranking": conservative_market_ranking(),
            },
            "evidence_diagnostic": {
                "strongest_market": evidence.get("strongest_market"),
                "recommendation": evidence.get("recommendation"),
                "markets": evidence.get("markets"),
            },
        })
        result.setdefault("method", {}).update({
            "architecture": "SPEC_V1_1_FULL5_JOINT_OUTCOME",
            "probability_core": "JOINT_POISSON_EMPIRICAL_BAYES_FULL5_EXPONENTIAL_TILT",
            "market_selector": "MAXIMUM_COHERENT_JOINT_PROBABILITY",
            "decision_engine": "MARKET_CONDITIONAL_CONSERVATIVE_RANK",
            "manual_probability_threshold": False,
            "historical_residual_layer": False,
            "ml_reranker": False,
            "legacy_signal_ranking_role": "LATENT_SCORE_MATRIX_UPDATE",
            "full5_evidence_in_final_probabilities": True,
            "research_only": False,
        })
        result.setdefault("notes", []).append(
            "Alle fünf zentralen Pre-Match-Quellen aktualisieren die gemeinsame Score-Matrix; das frühere Ranking ist kein separater Entscheider."
        )
        return result

    legacy._analyze_bundle = analyze_joint
    ui_replacements = {
        "SPEC v1.1 · Engine v1.1.6": "SPEC v1.1 · Joint-Outcome Engine",
        "FootyStats 5-Dateien-Auswertung · Build 1.1.6-cross-market-normalized": "FootyStats 5-Dateien-Auswertung · Build 1.1.6-full5-joint-outcome",
        "5 Dateien · vollständige sinnvolle SPEC-v1.1-Signalbreite · verwandte Felder als Evidenzblöcke · unabhängige Quellen zuerst · COLD START/LOW SAMPLE erlaubt · kein V0.4.x · kein Fallback · keine Odds · keine Decision Engine.": "Alle 5 Quellen wirken auf die gemeinsame Ergebnismatrix: Match · League · Form · Table · Player · Empirical-Bayes-Shrinkage · 7 konsistente Märkte · SPIELEN/BEOBACHTEN/AUSLASSEN · keine Odds.",
        "SPEC v1.1 / Engine v1.1.6 auswerten": "Joint-Outcome V1.1.6 auswerten",
    }
    for old_text, new_text in ui_replacements.items():
        legacy.INDEX_HTML = legacy.INDEX_HTML.replace(old_text, new_text)

    app.router.routes = [route for route in app.router.routes if getattr(route, "path", None) != "/api/health"]

    def health():
        return {
            "ok": True, "production": True, "research_only": False,
            "engine": ENGINE_NAME, "version": ENGINE_VERSION, "spec_version": "1.1",
            "architecture": "SPEC_V1_1_FULL5_JOINT_OUTCOME",
            "probability_core": "JOINT_POISSON_EMPIRICAL_BAYES_FULL5_EXPONENTIAL_TILT",
            "decision_engine": "MARKET_CONDITIONAL_CONSERVATIVE_RANK",
            "manual_probability_threshold": False,
            "legacy_signal_ranking_role": "LATENT_SCORE_MATRIX_UPDATE",
            "full5_evidence_in_final_probabilities": True,
            "render_deployment_authorized": True,
            "shortcut_capture_unix": int(time.time()),
        }

    app.add_api_route("/api/health", health, methods=["GET"])
    app.version = ENGINE_VERSION
    app.title = "FootyStats V1.1.6 Full-5 Joint-Outcome"
    return app
