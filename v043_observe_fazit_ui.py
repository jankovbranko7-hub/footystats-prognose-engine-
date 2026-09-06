"""Visible BEOBACHTEN short rationale for V0.4.3 FULL-5 production UI.

Presentation-only patch. It reads the already computed V5.2 decision reasons,
confirming blocks and counter blocks. Model probabilities, lambdas, FULL-5,
Dixon-Coles and decision gates remain unchanged.
"""
from __future__ import annotations
from typing import Any

import v043_pairing_ui


def apply_patch(legacy: Any) -> Any:
    app = v043_pairing_ui.apply_patch(legacy)
    html = legacy.INDEX_HTML

    js_anchor = "    const full5=(((goal||{}).hybrid_model||{}).full5)||{};"
    if js_anchor not in html:
        raise RuntimeError("BEOBACHTEN-Fazit JS anchor not found.")

    js_extra = """    const finalDecision=protocol.final_decision||data.decision||'';
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
    html = html.replace(js_anchor, js_extra + js_anchor, 1)

    card_anchor = "      '</div></div>'+\n      '<div class=\"c\"><h3>Result vs Underlying</h3><div class=\"g\">'+"
    if card_anchor not in html:
        raise RuntimeError("BEOBACHTEN-Fazit card anchor not found.")

    card_replacement = (
        "      '</div></div>'+\n"
        "      observeCard+\n"
        "      '<div class=\"c\"><h3>Result vs Underlying</h3><div class=\"g\">'+"
    )
    legacy.INDEX_HTML = html.replace(card_anchor, card_replacement, 1)
    return app
