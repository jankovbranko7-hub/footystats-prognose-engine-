from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Mapping, Optional, Sequence


REQUIRED_SOURCES=("match","league","form","table","player")


def _num(v:Any)->Optional[float]:
    if v is None or isinstance(v,bool): return None
    try:return float(v)
    except (TypeError,ValueError):return None


def _int(v:Any)->Optional[int]:
    x=_num(v); return int(x) if x is not None else None


def _parse_iso_unix(v:Any)->Optional[int]:
    if not isinstance(v,str) or not v.strip():return None
    try:
        value=v.strip().replace("Z","+00:00")
        return int(datetime.fromisoformat(value).timestamp())
    except ValueError:
        return None


def _api_data(v:Any)->Any:
    return v.get("data") if isinstance(v,dict) and "data" in v else v


def _source(report:Mapping[str,Any],name:str)->Mapping[str,Any]:
    sources=report.get("sources")
    if not isinstance(sources,Mapping) or name not in sources:
        raise ValueError(f"legacy archive missing source: {name}")
    src=sources[name]
    if not isinstance(src,Mapping) or not isinstance(src.get("content"),Mapping):
        raise ValueError(f"legacy archive invalid source wrapper: {name}")
    return src


def _form_side_responses(content:Mapping[str,Any],home_id:int,away_id:int)->Dict[str,Any]:
    teams=content.get("teams")
    if not isinstance(teams,list):
        raise ValueError("legacy form content missing teams")

    found={"home":None,"away":None}
    for response in teams:
        data=_api_data(response)
        if not isinstance(data,list):
            continue
        ids={_int(row.get("id")) for row in data if isinstance(row,Mapping)}
        if home_id in ids:
            if found["home"] is not None:
                raise ValueError("ambiguous legacy home form response")
            found["home"]=response
        if away_id in ids:
            if found["away"] is not None:
                raise ValueError("ambiguous legacy away form response")
            found["away"]=response

    if found["home"] is None or found["away"] is None:
        raise ValueError("legacy form target response missing")
    return found


def adapt_legacy_archive_report(report:Mapping[str,Any])->Dict[str,Any]:
    """Build Gold-compatible namespaces from old iPhone archive reports.

    Provenance contract:
    - strictness is proven by archive.created_at < target kickoff;
    - source hashes/filenames are preserved exactly as archived;
    - no per-source captured_at/max_time is invented;
    - Referee/Manager are never backfilled here.
    """
    for name in REQUIRED_SOURCES:
        _source(report,name)

    created_at_unix=_parse_iso_unix(report.get("created_at"))
    match_src=_source(report,"match")
    match_content=match_src["content"]
    match=_api_data(match_content)
    if not isinstance(match,Mapping):
        raise ValueError("legacy MatchDaten payload invalid")

    ident={
        "match_id":_int(match.get("id")),
        "home_id":_int(match.get("homeID")),
        "away_id":_int(match.get("awayID")),
        "season_id":_int(match.get("competition_id")),
        "kickoff_unix":_int(match.get("date_unix")),
        "referee_id":(_int(match.get("refereeID")) if (_int(match.get("refereeID")) or 0)>0 else None),
    }
    if any(ident[k] is None for k in ("match_id","home_id","away_id","season_id","kickoff_unix")):
        raise ValueError("legacy archive match identity incomplete")
    if created_at_unix is None or created_at_unix>=ident["kickoff_unix"]:
        raise ValueError("legacy archive is not strict pre-match")

    report_match=report.get("match")
    if isinstance(report_match,Mapping):
        archived_match_id=_int(report_match.get("match_id"))
        if archived_match_id is not None and archived_match_id!=ident["match_id"]:
            raise ValueError("archive header/match source identity mismatch")

    coverage=report.get("source_coverage")
    if isinstance(coverage,Mapping):
        missing=coverage.get("missing")
        if isinstance(missing,list) and missing:
            raise ValueError(f"legacy archive source coverage incomplete: {missing}")

    league_src=_source(report,"league")
    league_content=league_src["content"]
    pages=league_content.get("pages ")
    if pages is None:
        pages=league_content.get("pages")
    if not isinstance(pages,list) or not pages:
        raise ValueError("legacy league team pages missing")

    form_src=_source(report,"form")
    form_sides=_form_side_responses(
        form_src["content"], ident["home_id"], ident["away_id"]
    )

    table_src=_source(report,"table")
    player_src=_source(report,"player")
    player_pages=player_src["content"].get("pages")
    if not isinstance(player_pages,list) or not player_pages:
        raise ValueError("legacy player pages missing")

    namespaces={
        "match":match_content,
        "league":{"team_pages":pages},
        "form":form_sides,
        "table":table_src["content"],
        "player":player_src["content"],
        "referee":{},
        "manager":{},
    }

    lineage={}
    for name in REQUIRED_SOURCES:
        src=_source(report,name)
        lineage[name]={
            "filename":src.get("filename"),
            "sha256":src.get("sha256"),
            "provenance_mode":"ARCHIVED_CONTENT_HASH",
            "captured_at_unix":None,
            "max_time":None,
        }
    for name in ("referee","manager"):
        lineage[name]={
            "filename":None,
            "sha256":None,
            "provenance_mode":"NOT_CAPTURED_HISTORICALLY",
            "captured_at_unix":None,
            "max_time":None,
        }

    return {
        "identity":ident,
        "namespaces":namespaces,
        "lineage":lineage,
        "quality":{
            "status":"VALID_LEGACY_ARCHIVE_STRICT",
            "strict_pre_match":True,
            "provenance_mode":"LEGACY_ARCHIVE_STRICT",
            "archive_created_at_unix":created_at_unix,
            "snapshot_captured_at_unix":created_at_unix,
            "source_level_capture_timestamps_available":False,
            "source_level_max_time_available":False,
            "historical_source_count":5,
            "referee_status":"NOT_CAPTURED_HISTORICALLY",
            "manager_status":"NOT_CAPTURED_HISTORICALLY",
            "no_provenance_backfill":True,
            "training_scope":"BASE5_HISTORICAL_CORE",
        },
        "adapter_version":"FULL7_LEGACY_ARCHIVE_ADAPTER_0.1",
        "record_id":report.get("record_id"),
    }
