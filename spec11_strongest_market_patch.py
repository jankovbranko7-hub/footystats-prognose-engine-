"""Production surface for SPEC v1.1 strongest-market analysis."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict

from spec11_strongest_market_engine import (
    ENGINE_NAME,
    ENGINE_VERSION,
    SPEC_VERSION,
    analyze_bundle,
)

REGISTRY_FILE = Path(__file__).resolve().parent / "footystats_field_registry.json"
SHORTCUT_SCHEMA_FILE = Path(__file__).resolve().parent / "footystats_shortcut_api_schema.json"


INDEX_HTML = r'''<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>FootyStats SPEC v1.1 – Stärkster Markt</title>
<style>
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:#f3f4f6;margin:0;color:#111827}
.w{max-width:900px;margin:auto;padding:16px}.c{background:#fff;border-radius:15px;padding:16px;margin:12px 0;box-shadow:0 1px 5px #0001}
.g{display:grid;grid-template-columns:repeat(auto-fit,minmax(155px,1fr));gap:9px}.m{border:1px solid #e5e7eb;border-radius:11px;padding:11px}
.b{font-size:1.1rem;font-weight:700}.hero{font-size:1.45rem;font-weight:800}.s{font-size:.84rem;color:#6b7280}.ok{color:#047857}.warn{color:#b45309}.bad{color:#b91c1c}
button{width:100%;padding:13px;border:0;border-radius:11px;background:#111827;color:#fff;font-weight:700;font-size:1rem;margin-top:8px}
input{width:100%;margin:8px 0 8px}table{width:100%;border-collapse:collapse}td,th{padding:9px 6px;border-bottom:1px solid #eee;text-align:left;font-size:.9rem}
summary{font-weight:700;cursor:pointer}pre{white-space:pre-wrap;word-break:break-word;font-size:.74rem}
</style>
</head>
<body>
<div class="w">
  <div class="c">
    <h2>SPEC-v1.1-Auswertung der FootyStats-Daten</h2>
    <p class="s">5 Dateien · Strict Pre-Match · COLD START und LOW SAMPLE erlaubt · kein V0.4.3 · kein V0.4.2 · kein Fallback · keine Odds · keine SPIELEN/BEOBACHTEN/AUSLASSEN-Engine.</p>
    <h3>5 Dateien eines Spiels auswählen</h3>
    <input id="files" type="file" multiple accept=".json,application/json">
    <div id="chosen" class="s">Noch keine Dateien ausgewählt.</div>
    <button id="go">SPEC v1.1 auswerten</button>
  </div>
  <div id="out"></div>
</div>
<script>
const picker=document.getElementById('files');
function esc(v){return String(v==null?'':v).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
function cls(v){if(v==='BESTÄTIGEND'||v===true||v==='KLAR FÜHREND')return'ok';if(v==='COLD START'||v==='LOW SAMPLE'||v==='NEUTRAL'||v==='KEINE KLARE EMPFEHLUNG')return'warn';if(v==='WIDERSPRUCH'||v===false)return'bad';return'';}
picker.onchange=function(){
  const names=[...picker.files].map(f=>f.name);
  document.getElementById('chosen').innerHTML='<b>'+names.length+' Datei(en)</b><br>'+names.map(esc).join('<br>');
};
function formFor(files){const f=new FormData();files.forEach(x=>f.append('files',x,x.name));return f;}
function signalRows(signals){
  return (signals||[]).map(s=>'<tr><td>'+esc(s.source)+'</td><td>'+esc(s.domain)+'</td><td class="'+cls(s.status)+'"><b>'+esc(s.status)+'</b></td><td>'+esc(s.reason)+'</td></tr>').join('');
}
document.getElementById('go').onclick=async function(){
  const files=[...picker.files],out=document.getElementById('out');
  if(files.length!==5){out.innerHTML='<div class="c bad"><b>Exakt 5 JSON-Dateien auswählen.</b></div>';return;}
  out.innerHTML='<div class="c">SPEC v1.1 prüft Pairing, Zeitstempel, Pagination und alle verfügbaren FootyStats-Signale…</div>';
  try{
    const r=await fetch('/api/predict-bundle',{method:'POST',body:formFor(files)});
    const d=await r.json();
    if(!d.ok){
      out.innerHTML='<div class="c"><h3 class="bad">Auswertung nicht möglich</h3><p>'+esc(d.error||'Integritätsprüfung fehlgeschlagen.')+'</p><details><summary>Details</summary><pre>'+esc(JSON.stringify(d,null,2))+'</pre></details></div>';
      return;
    }
    const top=d.strongest_market||{},sample=d.sample_state||{},integ=d.integrity||{},match=(d.audit||{}).match||{};
    const lead=top.clear_lead?'KLAR FÜHREND':'KEINE KLARE EMPFEHLUNG';
    const markets=(d.markets||[]).map(m=>'<tr><td>'+esc(m.rank)+'</td><td><b>'+esc(m.label)+'</b></td><td>'+esc(m.support_count)+'</td><td>'+esc(m.contradiction_count)+'</td><td>'+esc(m.neutral_count)+'</td><td>'+esc(m.available_signal_count)+'</td><td><b>'+esc(m.net_evidence)+'</b></td></tr>').join('');
    const details=(d.markets||[]).map(m=>'<div class="c"><details><summary>#'+esc(m.rank)+' '+esc(m.label)+'</summary><p class="s">Bestätigend '+esc(m.support_count)+' · Widerspruch '+esc(m.contradiction_count)+' · Neutral '+esc(m.neutral_count)+' · verfügbar '+esc(m.available_signal_count)+' · Netto '+esc(m.net_evidence)+'</p><table><tr><th>Quelle</th><th>Signal</th><th>Status</th><th>Begründung</th></tr>'+signalRows(m.signals)+'</table></details></div>').join('');
    out.innerHTML=
      '<div class="c"><h3>Spiel</h3><div class="b">'+esc(match.home_name||'Heim')+' – '+esc(match.away_name||'Auswärts')+'</div><div class="s">Match-ID '+esc(match.match_id)+' · Competition '+esc(match.competition_id)+'</div></div>'+ 
      '<div class="c"><h3>1. SPEC-v1.1 Datenprüfung</h3><div class="g">'+
        '<div class="m"><div class="s">Strict Pre-Match</div><div class="b '+cls(integ.strict_prematch)+'">'+esc(integ.strict_prematch?'BESTANDEN':'NICHT BESTANDEN')+'</div></div>'+ 
        '<div class="m"><div class="s">League-Pagination</div><div class="b '+cls(((integ.pagination||{}).league_teams||{}).complete)+'">'+esc(((integ.pagination||{}).league_teams||{}).complete?'VOLLSTÄNDIG':'FEHLER')+'</div></div>'+ 
        '<div class="m"><div class="s">Player-Pagination</div><div class="b '+cls(((integ.pagination||{}).players||{}).complete)+'">'+esc(((integ.pagination||{}).players||{}).complete?'VOLLSTÄNDIG':'FEHLER')+'</div></div>'+ 
      '</div></div>'+ 
      '<div class="c"><h3>2. Stichprobe</h3><div class="g">'+
        '<div class="m"><div class="s">'+esc(match.home_name||'Heim')+'</div><div class="b '+cls((sample.home||{}).class)+'">'+esc((sample.home||{}).class)+'</div><div class="s">'+esc((sample.home||{}).matches)+' Competition-Spiele</div></div>'+ 
        '<div class="m"><div class="s">'+esc(match.away_name||'Auswärts')+'</div><div class="b '+cls((sample.away||{}).class)+'">'+esc((sample.away||{}).class)+'</div><div class="s">'+esc((sample.away||{}).matches)+' Competition-Spiele</div></div>'+ 
      '</div><p class="s">0 Spiele = COLD START · 1–3 = LOW SAMPLE · diese Spiele bleiben analysierbar. Fehlende Competition-Werte werden NICHT VERFÜGBAR und nicht als Schwäche behandelt.</p></div>'+ 
      '<div class="c"><h3>3. SPEC-v1.1-Auswertung der FootyStats-Daten: stärkster Markt</h3><div class="hero">'+esc(top.label||'—')+'</div><div class="g" style="margin-top:12px">'+
        '<div class="m"><div class="s">Vergleichsstatus</div><div class="b '+cls(lead)+'">'+esc(lead)+'</div></div>'+ 
        '<div class="m"><div class="s">Bestätigende Signale</div><div class="b">'+esc(top.support_count)+'</div></div>'+ 
        '<div class="m"><div class="s">Widersprüche</div><div class="b">'+esc(top.contradiction_count)+'</div></div>'+ 
        '<div class="m"><div class="s">Neutrale Signale</div><div class="b">'+esc(top.neutral_count)+'</div></div>'+ 
        '<div class="m"><div class="s">Verfügbare Signale</div><div class="b">'+esc(top.available_signal_count)+'</div></div>'+ 
        '<div class="m"><div class="s">Netto-Evidenz</div><div class="b">'+esc(top.net_evidence)+'</div></div>'+ 
      '</div><p><b>Auswertung:</b> '+esc(d.recommendation)+'</p><p class="s">'+esc(d.recommendation_reason)+'</p><p class="s">Das ist eine Auswertung der gelieferten FootyStats-Daten nach SPEC v1.1. Es wird nicht behauptet, dass FootyStats selbst diese Wett-Empfehlung veröffentlicht.</p></div>'+ 
      '<div class="c"><h3>4. Marktvergleich</h3><table><tr><th>#</th><th>Markt</th><th>+</th><th>−</th><th>Neutral</th><th>verfügbar</th><th>Netto</th></tr>'+markets+'</table><p class="s">Keine versteckten Gewichte und keine Modellwahrscheinlichkeit. Die Rangfolge basiert auf der Richtung der tatsächlich verfügbaren SPEC-v1.1-Signale.</p></div>'+ 
      '<div class="c"><h3>5. Signal-Audit</h3><p class="s">Jeden Markt öffnen, um die verwendeten FootyStats-Signalblöcke und ihre Begründung zu sehen.</p></div>'+ 
      details+
      '<div class="c"><details><summary>Technischer SPEC-v1.1-Audit</summary><pre>'+esc(JSON.stringify(d,null,2))+'</pre></details></div>';
  }catch(e){out.innerHTML='<div class="c bad">Fehler: '+esc(String(e))+'</div>';}
};
</script>
</body>
</html>'''


def _load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def apply_patch(legacy: Any) -> Any:
    legacy._analyze_bundle = analyze_bundle
    legacy.INDEX_HTML = INDEX_HTML
    app = legacy.app

    app.router.routes = [
        route for route in app.router.routes
        if getattr(route, "path", None) not in {
            "/api/health",
            "/api/predict",
            "/api/predict-files",
            "/api/archive-bundle",
            "/api/footystats-official-spec",
            "/api/shortcut-api-schema",
        }
    ]

    def health() -> Dict[str, Any]:
        return {
            "ok": True,
            "production": True,
            "engine": ENGINE_NAME,
            "version": ENGINE_VERSION,
            "spec_version": SPEC_VERSION,
            "architecture": "SPEC_V1_1_SIGNAL_COMPARISON",
            "analysis_type": "STRONGEST_MARKET",
            "decision_engine": "NONE",
            "probability_core": "NONE",
            "v043_used": False,
            "v042_used": False,
            "fallback": "NONE",
            "odds_used": False,
            "cold_start_supported": True,
            "low_sample_supported": True,
            "shortcut_capture_unix": int(time.time()),
        }

    def official_spec() -> Dict[str, Any]:
        return _load_json(REGISTRY_FILE)

    def shortcut_schema() -> Dict[str, Any]:
        return _load_json(SHORTCUT_SCHEMA_FILE)

    app.add_api_route("/api/health", health, methods=["GET"])
    app.add_api_route("/api/footystats-official-spec", official_spec, methods=["GET"])
    app.add_api_route("/api/shortcut-api-schema", shortcut_schema, methods=["GET"])
    app.version = ENGINE_VERSION
    app.title = "FootyStats SPEC v1.1 Strongest Market Analysis"
    return app
