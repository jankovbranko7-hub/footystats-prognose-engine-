from __future__ import annotations

import json
from typing import Any, Dict, List

from fastapi import FastAPI, File, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, Response

import engine_core as core

RELEASE_VERSION = "0.6.0"
MODEL_VERSION = "0.5.0"
REQUIRED_KINDS = ("match", "league", "form", "table", "player", "history")

app = FastAPI(
    title="FootyStats Prognose Engine",
    version=RELEASE_VERSION,
    description="Six-file FootyStats package: Match, League, Form, Table, Player, History.",
)


def _display_kind(kind: str) -> str:
    return {
        "match": "MatchDaten",
        "league": "LeagueDaten",
        "form": "FormDaten",
        "table": "TableDaten",
        "player": "PlayerDaten",
        "history": "HistoryDaten",
    }.get(kind, kind)


def _file_audit(parsed: List[Dict[str, Any]]) -> Dict[str, Any]:
    grouped: Dict[str, List[str]] = {kind: [] for kind in REQUIRED_KINDS}
    unknown: List[str] = []
    for item in parsed:
        kind = core._source_kind(item["name"])
        if kind in grouped:
            grouped[kind].append(item["name"])
        else:
            unknown.append(item["name"])

    status = {}
    for kind in REQUIRED_KINDS:
        names = grouped[kind]
        if not names:
            state = "FEHLT"
        elif len(names) > 1:
            state = "DUPLIKAT"
        else:
            state = "OK"
        status[kind] = {"label": _display_kind(kind), "status": state, "files": names}

    complete = all(status[k]["status"] == "OK" for k in REQUIRED_KINDS)
    return {"complete": complete, "sources": status, "unknown_json": unknown}


async def _parse_uploads(files: List[UploadFile]) -> tuple[List[Dict[str, Any]], List[Dict[str, str]]]:
    parsed: List[Dict[str, Any]] = []
    errors: List[Dict[str, str]] = []
    for upload in files:
        name = upload.filename or "unbenannt.json"
        if not name.lower().endswith(".json"):
            continue
        try:
            raw = await upload.read()
            data = json.loads(raw.decode("utf-8-sig"))
            parsed.append({"name": name, "data": data})
        except Exception as exc:
            errors.append({"file": name, "error": str(exc)})
    return parsed, errors


@app.get("/api/health")
def health() -> Dict[str, Any]:
    return {
        "ok": True,
        "release_version": RELEASE_VERSION,
        "model_version": MODEL_VERSION,
        "six_file_package": True,
        "required_files": [_display_kind(k) for k in REQUIRED_KINDS],
    }


@app.get("/api/shortcut-source")
def shortcut_source() -> Response:
    try:
        data = core._prepared_shortcut_data()
    except Exception as exc:
        return JSONResponse({"ok": False, "error": f"Shortcut-Datei nicht erzeugbar: {exc}"}, status_code=500)
    return Response(
        content=data,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": 'attachment; filename="FootyStats API Export V3 6 Dateien.shortcut"',
            "Cache-Control": "no-store",
        },
    )


@app.post("/api/predict-bundle")
async def predict_bundle(files: List[UploadFile] = File(...)) -> Dict[str, Any]:
    parsed, errors = await _parse_uploads(files)
    if errors:
        return {
            "ok": False,
            "phase": "FILE_READ_FAILED",
            "decision": "ANALYSE NICHT MÖGLICH",
            "release_version": RELEASE_VERSION,
            "errors": errors,
        }

    audit = _file_audit(parsed)
    if not audit["complete"]:
        return {
            "ok": False,
            "phase": "SIX_FILE_AUDIT_FAILED",
            "decision": "ANALYSE NICHT MÖGLICH – DATA_AUDIT_FAILED",
            "release_version": RELEASE_VERSION,
            "six_file_audit": audit,
        }

    result = core._analyze_bundle(parsed)
    result.pop("_archive_pair", None)
    result["release_version"] = RELEASE_VERSION
    result["engine_model_version"] = result.get("model_version", MODEL_VERSION)
    result["six_file_audit"] = audit
    return result


INDEX_HTML = r'''<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>FootyStats Engine v0.6.0</title>
<style>
:root{color-scheme:light dark;--bg:#f4f5f7;--card:#fff;--text:#111827;--muted:#6b7280;--line:#e5e7eb;--good:#047857;--bad:#b91c1c;--blue:#2563eb}
@media(prefers-color-scheme:dark){:root{--bg:#0b0d10;--card:#15181d;--text:#f4f4f5;--muted:#a1a1aa;--line:#2a2e35}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
.w{max-width:920px;margin:auto;padding:18px}.c{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:17px;margin:12px 0}.g{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:9px}.m{border:1px solid var(--line);border-radius:12px;padding:11px}.s{font-size:.86rem;color:var(--muted)}.b{font-size:1.15rem;font-weight:750}.ok{color:var(--good)}.bad{color:var(--bad)}
button,a.btn{display:block;width:100%;text-align:center;text-decoration:none;padding:13px;border:0;border-radius:11px;background:var(--text);color:var(--card);font-weight:750;font-size:1rem;margin-top:10px}a.btn.secondary{background:var(--blue);color:#fff}input{width:100%;margin:8px 0 4px}table{width:100%;border-collapse:collapse}th,td{padding:9px;border-bottom:1px solid var(--line);text-align:left}pre{white-space:pre-wrap;word-break:break-word;font-size:.75rem}.pill{display:inline-block;border:1px solid var(--line);border-radius:999px;padding:5px 9px;margin:3px 3px 3px 0;font-size:.8rem}
</style>
</head>
<body><div class="w">
<div class="c">
<h2>FootyStats Prognose Engine v0.6.0</h2>
<p class="s">Sauberer 6-Dateien-Workflow. Der probabilistische Modellkern bleibt v0.5.0; diese Release-Version vereinheitlicht Export, Audit und Render-Upload.</p>
<div class="g">
<div class="m"><b>1</b><div class="s">MatchDaten</div></div><div class="m"><b>2</b><div class="s">LeagueDaten</div></div><div class="m"><b>3</b><div class="s">FormDaten</div></div><div class="m"><b>4</b><div class="s">TableDaten</div></div><div class="m"><b>5</b><div class="s">PlayerDaten</div></div><div class="m"><b>6</b><div class="s">HistoryDaten</div></div>
</div>
<a class="btn secondary" href="/api/shortcut-source">FootyStats API Export V3 herunterladen</a>
<p class="s">Der Download ist absichtlich unsigniert. Auf dem iPhone anschließend über „Sign Shortcut File“ signieren.</p>
</div>
<div class="c">
<h3>Match-Ordner auswählen</h3>
<p class="s">Wähle den Match-Ordner mit genau den sechs JSON-Dateien. Andere Dateitypen werden ignoriert.</p>
<input id="files" type="file" multiple webkitdirectory directory accept=".json,application/json">
<button id="go">Analyse starten</button>
</div>
<div id="out"></div>
</div>
<script>
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function form(){const f=new FormData();[...document.getElementById('files').files].forEach(x=>f.append('files',x,x.webkitRelativePath||x.name));return f;}
function auditHtml(a){if(!a||!a.sources)return'';return Object.values(a.sources).map(x=>'<span class="pill '+(x.status==='OK'?'ok':'bad')+'">'+esc(x.label)+': '+esc(x.status)+'</span>').join('');}
document.getElementById('go').onclick=async()=>{
 const out=document.getElementById('out'); const fs=[...document.getElementById('files').files];
 if(!fs.length){out.innerHTML='<div class="c bad"><b>Kein Ordner ausgewählt.</b></div>';return;}
 out.innerHTML='<div class="c">6-Dateien-Paket wird geprüft…</div>';
 try{
  const r=await fetch('/api/predict-bundle',{method:'POST',body:form()}); const d=await r.json();
  if(!d.ok){out.innerHTML='<div class="c"><h3 class="bad">Analyse nicht möglich</h3>'+auditHtml(d.six_file_audit)+'<pre>'+esc(JSON.stringify(d,null,2))+'</pre></div>';return;}
  const diag=d.diagnostics||{}, rvu=diag.result_vs_underlying_detail||{}, hist=diag.history||{}, prot=diag.elite_protocol||{};
  const rows=(d.markets||[]).map(x=>'<tr><td>'+esc(x.rank)+'</td><td>'+esc(x.label)+'</td><td><b>'+esc(x.probability_pct)+'%</b></td></tr>').join('');
  out.innerHTML='<div class="c"><h3>6-Dateien-Audit</h3>'+auditHtml(d.six_file_audit)+'</div>'+ 
   '<div class="c"><h3>Entscheidung</h3><div class="g"><div class="m"><div class="s">Bester Markt</div><div class="b">'+esc((d.strongest_market||{}).label)+'</div></div><div class="m"><div class="s">Wahrscheinlichkeit</div><div class="b">'+esc((d.strongest_market||{}).probability_pct)+'%</div></div><div class="m"><div class="s">Gate</div><div class="b">'+esc(d.decision)+'</div></div><div class="m"><div class="s">History</div><div class="b">'+esc(hist.active?'AKTIV':'NICHT AKTIV')+'</div><div class="s">'+esc(hist.records_used??0)+' Spiele verwendet</div></div></div></div>'+ 
   '<div class="c"><h3>Result vs Underlying</h3><div class="g"><div class="m"><div class="s">Result</div><div class="b">'+esc(rvu.result_probability_pct==null?'—':rvu.result_probability_pct+'%')+'</div></div><div class="m"><div class="s">Underlying</div><div class="b">'+esc(rvu.underlying_probability_pct==null?'—':rvu.underlying_probability_pct+'%')+'</div></div><div class="m"><div class="s">Status</div><div class="b">'+esc(rvu.status||diag.result_vs_underlying||'—')+'</div></div></div></div>'+ 
   '<div class="c"><h3>Alle 6 Märkte</h3><table><tr><th>Rang</th><th>Markt</th><th>Wahrscheinlichkeit</th></tr>'+rows+'</table></div>'+ 
   '<div class="c"><h3>V5.2 / V5.5 Diagnose</h3><div class="s">Phase 1: '+esc(prot.phase_1_data_audit||'—')+' · Phase 2: '+esc(prot.phase_2_all_six_markets||'—')+' · Phase 3: '+esc(prot.phase_3_decision_gates||'—')+'</div><details><summary>Technische Details</summary><pre>'+esc(JSON.stringify(d,null,2))+'</pre></details></div>';
 }catch(e){out.innerHTML='<div class="c bad">Fehler: '+esc(e)+'</div>';}
};
</script></body></html>'''


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return INDEX_HTML
