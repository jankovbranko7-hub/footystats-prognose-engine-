from __future__ import annotations
import copy, hashlib, json, re
from typing import Any, Dict, List

from .current_match_context import validate_current_match_context, ContextValidationError

SNAPSHOT_SCHEMA = "footystats-current-context-v1"
SOURCE_KINDS = ("match", "league", "form", "table", "player")

def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")

def sha256_json(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()

def _safe_name(value: Any, fallback: str) -> str:
    part=re.sub(r"[^A-Za-z0-9._-]+","-",str(value or fallback)).strip("-")
    return (part or fallback)[:72]

def source_manifest(parsed_files: List[Dict[str, Any]], pair: Dict[str, Any]) -> Dict[str, Any]:
    wanted={"match":pair.get("match_file"),"league":pair.get("league_file")}
    wanted.update(pair.get("source_files") or {})
    manifest: Dict[str, Any]={}
    for kind in SOURCE_KINDS:
        filename=wanted.get(kind)
        item=next((x for x in parsed_files if x.get("name")==filename),None)
        if not filename or item is None:
            raise ContextValidationError(f"missing source for snapshot manifest: {kind}")
        manifest[kind]={"filename":str(filename),"sha256":sha256_json(item.get("data"))}
    return manifest

def _baseline_subset(analysis: Dict[str, Any]) -> Dict[str, Any]:
    return copy.deepcopy({
        "ok":analysis.get("ok"),
        "model_version":analysis.get("model_version"),
        "expected_goals":analysis.get("expected_goals"),
        "probabilities":analysis.get("probabilities"),
        "markets":analysis.get("markets"),
        "strongest_market":analysis.get("strongest_market"),
        "decision":analysis.get("decision"),
        "method":analysis.get("method"),
    })

def build_context_snapshot_record(parsed_files: List[Dict[str, Any]], pair: Dict[str, Any], analysis: Dict[str, Any]) -> Dict[str, Any]:
    context=copy.deepcopy(analysis.get("current_context_snapshot"))
    if not isinstance(context,dict):
        raise ContextValidationError("analysis is missing current_context_snapshot")
    raw_context={k:v for k,v in context.items() if k!="integrity"}
    audit=validate_current_match_context(raw_context)
    if not audit.get("valid"):
        raise ContextValidationError("invalid current context: " + "; ".join(audit.get("errors") or []))
    manifest=source_manifest(parsed_files,pair)
    match=copy.deepcopy(context.get("match") or {})
    record={
        "snapshot_schema":SNAPSHOT_SCHEMA,
        "captured_at_utc":context.get("generated_at_utc"),
        "match":match,
        "five_file_sources":manifest,
        "five_file_manifest_sha256":sha256_json(manifest),
        "current_context":context,
        "current_context_sha256":audit["context_sha256"],
        "frozen_v043_output":_baseline_subset(analysis),
        "research_context":copy.deepcopy(analysis.get("research_context") or {}),
        "policies":{
            "one_match_one_unit":True,
            "strict_pre_match_required":True,
            "target_result_in_snapshot":False,
            "current_context_changes_probabilities":False,
            "manual_context_weights":False,
            "manual_betting_thresholds":False,
            "server_side_persistence_claimed":False,
        },
    }
    record["record_sha256"]=sha256_json(record)
    record["record_id"]="{}-{}-{}".format(
        _safe_name(match.get("match_id"),"match"),
        _safe_name(str(record.get("captured_at_utc") or "time").replace(":","").replace("-",""),"time"),
        record["record_sha256"][:12],
    )
    return record

def snapshot_download_name(record: Dict[str, Any]) -> str:
    m=record.get("match") or {}
    return "FootyStats-Context-{}-{}-vs-{}-{}.json".format(
        _safe_name(m.get("match_id"),"match"),
        _safe_name(m.get("home_team"),"home"),
        _safe_name(m.get("away_team"),"away"),
        record.get("record_sha256","")[:12] or "snapshot",
    )
