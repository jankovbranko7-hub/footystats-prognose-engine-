"""Render entry point for FootyStats V0.5.0 production with a SPEC v1.1-first UI."""
import app_v040 as legacy
import v043_engine
from v050_footystats_unified_logic import apply_patch as apply_v050_patch
from v050_official_spec_patch import apply_patch as apply_official_spec_patch

# Keep the frozen V0.4.3 FULL-5 probability stack bound exactly as before.
v043_engine.legacy = legacy

app = apply_official_spec_patch(legacy, apply_v050_patch(legacy))

# The backend remains fully audit-capable. The normal screen is deliberately
# reduced to the Official Analysis Spec v1.1 workflow so the user sees one
# coherent path instead of several historical/research layers at once.
_legacy_diag_labels = (
    "Legacy V5.2-Diagnostik",
    "V5.2-Protokoll",
    "Interne Diagnose (ohne Einfluss)",
)
for _label in _legacy_diag_labels:
    _tile = (
        "'<div class=\"m\"><div class=\"s\">" + _label + "</div><b>'+"
        "escapeHtml(protocol.phase_1_data_audit||'—')+' / '+"
        "escapeHtml(protocol.phase_2_all_six_markets||'—')+'</b></div>'+"
    )
    legacy.INDEX_HTML = legacy.INDEX_HTML.replace(_tile, "", 1)

# One clear identity: SPEC v1.1 on top, frozen model mechanics in the backend.
_v050_banner = (
    '<div class="c"><h2>FootyStats V0.5.0 CONTEXT-AWARE</h2>'
    '<div class="s">Eine Engine · Probability Core: V0.4.3 FULL-5 · 5 Dateien · '
    'gelernte Reliability-Policy · Trend + News/Verfügbarkeit + optionale Aufstellung '
    'ohne erfundene Strafwerte</div></div>'
)
legacy.INDEX_HTML = legacy.INDEX_HTML.replace(_v050_banner, "", 1)
legacy.INDEX_HTML = legacy.INDEX_HTML.replace(
    "V0.5.0 CONTEXT-AWARE – 5-Dateien Analyse",
    "FootyStats SPEC v1.1 – 5-Dateien Analyse",
    1,
).replace(
    "FootyStats V0.5.0 CONTEXT-AWARE",
    "FootyStats SPEC v1.1 – 5-Dateien Analyse",
    1,
).replace(
    "Eine gemeinsame Analyse: V0.4.3 FULL-5 Probability Core + gelernte Reliability-Policy + aktueller Match-Kontext · 5 FootyStats-Dateien · keine Odds",
    "Strict Pre-Match · MatchDaten + LeagueDaten + FormDaten + TableDaten + PlayerDaten · Marktvergleich und abgeleitete Empfehlung · keine Odds",
    1,
).replace(
    "5-Dateien Pre-Match Analyse · V0.4.3 FULL-5 Probability Core · ergebnisvalidierte OOF-Reliability-Policy + FootyStats Gesamtlogik · Official Analysis Spec 1.1 · keine Odds",
    "Strict Pre-Match · MatchDaten + LeagueDaten + FormDaten + TableDaten + PlayerDaten · Marktvergleich und abgeleitete Empfehlung · keine Odds",
    1,
).replace(
    "Match-Ordner auswählen",
    "5-Dateien Match-Paket auswählen",
    1,
).replace(
    ">V0.5.0 Analyse starten<",
    ">SPEC v1.1 Analyse starten<",
    1,
).replace(
    ">Analyse starten<",
    ">SPEC v1.1 Analyse starten<",
    1,
)

# Replace the small provenance-only SPEC card by one compact decision-oriented
# SPEC view. This does NOT claim that FootyStats publishes a universal betting
# decision formula. The recommendation is explicitly labelled as engine-derived
# from the SPEC v1.1 data package plus the already validated/frozen model path.
_old_spec_card = """    const officialSpecCard=officialSpec.name
      ? '<div class=\"c\"><h3>FootyStats Official Analysis Spec '+escapeHtml(officialSpec.version||'')+'</h3><div class=\"g\">'+
        '<div class=\"m\"><div class=\"s\">Temporal Audit</div><div class=\"b\">'+escapeHtml(temporalOfficial.overall||'—')+'</div></div>'+
        '<div class=\"m\"><div class=\"s\">BTTS Tutorial-Regel</div><div class=\"b\">'+escapeHtml(bttsOfficial.live_status||bttsOfficial.strict_historical_status||'—')+'</div></div>'+
        '<div class=\"m\"><div class=\"s\">Low-Scoring Tutorial-Regel</div><div class=\"b\">'+escapeHtml(lowOfficial.live_status||lowOfficial.strict_historical_status||'—')+'</div></div>'+
        '</div><p class=\"s\">Offizielle FootyStats-Definitionen und Tutorial-Regeln werden getrennt ausgewiesen. Sie sind Evidenz-Flags, keine kalibrierten Wahrscheinlichkeiten und verändern weder den V0.4.3 Probability Core noch automatisch die finale Aktion.</p></div>'
      : '';
"""
_new_spec_card = """    const spec11Resolution=fsLogic.resolution||{};
    const spec11Signals=Array.isArray(fsLogic.signals)?fsLogic.signals:[];
    const spec11PlayerPagination=officialSpec.player_pagination||{};
    const spec11Leakage=officialSpec.target_match_leakage||{};
    const spec11Strongest=data.strongest_market||{};
    const spec11Markets=Array.isArray(data.markets)?data.markets:[];
    const spec11SignalRows=spec11Signals.map(function(sig){
      return '<div class=\"m\"><div class=\"s\">'+escapeHtml(sig.domain||'SPEC-Signal')+'</div><div class=\"b\">'+escapeHtml(sig.status||'—')+'</div><div class=\"s\">'+escapeHtml(sig.reason||'')+'</div></div>';
    }).join('');
    const spec11MarketRows=spec11Markets.map(function(m){
      const p=(m.probability_pct==null)?'—':(Number(m.probability_pct).toFixed(1)+' %');
      return '<tr><td>'+escapeHtml(m.label||m.key||'—')+'</td><td><b>'+escapeHtml(p)+'</b></td></tr>';
    }).join('');
    const spec11Integrity=spec11Leakage.prediction_feature_use_allowed===false?'TARGET-LEAKAGE GESPERRT':'SAUBER';
    const spec11Recommendation=spec11Resolution.final_action||data.decision||'—';
    const spec11Reason=spec11Resolution.reason||'Empfehlung wird aus der validierten Modellaktion und den verfügbaren SPEC-v1.1-Kontextsignalen abgeleitet.';
    const officialSpecCard=officialSpec.name
      ? '<div class=\"c\"><h3>FootyStats SPEC v1.1 – Datenprüfung & Empfehlung</h3>'+
        '<div class=\"g\">'+
        '<div class=\"m\"><div class=\"s\">Strict Pre-Match</div><div class=\"b\">'+escapeHtml(temporalOfficial.overall||'—')+'</div></div>'+
        '<div class=\"m\"><div class=\"s\">Player-Pagination</div><div class=\"b\">'+escapeHtml(spec11PlayerPagination.status||'—')+'</div></div>'+
        '<div class=\"m\"><div class=\"s\">Target-Datenintegrität</div><div class=\"b\">'+escapeHtml(spec11Integrity)+'</div></div>'+
        '<div class=\"m\"><div class=\"s\">Stärkster Markt</div><div class=\"b\">'+escapeHtml(spec11Strongest.label||'—')+'</div></div>'+
        '<div class=\"m\"><div class=\"s\">Modellwahrscheinlichkeit</div><div class=\"b\">'+escapeHtml(spec11Strongest.probability_pct==null?'—':(Number(spec11Strongest.probability_pct).toFixed(2)+' %'))+'</div></div>'+
        '<div class=\"m\"><div class=\"s\">SPEC-Datenbild</div><div class=\"b\">'+escapeHtml(fsLogic.overall_status||'—')+'</div></div>'+
        '<div class=\"m\"><div class=\"s\">Abgeleitete Empfehlung</div><div class=\"b\">'+escapeHtml(spec11Recommendation)+'</div></div>'+
        '</div>'+
        '<h4>Marktvergleich</h4><table><thead><tr><th>Markt</th><th>Wahrscheinlichkeit</th></tr></thead><tbody>'+spec11MarketRows+'</tbody></table>'+
        '<h4>SPEC-v1.1-Signale</h4><div class=\"g\">'+spec11SignalRows+'</div>'+
        '<p><b>Begründung:</b> '+escapeHtml(spec11Reason)+'</p>'+
        '<p class=\"s\">BTTS-Tutorial: '+escapeHtml(bttsOfficial.live_status||bttsOfficial.strict_historical_status||'—')+' · Low-Scoring-Tutorial: '+escapeHtml(lowOfficial.live_status||lowOfficial.strict_historical_status||'—')+'. Diese offiziellen Tutorial-Regeln bleiben Evidenz-Flags.</p>'+
        '<p class=\"s\"><b>Transparenz:</b> FootyStats veröffentlicht keine universelle SPEC-v1.1-Formel für SPIELEN / BEOBACHTEN / AUSLASSEN. Die hier angezeigte Empfehlung ist deshalb ausdrücklich eine Engine-Ableitung aus den SPEC-v1.1-Daten, dem eingefrorenen Probability Core und der validierten Reliability-/Kontextlogik – keine als offiziell ausgegebene FootyStats-Wettregel.</p></div>'
      : '';
"""
if _old_spec_card in legacy.INDEX_HTML:
    legacy.INDEX_HTML = legacy.INDEX_HTML.replace(_old_spec_card, _new_spec_card, 1)

# The normal mobile result view keeps only the pairing/assignment and the new
# SPEC v1.1 card. Legacy, research and implementation-detail cards remain in the
# JSON/backend for auditability but are hidden from the normal screen.
_spec11_ui_cleanup = r"""
<script>
(function(){
  const keepPrefixes=['Dateien automatisch zugeordnet','Spielpaarung','FootyStats SPEC v1.1'];
  function cleanSpec11View(){
    const out=document.getElementById('out');
    if(!out)return;
    out.querySelectorAll('.c').forEach(function(card){
      const heading=card.querySelector(':scope > h3');
      if(!heading)return;
      const text=(heading.textContent||'').trim();
      if(!keepPrefixes.some(function(prefix){return text.indexOf(prefix)===0;})){
        card.style.display='none';
      }
    });
  }
  document.addEventListener('DOMContentLoaded',function(){
    cleanSpec11View();
    const out=document.getElementById('out');
    if(out)new MutationObserver(cleanSpec11View).observe(out,{childList:true,subtree:true});
  });
})();
</script>
"""
legacy.INDEX_HTML = legacy.INDEX_HTML.replace('</body>', _spec11_ui_cleanup + '</body>', 1)

# Keep explanatory legacy wording out of the visible SPEC-first identity.
legacy.INDEX_HTML = legacy.INDEX_HTML.replace(
    "Die OOF-Reliability-Policy liefert die Ausgangsaktion. Danach prüft die FootyStats Gesamtlogik die zusätzlichen fünf-Dateien-Kontextblöcke als eine qualitative Einheit. Ein klarer Widerspruch kann die Aktion eine Stufe senken; nur vollständige einstimmige Bestätigung kann sie eine Stufe erhöhen. Wahrscheinlichkeiten werden dabei nicht verändert.",
    "Die Empfehlung wird aus der validierten Modellaktion und den verfügbaren SPEC-v1.1-Datensignalen abgeleitet; fehlende Daten werden nicht erfunden.",
)
