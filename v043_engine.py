"""V0.4.3 candidate: targeted FULL-5 lambda strengthening over V0.4.2.

All five FootyStats files are used in one regularized goal-lambda layer:
- MatchDaten: prematch xG
- LeagueDaten: venue PPG/xG/GF/xGA/GA, attacks, dangerous attacks, shots, SOT, efficiency
- FormDaten: Last10 level + Last5-vs-Last10 momentum
- TableDaten: venue PPG/position/GF/GA context
- PlayerDaten: goals/90, assists/90, minutes coverage

The V0.4.2 hybrid lambda remains the base signal (log_base). The final home and
away lambdas are produced by a regularized Poisson GLM fitted on 137 strict
pre-match archives (competition-grouped validation). Dixon-Coles remains the
score-distribution layer. Missing FULL-5 inputs do not get invented: the engine
falls back to the unchanged V0.4.2 lambdas for that match.
"""
from __future__ import annotations

import math
from contextvars import ContextVar
from typing import Any, Dict, List, Optional, Tuple

import v041_engine
import v042_engine

VERSION = "0.4.3"
FEATURE_COUNT = 40
FULL5_ALPHA = 1.0
TRAINING_REFERENCE = "137 strict pre-match archives; competition-grouped repeated/nested CV"
_FULL5_CONTEXT: ContextVar[Optional[Dict[str, Any]]] = ContextVar("v043_full5_context", default=None)

FULL5_FEATURES = ['log_base', 'is_home', 'prematch_xg', 'ppg', 'opp_ppg', 'atk_xg', 'atk_gf', 'def_xga', 'def_ga', 'atk_attacks', 'atk_dangerous', 'atk_shots', 'atk_sot', 'atk_sot_rate', 'atk_xg_minus_goals', 'def_xga_minus_ga', 'form10_xg', 'form10_ppg', 'form10_goals_for_per_match', 'form10_shots_on_target_avg', 'opp_form10_xga', 'opp_form10_goals_against_per_match', 'mom_xg', 'mom_ppg', 'mom_goals_for_per_match', 'mom_shots_on_target_avg', 'opp_mom_xga', 'opp_mom_goals_against_per_match', 'table_ppg', 'opp_table_ppg', 'table_position', 'opp_table_position', 'table_goals_for_per_match', 'opp_table_goals_against_per_match', 'player_goals_per_90', 'player_assists_per_90', 'player_minutes_coverage_pct', 'opp_player_goals_per_90', 'opp_player_assists_per_90', 'opp_player_minutes_coverage_pct']
FULL5_MEAN = [0.3597050204326385, 0.5, 1.4796715328467154, 1.336824817518248, 1.336824817518248, 1.4708394160583942, 1.3833576642335765, 1.4868248175182481, 1.4537956204379563, 95.2359489051095, 47.78631386861314, 12.90978102189781, 4.384051094890511, 0.34442362939773496, 0.08748175182481752, 0.03302919708029195, 1.4927007299270072, 1.3974452554744525, 1.4631386861313869, 4.529963503649635, 1.4513868613138685, 1.4043795620437958, 0.005802919708029196, -0.014233576642335764, 0.0032846715328467197, 0.04740875912408761, 0.029999999999999995, 0.013138686131386863, 1.3585401459854014, 1.3585401459854014, 11.218978102189782, 11.218978102189782, 1.3834051094890512, 1.4538321167883212, 0.13156204379562045, 0.09215693430656935, 98.99270072992701, 0.13156204379562045, 0.09215693430656935, 98.99270072992701]
FULL5_SCALE = [0.2537271686379997, 0.5, 0.47854962764997294, 1.017502197116014, 1.017502197116014, 0.4812791158480532, 0.9978976275129648, 0.4946175164298908, 1.07622558307924, 20.469128241351484, 15.923365512954563, 4.754244429773673, 2.0443229237005136, 0.12258901834199282, 0.9009588614942196, 0.9428385193659015, 0.29090847796895114, 0.5180966417713164, 0.5799499749692959, 1.1767828524752115, 0.2510697767953675, 0.4850868856087425, 0.17927340533411096, 0.4194821670913384, 0.3991187546031719, 0.8596304167221717, 0.18287844473159012, 0.408811258406289, 1.0560334199989712, 1.0560334199989712, 6.423287159533431, 6.423287159533431, 0.9978865989447173, 1.076096931903313, 0.06926183909590466, 0.05514474158891393, 3.2799130982901414, 0.06926183909590466, 0.05514474158891393, 3.2799130982901414]
FULL5_COEF = [0.03960919564207756, 0.030784268354458206, 0.017326547758837026, 0.03334595508459388, 0.00394623555488075, 0.009879408201307492, -0.006868491424739642, 0.032744906243068465, 0.00998014249928252, 0.038684493324057705, -0.03370148287110967, 0.02983752270388955, -0.0032754402653534537, -0.002406939837676652, 0.01288494362807554, 0.005786059234025434, 0.04526736123129221, -0.036808796734159974, 0.06288660266967004, 0.024263842100379712, 0.048821076634482055, 0.02557148545821829, -0.03666229136633528, -0.015442889163347497, 0.0665100557178949, 0.014634320797658137, -0.00653356665374662, -0.003918766980868451, 0.033697706157920226, -0.004114251968757935, -0.04506071029737455, -0.03731286170785292, -0.006854215278627382, 0.010062923837260705, -0.004895071253628009, 0.03336938734948439, 0.013681424300586303, 0.011868654545855383, -0.010223994838798649, 0.0174597223721102]
FULL5_INTERCEPT = 0.43556369049305005

if not (len(FULL5_FEATURES) == len(FULL5_MEAN) == len(FULL5_SCALE) == len(FULL5_COEF) == FEATURE_COUNT):
    raise RuntimeError("V0.4.3 FULL-5 Parameterlängen sind inkonsistent.")


def _num(value: Any) -> Optional[float]:
    try:
        if value is None or isinstance(value, bool):
            return None
        out = float(value)
        return out if math.isfinite(out) else None
    except Exception:
        return None


def _window(team: Dict[str, Any], sample: int) -> Dict[str, Any]:
    return ((team.get("windows") or {}).get(str(sample)) or {})


def _momentum(team: Dict[str, Any], metric: str) -> Optional[float]:
    recent, reference = _window(team, 5), _window(team, 10)
    a, b = _num(recent.get(metric)), _num(reference.get(metric))
    return a - b if a is not None and b is not None else None


def _league_metric(legacy: Any, team: Any, metric: str, venue: str) -> Optional[float]:
    try:
        return _num(legacy.tnum(team, metric, venue))
    except Exception:
        return None


def _league_direct(legacy: Any, team: Any, key: str) -> Optional[float]:
    try:
        return _num(legacy.firstnum(team, [key]))
    except Exception:
        return None


def _full5_row(legacy: Any, side: str, match_fields: Dict[str, Any], home_team: Any, away_team: Any, report: Dict[str, Any], base_lambda: float) -> Tuple[Optional[Dict[str, float]], List[str]]:
    is_home = side == "home"
    attack_team = home_team if is_home else away_team
    defence_team = away_team if is_home else home_team
    venue = "home" if is_home else "away"
    opp_venue = "away" if is_home else "home"

    coverage = report.get("coverage") or {}
    form = coverage.get("form") or {}
    table = coverage.get("table") or {}
    player = coverage.get("player") or {}
    form_team = (form.get("home") if is_home else form.get("away")) or {}
    form_opp = (form.get("away") if is_home else form.get("home")) or {}
    table_team = (table.get("home") if is_home else table.get("away")) or {}
    table_opp = (table.get("away") if is_home else table.get("home")) or {}
    player_team = (player.get("home") if is_home else player.get("away")) or {}
    player_opp = (player.get("away") if is_home else player.get("home")) or {}

    f10 = _window(form_team, 10)
    o10 = _window(form_opp, 10)

    atk_xg = _league_metric(legacy, attack_team, "xg", venue)
    atk_gf = _league_metric(legacy, attack_team, "gf", venue)
    def_xga = _league_metric(legacy, defence_team, "xga", opp_venue)
    def_ga = _league_metric(legacy, defence_team, "ga", opp_venue)
    atk_shots = _league_metric(legacy, attack_team, "shots", venue)
    atk_sot = _league_metric(legacy, attack_team, "sot", venue)
    atk_attacks = _league_direct(legacy, attack_team, f"attacks_avg_{venue}")
    atk_dangerous = _league_direct(legacy, attack_team, f"dangerous_attacks_avg_{venue}")
    atk_sot_rate = (atk_sot / atk_shots) if atk_sot is not None and atk_shots is not None and atk_shots > 0 else None

    row: Dict[str, Optional[float]] = {
        "log_base": math.log(max(.05, float(base_lambda))),
        "is_home": 1.0 if is_home else 0.0,
        "prematch_xg": _num(match_fields.get("home_prematch_xg" if is_home else "away_prematch_xg")),
        "ppg": _league_metric(legacy, attack_team, "ppg", venue),
        "opp_ppg": _league_metric(legacy, defence_team, "ppg", opp_venue),
        "atk_xg": atk_xg,
        "atk_gf": atk_gf,
        "def_xga": def_xga,
        "def_ga": def_ga,
        "atk_attacks": atk_attacks,
        "atk_dangerous": atk_dangerous,
        "atk_shots": atk_shots,
        "atk_sot": atk_sot,
        "atk_sot_rate": atk_sot_rate,
        "atk_xg_minus_goals": (atk_xg - atk_gf) if atk_xg is not None and atk_gf is not None else None,
        "def_xga_minus_ga": (def_xga - def_ga) if def_xga is not None and def_ga is not None else None,
        "form10_xg": _num(f10.get("xg")),
        "form10_ppg": _num(f10.get("ppg")),
        "form10_goals_for_per_match": _num(f10.get("goals_for_per_match")),
        "form10_shots_on_target_avg": _num(f10.get("shots_on_target_avg")),
        "opp_form10_xga": _num(o10.get("xga")),
        "opp_form10_goals_against_per_match": _num(o10.get("goals_against_per_match")),
        "mom_xg": _momentum(form_team, "xg"),
        "mom_ppg": _momentum(form_team, "ppg"),
        "mom_goals_for_per_match": _momentum(form_team, "goals_for_per_match"),
        "mom_shots_on_target_avg": _momentum(form_team, "shots_on_target_avg"),
        "opp_mom_xga": _momentum(form_opp, "xga"),
        "opp_mom_goals_against_per_match": _momentum(form_opp, "goals_against_per_match"),
        "table_ppg": _num(table_team.get("ppg")),
        "opp_table_ppg": _num(table_opp.get("ppg")),
        "table_position": _num(table_team.get("position")),
        "opp_table_position": _num(table_opp.get("position")),
        "table_goals_for_per_match": _num(table_team.get("goals_for_per_match")),
        "opp_table_goals_against_per_match": _num(table_opp.get("goals_against_per_match")),
        "player_goals_per_90": _num(player_team.get("goals_per_90")),
        "player_assists_per_90": _num(player_team.get("assists_per_90")),
        "player_minutes_coverage_pct": _num(player_team.get("minutes_coverage_pct")),
        "opp_player_goals_per_90": _num(player_opp.get("goals_per_90")),
        "opp_player_assists_per_90": _num(player_opp.get("assists_per_90")),
        "opp_player_minutes_coverage_pct": _num(player_opp.get("minutes_coverage_pct")),
    }

    missing = [name for name in FULL5_FEATURES if _num(row.get(name)) is None]
    if missing:
        return None, missing
    return {name: float(row[name]) for name in FULL5_FEATURES}, []


def _predict_lambda(row: Dict[str, float]) -> float:
    linear = FULL5_INTERCEPT
    for index, name in enumerate(FULL5_FEATURES):
        scale = FULL5_SCALE[index]
        if not math.isfinite(scale) or scale <= 0:
            raise ValueError(f"Ungültige FULL-5-Skalierung für {name}.")
        z = (float(row[name]) - FULL5_MEAN[index]) / scale
        linear += FULL5_COEF[index] * z
    value = math.exp(max(-6.0, min(3.0, linear)))
    return max(.05, min(3.95, value))


def _patch_lambda_core(legacy: Any) -> None:
    original = getattr(v041_engine, "_v043_original_hybrid_lambdas", None)
    if original is None:
        original = v041_engine._hybrid_lambdas
        v041_engine._v043_original_hybrid_lambdas = original

    def full5_hybrid_lambdas(legacy_module: Any, h_profile: Dict[str, Any], a_profile: Dict[str, Any], match_fields: Dict[str, Any], home_team: Any, away_team: Any, league: Any, neutralize: Optional[str] = None) -> Tuple[float, float, Dict[str, Any]]:
        base_h, base_a, detail = original(legacy_module, h_profile, a_profile, match_fields, home_team, away_team, league, neutralize=neutralize)
        detail = dict(detail)
        context = _FULL5_CONTEXT.get()
        if not context:
            detail["full5"] = {
                "applied": False,
                "reason": "FULL-5-Kontext nicht vorhanden; unveränderte V0.4.2-Lambdas verwendet.",
                "base_expected_goals": {"home": round(base_h, 6), "away": round(base_a, 6)},
            }
            return base_h, base_a, detail

        report = context.get("report") or {}
        home_row, home_missing = _full5_row(legacy_module, "home", match_fields, home_team, away_team, report, base_h)
        away_row, away_missing = _full5_row(legacy_module, "away", match_fields, home_team, away_team, report, base_a)
        if home_row is None or away_row is None:
            detail["full5"] = {
                "applied": False,
                "reason": "FULL-5 nicht vollständig; keine Median-/Ersatzwerte erfunden.",
                "missing_home": home_missing,
                "missing_away": away_missing,
                "base_expected_goals": {"home": round(base_h, 6), "away": round(base_a, 6)},
            }
            return base_h, base_a, detail

        new_h, new_a = _predict_lambda(home_row), _predict_lambda(away_row)
        detail["method"] = "V0.4.3 FULL-5 regularized Poisson lambda over V0.4.2 hybrid base"
        detail["full5"] = {
            "applied": True,
            "feature_count": FEATURE_COUNT,
            "alpha": FULL5_ALPHA,
            "training_reference": TRAINING_REFERENCE,
            "base_expected_goals": {"home": round(base_h, 6), "away": round(base_a, 6), "total": round(base_h + base_a, 6)},
            "full5_expected_goals": {"home": round(new_h, 6), "away": round(new_a, 6), "total": round(new_h + new_a, 6)},
            "sources": {
                "match": "prematch xG",
                "league": "venue PPG/xG/GF/xGA/GA + attacks/dangerous attacks/shots/SOT/efficiency",
                "form": "Last10 level + Last5-minus-Last10 momentum",
                "table": "venue PPG/position/GF/GA context",
                "player": "goals/90 + assists/90 + minutes coverage",
            },
            "missing_value_policy": "fallback_to_v0.4.2_no_imputation",
        }
        return new_h, new_a, detail

    v041_engine._hybrid_lambdas = full5_hybrid_lambdas


def _replace_version_strings(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _replace_version_strings(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_replace_version_strings(v) for v in value]
    if isinstance(value, str):
        return value.replace("0.4.2", VERSION).replace("V0.4.2", "V0.4.3 FULL-5")
    return value


def apply_patch(legacy: Any) -> Any:
    app = v042_engine.apply_patch(legacy)
    _patch_lambda_core(legacy)

    predict_v042 = legacy.predict
    protocol_v042 = legacy.elite_protocol_report
    attach_v042 = legacy._attach_supplemental
    supplemental_v042 = legacy.supplemental_report
    analyze_bundle_v042 = legacy._analyze_bundle

    def supplemental_v043(match_data: Any, league_data: Any = None, form_data: Any = None, table_data: Any = None, player_data: Any = None) -> Dict[str, Any]:
        report = dict(supplemental_v042(match_data, league_data, form_data, table_data, player_data))
        report["model_use"] = {
            "match": "FULL-5 Lambda: teambezogenes Prematch-xG; zusätzlich Match-Evidenz.",
            "league": "FULL-5 Lambda: Venue PPG/xG/GF/xGA/GA, Attacks, Dangerous Attacks, Shots, SOT und Effizienz; V0.4.2-Hybrid bleibt Base.",
            "form": "FULL-5 Lambda: Last10-Level + Last5-Momentum; zusätzlich unabhängiger Decision-Gate-Block.",
            "table": "FULL-5 Lambda: Venue-PPG, Position sowie GF/GA-Kontext; zusätzlich 1X2-Gate.",
            "player": "FULL-5 Lambda: Goals/90, Assists/90 und Minuten-Coverage; zusätzlich O/U-Gate; keine Lineup-Annahme.",
        }
        return report

    legacy.supplemental_report = supplemental_v043

    def predict_v043(match: Any, league: Any) -> Dict[str, Any]:
        out = _replace_version_strings(predict_v042(match, league))
        out["model_version"] = VERSION
        method = dict(out.get("method") or {})
        method.update({
            "lambda_core": "V0.4.2 hybrid base + regularized FULL-5 Poisson layer",
            "full5_feature_count": FEATURE_COUNT,
            "full5_alpha": FULL5_ALPHA,
            "full5_training_reference": TRAINING_REFERENCE,
            "score_distribution": "Dixon-Coles",
            "dixon_coles_rho": v042_engine.RHO,
            "release_status": "candidate",
            "odds_used": False,
        })
        out["method"] = method
        out.setdefault("notes", [])
        out["notes"] = [n for n in out["notes"] if "V0.4.2" not in str(n)] + [
            "V0.4.3 FULL-5 Kandidat aktiv: alle fünf FootyStats-Dateien werden gezielt im Lambda-/Gate-System genutzt.",
            "Fehlende FULL-5-Kernfeatures werden nicht imputiert; in diesem Fall bleibt der V0.4.2-Lambda unverändert.",
            f"Dixon-Coles rho={v042_engine.RHO:.2f} bleibt unverändert.",
        ]
        return out

    legacy.predict = predict_v043

    def protocol_v043(result: Dict[str, Any], report: Dict[str, Any]) -> Dict[str, Any]:
        out = _replace_version_strings(protocol_v042(result, report))
        out["version"] = "0.4.3 / FULL-5 Regularized Lambda + Dixon-Coles + Five-Source Decision Engine"
        out["score_model"] = {
            "distribution": "Dixon-Coles",
            "rho": v042_engine.RHO,
            "base_lambdas": "V0.4.2 hybrid",
            "final_lambdas": "40-feature regularized FULL-5 Poisson",
        }
        out["source_integration"] = {
            "match": "Prematch-xG direkt im FULL-5-Lambda; Match-Evidenz bleibt erhalten.",
            "league": "Venue-Leistung + Attack Quality direkt im FULL-5-Lambda.",
            "form": "Last10-Level + Last5-Momentum direkt im FULL-5-Lambda und als unabhängiger Gate-Block.",
            "table": "PPG/Position/GF/GA direkt im FULL-5-Lambda; 1X2-Gate bleibt erhalten.",
            "player": "Goals/90, Assists/90, Minuten-Coverage direkt im FULL-5-Lambda; O/U-Gate bleibt erhalten.",
        }
        return out

    legacy.elite_protocol_report = protocol_v043

    def attach_v043(result: Dict[str, Any], report: Dict[str, Any], source_files: Dict[str, str]) -> Dict[str, Any]:
        out = _replace_version_strings(attach_v042(result, report, source_files))
        out["model_version"] = VERSION
        return out

    legacy._attach_supplemental = attach_v043

    def analyze_bundle_v043(parsed_files: List[Dict[str, Any]]) -> Dict[str, Any]:
        pair = legacy.select_pair(parsed_files)
        if not pair.get("ok"):
            return pair
        extras = pair.get("supplemental_data") or {}
        report = legacy.supplemental_report(pair["match_data"], pair["league_data"], extras.get("form"), extras.get("table"), extras.get("player"))
        token = _FULL5_CONTEXT.set({"report": report})
        try:
            return analyze_bundle_v042(parsed_files)
        finally:
            _FULL5_CONTEXT.reset(token)

    legacy._analyze_bundle = analyze_bundle_v043

    legacy.app.router.routes = [route for route in legacy.app.router.routes if getattr(route, "path", None) not in {"/api/predict", "/api/health"}]

    def predict_json_v043(payload: legacy.Payload) -> Dict[str, Any]:
        report = legacy.supplemental_report(payload.matchData, payload.leagueData, payload.formData, payload.tableData, payload.playerData)
        token = _FULL5_CONTEXT.set({"report": report})
        try:
            return legacy._attach_supplemental(legacy.predict(payload.matchData, payload.leagueData), report, {})
        finally:
            _FULL5_CONTEXT.reset(token)

    def health() -> Dict[str, Any]:
        return {
            "ok": True,
            "version": VERSION,
            "engine": "five-source-full5-regularized-dixon-coles",
            "rho": v042_engine.RHO,
            "full5_features": FEATURE_COUNT,
            "alpha": FULL5_ALPHA,
            "production": False,
            "candidate": True,
            "baseline": "v0.4.2",
        }

    legacy.app.add_api_route("/api/predict", predict_json_v043, methods=["POST"])
    legacy.app.add_api_route("/api/health", health, methods=["GET"])

    legacy.app.version = VERSION
    legacy.app.title = "FootyStats Prognose Engine V0.4.3 FULL-5"
    legacy.INDEX_HTML = legacy.INDEX_HTML.replace("FootyStats Prognose Engine v0.4.2 Dixon-Coles", "FootyStats Prognose Engine v0.4.3 FULL-5")
    legacy.INDEX_HTML = legacy.INDEX_HTML.replace("V0.4.2 Dixon-Coles", "V0.4.3 FULL-5 · Regularized Lambda + Dixon-Coles")
    return app
