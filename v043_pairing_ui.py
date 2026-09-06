"""Visible pairing card for V0.4.3 FULL-5 production UI.

This patch changes presentation only. Model calculations, FULL-5 parameters,
Dixon-Coles and fallback behavior remain untouched.
"""
from __future__ import annotations
from typing import Any

import v043_release


def apply_patch(legacy: Any) -> Any:
    app = v043_release.apply_patch(legacy)
    html = legacy.INDEX_HTML

    js_anchor = "    const full5=(((goal||{}).hybrid_model||{}).full5)||{};"
    if js_anchor not in html:
        raise RuntimeError("Pairing UI JS anchor not found.")

    pairing_js = """    const matchInfo=((data.audit||{}).match||{});
    const pairInfo=data.pairing||{};
    const homeName=matchInfo.home_name||pairInfo.home_name||'—';
    const awayName=matchInfo.away_name||pairInfo.away_name||'—';
    const matchId=matchInfo.match_id||pairInfo.match_id||'—';
"""
    html = html.replace(js_anchor, pairing_js + js_anchor, 1)

    card_anchor = "      '<div class=\"c\"><h3>FULL-5-Status</h3>"
    if card_anchor not in html:
        raise RuntimeError("Pairing UI card anchor not found.")

    pairing_card = (
        "      '<div class=\"c\"><h3>Spielpaarung</h3>"
        "<div class=\"b\">'+escapeHtml(homeName)+' – '+escapeHtml(awayName)+'</div>"
        "<div class=\"s\">Match-ID: '+escapeHtml(matchId)+'</div></div>'+\n"
        + card_anchor
    )
    legacy.INDEX_HTML = html.replace(card_anchor, pairing_card, 1)
    return app
