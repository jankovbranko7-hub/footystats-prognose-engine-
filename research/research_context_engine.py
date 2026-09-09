from __future__ import annotations
import copy, json, os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import File, Form, Response, UploadFile

from .api_football_context_adapter import ApiFootballClient, build_api_football_context_layers
from .context_snapshot_archive import build_context_snapshot_record, snapshot_download_name
from .context_snapshot_store import persist_context_snapshot, snapshot_store_config
from .current_context_runtime import build_runtime_context, extract_match_identity
from .current_match_context import ContextValidationError, validate_current_match_context

RESEARCH_CONTEXT_VERSION = "0.10.0-research"
EXPECTED_FIVE_SOURCES = {"match", "league", "form", "table", "player"}

def _now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

def _date_utc(iso_value: str) -> str:
    return iso_value[:10]

def _truthy(value: Optional[str]) -> bool:
    return str(value or "").strip().lower() in {"1","true","yes","on"}

def _external_layers(match_identity: Dict[str, Any], observed_at_utc: str) -> Dict[str, Any]:
    key=(os.getenv("API_FOOTBALL_KEY") or "").strip()
    if not key:
        return {"news_availability":{"status":"UNAVAILABLE","events":[]},"lineup_context":{"status":"UNAVAILABLE"},"audit":{"provider":"API_FOOTBALL","status":"UNAVAILABLE_NO_KEY","fixture_resolved":False}}
    client=ApiFootballClient(key)
    fixtures=client.fixtures_by_date(_date_utc(match_identity["kickoff_at_utc"]))
    fixture,_,_=build_api_football_context_layers(match_identity,fixtures,None,None,observed_at_utc)
    fixture_id=int((fixture.get("fixture") or {})["id"])
    injuries=client.injuries_by_fixture(fixture_id)
    lineups=client.lineups_by_fixture(fixture_id) if _truthy(os.getenv("API_FOOTBALL_FETCH_LINEUPS")) else None
    fixture,news,lineup=build_api_football_context_layers(match_identity,fixtures,injuries,lineups,observed_at_utc)
    return {"news_availability":news,"lineup_context":lineup,"audit":{"provider":"API_FOOTBALL","status":"AVAILABLE","fixture_resolved":True,"fixture_id":fixture_id,"lineup_query_enabled":lineups is not None}}

def build_analysis_with_current_context(legacy: Any, parsed_files: List[Dict[str, Any]], *, generated_at_utc: Optional[str]=None, fetch_external: bool=True) -> Dict[str, Any]:
    pair=legacy.select_pair(parsed_files)
    if not pair.get("ok"): return pair
    source_files=set((pair.get("source_files") or {}).keys())
    missing=sorted(EXPECTED_FIVE_SOURCES-source_files)
    if missing:
        return {"ok":False,"decision":"ANALYSE NICHT MÖGLICH","phase":"RESEARCH_CONTEXT_FIVE_FILE_REQUIRED","error":"Research-Kontext benötigt weiterhin exakt den vollständigen Fünf-Dateien-Kern.","missing_sources":missing}
    baseline=legacy._analyze_bundle(parsed_files)
    if not isinstance(baseline,dict) or not baseline.get("ok"): return baseline
    baseline=copy.deepcopy(baseline)
    generated_at_utc=generated_at_utc or _now_utc()
    form_data=(pair.get("supplemental_data") or {}).get("form")
    identity=extract_match_identity(pair["match_data"])
    external={"news_availability":{"status":"UNAVAILABLE","events":[]},"lineup_context":{"status":"UNAVAILABLE"},"audit":{"status":"DISABLED","fixture_resolved":False}}
    if fetch_external:
        try:
            external=_external_layers(identity,generated_at_utc)
        except Exception as exc:
            external={"news_availability":{"status":"UNAVAILABLE","events":[]},"lineup_context":{"status":"UNAVAILABLE"},"audit":{"provider":"API_FOOTBALL","status":"REJECTED_OR_FAILED","fixture_resolved":False,"error":str(exc)}}
    context=build_runtime_context(pair["match_data"],form_data,generated_at_utc=generated_at_utc,news_availability=external["news_availability"],lineup_context=external["lineup_context"])
    context_audit=validate_current_match_context({k:v for k,v in context.items() if k!="integrity"})
    if not context_audit["valid"]: raise ContextValidationError('; '.join(context_audit["errors"]))
    out=copy.deepcopy(baseline)
    out["research_context"]={"version":RESEARCH_CONTEXT_VERSION,"probability_core":"V0.4.3 FULL-5 FROZEN","probabilities_modified_by_current_context":False,"manual_context_weights":False,"manual_betting_thresholds":False,"iphone_file_count":5,"trend_status":context["trend"]["status"],"news_availability_status":context["news_availability"]["status"],"lineup_status":context["lineup_context"]["status"],"external_source_audit":external["audit"],"context_sha256":context["integrity"]["context_sha256"]}
    out["current_context_snapshot"]=context
    return out

def _snapshot_and_persist(parsed: List[Dict[str, Any]], pair: Dict[str, Any], analysis: Dict[str, Any]):
    record=build_context_snapshot_record(parsed,pair,analysis)
    persistence=persist_context_snapshot(record)
    research=analysis.setdefault("research_context",{})
    research["snapshot_record_sha256"]=record["record_sha256"]
    research["snapshot_persistence"]=persistence
    return record,persistence

def install_research_context(legacy: Any) -> Any:
    app=legacy.app
    research_paths={"/api/research/predict-context","/api/research/context-health","/api/research/context-archive-bundle"}
    app.router.routes=[route for route in app.router.routes if getattr(route,"path",None) not in research_paths]
    async def predict_context(files: List[UploadFile]=File(...), fetch_external: str=Form("true")) -> Dict[str, Any]:
        parsed,errors=await legacy._read_bundle_uploads(files)
        if errors: return {"ok":False,"decision":"ANALYSE NICHT MÖGLICH","phase":"FILE_PARSE_FAILED","errors":errors}
        pair=legacy.select_pair(parsed)
        if not pair.get("ok"): return pair
        analysis=build_analysis_with_current_context(legacy,parsed,fetch_external=_truthy(fetch_external))
        if isinstance(analysis,dict) and analysis.get("ok"):
            _snapshot_and_persist(parsed,pair,analysis)
        return analysis
    async def context_archive_bundle(files: List[UploadFile]=File(...), fetch_external: str=Form("true")):
        parsed,errors=await legacy._read_bundle_uploads(files)
        if errors:
            return {"ok":False,"decision":"ANALYSE NICHT MÖGLICH","phase":"FILE_PARSE_FAILED","errors":errors}
        pair=legacy.select_pair(parsed)
        if not pair.get("ok"): return pair
        analysis=build_analysis_with_current_context(legacy,parsed,fetch_external=_truthy(fetch_external))
        if not isinstance(analysis,dict) or not analysis.get("ok"): return analysis
        record,persistence=_snapshot_and_persist(parsed,pair,analysis)
        body=json.dumps(record,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False).encode("utf-8")
        return Response(content=body,media_type="application/json",headers={"Content-Disposition":f'attachment; filename="{snapshot_download_name(record)}"',"Cache-Control":"no-store","X-Context-Record-SHA256":record["record_sha256"],"X-Context-Persistence-Status":str(persistence.get("status") or "UNKNOWN")})
    def context_health() -> Dict[str, Any]:
        store=snapshot_store_config()
        safe_store={k:v for k,v in store.items() if k not in {"key","url"}}
        return {"ok":True,"version":RESEARCH_CONTEXT_VERSION,"research_only":True,"production_core":"0.4.3","iphone_files":5,"external_api_key_configured":bool((os.getenv("API_FOOTBALL_KEY") or "").strip()),"api_football_lineup_query_enabled":_truthy(os.getenv("API_FOOTBALL_FETCH_LINEUPS")),"probabilities_modified_by_current_context":False,"context_archive":"PROVENANCE_LOCKED","snapshot_store":safe_store}
    app.add_api_route("/api/research/predict-context",predict_context,methods=["POST"])
    app.add_api_route("/api/research/context-archive-bundle",context_archive_bundle,methods=["POST"])
    app.add_api_route("/api/research/context-health",context_health,methods=["GET"])
    return app
