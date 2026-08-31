from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, Response

import app as engine

VERSION = "0.6.0"
SHORTCUT_NAME = "FootyStats API Export V3 - 6 Dateien"
REQUIRED_KINDS = ("match", "league", "form", "table", "player", "history")
KIND_LABELS = {
    "match": "MatchDaten",
    "league": "LeagueDaten",
    "form": "FormDaten",
    "table": "TableDaten",
    "player": "PlayerDaten",
    "history": "HistoryDaten",
}

app = FastAPI(
    title="FootyStats Prognose Engine V3",
    version=VERSION,
    description="Strict six-file wrapper around the validated FootyStats engine core.",
)


def _kind_from_name(name: str) -> Optional[str]:
    normalized = (name or "").lower().replace(" ", "")
    for kind, label in KIND_LABELS.items():
        if label.lower() in normalized:
            return kind
    return None


def _six_file_contract(parsed: List[Dict[str, Any]]) -> Dict[str, Any]:
    found: Dict[str, List[str]] = {kind: [] for kind in REQUIRED_KINDS}
    unknown: List[str] = []
    for item in parsed:
        name = item.get("name") or ""
        kind = _kind_from_name(name)
        if kind is None:
            unknown.append(name)
        else:
            found[kind].append(name)

    missing = [KIND_LABELS[k] for k in REQUIRED_KINDS if len(found[k]) == 0]
    duplicates = {KIND_LABELS[k]: names for k, names in found.items() if len(names) > 1}
    exact_six = len(parsed) == 6 and not unknown and not missing and not duplicates
    return {
        "valid": exact_six,
        "expected_file_count": 6,
        "received_file_count": len(parsed),
        "required": [KIND_LABELS[k] for k in REQUIRED_KINDS],
        "found": {KIND_LABELS[k]: names for k, names in found.items()},
        "missing": missing,
        "duplicates": duplicates,
        "unknown": unknown,
    }


def _decorate(result: Dict[str, Any], contract: Dict[str, Any]) -> Dict[str, Any]:
    clean = dict(result)
    clean.pop("_archive_pair", None)
    clean["v3"] = {
        "version": VERSION,
        "package": "STRICT_6_FILE",
        "contract": contract,
        "source_order": [KIND_LABELS[k] for k in REQUIRED_KINDS],
        "probability_policy": "Match+League core; Form/Table/Player diagnostics; History only after strict pre-match/pagination validation.",
        "odds_used": False,
    }
    clean["model_version"] = VERSION
    return clean


async def _parse(files: List[UploadFile]) -> tuple[List[Dict[str, Any]], List[Dict[str, str]]]:
    return await engine._read_bundle_uploads(files)


@app.get("/api/health")
def health() -> Dict[str, Any]:
    return {
        "ok": True,
        "version": VERSION,
        "package": "STRICT_6_FILE",
        "required_files": [KIND_LABELS[k] for k in REQUIRED_KINDS],
    }


@app.get("/api/shortcut-source")
def shortcut_source() -> Response:
    """Unsigned Apple Shortcut source. Sign once with RoutineHub/HubSign on iPhone."""
    data = engine._prepared_shortcut_data()
    marker = str(engine._plistlib.loads(data).get("WFWorkflowActions", []))
    if "HistoryDaten" not in marker or "league-matches" not in marker:
        raise HTTPException(status_code=500, detail="History-Exportblock fehlt im vorbereiteten Kurzbefehl.")
    return Response(
        content=data,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": 'attachment; filename="FootyStats API Export V3 - 6 Dateien unsigned.shortcut"',
            "Cache-Control": "no-store",
        },
    )


@app.post("/api/predict-bundle")
async def predict_bundle(files: List[UploadFile] = File(...)) -> Dict[str, Any]:
    parsed, errors = await _parse(files)
    if errors:
        return {
            "ok": False,
            "decision": "ANALYSE NICHT MÖGLICH",
            "phase": "FILE_READ_FAILED",
            "error": "Mindestens eine JSON-Datei konnte nicht gelesen werden.",
            "files": errors,
            "model_version": VERSION,
        }

    contract = _six_file_contract(parsed)
    if not contract["valid"]:
        return {
            "ok": False,
            "decision": "ANALYSE NICHT MÖGLICH",
            "phase": "SIX_FILE_CONTRACT_FAILED",
            "error": "V3 akzeptiert exakt eine Datei jedes der sechs FootyStats-Dateitypen.",
            "v3": {"version": VERSION, "package": "STRICT_6_FILE", "contract": contract},
        }

    result = engine._analyze_bundle(parsed)
    return _decorate(result, contract)


@app.post("/api/archive-bundle")
async def archive_bundle(files: List[UploadFile] = File(...)):
    parsed, errors = await _parse(files)
    if errors:
        raise HTTPException(status_code=400, detail={"phase": "FILE_READ_FAILED", "files": errors})
    contract = _six_file_contract(parsed)
    if not contract["valid"]:
        raise HTTPException(status_code=400, detail={"phase": "SIX_FILE_CONTRACT_FAILED", "contract": contract})

    result = engine._analyze_bundle(parsed)
    pair = result.pop("_archive_pair", None)
    if not result.get("ok") or not pair:
        return _decorate(result, contract)

    decorated = _decorate(result, contract)
    package = engine._archive_package(parsed, pair, decorated)
    package["engine_v3"] = {
        "version": VERSION,
        "strict_six_file": True,
        "contract": contract,
    }
    return Response(
        content=engine._archive_bytes(package),
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="{engine._archive_download_name(package)}"',
            "Cache-Control": "no-store",
        },
    )


INDEX_HTML = r'''<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>FootyStats Engine V3 · 6 Dateien</title>
<style>
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:#f3f4f6;margin:0;color:#111827}
.w{max-width:920px;margin:auto;padding:18px}.c{background:#fff;border-radius:16px;padding:18px;margin:12px 0;box-shadow:0 1px 5px #0001}
.g{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:9px}.m{border:1px solid #e5e7eb;border-radius:11px;padding:11px}
.s{font-size:.86rem;color:#6b7280}.b{font-size:1.18rem;font-weight:750}.ok{color:#047857}.bad{color:#b91c1c}
button,.link{display:block;box-sizing:border-box;width:100%;padding:13px;border:0;border-radius:11px;background:#111827;color:#fff;font-weight:700;font-size:1rem;margin-top:10px;text-align:center;text-decoration:none}
.link{background:#2563eb}input{width:100%;margin:8px 0 12px}table{width:100%;border-collapse:collapse}td,th{padding:8px;border-bottom:1px solid #eee;text-align:left}pre{white-space:pre-wrap;word-break:break-word;font-size:.76rem}
</style>
</head>
<body><div class="w">
<div class="c">
<h2>FootyStats Prognose Engine V3</h2>
<p class="s"><b>Strict 6-File Package:</b> MatchDaten · LeagueDaten · FormDaten · TableDaten · PlayerDaten · HistoryDaten. Keine Odds.</p>
<div class="g">
<div class="m"><b>1</b><div class="s">MatchDaten</div></div><div class="m"><b>2</b><div class="s">LeagueDaten</div></div><div class="m"><b>3</b><div class="s">FormDaten</div></div>
<div class="m"><b>4</b><div class="s">TableDaten</div></div><div class="m"><b>5</b><div class="s">PlayerDaten</div></div><div class="m"><b>6</b><div class="s">HistoryDaten</div></div>
</div>
<h3>Match-Ordner oder 6 JSON-Dateien auswählen</h3>
<input id="folder" type="file" webkitdirectory directory multiple accept=".json,application/json">
<input id="files" type="file" multiple accept=".json,application/json">
<button id="go">6-Dateien-Paket analysieren</button>
<a class="link" href="/api/shortcut-source">V3-Kurzbefehl herunterladen (unsigned)</a>
</div><div id="out"></div>
</div>
<script>
function esc(v){return String(v==null?'':v).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
function selected(){const f=[...document.getElementById('folder').files];return f.length?f:[...document.getElementById('files').files];}
function form(files){const x=new FormData();files.forEach(f=>x.append('files',f,f.webkitRelativePath||f.name));return x;}
document.getElementById('go').onclick=async()=>{const files=selected(),out=document.getElementById('out');if(files.length!==6){out.innerHTML='<div class="c bad"><b>V3 benötigt exakt 6 JSON-Dateien.</b><div class="s">Ausgewählt: '+files.length+'</div></div>';return;}out.innerHTML='<div class="c">Prüfung läuft…</div>';try{const r=await fetch('/api/predict-bundle',{method:'POST',body:form(files)});const d=await r.json();if(!d.ok){out.innerHTML='<div class="c bad"><h3>Analyse nicht möglich</h3><pre>'+esc(JSON.stringify(d,null,2))+'</pre></div>';return;}const m=d.markets||[],diag=d.diagnostics||{},h=diag.history||{},rows=m.map(x=>'<tr><td>'+esc(x.rank)+'</td><td>'+esc(x.label)+'</td><td><b>'+esc(x.probability_pct)+'%</b></td></tr>').join('');out.innerHTML='<div class="c"><h3 class="ok">6-Dateien-Paket bestanden</h3><div class="g"><div class="m"><div class="s">Bester Markt</div><div class="b">'+esc((d.strongest_market||{}).label)+'</div></div><div class="m"><div class="s">Wahrscheinlichkeit</div><div class="b">'+esc((d.strongest_market||{}).probability_pct)+'%</div></div><div class="m"><div class="s">Entscheidung</div><div class="b">'+esc(d.decision)+'</div></div><div class="m"><div class="s">History</div><b>'+esc(h.active?'AKTIV':(h.received?'ERKANNT / NICHT AKTIV':'FEHLT'))+'</b></div></div></div><div class="c"><h3>Alle 6 Märkte</h3><table><tr><th>#</th><th>Markt</th><th>Modell</th></tr>'+rows+'</table></div><div class="c"><details><summary>Technische Diagnose</summary><pre>'+esc(JSON.stringify(d,null,2))+'</pre></details></div>';}catch(e){out.innerHTML='<div class="c bad">Fehler: '+esc(e)+'</div>';}};
</script></body></html>'''


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return INDEX_HTML
