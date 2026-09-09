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

    # Add a release banner without relabelling the frozen V0.4.3 probability core.
    wrapper_anchor = '<div class="w">'
    if wrapper_anchor in html:
        banner = (
            '<div class="w">'
            '<div class="c"><h2>FootyStats V0.5.0 CONTEXT-AWARE</h2>'
            '<div class="s">Probability Core: V0.4.3 FULL-5 · 5 Dateien · gelernte Reliability-Policy · '
            'Trend + News/Verfügbarkeit + optionale Aufstellung ohne erfundene Strafwerte</div></div>'
        )
        html = html.replace(wrapper_anchor, banner, 1)

    js_anchor = "    const full5=(((goal||{}).hybrid_model||{}).full5)||{};"
    if js_anchor in html:
        js_extra = js_anchor + "\n" + """    const ctxMeta=data.research_context||{};
    const ctxInterp=data.context_interpretation||{};
    const availability=ctxInterp.availability||{};
    const contextCard='<div class="c"><h3>Aktueller Match-Kontext</h3><div class="g">'+
      '<div class="m"><div class="s">Trend</div><div class="b">'+escapeHtml(ctxMeta.trend_status||'UNAVAILABLE')+'</div></div>'+
      '<div class="m"><div class="s">News / Verfügbarkeit</div><div class="b">'+escapeHtml(ctxMeta.news_availability_status||'UNAVAILABLE')+'</div></div>'+
      '<div class="m"><div class="s">Aufstellung</div><div class="b">'+escapeHtml(ctxMeta.lineup_status||'UNAVAILABLE')+'</div></div>'+
      '<div class="m"><div class="s">Exakt verknüpfte Spieler-News</div><div class="b">'+escapeHtml(availability.exact_player_links==null?'—':availability.exact_player_links)+'</div></div>'+
      '</div><p class="s">News und Aufstellung werden mit echten PlayerDaten verknüpft. Keine feste Injury-Penalty, kein NewsScore, keine erfundene Prozentkorrektur.</p></div>';
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
