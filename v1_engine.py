"""FootyStats V1 production overlay on the frozen V0.4.3 FULL-5 core.

V1 intentionally does NOT replace the V0.4.3 probability model.  The 40-feature
FULL-5 lambda, alpha=3 production lock, V0.4.2 fallback and Dixon-Coles rho=-0.25
remain owned by the existing V0.4.3 modules.

V1 adds two things above that frozen probability core:
1. Gate V1: required confirmations are capped by the *structurally applicable*
   evidence-block count of the selected market family.  This changes only the
   known low-sample BTTS 4-of-3 impossibility (BTTS max=3).
2. Five-file specialist profiles (FH-BTTS, CS/FTS scoring survival and Player
   Depth) as transparent diagnostics/robustness context.  They do not invent
   probability weights and cannot silently modify V0.4.3 lambdas.

The existing V0.4.3 pairing card and visible "Warum BEOBACHTEN?" UI remain in
place because this overlay is installed after v043_observe_fazit_ui.
"""
from __future__ import annotations

from collections import defaultdict
from statistics import median
from typing import Any, Dict, Iterable, List, Optional

import v042_engine
import v043_engine
import v043_observe_fazit_ui
import v043_release

VERSION = "1.0.0"
BASELINE = "0.4.3 FULL-5"
STRUCTURAL_APPLICABLE_BLOCKS = {"1X2": 4, "BTTS": 3, "OU_2_5": 4}
TECHNICAL_BLOCK_LABELS = {
    "UNDERLYING": "V0.4.3 Wahrscheinlichkeitskern",
    "MATCH": "Pre-Match-Spielprofil",
    "FORM": "aktuelle Form",
    "TABLE": "Tabellen-/Venue-Kontext",
    "PLAYER": "Spieler-/Kaderkontext",
}


def _num(legacy: Any, value: Any) -> Optional[float]:
    try:
        out = legacy.num(value)
        return float(out) if out is not None else None
    except Exception:
        return None


def _firstnum(legacy: Any, obj: Any, keys: Iterable[str]) -> Optional[float]:
    try:
        out = legacy.firstnum(obj, list(keys))
        return float(out) if out is not None else None
    except Exception:
        return None


def _mean(values: Iterable[Optional[float]]) -> Optional[float]:
    clean = [float(v) for v in values if v is not None]
    return sum(clean) / len(clean) if clean else None


def _weighted_mean(rows: Iterable[tuple[Optional[float], Optional[float]]]) -> Optional[float]:
    clean = [(float(v), float(w)) for v, w in rows if v is not None and w is not None and float(w) > 0]
    if not clean:
        return None
    total = sum(w for _, w in clean)
    return sum(v * w for v, w in clean) / total


def _split_from_key(key: str) -> Optional[str]:
    if key.endswith("_home"):
        return "home"
    if key.endswith("_away"):
        return "away"
    return None


def _league_metric_mean(legacy: Any, teams: List[Any], key: str) -> Optional[float]:
    split = _split_from_key(key)
    match_key = f"seasonMatchesPlayed_{split}" if split else None
    rows = []
    for team in teams:
        value = _firstnum(legacy, team, [key])
        weight = _firstnum(legacy, team, [match_key]) if match_key else 1.0
        rows.append((value, weight))
    return _weighted_mean(rows)


def _direction_from_pair(a_delta: Optional[float], b_delta: Optional[float]) -> str:
    if a_delta is None or b_delta is None:
        return "NICHT BEWERTBAR"
    if a_delta > 0 and b_delta > 0:
        return "BTTS_YES"
    if a_delta < 0 and b_delta < 0:
        return "BTTS_NO"
    return "GEMISCHT"


def _fh_btts_profile(legacy: Any, home_team: Any, away_team: Any, teams: List[Any]) -> Dict[str, Any]:
    home = _firstnum(legacy, home_team, ["seasonBTTSPercentageHT_home", "btts_fhg_percentage_home"])
    away = _firstnum(legacy, away_team, ["seasonBTTSPercentageHT_away", "btts_fhg_percentage_away"])
    league_home = _league_metric_mean(legacy, teams, "seasonBTTSPercentageHT_home")
    league_away = _league_metric_mean(legacy, teams, "seasonBTTSPercentageHT_away")
    home_delta = home - league_home if home is not None and league_home is not None else None
    away_delta = away - league_away if away is not None and league_away is not None else None
    direction = _direction_from_pair(home_delta, away_delta)
    wording = {
        "BTTS_YES": "Beide Teams liegen im passenden Venue-Split beim First-Half-BTTS über ihrem Liga-Kontext.",
        "BTTS_NO": "Beide Teams liegen im passenden Venue-Split beim First-Half-BTTS unter ihrem Liga-Kontext.",
        "GEMISCHT": "Das First-Half-BTTS-Profil ist zwischen Heim- und Auswärtsteam gemischt.",
        "NICHT BEWERTBAR": "Das First-Half-BTTS-Profil ist aus den gelieferten LeagueDaten nicht vollständig bewertbar.",
    }[direction]
    return {
        "name": "First-Half BTTS Venue Profile",
        "mode": "DIAGNOSTIC_NO_PROBABILITY_WEIGHT",
        "direction": direction,
        "home_pct": round(home, 2) if home is not None else None,
        "away_pct": round(away, 2) if away is not None else None,
        "league_home_pct": round(league_home, 2) if league_home is not None else None,
        "league_away_pct": round(league_away, 2) if league_away is not None else None,
        "home_delta_pp": round(home_delta, 2) if home_delta is not None else None,
        "away_delta_pp": round(away_delta, 2) if away_delta is not None else None,
        "explanation": wording,
    }


def _scoring_survival(fts: Optional[float], opponent_cs: Optional[float]) -> Optional[float]:
    if fts is None or opponent_cs is None:
        return None
    return max(0.0, min(100.0, 100.0 - (float(fts) + float(opponent_cs)) / 2.0))


def _cs_fts_profile(legacy: Any, home_team: Any, away_team: Any, teams: List[Any]) -> Dict[str, Any]:
    h_fts = _firstnum(legacy, home_team, ["seasonFTSPercentage_home"])
    a_cs = _firstnum(legacy, away_team, ["seasonCSPercentage_away"])
    a_fts = _firstnum(legacy, away_team, ["seasonFTSPercentage_away"])
    h_cs = _firstnum(legacy, home_team, ["seasonCSPercentage_home"])

    home_survival = _scoring_survival(h_fts, a_cs)
    away_survival = _scoring_survival(a_fts, h_cs)

    l_h_fts = _league_metric_mean(legacy, teams, "seasonFTSPercentage_home")
    l_a_cs = _league_metric_mean(legacy, teams, "seasonCSPercentage_away")
    l_a_fts = _league_metric_mean(legacy, teams, "seasonFTSPercentage_away")
    l_h_cs = _league_metric_mean(legacy, teams, "seasonCSPercentage_home")
    home_baseline = _scoring_survival(l_h_fts, l_a_cs)
    away_baseline = _scoring_survival(l_a_fts, l_h_cs)

    home_delta = home_survival - home_baseline if home_survival is not None and home_baseline is not None else None
    away_delta = away_survival - away_baseline if away_survival is not None and away_baseline is not None else None
    direction = _direction_from_pair(home_delta, away_delta)
    wording = {
        "BTTS_YES": "Beide Mannschaften besitzen im FTS/Clean-Sheet-Vergleich eine überdurchschnittliche strukturelle Chance, selbst zu treffen.",
        "BTTS_NO": "Bei beiden Torseiten liegt die FTS/Clean-Sheet-Struktur unter dem jeweiligen Liga-Kontext und bremst die BTTS-These.",
        "GEMISCHT": "Das CS/FTS-Profil unterstützt nur eine der beiden benötigten Torseiten klar; für BTTS ist das strukturell gemischt.",
        "NICHT BEWERTBAR": "Das CS/FTS-Profil ist aus den gelieferten LeagueDaten nicht vollständig bewertbar.",
    }[direction]
    return {
        "name": "BTTS CS/FTS Scoring-Survival Profile",
        "mode": "DIAGNOSTIC_NO_PROBABILITY_WEIGHT",
        "direction": direction,
        "home_scoring_survival": round(home_survival, 2) if home_survival is not None else None,
        "away_scoring_survival": round(away_survival, 2) if away_survival is not None else None,
        "league_home_baseline": round(home_baseline, 2) if home_baseline is not None else None,
        "league_away_baseline": round(away_baseline, 2) if away_baseline is not None else None,
        "home_delta_pp": round(home_delta, 2) if home_delta is not None else None,
        "away_delta_pp": round(away_delta, 2) if away_delta is not None else None,
        "explanation": wording,
    }


def _player_rows(player_data: Any) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if not isinstance(player_data, dict):
        return rows
    for page in player_data.get("pages") or []:
        if isinstance(page, dict):
            rows.extend(row for row in (page.get("data") or []) if isinstance(row, dict))
    return rows


def _player_team_id(legacy: Any, player: Dict[str, Any]) -> Optional[int]:
    for key in ("club_team_id", "club_team_2_id"):
        value = _num(legacy, player.get(key))
        if value is not None and value > 0:
            return int(value)
    return None


def _player_depth_profile(legacy: Any, report: Dict[str, Any], player_data: Any) -> Dict[str, Any]:
    coverage = ((report.get("coverage") or {}).get("player") or {})
    home = coverage.get("home") or {}
    away = coverage.get("away") or {}
    counts: Dict[int, int] = defaultdict(int)
    for player in _player_rows(player_data):
        team_id = _player_team_id(legacy, player)
        if team_id is not None:
            counts[team_id] += 1
    league_median = float(median(counts.values())) if counts else None
    home_count = _num(legacy, home.get("players_found"))
    away_count = _num(legacy, away.get("players_found"))
    minimum = min(home_count, away_count) if home_count is not None and away_count is not None else None
    concentration_values = [
        _num(legacy, home.get("top3_contribution_share_pct")),
        _num(legacy, away.get("top3_contribution_share_pct")),
    ]
    concentration_values = [v for v in concentration_values if v is not None]
    max_concentration = max(concentration_values) if concentration_values else None

    if minimum is None or league_median is None:
        status = "NICHT BEWERTBAR"
        explanation = "Die Kaderbreite ist aus PlayerDaten nicht vollständig bewertbar."
    elif minimum < 0.75 * league_median or (max_concentration is not None and max_concentration >= 75.0):
        status = "FRAGIL"
        explanation = "Mindestens ein Team besitzt im Liga-Vergleich geringe Player Depth oder eine hohe Abhängigkeit von wenigen Torbeteiligten."
    elif minimum >= league_median and (max_concentration is None or max_concentration < 75.0):
        status = "ROBUST"
        explanation = "Beide Teams besitzen mindestens liga-typische Player Depth ohne extreme Top-3-Abhängigkeit."
    else:
        status = "NORMAL"
        explanation = "Die Player Depth liegt im normalen Bereich; es gibt weder ein klares Robustheits- noch ein klares Fragilitätssignal."
    return {
        "name": "Player Depth / Concentration",
        "mode": "RELIABILITY_DIAGNOSTIC_NO_PROBABILITY_WEIGHT",
        "status": status,
        "home_players_found": int(home_count) if home_count is not None else None,
        "away_players_found": int(away_count) if away_count is not None else None,
        "league_median_players": round(league_median, 1) if league_median is not None else None,
        "home_top3_contribution_share_pct": _num(legacy, home.get("top3_contribution_share_pct")),
        "away_top3_contribution_share_pct": _num(legacy, away.get("top3_contribution_share_pct")),
        "explanation": explanation,
    }


def _specialist_profiles(legacy: Any, match_data: Any, league_data: Any, player_data: Any, report: Dict[str, Any]) -> Dict[str, Any]:
    match = legacy.mf(match_data)
    home_id, away_id = match.get("home_id"), match.get("away_id")
    try:
        home_team = legacy.team_obj(league_data, home_id)
        away_team = legacy.team_obj(league_data, away_id)
        teams = legacy.league_team_list(league_data)
    except Exception:
        home_team = away_team = None
        teams = []
    if not home_team or not away_team or not teams:
        return {
            "status": "NICHT BEWERTBAR",
            "policy": "Keine Ersatzwerte; V0.4.3 Probability Core bleibt unverändert.",
        }
    return {
        "status": "BERECHNET",
        "policy": "Specialists sind V1-Diagnostik/Robustheitskontext; keine erfundenen Lambda- oder Probability-Gewichte.",
        "fh_btts": _fh_btts_profile(legacy, home_team, away_team, teams),
        "cs_fts": _cs_fts_profile(legacy, home_team, away_team, teams),
        "player_depth": _player_depth_profile(legacy, report, player_data),
    }


def _family_for_market(key: Optional[str]) -> Optional[str]:
    if key in {"home_win", "away_win"}:
        return "1X2"
    if key in {"btts_yes", "btts_no"}:
        return "BTTS"
    if key in {"over_2_5", "under_2_5"}:
        return "OU_2_5"
    return None


def _selected_label(result: Dict[str, Any], market_key: Optional[str]) -> str:
    strongest = result.get("strongest_market") or {}
    return str(strongest.get("label") or market_key or "der stärkste Markt")


def _specialist_note(report: Dict[str, Any], market_key: Optional[str]) -> Optional[str]:
    profiles = report.get("v1_specialist_profiles") or {}
    if profiles.get("status") != "BERECHNET":
        return None
    if market_key in {"btts_yes", "btts_no"}:
        wanted = "BTTS_YES" if market_key == "btts_yes" else "BTTS_NO"
        opposite = "BTTS_NO" if wanted == "BTTS_YES" else "BTTS_YES"
        fh = (profiles.get("fh_btts") or {}).get("direction")
        cs = (profiles.get("cs_fts") or {}).get("direction")
        if fh == wanted and cs == wanted:
            return "Zusatzprofil: First-Half-BTTS und CS/FTS stützen dieselbe BTTS-Richtung; sie dienen in V1.0 als Robustheitskontext und verändern die V0.4.3-Prozentzahl nicht."
        if fh == opposite and cs == opposite:
            return "Zusatzprofil: First-Half-BTTS und CS/FTS laufen beide gegen die ausgewählte BTTS-Richtung. Das wird sichtbar als Warnsignal ausgewiesen; V1.0 erfindet dafür keine Prozentkorrektur."
        return "Zusatzprofil: Die BTTS-Specialists liefern ein gemischtes Bild. Deshalb werden sie transparent gezeigt, aber nicht als künstlicher Wahrscheinlichkeitsaufschlag verwendet."
    depth = (profiles.get("player_depth") or {}).get("status")
    if depth == "FRAGIL":
        return "Zusatzprofil: Die Player-Depth-/Concentration-Prüfung zeigt erhöhte Kaderfragilität; dies ist ein Reliability-Hinweis, kein erfundener Lambda-Abzug."
    return None


def _human_block_list(blocks: List[str]) -> str:
    return ", ".join(TECHNICAL_BLOCK_LABELS.get(block, block) for block in blocks)


def apply_gate_v1_to_protocol(result: Dict[str, Any], report: Dict[str, Any], protocol: Dict[str, Any]) -> Dict[str, Any]:
    """Apply the isolated Gate-V1 rule while keeping all V0.4.3 probabilities fixed."""
    out = dict(protocol)
    selected = dict(out.get("selected_market_family") or {})
    market_key = selected.get("key") or (result.get("strongest_market") or {}).get("key")
    family = selected.get("family") or _family_for_market(market_key)
    diagnostics = result.get("diagnostics") or {}
    sample_security = (result.get("samples") or {}).get("security")
    strength = _num_obj(selected.get("strength"))
    if strength is None:
        strength = (_num_obj((diagnostics or {}).get("family_strength_pct")) or 0.0) / 100.0

    evidence = out.get("evidence_blocks") or {}
    confirmations = list(out.get("confirming_blocks") or [name for name, sig in evidence.items() if (sig or {}).get("status") == "BESTÄTIGEND"])
    counters = list(out.get("counter_blocks") or [name for name, sig in evidence.items() if (sig or {}).get("status") == "GEGENARGUMENT"])
    original_required = 4 if sample_security == "NIEDRIG" else 3
    structural_max = STRUCTURAL_APPLICABLE_BLOCKS.get(str(family), original_required)
    required = min(original_required, structural_max)

    gates = dict(out.get("gates") or {})
    multi = "BESTANDEN" if len(confirmations) >= required and any(name != "UNDERLYING" for name in confirmations) else ("EINGESCHRÄNKT" if len(confirmations) >= 2 else "NICHT BESTANDEN")
    old_multi = gates.get("multi_block_confirmation")
    if isinstance(old_multi, dict):
        multi_payload = dict(old_multi)
        multi_payload.update({"status": multi, "confirmations": len(confirmations), "required": required,
                              "original_required": original_required, "structural_applicable_max": structural_max})
    else:
        multi_payload = {"status": multi, "confirmations": len(confirmations), "required": required,
                         "original_required": original_required, "structural_applicable_max": structural_max}
    gates["multi_block_confirmation"] = multi_payload
    gates["gate_v1"] = {
        "rule": "min(original_required, structural_applicable_block_count_for_family)",
        "family": family,
        "original_required": original_required,
        "structural_applicable_max": structural_max,
        "required": required,
        "availability_does_not_reduce_requirement": True,
    }

    pre = gates.get("pre_match_integrity") or result.get("pre_match_integrity") or {}
    robustness = gates.get("robustness") or diagnostics.get("robustness_status") or "NICHT PRÜFBAR"
    quality = gates.get("data_quality") or diagnostics.get("data_quality") or "MITTEL"
    coherence = gates.get("coherence") or {}
    coherence_ok = coherence.get("passed", True) if isinstance(coherence, dict) else True
    label = _selected_label(result, market_key)
    p_pct = (result.get("strongest_market") or {}).get("probability_pct")
    p_text = f" bei {p_pct} %" if p_pct is not None else ""

    reasons: List[str] = []
    if isinstance(pre, dict) and pre.get("strict_pre_match") is False:
        final = "AUSLASSEN"
        reasons.append("Die Analyse wurde nicht mehr vor dem dokumentierten Anpfiffzeitpunkt erstellt; deshalb ist eine Pre-Match-Freigabe ausgeschlossen.")
    elif strength < 0.20 or len(counters) >= 2:
        final = "AUSLASSEN"
        if strength < 0.20:
            reasons.append(f"{label}{p_text} ist innerhalb seiner Marktfamilie nicht deutlich genug vom neutralen Niveau getrennt. Die These ist zu schwach für BEOBACHTEN oder SPIELEN.")
        else:
            reasons.append(f"{label}{p_text} wird von mindestens zwei relevanten Gegenargumenten gebremst ({_human_block_list(counters)}). Die Prognose ist dadurch nicht robust genug.")
    elif strength < 0.30:
        final = "BEOBACHTEN"
        reasons.append(f"{label}{p_text} ist zwar der stärkste Markt, aber die normalisierte Marktfamilienstärke liegt mit {round(strength*100,1)} % unter der SPIELEN-Schwelle von 30 %. Deshalb bleibt die Empfehlung BEOBACHTEN.")
    else:
        blockers: List[str] = []
        if len(confirmations) < required:
            blockers.append(f"Die Wahrscheinlichkeit ist stark genug, aber nur {len(confirmations)} von {required} strukturell erforderlichen Evidenzblöcken bestätigen {label}. Die These ist noch nicht breit genug abgesichert.")
        if counters:
            blockers.append(f"Es gibt ein relevantes Gegenargument aus {_human_block_list(counters)}. Dadurch ist {label} trotz der Modellwahrscheinlichkeit nicht widerspruchsfrei.")
        if robustness == "NICHT BESTANDEN":
            blockers.append("Der Removal-Stress ist nicht bestanden: Wird der einflussreichste Kernblock neutralisiert, bleibt die Prognose nicht stabil genug.")
        if quality == "NIEDRIG":
            blockers.append("Die Datenqualität ist für eine SPIELEN-Freigabe zu niedrig; V1 ersetzt fehlende oder schwache Daten nicht durch Annahmen.")
        if not coherence_ok:
            blockers.append("Die Wahrscheinlichkeiten bestehen die Kohärenzprüfung nicht vollständig; deshalb wird keine SPIELEN-Freigabe erteilt.")
        final = "SPIELEN" if not blockers else "BEOBACHTEN"
        if blockers:
            reasons.extend(blockers)
        else:
            reasons.append(f"{label}{p_text} erfüllt Gate V1: ausreichende Marktfamilienstärke, {len(confirmations)}/{required} Bestätigungen, kein relevantes Gegenargument und keine harte Robustheits-/Qualitätssperre.")

    specialist_note = _specialist_note(report, market_key)
    if specialist_note:
        reasons.append(specialist_note)

    out["version"] = "V1 / V0.4.3 FULL-5 Core + Gate V1 + Five-File Specialist Profiles"
    out["scope"] = "V0.4.3 bleibt der Probability Core. Gate V1 korrigiert nur strukturelle Confirmation-Anwendbarkeit; Specialist-Profile liefern transparente Robustheitsdiagnostik ohne erfundene Probability-Gewichte."
    out["gates"] = gates
    out["final_decision"] = final
    out["decision_reasons"] = reasons
    out["decision_reason_summary"] = reasons[0] if reasons else "Keine zusätzliche Begründung verfügbar."
    out["confirming_blocks"] = confirmations
    out["counter_blocks"] = counters
    out["confirming_block_labels"] = [TECHNICAL_BLOCK_LABELS.get(x, x) for x in confirmations]
    out["counter_block_labels"] = [TECHNICAL_BLOCK_LABELS.get(x, x) for x in counters]
    out["specialist_profiles"] = report.get("v1_specialist_profiles") or {}
    out["probability_core_lock"] = {
        "baseline": BASELINE,
        "full5_features": v043_engine.FEATURE_COUNT,
        "alpha": v043_release.FULL5_ALPHA,
        "dixon_coles_rho": v042_engine.RHO,
        "probabilities_modified_by_v1": False,
    }
    return out


def _num_obj(value: Any) -> Optional[float]:
    try:
        if value is None or isinstance(value, bool):
            return None
        return float(value)
    except Exception:
        return None


def _install_v1_ui(legacy: Any) -> None:
    html = legacy.INDEX_HTML
    # Replace the technical block-name display with readable labels when V1 provides them.
    old = "    const confirmingBlocks=Array.isArray(protocol.confirming_blocks)?protocol.confirming_blocks.filter(Boolean):[];\n    const counterBlocks=Array.isArray(protocol.counter_blocks)?protocol.counter_blocks.filter(Boolean):[];"
    new = "    const confirmingBlocks=Array.isArray(protocol.confirming_block_labels)?protocol.confirming_block_labels.filter(Boolean):(Array.isArray(protocol.confirming_blocks)?protocol.confirming_blocks.filter(Boolean):[]);\n    const counterBlocks=Array.isArray(protocol.counter_block_labels)?protocol.counter_block_labels.filter(Boolean):(Array.isArray(protocol.counter_blocks)?protocol.counter_blocks.filter(Boolean):[]);"
    if old not in html:
        raise RuntimeError("V1 BEOBACHTEN label anchor not found.")
    html = html.replace(old, new, 1)
    html = html.replace("FootyStats Prognose Engine v0.4.3 FULL-5", "FootyStats Prognose Engine V1", 1)
    legacy.INDEX_HTML = html


def apply_patch(legacy: Any) -> Any:
    # This call preserves the complete proven V0.4.3 chain, including pairing and
    # visible BEOBACHTEN rationale, before V1 adds its overlay.
    app = v043_observe_fazit_ui.apply_patch(legacy)
    base_supplemental = legacy.supplemental_report
    base_protocol = legacy.elite_protocol_report

    def supplemental_v1(match_data: Any, league_data: Any = None, form_data: Any = None,
                        table_data: Any = None, player_data: Any = None) -> Dict[str, Any]:
        report = dict(base_supplemental(match_data, league_data, form_data, table_data, player_data))
        report["v1_specialist_profiles"] = _specialist_profiles(
            legacy, match_data, league_data, player_data, report
        )
        report["v1_policy"] = {
            "five_files_only": True,
            "new_shortcut_required": False,
            "player_detail_required": False,
            "probability_core": BASELINE,
            "specialist_probability_weights": "NONE_UNTIL_OOS_VALIDATED",
        }
        return report

    def protocol_v1(result: Dict[str, Any], report: Dict[str, Any]) -> Dict[str, Any]:
        base = base_protocol(result, report)
        if not result.get("ok"):
            out = dict(base)
            out["version"] = "V1 / V0.4.3 FULL-5 Core + Gate V1"
            return out
        return apply_gate_v1_to_protocol(result, report, base)

    legacy.supplemental_report = supplemental_v1
    legacy.elite_protocol_report = protocol_v1

    legacy.app.router.routes = [
        route for route in legacy.app.router.routes if getattr(route, "path", None) != "/api/health"
    ]

    def health() -> Dict[str, Any]:
        return {
            "ok": True,
            "version": VERSION,
            "engine": "v1-v043-full5-gate-specialists",
            "baseline": BASELINE,
            "v043_probability_core_locked": True,
            "full5_features": v043_engine.FEATURE_COUNT,
            "alpha": v043_release.FULL5_ALPHA,
            "rho": v042_engine.RHO,
            "gate_v1": True,
            "structural_applicable_blocks": STRUCTURAL_APPLICABLE_BLOCKS,
            "five_source_only": True,
            "new_shortcut_required": False,
            "player_detail_required": False,
            "specialist_probability_weights": False,
            "production": True,
        }

    legacy.app.add_api_route("/api/health", health, methods=["GET"])
    legacy.app.version = VERSION
    legacy.app.title = "FootyStats V1 — V0.4.3 FULL-5 + Gate V1"
    _install_v1_ui(legacy)
    return app
