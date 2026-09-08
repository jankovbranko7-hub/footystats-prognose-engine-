"""Production integration and visible UI for FULL-5 NEXT."""
from __future__ import annotations

from typing import Any, Dict, List

import full5_next_engine as next_engine
import v043_observe_fazit_ui


def _install_ui(legacy: Any) -> None:
    html = legacy.INDEX_HTML
    html = html.replace("<title>FootyStats Prognose Engine</title>", "<title>FootyStats FULL-5 NEXT</title>", 1)
    html = html.replace("<h2>FootyStats Prognose Engine v0.4.0</h2>", "<h2>FootyStats FULL-5 NEXT</h2>", 1)
    html = html.replace(
        "Liga-relativer V5.5-Kern · keine Odds · keine externen Matchdaten · INSUFFICIENT_DATA-Sperre und V5.2-Guardrails aktiv",
        "V0.4.3 FULL-5 Probability Core · 40 Features · Alpha 3.0 · Dixon-Coles rho -0.25 · finale evidenzbasierte Decision Engine",
        1,
    )

    js_anchor = "    const finalDecision=protocol.final_decision||data.decision||'';"
    if js_anchor not in html:
        raise RuntimeError("FULL-5 NEXT UI JavaScript anchor not found")
    next_js = js_anchor + "\n" + r"""    const next=data.full5_next||{};
    const nextDecision=next.decision||finalDecision||data.decision||'AUSLASSEN / KEIN BET';
    const nextReasons=Array.isArray(next.positive_reasons)?next.positive_reasons.filter(Boolean):[];
    const nextCounters=Array.isArray(next.counterarguments)?next.counterarguments.filter(Boolean):[];
    const nextConfirmation=next.confirmation_gate||{};
    const nextConfirmationText=(nextConfirmation.confirmations==null||nextConfirmation.applicable_blocks==null)
      ? '—'
      : nextConfirmation.confirmations+'/'+nextConfirmation.applicable_blocks+' anwendbare Signalblöcke bestätigt → '+(nextConfirmation.status||'—');
    const nextDecisionClass=nextDecision==='SPIELEN'?'ok':(nextDecision.indexOf('KEIN BET')>=0?'bad':'');
    const nextReasonList=nextReasons.length?'<ul>'+nextReasons.map(function(x){return '<li>'+escapeHtml(x)+'</li>';}).join('')+'</ul>':'<p class="s">Keine bestätigenden Gründe verfügbar.</p>';
    const nextCounterList=nextCounters.length?'<ul>'+nextCounters.map(function(x){return '<li>'+escapeHtml(x)+'</li>';}).join('')+'</ul>':'<p class="ok"><b>Keine relevanten Gegenargumente.</b></p>';
    const nextCard='<div class="c"><h3>FULL-5 NEXT – Finale Entscheidung</h3><div class="g">'+
      '<div class="m"><div class="s">Gewählter Markt</div><div class="b">'+escapeHtml(next.selected_market_label||'—')+'</div></div>'+
      '<div class="m"><div class="s">V0.4.3 Core</div><div class="b">'+escapeHtml(next.probability_pct==null?'—':next.probability_pct+'%')+'</div></div>'+
      '<div class="m"><div class="s">Entscheidung</div><div class="b '+nextDecisionClass+'">'+escapeHtml(nextDecision)+'</div></div>'+
      '<div class="m"><div class="s">Signal Agreement / Conflict</div><div class="b">'+escapeHtml(next.signal_agreement==null?'—':next.signal_agreement)+' / '+escapeHtml(next.signal_conflict==null?'—':next.signal_conflict)+'</div></div>'+
      '<div class="m"><div class="s">Bestätigung</div><div class="b">'+escapeHtml(nextConfirmationText)+'</div></div>'+
      '<div class="m"><div class="s">Datenqualität</div><div class="b">'+escapeHtml(next.data_quality||diag.data_quality||'—')+'</div></div>'+
      '<div class="m"><div class="s">Robustheit</div><div class="b">'+escapeHtml(next.robustness||'—')+'</div></div>'+
      '<div class="m"><div class="s">Sample</div><div class="b">'+escapeHtml(next.sample_security||diag.sample_security||'—')+'</div><div class="s">Quality '+escapeHtml(next.sample_quality==null?'—':next.sample_quality)+'</div></div>'+
      '<div class="m"><div class="s">FULL-5</div><div class="b">'+escapeHtml(next.full5_status||'—')+'</div></div>'+
      '</div><h4>Wichtigste Entscheidungsgründe</h4>'+nextReasonList+
      '<h4>Gegenargumente / Konflikte</h4>'+nextCounterList+
      '<p class="s">'+escapeHtml(next.why_not_higher_probability_market||'')+'</p></div>';
"""
    html = html.replace(js_anchor, next_js, 1)

    card_anchor = "      observeCard+\n      '<div class=\"c\"><h3>Result vs Underlying</h3><div class=\"g\">'+"
    if card_anchor not in html:
        raise RuntimeError("FULL-5 NEXT UI card anchor not found")
    html = html.replace(card_anchor, "      nextCard+\n" + card_anchor, 1)
    legacy.INDEX_HTML = html


def apply_patch(legacy: Any) -> Any:
    app = v043_observe_fazit_ui.apply_patch(legacy)
    analyze_v043 = legacy._analyze_bundle

    def analyze_bundle_next(parsed_files: List[Dict[str, Any]]) -> Dict[str, Any]:
        blocked = next_engine.blocked_target_fields(parsed_files)
        clean_files = next_engine.sanitize_parsed_files(parsed_files)
        result = analyze_v043(clean_files)
        result = next_engine.apply_full5_next(result, clean_files)
        if result.get("ok") and result.get("full5_next") is not None:
            result["full5_next"]["blocked_target_fields"] = blocked
            result["diagnostics"]["full5_next"]["blocked_target_fields"] = blocked
        return result

    legacy._analyze_bundle = analyze_bundle_next
    _install_ui(legacy)
    legacy.app.router.routes = [route for route in legacy.app.router.routes if getattr(route, "path", None) != "/api/health"]

    def health() -> Dict[str, Any]:
        return {
            "ok": True,
            "version": next_engine.VERSION,
            "engine": "full5-next-evidence-gated-six-market",
            "probability_core": "V0.4.3 FULL-5",
            "baseline": "v0.4.2-hybrid-lambda",
            "full5_features": 40,
            "alpha": 3.0,
            "rho": -0.25,
            "elite_lambda_correction": False,
            "new_feature_blocks": 0,
            "file_6": False,
            "file_7": False,
            "no_bet": True,
            "oos": {"hits": 23, "plays": 33, "hit_rate": 0.696969696969697},
            "production": True,
        }

    legacy.app.add_api_route("/api/health", health, methods=["GET"])
    legacy.app.version = next_engine.VERSION
    legacy.app.title = "FootyStats FULL-5 NEXT Production"
    return app
