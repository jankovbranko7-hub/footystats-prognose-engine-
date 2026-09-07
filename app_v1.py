"""Standalone Render entry point for FootyStats V1 FULL-DATA.

No V0.4.x application or engine module is imported at runtime.
Start command:
python -m uvicorn app_v1:app --host 0.0.0.0 --port $PORT
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

import v1_standalone_engine as engine

app=FastAPI(title="FootyStats V1 FULL-DATA",version=engine.VERSION)


class Payload(BaseModel):
    matchData: Dict[str,Any]
    leagueData: Dict[str,Any]
    formData: Optional[Dict[str,Any]]=None
    tableData: Optional[Dict[str,Any]]=None
    playerData: Optional[Dict[str,Any]]=None
    playerDetailData: Optional[Dict[str,Any]]=None


def _kind(name:str)->Optional[str]:
    s=(name or "").lower().replace(" ","").replace("_","")
    # PlayerDetail must be checked before Player.
    if "playerdetaildaten" in s:return "player_detail"
    if "matchdaten" in s:return "match"
    if "leaguedaten" in s:return "league"
    if "formdaten" in s:return "form"
    if "tabledaten" in s:return "table"
    if "playerdaten" in s:return "player"
    return None


@app.get("/api/health")
def health()->Dict[str,Any]:
    return {"ok":True,"version":engine.VERSION,"engine":"v1-standalone-full-data","standalone":True,"v043_runtime_dependency":False,"expected_sources":["MatchDaten","LeagueDaten","FormDaten","TableDaten","PlayerDaten","PlayerDetailDaten"]}


@app.post("/api/predict")
def predict(payload:Payload)->Dict[str,Any]:
    try:
        return engine.analyze(payload.matchData,payload.leagueData,payload.formData,payload.tableData,payload.playerData,payload.playerDetailData)
    except ValueError as exc:
        raise HTTPException(status_code=400,detail=str(exc))


@app.post("/api/analyze-files")
async def analyze_files(files:List[UploadFile]=File(...))->Dict[str,Any]:
    parsed:Dict[str,Any]={}; names:Dict[str,str]={}; ignored=[]
    for f in files:
        k=_kind(f.filename or "")
        if not k:
            ignored.append(f.filename); continue
        if k in parsed:
            raise HTTPException(status_code=400,detail=f"Doppelte V1-Datei für {k}: {names[k]} und {f.filename}")
        try:
            parsed[k]=json.loads((await f.read()).decode("utf-8")); names[k]=f.filename or k
        except Exception as exc:
            raise HTTPException(status_code=400,detail=f"Ungültige JSON-Datei {f.filename}: {exc}")
    missing=[k for k in ("match","league") if k not in parsed]
    if missing:raise HTTPException(status_code=400,detail="V1 benötigt mindestens MatchDaten und LeagueDaten. Fehlend: "+", ".join(missing))
    try:
        out=engine.analyze(parsed["match"],parsed["league"],parsed.get("form"),parsed.get("table"),parsed.get("player"),parsed.get("player_detail"))
    except ValueError as exc:
        raise HTTPException(status_code=400,detail=str(exc))
    out["input_sources"]={k:names[k] for k in names}; out["ignored_files"]=ignored
    out["source_coverage"]={"expected":["match","league","form","table","player","player_detail"],"available":list(parsed),"missing":[k for k in ("match","league","form","table","player","player_detail") if k not in parsed]}
    return out


INDEX="""<!doctype html><html lang='de'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>FootyStats V1 FULL-DATA</title><style>body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#111;color:#eee;margin:0}.w{max-width:920px;margin:auto;padding:24px}.c{background:#1c1c1e;border:1px solid #343438;border-radius:16px;padding:20px}input,button{font-size:17px;margin-top:12px}button{padding:12px 16px;border:0;border-radius:10px;font-weight:700}.ok{color:#30d158}pre{white-space:pre-wrap;word-break:break-word;background:#000;padding:14px;border-radius:10px;max-height:65vh;overflow:auto}.s{color:#aaa}</style></head><body><div class='w'><div class='c'><h1>FootyStats V1 FULL-DATA</h1><p class='ok'><strong>Eigenständige V1 Engine</strong></p><p class='s'>6 Quellen: Match · League · Form · Table · Player · PlayerDetail. Keine Laufzeit-Abhängigkeit von V0.4.3.</p><input id='f' type='file' multiple accept='.json,application/json'><br><button onclick='go()'>V1 analysieren</button><pre id='o'>Noch keine Analyse.</pre></div></div><script>async function go(){const fs=document.getElementById('f').files;if(!fs.length)return;const fd=new FormData();for(const f of fs)fd.append('files',f);const o=document.getElementById('o');o.textContent='Analyse läuft…';try{const r=await fetch('/api/analyze-files',{method:'POST',body:fd});const j=await r.json();o.textContent=JSON.stringify(j,null,2)}catch(e){o.textContent=String(e)}}</script></body></html>"""


@app.get("/",response_class=HTMLResponse)
def index()->str:return INDEX
