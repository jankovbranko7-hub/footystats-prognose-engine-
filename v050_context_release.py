"""V0.5.0 CONTEXT-AWARE release patch.

Probability core stays byte-for-byte V0.4.3 FULL-5 behavior.  The promoted
changes are: five-file trend/context audit, fact-only availability/lineup
interpretation, provenance snapshots, and the learned reliability-cluster final
decision policy.  Legacy V0.4.3 performance gates remain diagnostics only.
"""
from __future__ import annotations
from typing import Any

import v043_observe_fazit_ui
from research.research_context_engine import install_context_production

VERSION = "0.5.0"


def _install_context_ui(legacy: Any) -> None:
    html = legacy.INDEX_HTML

    # Add one clear V0.5.0 release identity while keeping V0.4.3 explicitly
    # labelled as the frozen probability core rather than a second engine.
    wrapper_anchor = '<div class="w">'
    if wrapper_anchor in html:
        banner = (
            '<div class="w">'
            '<div class="c"><h2>FootyStats V0.5.0 CONTEXT-AWARE</h2>'
            '<div class="s">Eine Engine · Probability Core: V0.4.3 FULL-5 · 5 Dateien · '
            'gelernte Reliability-Policy · Trend + News/Verfügbarkeit + optionale Aufstellung '
            'ohne erfundene Strafwerte</div></div>'
        )
        html = html.replace(wrapper_anchor, banner, 1)

    # The legacy upload card is still the same five-file input surface. Relabel
    # it so the UI does not look like two separate prediction engines.
    html = html.replace(
        'FootyStats Prognose Engine v0.4.3 FULL-5',
        'V0.5.0 CONTEXT-AWARE – 5-Dateien Analyse',
        1,
    )
    html = html.replace(
        'V0.4.3 FULL-5 · Regularized Lambda + Dixon-Coles · 5 FootyStats-Dateien · familiennormalisierte Märkte · keine Odds',
        'Eine gemeinsame Analyse: V0.4.3 FULL-5 Probability Core + gelernte Reliability-Policy + aktueller Match-Kontext · 5 FootyStats-Dateien · keine Odds',
        1,
    )

    # V0.4.3 still computes legacy gate diagnostics, but they must never be
    # presented as the reason for the V0.5.0 final action. Replace only the
    # presentation block; no model values are touched.
    legacy_observe_js = """    const finalDecision=protocol.final_decision||data.decision||'';
    const decisionReasons=Array.isArray(protocol.decision_reasons)?protocol.decision_reasons.filter(Boolean):[];
    const confirmingBlocks=Array.isArray(protocol.confirming_blocks)?protocol.confirming_blocks.filter(Boolean):[];
    const counterBlocks=Array.isArray(protocol.counter_blocks)?protocol.counter_blocks.filter(Boolean):[];
    const strongest=data.strongest_market||{};
    const observeLead=(strongest.label&&strongest.probability_pct!=null)
      ? strongest.label+' liegt bei '+strongest.probability_pct+' %, ist aber nach den Decision Gates noch nicht für SPIELEN freigegeben.'
      : 'Der stärkste Markt ist nach den Decision Gates noch nicht für SPIELEN freigegeben.';
    const observeReasonText=decisionReasons.length
      ? decisionReasons.join(' ')
      : 'Mindestens ein Freigabe-Gate ist noch nicht stark genug bestätigt.';
    const observeBlocks=[];
    if(confirmingBlocks.length)observeBlocks.push('Bestätigend: '+confirmingBlocks.join(', '));
    if(counterBlocks.length)observeBlocks.push('Gegenargumente: '+counterBlocks.join(', '));
    const observeCard=finalDecision==='BEOBACHTEN'
      ? '<div class="c"><h3>Warum BEOBACHTEN?</h3><div class="b">'+escapeHtml(observeLead)+'</div><p>'+escapeHtml(observeReasonText)+'</p>'+
        (observeBlocks.length?'<div class="s">'+escapeHtml(observeBlocks.join(' · '))+'</div>':'')+'</div>'
      : '';
"""
    policy_observe_js = """    const finalDecision=data.decision||protocol.final_decision||'';
    const strongest=data.strongest_market||{};
    const learnedPolicy=data.learned_decision_policy||{};
    const assignedCentroid=(typeof learnedPolicy.assigned_centroid==='number')?learnedPolicy.assigned_centroid:null;
    const observeLead=(strongest.label&&strongest.probability_pct!=null)
      ? strongest.label+' ist mit '+strongest.probability_pct+' % der stärkste Markt und wurde von der gelernten Reliability-Policy der mittleren Zuverlässigkeitsgruppe zugeordnet.'
      : 'Der stärkste Markt wurde von der gelernten Reliability-Policy der mittleren Zuverlässigkeitsgruppe zugeordnet.';
    const observeReasonText='Die finale V0.5.0-Entscheidung stammt aus der gelernten Reliability-Cluster-Policy. Alte V0.4.3 Decision Gates sind nur Diagnostik und beeinflussen SPIELEN / BEOBACHTEN / AUSLASSEN nicht.';
    const observePolicyDetail=assignedCentroid==null
      ? 'Keine manuell gesetzte Performance-Schwelle.'
      : 'Zentrum der gelernten Gruppe: '+(assignedCentroid*100).toFixed(2)+' % · Zuordnung nach nächstem gelerntem Clusterzentrum · keine manuell gesetzte Performance-Schwelle.';
    const observeCard=finalDecision==='BEOBACHTEN'
      ? '<div class="c"><h3>Warum BEOBACHTEN?</h3><div class="b">'+escapeHtml(observeLead)+'</div><p>'+escapeHtml(observeReasonText)+'</p><div class="s">'+escapeHtml(observePolicyDetail)+'</div></div>'
      : '';
"""
    if legacy_observe_js in html:
        html = html.replace(legacy_observe_js, policy_observe_js, 1)

    # Make any still-visible legacy diagnostics unmistakably diagnostic only.
    html = html.replace('V5.2-Protokoll', 'Legacy V5.2-Diagnostik')
    html = html.replace('Result (historische Quote)', 'Historische Ergebnisrate')

    js_anchor = "    const full5=(((goal||{}).hybrid_model||{}).full5)||{};"
    if js_anchor in html:
        js_extra = js_anchor + "\n" + """    const ctxMeta=data.research_context||{};
    const ctxInterp=data.context_interpretation||{};
    const availability=ctxInterp.availability||{};
    const externalAudit=ctxMeta.external_source_audit||{};
    const providerStatus=externalAudit.status||'UNAVAILABLE';
    const fixtureStatus=externalAudit.fixture_resolved===true?'ZUgeordnet':(externalAudit.fixture_resolved===false?'NICHT ZUGEORDNET':'—');
    const providerError=externalAudit.error?'<p class="s">Provider-Hinweis: '+escapeHtml(externalAudit.error)+'</p>':'';
    const contextCard='<div class="c"><h3>Aktueller Match-Kontext</h3><div class="g">'+
      '<div class="m"><div class="s">Trend</div><div class="b">'+escapeHtml(ctxMeta.trend_status||'UNAVAILABLE')+'</div></div>'+
      '<div class="m"><div class="s">News / Verfügbarkeit</div><div class="b">'+escapeHtml(ctxMeta.news_availability_status||'UNAVAILABLE')+'</div></div>'+
      '<div class="m"><div class="s">Aufstellung</div><div class="b">'+escapeHtml(ctxMeta.lineup_status||'UNAVAILABLE')+'</div></div>'+
      '<div class="m"><div class="s">Exakt verknüpfte Spieler-News</div><div class="b">'+escapeHtml(availability.exact_player_links==null?'—':availability.exact_player_links)+'</div></div>'+
      '<div class="m"><div class="s">API-Football Status</div><div class="b">'+escapeHtml(providerStatus)+'</div></div>'+
      '<div class="m"><div class="s">Fixture-Zuordnung</div><div class="b">'+escapeHtml(fixtureStatus)+'</div></div>'+
      '</div>'+providerError+'<p class="s">News und Aufstellung werden mit echten PlayerDaten verknüpft. Keine feste Injury-Penalty, kein NewsScore, keine erfundene Prozentkorrektur.</p></div>';
"""
        html = html.replace(js_anchor, js_extra, 1)

        card_anchor = "      '<div class=\"c\"><h3>FULL-5-Status</h3>"
        if card_anchor in html:
            html = html.replace(card_anchor, "      contextCard+\n" + card_anchor, 1)

    legacy.INDEX_HTML = html


def apply_patch(legacy: Any) -> Any:
    app = v043_observe_fazit_ui.apply_patch(legacy)
    app = install_context_production(legacy)
    _install_context_ui(legacy)
    app.version = VERSION
    app.title = "FootyStats Prognose Engine V0.5.0 CONTEXT-AWARE"
    return app
