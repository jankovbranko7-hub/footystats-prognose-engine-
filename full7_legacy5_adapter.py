from __future__ import annotations

from typing import Any, Dict, Mapping, Optional, Sequence


REQUIRED_LEGACY_KINDS=("match","league","form","table","player")


def _kind(name:str)->Optional[str]:
    low=(name or "").lower().replace(" ","")
    for kind in REQUIRED_LEGACY_KINDS:
        if f"{kind}daten" in low:
            return kind
    return None


def _int(v:Any)->Optional[int]:
    if v is None or isinstance(v,bool):
        return None
    try:
        return int(float(v))
    except (TypeError,ValueError):
        return None


def _payload(raw:Mapping[str,Any])->Any:
    return raw.get("payload") if "payload" in raw else raw


def _data(v:Any)->Any:
    return v.get("data") if isinstance(v,dict) and "data" in v else v


def adapt_legacy5_report(report:Mapping[str,Any])->Dict[str,Any]:
    """Translate a historical five-source report into research Gold input.

    This adapter NEVER fabricates RefereeDaten or ManagerDaten. Those namespaces
    are empty and explicitly marked NOT_CAPTURED_HISTORICALLY.
    """
    inputs=report.get("input_files")
    if not isinstance(inputs,list):
        raise ValueError("legacy report missing input_files")

    found:Dict[str,Dict[str,Any]]={}
    for item in inputs:
        if not isinstance(item,Mapping):
            continue
        kind=_kind(str(item.get("name") or ""))
        raw=item.get("json")
        if kind and isinstance(raw,dict):
            if kind in found:
                raise ValueError(f"duplicate legacy source: {kind}")
            found[kind]=raw

    missing=set(REQUIRED_LEGACY_KINDS)-set(found)
    if missing:
        raise ValueError(f"legacy report missing sources: {sorted(missing)}")

    match_payload=_data(_payload(found["match"]))
    if not isinstance(match_payload,dict):
        raise ValueError("legacy MatchDaten payload invalid")

    ident={
        "match_id":_int(match_payload.get("id")),
        "home_id":_int(match_payload.get("homeID")),
        "away_id":_int(match_payload.get("awayID")),
        "season_id":_int(match_payload.get("competition_id")),
        "kickoff_unix":_int(match_payload.get("date_unix")),
        "referee_id":(
            _int(match_payload.get("refereeID"))
            if (_int(match_payload.get("refereeID")) or 0)>0
            else None
        ),
    }
    if any(ident[k] is None for k in ("match_id","home_id","away_id","season_id","kickoff_unix")):
        raise ValueError("legacy MatchDaten identity incomplete")
    report_mid=_int(report.get("match_id"))
    if report_mid is not None and report_mid!=ident["match_id"]:
        raise ValueError("report/match identity mismatch")

    kickoff=ident["kickoff_unix"]
    lineage={}
    capture_times=[]
    for kind,raw in found.items():
        meta=raw.get("_footystats_meta")
        if not isinstance(meta,dict):
            raise ValueError(f"legacy source missing metadata: {kind}")
        captured=_int(meta.get("captured_at_unix"))
        if captured is None or captured>=kickoff:
            raise ValueError(f"legacy source is not strict pre-match: {kind}")
        capture_times.append(captured)

        if kind in {"league","table","player"}:
            max_time=_int(meta.get("max_time"))
            if max_time is None or max_time>=kickoff:
                raise ValueError(f"legacy source max_time invalid: {kind}")
        else:
            max_time=_int(meta.get("max_time"))

        if kind=="player":
            complete=meta.get("pagination_complete")
            if complete not in (True,"true","True",1,"1"):
                raise ValueError("legacy player pagination incomplete")
        if kind=="league":
            complete=meta.get("team_pagination_complete")
            if complete not in (True,"true","True",1,"1"):
                raise ValueError("legacy league team pagination incomplete")

        lineage[kind]={
            "filename":next(
                str(x.get("name"))
                for x in inputs
                if isinstance(x,Mapping) and _kind(str(x.get("name") or ""))==kind
            ),
            "endpoint":meta.get("endpoint"),
            "captured_at_unix":captured,
            "max_time":max_time,
        }

    namespaces={kind:_payload(raw) for kind,raw in found.items()}
    namespaces["referee"]={}
    namespaces["manager"]={}

    lineage["referee"]={
        "filename":None,
        "endpoint":None,
        "captured_at_unix":None,
        "max_time":None,
        "availability":"NOT_CAPTURED_HISTORICALLY",
    }
    lineage["manager"]={
        "filename":None,
        "endpoint":None,
        "captured_at_unix":None,
        "max_time":None,
        "availability":"NOT_CAPTURED_HISTORICALLY",
    }

    return {
        "identity":ident,
        "namespaces":namespaces,
        "lineage":lineage,
        "quality":{
            "status":"VALID_FOR_BASE5_RESEARCH",
            "strict_pre_match":True,
            "snapshot_captured_at_unix":max(capture_times),
            "historical_source_count":5,
            "full7_source_count":7,
            "referee_status":"NOT_CAPTURED_HISTORICALLY",
            "manager_status":"NOT_CAPTURED_HISTORICALLY",
            "no_backfill":True,
            "training_scope":"BASE5_CORE_ONLY",
        },
        "adapter_version":"FULL7_LEGACY5_ADAPTER_0.1",
    }
