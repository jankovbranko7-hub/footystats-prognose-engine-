from __future__ import annotations
import copy, hashlib, json
from datetime import datetime, timezone
from typing import Any, Dict, List

SCHEMA_VERSION = "0.7.0"
FORBIDDEN_SCORE_KEYS = {
    "trend_score", "news_score", "availability_score", "lineup_score",
    "evidence_score", "strength_score", "play_score", "bet_score"
}
FORBIDDEN_POST_KEYS = {
    "final_score", "result", "home_goals", "away_goals", "winner",
    "actual_1x2", "actual_btts", "actual_ou25", "live_score",
    "minute", "match_status_live", "full_time_score", "half_time_score"
}
EVENT_TYPES = {"INJURY","SUSPENSION","DOUBTFUL","QUESTIONABLE","RETURN","ROTATION","MANAGER","TEAM_NEWS","OTHER"}
LINEUP_STATUS = {"CONFIRMED","PARTIAL","EXPECTED","UNAVAILABLE"}
SIDE = {"home","away"}

class ContextValidationError(ValueError):
    pass

def _dt(v: str) -> datetime:
    if not isinstance(v, str) or not v.strip():
        raise ContextValidationError(f"invalid timestamp: {v!r}")
    s=v.strip().replace("Z", "+00:00")
    d=datetime.fromisoformat(s)
    if d.tzinfo is None:
        d=d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)

def _walk_keys(obj: Any, path=""):
    if isinstance(obj, dict):
        for k,v in obj.items():
            p=f"{path}.{k}" if path else str(k)
            yield p, str(k).lower(), v
            yield from _walk_keys(v,p)
    elif isinstance(obj, list):
        for i,v in enumerate(obj):
            yield from _walk_keys(v,f"{path}[{i}]")

def canonical_hash(context: Dict[str,Any]) -> str:
    b=json.dumps(context,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(b).hexdigest()

def _evidence_time(e: Dict[str,Any], prefix: str, errors: List[str]):
    pub=e.get("published_at_utc")
    obs=e.get("observed_at_utc")
    if pub:
        try: return _dt(pub), "PUBLISHED_AT"
        except Exception as ex: errors.append(f"{prefix}.published_at_utc: {ex}"); return None,None
    if obs:
        try: return _dt(obs), "OBSERVED_AT_API_FETCH"
        except Exception as ex: errors.append(f"{prefix}.observed_at_utc: {ex}"); return None,None
    errors.append(f"{prefix} requires published_at_utc or observed_at_utc")
    return None,None

def validate_current_match_context(context: Dict[str,Any]) -> Dict[str,Any]:
    errors: List[str]=[]; warnings: List[str]=[]
    if not isinstance(context,dict):
        return {"valid":False,"errors":["context must be an object"],"warnings":[]}
    if context.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION}")
    for k in ["match","generated_at_utc","trend","news_availability","lineup_context"]:
        if k not in context: errors.append(f"missing top-level field: {k}")
    if errors: return {"valid":False,"errors":errors,"warnings":warnings}

    m=context["match"]
    for k in ["match_id","home_team","away_team","kickoff_at_utc"]:
        if not m.get(k): errors.append(f"match.{k} missing")
    try:
        kickoff=_dt(m.get("kickoff_at_utc")); generated=_dt(context.get("generated_at_utc"))
        if generated >= kickoff: errors.append("generated_at_utc must be strictly before kickoff")
    except Exception as e: errors.append(str(e)); kickoff=None; generated=None

    for p,k,v in _walk_keys(context):
        if k in FORBIDDEN_SCORE_KEYS: errors.append(f"forbidden manual score field: {p}")
        if k in FORBIDDEN_POST_KEYS: errors.append(f"forbidden target live/post field: {p}")

    trend=context.get("trend",{})
    ts=trend.get("status")
    if ts not in {"AVAILABLE","UNAVAILABLE"}: errors.append("trend.status invalid")
    if ts=="AVAILABLE":
        if trend.get("source") != "FOOTYSTATS_FIVE_FILE_DERIVED": errors.append("trend.source must be FOOTYSTATS_FIVE_FILE_DERIVED")
        try:
            snap=_dt(trend.get("snapshot_at_utc"))
            if kickoff and snap >= kickoff: errors.append("trend.snapshot_at_utc must be before kickoff")
            if generated and snap > generated: warnings.append("trend snapshot is later than context generated_at_utc")
        except Exception as e: errors.append(f"trend timestamp: {e}")
        for side in SIDE:
            if side not in trend: errors.append(f"trend.{side} missing")
    else:
        if any(k in trend for k in ["home","away"]): warnings.append("trend UNAVAILABLE contains home/away payload; verify it is not synthetic")

    na=context.get("news_availability",{})
    ns=na.get("status")
    if ns not in {"AVAILABLE","UNAVAILABLE"}: errors.append("news_availability.status invalid")
    events=na.get("events",[]) or []
    if ns=="UNAVAILABLE" and events: errors.append("news_availability UNAVAILABLE must not contain events")
    for i,e in enumerate(events):
        pre=f"news_availability.events[{i}]"
        if e.get("team_side") not in SIDE: errors.append(f"{pre}.team_side invalid")
        if e.get("event_type") not in EVENT_TYPES: errors.append(f"{pre}.event_type invalid")
        if not e.get("source_url"): errors.append(f"{pre}.source_url required")
        if not e.get("original_text"): errors.append(f"{pre}.original_text required")
        evtime,basis=_evidence_time(e,pre,errors)
        if evtime is not None:
            if kickoff and evtime >= kickoff: errors.append(f"{pre} evidence timestamp must be before kickoff")
            if generated and evtime > generated: errors.append(f"{pre} evidence timestamp cannot be after generated_at_utc")
            if e.get("timestamp_basis") and e.get("timestamp_basis") != basis:
                errors.append(f"{pre}.timestamp_basis inconsistent with timestamp field")

    lc=context.get("lineup_context",{})
    ls=lc.get("status")
    if ls not in LINEUP_STATUS: errors.append("lineup_context.status invalid")
    if ls=="UNAVAILABLE":
        if lc.get("home_players") or lc.get("away_players"): errors.append("UNAVAILABLE lineup must not contain players")
    else:
        if not lc.get("source_url"): errors.append("lineup source_url required for EXPECTED/CONFIRMED")
        ltime,basis=_evidence_time(lc,"lineup_context",errors)
        if ltime is not None:
            if kickoff and ltime >= kickoff: errors.append("lineup evidence timestamp must be before kickoff")
            if generated and ltime > generated: errors.append("lineup evidence timestamp cannot be after generated_at_utc")
            if lc.get("timestamp_basis") and lc.get("timestamp_basis") != basis:
                errors.append("lineup_context.timestamp_basis inconsistent with timestamp field")
        for side_key in ["home_players","away_players"]:
            if side_key in lc and not isinstance(lc[side_key],list): errors.append(f"lineup_context.{side_key} must be a list")

    out={"valid":not errors,"errors":errors,"warnings":warnings}
    if not errors: out["context_sha256"]=canonical_hash(context)
    return out

def build_context(match: Dict[str,Any], generated_at_utc: str, trend: Dict[str,Any] | None=None,
                  news_events: List[Dict[str,Any]] | None=None, lineup: Dict[str,Any] | None=None) -> Dict[str,Any]:
    ctx={
        "schema_version":SCHEMA_VERSION,
        "match":copy.deepcopy(match),
        "generated_at_utc":generated_at_utc,
        "trend":copy.deepcopy(trend) if trend is not None else {"status":"UNAVAILABLE"},
        "news_availability":{"status":"AVAILABLE" if news_events else "UNAVAILABLE","events":copy.deepcopy(news_events or [])},
        "lineup_context":copy.deepcopy(lineup) if lineup is not None else {"status":"UNAVAILABLE"}
    }
    audit=validate_current_match_context(ctx)
    if not audit["valid"]:
        raise ContextValidationError("; ".join(audit["errors"]))
    ctx["integrity"]={"valid":True,"context_sha256":audit["context_sha256"],"warnings":audit["warnings"]}
    return ctx
