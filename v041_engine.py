"""FootyStats Prognose Engine V0.4.1 patch layer.

Backtest-driven release built on the frozen V0.4.0 five-file production app.
The legacy web/API/archive surface stays unchanged; this module replaces only
model, evidence and decision logic.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

VERSION = "0.4.1"
PRIOR_EXPOSURE_CAP = 2.0
RAW_CORE_WEIGHT = 0.85
LEAGUE_CORE_WEIGHT = 0.15


def _safe_num(legacy: Any, value: Any) -> Optional[float]:
    try:
        return legacy.num(value)
    except Exception:
        return None


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _log_blend(a: float, b: float, wa: float = RAW_CORE_WEIGHT) -> float:
    """Geometric blend keeps positive lambdas and avoids additive scale bias."""
    a = max(1e-6, float(a)); b = max(1e-6, float(b))
    return math.exp(wa * math.log(a) + (1.0 - wa) * math.log(b))


def _family_strength(probability: float, family_size: int) -> float:
    """Normalize conviction relative to a neutral family baseline.

    Binary 65% -> 0.30. Three-way 53.33% -> 0.30.
    """
    neutral = 1.0 / family_size
    return _clamp((probability - neutral) / (1.0 - neutral), 0.0, 1.0)


def _select_family(probabilities: Dict[str, float]) -> Dict[str, Any]:
    home = float(probabilities["home_win"]); draw = float(probabilities["draw"]); away = float(probabilities["away_win"])
    win_key, win_p = max((("home_win", home), ("away_win", away)), key=lambda item: item[1])
    win_strength = _family_strength(win_p, 3) if win_p >= draw else 0.0
    btts_key, btts_p = max((("btts_yes", float(probabilities["btts_yes"])), ("btts_no", float(probabilities["btts_no"]))), key=lambda item: item[1])
    ou_key, ou_p = max((("over_2_5", float(probabilities["over_2_5"])), ("under_2_5", float(probabilities["under_2_5"]))), key=lambda item: item[1])
    families = [
        {"family": "1X2", "key": win_key, "probability": win_p, "strength": win_strength,
         "comparison": {"home_win": home, "draw": draw, "away_win": away}},
        {"family": "BTTS", "key": btts_key, "probability": btts_p, "strength": _family_strength(btts_p, 2),
         "comparison": {"btts_yes": probabilities["btts_yes"], "btts_no": probabilities["btts_no"]}},
        {"family": "OU_2_5", "key": ou_key, "probability": ou_p, "strength": _family_strength(ou_p, 2),
         "comparison": {"over_2_5": probabilities["over_2_5"], "under_2_5": probabilities["under_2_5"]}},
    ]
    selected = max(families, key=lambda item: (item["strength"], item["probability"]))
    return {"selected": selected, "families": families}


def _family_margin(probabilities: Dict[str, float], selected: Dict[str, Any]) -> float:
    key = selected["key"]
    if selected["family"] == "1X2":
        rivals = [probabilities[k] for k in ("home_win", "draw", "away_win") if k != key]
        return float(probabilities[key]) - max(float(v) for v in rivals)
    if selected["family"] == "BTTS":
        other = "btts_no" if key == "btts_yes" else "btts_yes"
    else:
        other = "under_2_5" if key == "over_2_5" else "over_2_5"
    return float(probabilities[key]) - float(probabilities[other])


def _family_edge_label(strength: float) -> str:
    if strength >= 0.30: return "KLAR"
    if strength >= 0.20: return "KNAPP"
    return "NICHT VORHANDEN"


def _league_shrunk_rate(legacy: Any, rate: Any, matches: Any, rows: List[Tuple[float, float]], league_mean: float) -> Dict[str, Any]:
    rate = _safe_num(legacy, rate); matches = _safe_num(legacy, matches)
    if rate is None or matches is None or rate < 0 or matches <= 0:
        raise ValueError("Zentraler Venue-xG-Wert oder seine Stichprobe fehlt.")
    total_weight = sum(weight for _, weight in rows)
    if len(rows) < 2 or total_weight <= 0:
        raise ValueError("Zu wenige Liga-Teams für datenabhängiges Shrinkage.")
    variance = sum(weight * (value - league_mean) ** 2 for value, weight in rows) / total_weight
    if variance <= 1e-10:
        posterior = league_mean; raw_prior_exposure = None; prior_exposure = None; reliability = 1.0
    else:
        raw_prior_exposure = league_mean / variance
        prior_exposure = min(float(raw_prior_exposure), PRIOR_EXPOSURE_CAP)
        prior_shape = league_mean * prior_exposure
        posterior = (matches * rate + prior_shape) / (matches + prior_exposure)
        reliability = matches / (matches + prior_exposure)
    return {"raw": float(rate), "league_mean": float(league_mean), "matches": float(matches),
            "variance": float(variance), "raw_prior_exposure": raw_prior_exposure,
            "prior_exposure": prior_exposure, "prior_exposure_cap": PRIOR_EXPOSURE_CAP,
            "reliability": float(reliability), "shrunk": float(posterior)}


def _worldwide_lambdas(legacy: Any, home_team: Any, away_team: Any, league: Any, neutralize: Optional[str] = None) -> Tuple[float, float, Dict[str, Any]]:
    teams = legacy.league_team_list(league)
    specs = {"home_xg": ("home", "xg"), "away_xg": ("away", "xg"), "home_xga": ("home", "xga"), "away_xga": ("away", "xga")}
    rows = {name: legacy.league_metric_rows(teams, *spec) for name, spec in specs.items()}
    baseline = {name: legacy.weighted_league_mean(metric_rows) for name, metric_rows in rows.items()}
    required = {
        "home_attack": (legacy.tnum(home_team, "xg", "home"), legacy.tnum(home_team, "matches", "home"), "home_xg"),
        "away_defence": (legacy.tnum(away_team, "xga", "away"), legacy.tnum(away_team, "matches", "away"), "away_xga"),
        "away_attack": (legacy.tnum(away_team, "xg", "away"), legacy.tnum(away_team, "matches", "away"), "away_xg"),
        "home_defence": (legacy.tnum(home_team, "xga", "home"), legacy.tnum(home_team, "matches", "home"), "home_xga"),
    }
    pooled: Dict[str, Any] = {}
    for name, (rate, matches, base_name) in required.items():
        pooled[name] = _league_shrunk_rate(legacy, rate, matches, rows[base_name], baseline[base_name])
    ratios = {
        "home_attack": pooled["home_attack"]["shrunk"] / baseline["home_xg"],
        "away_defence": pooled["away_defence"]["shrunk"] / baseline["away_xga"],
        "away_attack": pooled["away_attack"]["shrunk"] / baseline["away_xg"],
        "home_defence": pooled["home_defence"]["shrunk"] / baseline["home_xga"],
    }
    if neutralize in ratios: ratios[neutralize] = 1.0
    home_lambda = baseline["home_xg"] * ratios["home_attack"] * ratios["away_defence"]
    away_lambda = baseline["away_xg"] * ratios["away_attack"] * ratios["home_defence"]
    if not (math.isfinite(home_lambda) and math.isfinite(away_lambda)) or home_lambda <= 0 or away_lambda <= 0:
        raise ValueError("Liga-relative erwartete Tore sind nicht gültig.")
    detail = {
        "method": "V0.4.1 hybrid: raw-team core + capped league-relative empirical-Bayes Poisson",
        "league_team_count": len(teams),
        "league_baselines": {key: round(value, 6) for key, value in baseline.items()},
        "partial_pooling": {key: {k: (round(v, 6) if isinstance(v, (int, float)) else v) for k, v in vals.items()} for key, vals in pooled.items()},
        "relative_strengths": {key: round(value, 6) for key, value in ratios.items()},
        "neutralized_block": neutralize, "prior_exposure_cap": PRIOR_EXPOSURE_CAP,
        "fixed_global_thresholds_used": False, "dixon_coles_fitted": False,
    }
    return home_lambda, away_lambda, detail


def _hybrid_lambdas(legacy: Any, h_profile: Dict[str, Any], a_profile: Dict[str, Any], match_fields: Dict[str, Any], home_team: Any, away_team: Any, league: Any, neutralize: Optional[str] = None) -> Tuple[float, float, Dict[str, Any]]:
    world_h, world_a, world = _worldwide_lambdas(legacy, home_team, away_team, league, neutralize=neutralize)
    raw_available = True
    try:
        raw_h, raw_a = legacy.lambdas(h_profile, a_profile, match_fields)
    except Exception:
        raw_h, raw_a = world_h, world_a; raw_available = False
    home_lambda = _log_blend(raw_h, world_h, RAW_CORE_WEIGHT)
    away_lambda = _log_blend(raw_a, world_a, RAW_CORE_WEIGHT)
    detail = dict(world)
    detail.update({"raw_core_available": raw_available,
                   "raw_core_expected_goals": {"home": round(raw_h, 6), "away": round(raw_a, 6)},
                   "capped_league_core_expected_goals": {"home": round(world_h, 6), "away": round(world_a, 6)},
                   "hybrid_weights": {"raw_team_core": RAW_CORE_WEIGHT, "capped_league_core": LEAGUE_CORE_WEIGHT}})
    return home_lambda, away_lambda, detail


def _kickoff_integrity(legacy: Any, match_data: Any) -> Dict[str, Any]:
    kickoff = legacy.firstnum(match_data, ["date_unix", "dateUnix", "kickoff_unix", "kickoff_timestamp"])
    if kickoff is None:
        return {"kickoff_unix": None, "kickoff_at": None, "checked_at": datetime.now(timezone.utc).isoformat(), "strict_pre_match": None, "status": "NICHT PRÜFBAR"}
    now = datetime.now(timezone.utc); kickoff_dt = datetime.fromtimestamp(float(kickoff), tz=timezone.utc)
    strict = now.timestamp() < float(kickoff)
    return {"kickoff_unix": int(kickoff), "kickoff_at": kickoff_dt.isoformat(), "checked_at": now.isoformat(),
            "strict_pre_match": strict, "minutes_to_kickoff": round((float(kickoff) - now.timestamp()) / 60.0, 1),
            "status": "BESTANDEN" if strict else "NICHT BESTANDEN"}


def predict_v041(legacy: Any, match: Any, league: Any) -> Dict[str, Any]:
    a = legacy.audit(match, league)
    if not a["valid"]:
        return {"ok": False, "model_version": VERSION, "phase": "DATA_AUDIT_FAILED", "audit": {k: v for k, v in a.items() if k not in {"home_team", "away_team"}}, "decision": "ANALYSE NICHT MÖGLICH"}
    m = a["match"]
    kickoff_meta = _kickoff_integrity(legacy, match)
    if m.get("date") in (None, "") and kickoff_meta.get("kickoff_at"): m["date"] = kickoff_meta["kickoff_at"]
    m["date_unix"] = kickoff_meta.get("kickoff_unix")
    h = legacy.profile(a["home_team"], "home"); aw = legacy.profile(a["away_team"], "away")
    sufficient = legacy.insufficient_data_report(m, h, aw)
    if not sufficient["sufficient"]:
        return {"ok": False, "model_version": VERSION, "phase": "INSUFFICIENT_DATA", "decision": "ANALYSE NICHT MÖGLICH",
                "error": "Zu wenig belastbare historische Teamdaten für eine seriöse Marktprognose.",
                "audit": {"valid": True, "errors": [], "match": m, "pager": a["pager"]}, "samples": sufficient["samples"],
                "pre_match_integrity": kickoff_meta,
                "diagnostics": {"data_quality": "NIEDRIG", "sample_security": "NIEDRIG", "relative_edge": "NICHT PRÜFBAR", "robustness_status": "NICHT PRÜFBAR"},
                "insufficient_data": sufficient, "notes": ["Keine künstlichen Mindestwerte verwendet.", "Odds werden vollständig ignoriert."]}
    hn, an = h["home"]["matches"], aw["away"]["matches"]; ho, ao = h["overall"]["matches"], aw["overall"]["matches"]
    sample_security = legacy.sample(hn, an, ho, ao); quality = "HOCH"
    if not hn or not an: quality = "MITTEL"
    if sum(x is not None for x in [h["overall"]["xg"], h["overall"]["xga"], aw["overall"]["xg"], aw["overall"]["xga"]]) < 3: quality = "MITTEL"
    try:
        hl, al, model = _hybrid_lambdas(legacy, h, aw, m, a["home_team"], a["away_team"], league)
    except ValueError as exc:
        return {"ok": False, "model_version": VERSION, "phase": "MODEL_INPUT_FAILED", "audit": {"valid": True, "errors": [str(exc)], "match": m}, "decision": "ANALYSE NICHT MÖGLICH"}
    if model.get("league_team_count", 0) < 6: quality = "MITTEL"
    p = legacy.poisson(hl, al); family = _select_family(p); selected = family["selected"]
    top, top_p, strength = selected["key"], selected["probability"], selected["strength"]
    stress: Dict[str, float] = {}; stress_strength: Dict[str, float] = {}
    for block in ("home_attack", "away_defence", "away_attack", "home_defence"):
        sh, sa, _ = _hybrid_lambdas(legacy, h, aw, m, a["home_team"], a["away_team"], league, neutralize=block)
        sp = legacy.poisson(sh, sa); stress[block] = float(sp[top])
        selected_stress = _select_family(sp)["selected"]
        stress_strength[block] = selected_stress["strength"] if selected_stress["key"] == top else _family_strength(float(sp[top]), 3 if selected["family"] == "1X2" else 2)
    influence_block = max(stress, key=lambda block: abs(stress[block] - top_p))
    pooling = model.get("partial_pooling") or {}
    fragility_block = min(pooling, key=lambda block: _safe_num(legacy, (pooling.get(block) or {}).get("reliability")) if _safe_num(legacy, (pooling.get(block) or {}).get("reliability")) is not None else -1)
    influence_p = stress[influence_block]; fragility_p = stress[fragility_block]
    min_stress_strength = min(stress_strength.values()) if stress_strength else strength
    single_point = (strength - min_stress_strength >= 0.10) or min_stress_strength < 0.20
    robustness = "BESTANDEN" if not single_point and min_stress_strength >= 0.25 else ("EINGESCHRÄNKT" if min_stress_strength >= 0.20 else "NICHT BESTANDEN")
    rv_detail = legacy.rvu_detail(h, aw, top, top_p, hl, al); margin = _family_margin(p, selected); family_edge = _family_edge_label(strength)
    base_decision = "AUSLASSEN" if strength < 0.20 else "BEOBACHTEN"
    labels = legacy.LABEL
    def market_strength(key: str) -> float:
        probability = float(p[key])
        if key in {"home_win", "away_win"}: return _family_strength(probability, 3) if probability >= float(p["draw"]) else 0.0
        return _family_strength(probability, 2)
    market_rows = sorted(((key, float(p[key]), market_strength(key)) for key in ("home_win", "away_win", "btts_yes", "btts_no", "over_2_5", "under_2_5")), key=lambda item: (item[2], item[1]), reverse=True)
    return {
        "ok": True, "model_version": VERSION, "deterministic": True,
        "method": {"probability_core": model["method"], "league_relative": True, "empirical_bayes_shrinkage": True,
                   "prior_exposure_cap": PRIOR_EXPOSURE_CAP, "raw_team_core_weight": RAW_CORE_WEIGHT, "league_core_weight": LEAGUE_CORE_WEIGHT,
                   "market_family_normalization": True, "odds_used": False, "backtest_reference": "137 strict pre-match V0.4.0 snapshots / 180 unique results"},
        "audit": {"valid": True, "errors": [], "match": m, "pager": a["pager"]}, "pre_match_integrity": kickoff_meta,
        "samples": {"home_venue": hn, "home_class": legacy.sclass(hn), "away_venue": an, "away_class": legacy.sclass(an), "security": sample_security},
        "expected_goals": {"home": hl, "away": al, "total": hl + al, "hybrid_model": model}, "probabilities": p,
        "market_families": {"selected": {**selected, "probability_pct": round(top_p * 100, 1), "strength_pct": round(strength * 100, 1)},
                            "all": [{**item, "probability_pct": round(item["probability"] * 100, 1), "strength_pct": round(item["strength"] * 100, 1)} for item in family["families"]]},
        "markets": [{"rank": i + 1, "key": key, "label": labels[key], "probability_pct": round(prob * 100, 1), "family_strength_pct": round(ms * 100, 1)} for i, (key, prob, ms) in enumerate(market_rows)],
        "strongest_market": {"key": top, "label": labels[top], "probability_pct": round(top_p * 100, 1), "family": selected["family"], "family_strength_pct": round(strength * 100, 1)},
        "second_market": ({"key": market_rows[1][0], "label": labels[market_rows[1][0]], "probability_pct": round(market_rows[1][1] * 100, 1), "family_strength_pct": round(market_rows[1][2] * 100, 1)} if len(market_rows) > 1 else None),
        "diagnostics": {"data_quality": quality, "sample_security": sample_security, "result_vs_underlying": rv_detail["status"], "result_vs_underlying_detail": rv_detail,
                        "relative_edge": family_edge, "family_margin_pp": round(margin * 100, 1), "family_strength_pct": round(strength * 100, 1),
                        "single_point_of_failure": single_point, "influence_block": influence_block, "fragility_block": fragility_block,
                        "influence_stress_probability_pct": round(influence_p * 100, 1), "fragility_stress_probability_pct": round(fragility_p * 100, 1),
                        "all_central_block_stress": {key: round(value * 100, 1) for key, value in stress.items()},
                        "stress_family_strength_pct": {key: round(value * 100, 1) for key, value in stress_strength.items()},
                        "robustness_status": robustness, "insufficient_data_gate": "BESTANDEN"},
        "decision": base_decision,
        "notes": ["Odds werden vollständig ignoriert.", "Alle Markt-Basiswahrscheinlichkeiten stammen aus einem kohärenten Hybrid-Poisson-Scoregrid.",
                  "1X2, BTTS und O/U werden vor der finalen Auswahl familiennormalisiert statt roh gegeneinander gerankt.",
                  "V0.4.1 nutzt capped Shrinkage und einen backtestgestützten Secondary Team Core."]}


def _window(team: Dict[str, Any], sample: int) -> Dict[str, Any]: return ((team.get("windows") or {}).get(str(sample)) or {})
def _signal(status: str, reason: str, score: Optional[float] = None) -> Dict[str, Any]: return {"status": status, "reason": reason, "score": round(score, 3) if score is not None else None}


def _form_signal(report: Dict[str, Any], market: str) -> Dict[str, Any]:
    form = ((report.get("coverage") or {}).get("form") or {}); home, away = form.get("home") or {}, form.get("away") or {}
    if not (home.get("available") and away.get("available")): return _signal("NICHT VERFÜGBAR", "FormDaten nicht für beide Teams verfügbar.")
    h10, a10 = _window(home, 10) or home.get("reference") or {}, _window(away, 10) or away.get("reference") or {}
    h5, a5 = _window(home, 5) or home.get("recent_5") or {}, _window(away, 5) or away.get("recent_5") or {}
    if market in {"home_win", "away_win"}:
        vals = [h10.get("xg"), h10.get("xga"), a10.get("xg"), a10.get("xga")]
        if any(v is None for v in vals): return _signal("NICHT VERFÜGBAR", "Last-10 xG/xGA unvollständig.")
        diff = (float(h10["xg"]) - float(h10["xga"])) - (float(a10["xg"]) - float(a10["xga"]))
        if market == "away_win": diff = -diff
        if all(v is not None for v in [h5.get("xg"), h5.get("xga"), a5.get("xg"), a5.get("xga")]):
            recent = (float(h5["xg"]) - float(h5["xga"])) - (float(a5["xg"]) - float(a5["xga"]))
            if market == "away_win": recent = -recent
            diff = 0.75 * diff + 0.25 * recent
        return _signal("BESTÄTIGEND" if diff >= 0.25 else ("GEGENARGUMENT" if diff <= -0.25 else "NEUTRAL"), "Form-Level Last10 plus Last5-Momentum als EIN Formblock.", diff)
    if market in {"btts_yes", "btts_no"}:
        vals = [h10.get("btts_pct"), a10.get("btts_pct")]
        if any(v is None for v in vals): return _signal("NICHT VERFÜGBAR", "Last-10 BTTS fehlt.")
        q = (float(vals[0]) + float(vals[1])) / 200.0
        if market == "btts_no": q = 1.0 - q
    else:
        vals = [h10.get("over_25_pct"), a10.get("over_25_pct")]
        if any(v is None for v in vals): return _signal("NICHT VERFÜGBAR", "Last-10 O/U fehlt.")
        q = (float(vals[0]) + float(vals[1])) / 200.0
        if market == "under_2_5": q = 1.0 - q
    return _signal("BESTÄTIGEND" if q >= 0.60 else ("GEGENARGUMENT" if q <= 0.40 else "NEUTRAL"), "Last10 als Form-Level; Last5/6/10 werden nicht mehrfach gezählt.", q)


def _match_signal(legacy: Any, result: Dict[str, Any], market: str) -> Dict[str, Any]:
    m = ((result.get("audit") or {}).get("match") or {})
    hp, ap = _safe_num(legacy, m.get("home_prematch_xg")), _safe_num(legacy, m.get("away_prematch_xg"))
    hppg, appg = _safe_num(legacy, m.get("pre_match_home_ppg")), _safe_num(legacy, m.get("pre_match_away_ppg"))
    total = _safe_num(legacy, m.get("total_prematch_xg"))
    if total is None and hp is not None and ap is not None: total = hp + ap
    if market in {"home_win", "away_win"}:
        if hppg is None or appg is None: return _signal("NICHT VERFÜGBAR", "Pre-Match PPG fehlt.")
        diff = hppg - appg
        if market == "away_win": diff = -diff
        return _signal("BESTÄTIGEND" if diff >= 0.35 else ("GEGENARGUMENT" if diff <= -0.35 else "NEUTRAL"), "FootyStats Pre-Match-PPG als Match-Kontext.", diff)
    if market in {"over_2_5", "under_2_5"}:
        if total is None: return _signal("NICHT VERFÜGBAR", "Total Pre-Match-xG fehlt.")
        score = total if market == "over_2_5" else -total
        if market == "over_2_5": status = "BESTÄTIGEND" if total >= 2.8 else ("GEGENARGUMENT" if total <= 2.2 else "NEUTRAL")
        else: status = "BESTÄTIGEND" if total <= 2.2 else ("GEGENARGUMENT" if total >= 2.8 else "NEUTRAL")
        return _signal(status, "Total Pre-Match-xG; BTTS/O2.5-Potential wird nicht blind eingemischt.", score)
    if hp is None or ap is None: return _signal("NICHT VERFÜGBAR", "Team Pre-Match-xG fehlt.")
    minimum = min(hp, ap)
    if market == "btts_yes": status = "BESTÄTIGEND" if minimum >= 1.0 else ("GEGENARGUMENT" if minimum <= 0.7 else "NEUTRAL")
    else: status = "BESTÄTIGEND" if minimum <= 0.7 else ("GEGENARGUMENT" if minimum >= 1.0 else "NEUTRAL")
    return _signal(status, "Beide Team-Pre-Match-xG statt schwachem BTTS-Potential.", minimum)


def _table_signal(report: Dict[str, Any], market: str) -> Dict[str, Any]:
    if market not in {"home_win", "away_win"}: return _signal("NICHT ANWENDBAR", "TableDaten werden nicht doppelt in BTTS/O-U gewichtet.")
    table = ((report.get("coverage") or {}).get("table") or {}); home, away = table.get("home") or {}, table.get("away") or {}
    if not (home.get("available") and away.get("available")): return _signal("NICHT VERFÜGBAR", "Tabellensplit fehlt.")
    hppg, appg = home.get("ppg"), away.get("ppg")
    if hppg is None or appg is None: return _signal("NICHT VERFÜGBAR", "Tabellen-PPG fehlt.")
    diff = float(hppg) - float(appg)
    if market == "away_win": diff = -diff
    return _signal("BESTÄTIGEND" if diff >= 0.35 else ("GEGENARGUMENT" if diff <= -0.35 else "NEUTRAL"), "Table-Kontext für 1X2; GF/GA/PPG werden nicht als zweiter League-Kern gezählt.", diff)


def _player_signal(report: Dict[str, Any], market: str) -> Dict[str, Any]:
    if market not in {"over_2_5", "under_2_5"}: return _signal("NICHT ANWENDBAR", "PlayerDaten sind in V0.4.1 nur Goal-Intensity-Evidenz für O/U.")
    player = ((report.get("coverage") or {}).get("player") or {}); home, away = player.get("home") or {}, player.get("away") or {}
    if not (home.get("available") and away.get("available")): return _signal("NICHT VERFÜGBAR", "PlayerDaten nicht für beide Teams verfügbar.")
    parts = [home.get("goals_per_90"), away.get("goals_per_90"), home.get("assists_per_90"), away.get("assists_per_90")]
    if any(v is None for v in parts): return _signal("NICHT VERFÜGBAR", "Goal-Intensity unvollständig.")
    intensity = sum(float(v) for v in parts)
    if market == "over_2_5": status = "BESTÄTIGEND" if intensity >= 0.50 else ("GEGENARGUMENT" if intensity <= 0.32 else "NEUTRAL")
    else: status = "BESTÄTIGEND" if intensity <= 0.32 else ("GEGENARGUMENT" if intensity >= 0.50 else "NEUTRAL")
    return _signal(status, "Goals/90 + Assists/90 beider Teams; keine Aufstellungsannahme.", intensity)


def elite_protocol_v041(legacy: Any, result: Dict[str, Any], report: Dict[str, Any]) -> Dict[str, Any]:
    if not result.get("ok"):
        return {"version": VERSION, "phase_1_data_audit": "NICHT BESTANDEN", "phase_2_all_six_markets": "NEIN", "phase_3_decision_gates": "NEIN", "final_decision": result.get("decision"), "reason": "Kernanalyse war nicht gültig."}
    top = ((result.get("strongest_market") or {}).get("key")); selected = ((result.get("market_families") or {}).get("selected") or {})
    strength = (_safe_num(legacy, selected.get("strength")) if selected.get("strength") is not None else None)
    if strength is None: strength = (_safe_num(legacy, (result.get("diagnostics") or {}).get("family_strength_pct")) or 0.0) / 100.0
    diagnostics = result.get("diagnostics") or {}; sample_security = (result.get("samples") or {}).get("security"); quality = diagnostics.get("data_quality") or "MITTEL"
    coherence = legacy._coherence_check(result.get("probabilities") or {}); pre = result.get("pre_match_integrity") or {}
    evidence = {
        "UNDERLYING": _signal("BESTÄTIGEND", "Hybrid-Poisson-Core wählt diesen Markt innerhalb normalisierter Marktfamilien.", strength),
        "MATCH": _match_signal(legacy, result, top), "FORM": _form_signal(report, top), "TABLE": _table_signal(report, top), "PLAYER": _player_signal(report, top),
    }
    confirmations = [name for name, sig in evidence.items() if sig.get("status") == "BESTÄTIGEND"]
    counters = [name for name, sig in evidence.items() if sig.get("status") == "GEGENARGUMENT"]
    independent_confirmations = [name for name in confirmations if name != "UNDERLYING"]
    probability_gate = "BESTANDEN" if strength >= 0.30 else ("BEOBACHTEN" if strength >= 0.20 else "NICHT BESTANDEN")
    required_confirmations = 4 if sample_security == "NIEDRIG" else 3
    multi_block = "BESTANDEN" if len(confirmations) >= required_confirmations and independent_confirmations else ("EINGESCHRÄNKT" if len(confirmations) >= 2 else "NICHT BESTANDEN")
    robustness = diagnostics.get("robustness_status") or "NICHT PRÜFBAR"
    if pre.get("strict_pre_match") is False:
        final = "AUSLASSEN"; reasons = ["Analysezeit liegt nicht vor dem FootyStats-Anpfiffzeitpunkt."]
    elif strength < 0.20 or len(counters) >= 2:
        final = "AUSLASSEN"; reasons = ["Marktfamilienstärke unter Beobachtungsniveau." if strength < 0.20 else "Mindestens zwei unabhängige Gegenargumente."]
    elif strength < 0.30:
        final = "BEOBACHTEN"; reasons = ["Marktfamilienstärke reicht für Beobachten, nicht für Spielen."]
    else:
        blockers: List[str] = []
        if len(confirmations) < required_confirmations: blockers.append(f"nur {len(confirmations)} bestätigende Blöcke; benötigt {required_confirmations}")
        if counters: blockers.append("Gegenargument: " + ", ".join(counters))
        if robustness == "NICHT BESTANDEN": blockers.append("Robustness Removal Test nicht bestanden")
        if quality == "NIEDRIG": blockers.append("Datenqualität niedrig")
        if not coherence.get("passed"): blockers.append("Wahrscheinlichkeitskohärenz nicht bestanden")
        final = "SPIELEN" if not blockers else "BEOBACHTEN"; reasons = blockers or ["Familienstärke, unabhängige Bestätigungen und Robustheit bestanden."]
    return {
        "version": "0.4.1 / Hybrid-Core + Five-Source Decision Engine",
        "scope": "Ein kohärentes Scoregrid aus League+Match; Form, Table und Player wirken marktbezogen als unabhängige Evidenz im Decision Gate.",
        "phase_1_data_audit": "BESTANDEN", "phase_2_all_six_markets": "JA" if len(result.get("markets") or []) == 6 else "NEIN", "phase_3_decision_gates": "JA",
        "selected_market_family": selected,
        "source_integration": {"league": "Capped liga-relativer xG/xGA-Stabilisator im Lambda-Core.", "match": "Pre-Match-xG/PPG im Raw Team Core plus marktbezogener Match-Evidenzblock.",
                               "form": "Last10-Level + Last5-Momentum als EIN Formblock; nicht dreifach gezählt.", "table": "1X2-Kontext; keine doppelte GF/GA/PPG-Gewichtung.",
                               "player": "Goal-Intensity für O/U; ohne bestätigte Lineups keine individuelle Ausfallkorrektur."},
        "evidence_blocks": evidence, "confirming_blocks": confirmations, "counter_blocks": counters,
        "gates": {"pre_match_integrity": pre, "probability_family_strength": {"status": probability_gate, "strength_pct": round(strength * 100, 1)},
                  "multi_block_confirmation": {"status": multi_block, "confirmations": len(confirmations), "required": required_confirmations},
                  "counterargument": {"status": "KEIN RELEVANTES" if not counters else "RELEVANT", "blocks": counters}, "robustness": robustness,
                  "small_sample_stress": "BESTANDEN" if sample_security == "HOCH" else ("EINGESCHRÄNKT" if sample_security == "MITTEL" else "ERHÖHTE ANFORDERUNG"),
                  "result_vs_underlying": diagnostics.get("result_vs_underlying"), "relative_edge": diagnostics.get("relative_edge"), "data_quality": quality, "coherence": coherence},
        "final_decision": final, "decision_reasons": reasons,
        "backtest_note": "Gate-Struktur auf 137 strikten Pre-Match-Snapshots geprüft; historische Trefferquoten sind keine Zukunftsgarantie."}


def apply_patch(legacy: Any) -> Any:
    """Patch the frozen V0.4.0 module in-place and return its FastAPI app."""
    original_supplemental = legacy.supplemental_report; original_attach = legacy._attach_supplemental; original_mf = legacy.mf
    def mf_v041(data: Any) -> Dict[str, Any]:
        out = dict(original_mf(data)); kickoff = legacy.firstnum(data, ["date_unix", "dateUnix", "kickoff_unix", "kickoff_timestamp"])
        if kickoff is not None:
            out["date_unix"] = int(kickoff)
            if out.get("date") in (None, ""): out["date"] = datetime.fromtimestamp(float(kickoff), tz=timezone.utc).isoformat()
        return out
    def supplemental_v041(match_data: Any, league_data: Any = None, form_data: Any = None, table_data: Any = None, player_data: Any = None) -> Dict[str, Any]:
        report = dict(original_supplemental(match_data, league_data, form_data, table_data, player_data))
        report["model_use"] = {"league": "Probability Core: Venue xG/xGA + Liga-Baseline mit Prior-Cap.",
                               "match": "Probability Core: Pre-Match-xG/PPG im Raw Team Core; zusätzlich Match-Evidenz.",
                               "form": "Decision Engine: Last10-Level + Last5-Momentum, ein unabhängiger Formblock.",
                               "table": "Decision Engine: 1X2-Kontext, keine doppelte League-Gewichtung.",
                               "player": "Decision Engine: Goal-Intensity nur für O/U; keine unbestätigte Lineup-Annahme."}
        return report
    def predict(match: Any, league: Any) -> Dict[str, Any]: return predict_v041(legacy, match, league)
    def protocol(result: Dict[str, Any], report: Dict[str, Any]) -> Dict[str, Any]: return elite_protocol_v041(legacy, result, report)
    def attach(result: Dict[str, Any], report: Dict[str, Any], source_files: Dict[str, str]) -> Dict[str, Any]:
        out = original_attach(result, report, source_files); out["model_version"] = VERSION; out.setdefault("notes", [])
        if not any("V0.4.1" in str(note) for note in out["notes"]): out["notes"] = list(out["notes"]) + ["V0.4.1 Five-Source Decision Engine aktiv."]
        return out
    legacy.mf = mf_v041; legacy.predict = predict; legacy.supplemental_report = supplemental_v041; legacy.elite_protocol_report = protocol; legacy._attach_supplemental = attach
    legacy.app.version = VERSION; legacy.app.title = "FootyStats Prognose Engine V0.4.1"
    legacy.INDEX_HTML = legacy.INDEX_HTML.replace("FootyStats Prognose Engine v0.4.0", "FootyStats Prognose Engine v0.4.1")
    legacy.INDEX_HTML = legacy.INDEX_HTML.replace("Liga-relativer V5.5-Kern · keine Odds · keine externen Matchdaten · INSUFFICIENT_DATA-Sperre und V5.2-Guardrails aktiv",
                                                   "V0.4.1 Hybrid-Core · 5 FootyStats-Dateien · familiennormalisierte Märkte · keine Odds")
    legacy.app.router.routes = [route for route in legacy.app.router.routes if getattr(route, "path", None) != "/api/health"]
    def health() -> Dict[str, Any]: return {"ok": True, "version": VERSION, "engine": "five-source-hybrid", "backup": "v0.4.0"}
    legacy.app.add_api_route("/api/health", health, methods=["GET"])
    return legacy.app
