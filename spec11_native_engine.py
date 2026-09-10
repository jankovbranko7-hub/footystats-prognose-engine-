"""Standalone FootyStats SPEC v1.1 decision engine.

Consumes exactly five FootyStats export files and produces qualitative market
decisions without calling V0.4.3/V0.4.2 probability cores or any fallback.
"""
from __future__ import annotations

import math
from statistics import median
from typing import Any, Dict, Iterable, List, Optional, Tuple

ENGINE_NAME = "FOOTYSTATS_SPEC_V1_1_NATIVE_DECISION_ENGINE"
ENGINE_VERSION = "1.1.0-native"
SPEC_VERSION = "1.1"

SUPPORT = "BESTÄTIGEND"
CONTRADICT = "WIDERSPRUCH"
NEUTRAL = "NEUTRAL"
UNAVAILABLE = "NICHT VERFÜGBAR"

MARKETS = (
    ("home_win", "Sieg Heim"),
    ("draw", "Unentschieden"),
    ("away_win", "Sieg Auswärts"),
    ("btts_yes", "BTTS Yes"),
    ("btts_no", "BTTS No"),
    ("over_2_5", "Over 2,5"),
    ("under_2_5", "Under 2,5"),
)
LABELS = dict(MARKETS)
CENTRAL_SOURCES = {"MATCH", "LEAGUE", "FORM", "TABLE", "PLAYER"}


def _num(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _truthy_bool(value: Any) -> bool:
    if value is True:
        return True
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes"}
    return False


def _source_kind(filename: str) -> Optional[str]:
    name = (filename or "").lower().replace(" ", "")
    for kind, marker in (
        ("match", "matchdaten"),
        ("league", "leaguedaten"),
        ("form", "formdaten"),
        ("table", "tabledaten"),
        ("player", "playerdaten"),
    ):
        if marker in name:
            return kind
    return None


def _payload(wrapper: Any) -> Any:
    return wrapper.get("payload") if isinstance(wrapper, dict) and "payload" in wrapper else wrapper


def _meta(wrapper: Any) -> Dict[str, Any]:
    return dict(wrapper.get("_footystats_meta") or {}) if isinstance(wrapper, dict) else {}


def _api_data(response: Any) -> Any:
    if isinstance(response, dict) and "data" in response:
        return response.get("data")
    return response


def _match_obj(wrapper: Any) -> Dict[str, Any]:
    payload = _payload(wrapper)
    data = _api_data(payload)
    return data if isinstance(data, dict) else {}


def _pages(container: Any) -> List[Dict[str, Any]]:
    if isinstance(container, list):
        return [x for x in container if isinstance(x, dict)]
    if isinstance(container, dict):
        return [container]
    return []


def _page_rows(container: Any) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for page in _pages(container):
        data = _api_data(page)
        if isinstance(data, list):
            rows.extend(x for x in data if isinstance(x, dict))
    return rows


def _pager(page: Any) -> Dict[str, Any]:
    if not isinstance(page, dict):
        return {}
    pager = page.get("pager")
    return dict(pager) if isinstance(pager, dict) else {}


def _pair(parsed_files: List[Dict[str, Any]]) -> Dict[str, Any]:
    by_kind: Dict[str, List[Dict[str, Any]]] = {k: [] for k in ("match", "league", "form", "table", "player")}
    unknown: List[str] = []
    for item in parsed_files:
        kind = _source_kind(str(item.get("name") or ""))
        if kind is None:
            unknown.append(str(item.get("name") or ""))
        else:
            by_kind[kind].append(item)
    missing = [kind for kind, items in by_kind.items() if not items]
    duplicate = [kind for kind, items in by_kind.items() if len(items) > 1]
    if missing or duplicate or len(parsed_files) != 5:
        return {
            "ok": False,
            "decision": "ANALYSE NICHT MÖGLICH",
            "phase": "SPEC11_FILE_PAIRING_FAILED",
            "error": "SPEC v1.1 benötigt exakt fünf Dateien: Match, League, Form, Table und Player.",
            "missing_types": missing,
            "duplicate_types": duplicate,
            "unknown_files": unknown,
            "received_file_count": len(parsed_files),
        }
    match_item = by_kind["match"][0]
    match = _match_obj(match_item.get("data"))
    ids = {
        "match_id": int(_num(match.get("id")) or 0) or None,
        "home_id": int(_num(match.get("homeID")) or 0) or None,
        "away_id": int(_num(match.get("awayID")) or 0) or None,
        "competition_id": int(_num(match.get("competition_id")) or 0) or None,
        "kickoff_unix": int(_num(match.get("date_unix")) or 0) or None,
    }
    if any(v is None for v in ids.values()):
        return {
            "ok": False,
            "decision": "ANALYSE NICHT MÖGLICH",
            "phase": "SPEC11_IDENTITY_FAILED",
            "error": "Zentrale Match-/Team-/Competition-/Kickoff-ID fehlt.",
            "identity": ids,
        }
    return {
        "ok": True,
        "files": {k: by_kind[k][0] for k in by_kind},
        "match": match,
        "identity": ids,
    }


def _league_team_rows(league_wrapper: Any) -> List[Dict[str, Any]]:
    payload = _payload(league_wrapper)
    if not isinstance(payload, dict):
        return []
    return _page_rows(payload.get("team_pages"))


def _league_context(league_wrapper: Any) -> Dict[str, Any]:
    payload = _payload(league_wrapper)
    if not isinstance(payload, dict):
        return {}
    league = payload.get("league")
    if league is None:
        league = payload
    data = _api_data(league)
    return data if isinstance(data, dict) else {}


def _team_by_id(teams: Iterable[Dict[str, Any]], team_id: int) -> Optional[Dict[str, Any]]:
    for team in teams:
        tid = _num(team.get("id"))
        if tid is not None and int(tid) == int(team_id):
            return team
    return None


def _stats(team: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    return dict((team or {}).get("stats") or {})


def _field(team: Optional[Dict[str, Any]], key: str, *, sample_key: Optional[str] = None) -> Optional[float]:
    stats = _stats(team)
    if sample_key is not None:
        n = _num(stats.get(sample_key))
        if n is None or n <= 0:
            return None
    return _num(stats.get(key))


def _sample(team: Optional[Dict[str, Any]], split: str = "overall") -> Optional[int]:
    n = _field(team, f"seasonMatchesPlayed_{split}")
    return int(n) if n is not None and n >= 0 else None


def _sample_class(n: Optional[int]) -> str:
    if n is None or n <= 0:
        return "COLD START"
    if n <= 3:
        return "LOW SAMPLE"
    return "ESTABLISHED"


def _median(values: Iterable[Optional[float]]) -> Optional[float]:
    known = [v for v in values if v is not None]
    return float(median(known)) if known else None


def _metric(team: Optional[Dict[str, Any]], base: str, split: str) -> Optional[float]:
    key = f"{base}_{split}"
    sample_key = f"seasonMatchesPlayed_{split}"
    return _field(team, key, sample_key=sample_key)


def _metric_median(teams: Iterable[Dict[str, Any]], base: str, split: str) -> Optional[float]:
    return _median(_metric(team, base, split) for team in teams)


def _signal(source: str, domain: str, market: str, status: str, reason: str, **values: Any) -> Dict[str, Any]:
    return {"source": source, "domain": domain, "market": market, "status": status, "reason": reason, "values": values}


def _cmp(a: Optional[float], b: Optional[float]) -> Optional[int]:
    if a is None or b is None:
        return None
    return 1 if a > b else (-1 if a < b else 0)


def _relative_pair_signal(source: str, domain: str, market: str, hv: Optional[float], hm: Optional[float], av: Optional[float], am: Optional[float], *, high_supports: bool, reason: str) -> Dict[str, Any]:
    if None in (hv, hm, av, am):
        return _signal(source, domain, market, UNAVAILABLE, reason + " Mindestens ein Wert fehlt.", home_value=hv, home_reference=hm, away_value=av, away_reference=am)
    hc, ac = _cmp(hv, hm), _cmp(av, am)
    if not high_supports:
        hc, ac = -hc, -ac
    if hc > 0 and ac > 0:
        status = SUPPORT
    elif hc < 0 and ac < 0:
        status = CONTRADICT
    else:
        status = NEUTRAL
    return _signal(source, domain, market, status, reason, home_value=hv, home_reference=hm, away_value=av, away_reference=am)


def _match_signals(match: Dict[str, Any], home_sample: Optional[int], away_sample: Optional[int], league_ctx: Dict[str, Any], teams: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    hp = _num(match.get("pre_match_home_ppg")) if (home_sample or 0) > 0 else None
    ap = _num(match.get("pre_match_away_ppg")) if (away_sample or 0) > 0 else None
    hx = _num(match.get("team_a_xg_prematch")); ax = _num(match.get("team_b_xg_prematch"))
    hx = hx if hx is not None and hx > 0 else None; ax = ax if ax is not None and ax > 0 else None
    ppg_cmp, xg_cmp = _cmp(hp, ap), _cmp(hx, ax)
    for market in ("home_win", "away_win", "draw"):
        if ppg_cmp is None and xg_cmp is None:
            status = UNAVAILABLE
        elif market == "draw":
            known = [x for x in (ppg_cmp, xg_cmp) if x is not None]
            status = SUPPORT if known and (0 in known or (1 in known and -1 in known)) else (CONTRADICT if len(known) >= 2 and len(set(known)) == 1 and known[0] != 0 else NEUTRAL)
        else:
            direction = 1 if market == "home_win" else -1
            known = [x for x in (ppg_cmp, xg_cmp) if x is not None]
            status = SUPPORT if known and all(x == direction for x in known) else (CONTRADICT if known and all(x == -direction for x in known) else NEUTRAL)
        out.append(_signal("MATCH", "PREMATCH_STRENGTH", market, status, "Nur echte Pre-Match-PPG/xG-Werte; 0-Spiel-Competitionwerte werden nicht als Schwäche gewertet.", home_ppg=hp, away_ppg=ap, home_xg=hx, away_xg=ax))
    btts = _num(match.get("btts_potential")); league_btts = _num(league_ctx.get("seasonBTTSPercentage"))
    if league_btts is None:
        league_btts = _metric_median(teams, "seasonBTTSPercentage", "overall")
    for market, high in (("btts_yes", True), ("btts_no", False)):
        if btts is None or league_btts is None: st = UNAVAILABLE
        else:
            c = _cmp(btts, league_btts); st = NEUTRAL if c == 0 else (SUPPORT if (c > 0) == high else CONTRADICT)
        out.append(_signal("MATCH", "BTTS_POTENTIAL", market, st, "BTTS-Potential wird relativ zum gelieferten Competition-Kontext bewertet; es ist keine Modellwahrscheinlichkeit.", btts_potential=btts, competition_reference=league_btts))
    o25 = _num(match.get("o25_potential")); u25 = _num(match.get("u25_potential"))
    for market, wants_over in (("over_2_5", True), ("under_2_5", False)):
        if o25 is None or u25 is None: st = UNAVAILABLE
        else:
            c = _cmp(o25, u25); st = NEUTRAL if c == 0 else (SUPPORT if (c > 0) == wants_over else CONTRADICT)
        out.append(_signal("MATCH", "GOALS_POTENTIAL", market, st, "Over-/Under-Potential werden direkt gegeneinander geprüft; keine feste globale Prozentgrenze.", o25_potential=o25, u25_potential=u25))
    return out


def _league_signals(teams: List[Dict[str, Any]], home: Optional[Dict[str, Any]], away: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    hp = _metric(home, "seasonPPG", "home"); ap = _metric(away, "seasonPPG", "away")
    hm = _metric_median(teams, "seasonPPG", "home"); am = _metric_median(teams, "seasonPPG", "away")
    if None in (hp, ap, hm, am): result_status = {m: UNAVAILABLE for m in ("home_win", "away_win", "draw")}
    else:
        he = (_cmp(hp, hm) or 0) - (_cmp(ap, am) or 0)
        result_status = {"home_win": SUPPORT if he > 0 else (CONTRADICT if he < 0 else NEUTRAL), "away_win": SUPPORT if he < 0 else (CONTRADICT if he > 0 else NEUTRAL), "draw": SUPPORT if he == 0 else CONTRADICT}
    for market in ("home_win", "draw", "away_win"):
        out.append(_signal("LEAGUE", "VENUE_PPG", market, result_status[market], "Heim- und Auswärts-PPG werden nur relativ zu den Medianen der gelieferten Competition verglichen.", home_value=hp, home_median=hm, away_value=ap, away_median=am))
    for market, base, high in (("btts_yes", "seasonBTTSPercentage", True), ("btts_no", "seasonBTTSPercentage", False), ("over_2_5", "seasonOver25Percentage", True), ("under_2_5", "seasonUnder25Percentage", True)):
        hv = _metric(home, base, "home"); av = _metric(away, base, "away"); hm2 = _metric_median(teams, base, "home"); am2 = _metric_median(teams, base, "away")
        if market == "btts_no": high = False
        out.append(_relative_pair_signal("LEAGUE", "VENUE_PROFILE", market, hv, hm2, av, am2, high_supports=high, reason="Beide Venue-Profile werden relativ zur Competition bewertet; Nullwerte ohne Sample sind NICHT VERFÜGBAR."))
    for market, high in (("btts_yes", True), ("btts_no", False), ("over_2_5", True), ("under_2_5", False)):
        hv = _metric(home, "seasonBTTSPercentageHT", "home"); av = _metric(away, "seasonBTTSPercentageHT", "away"); hm2 = _metric_median(teams, "seasonBTTSPercentageHT", "home"); am2 = _metric_median(teams, "seasonBTTSPercentageHT", "away")
        out.append(_relative_pair_signal("LEAGUE", "FIRST_HALF_BTTS", market, hv, hm2, av, am2, high_supports=high, reason="First-Half-BTTS Home/Away wird liga-relativ geprüft."))
    for market, wants_open in (("btts_yes", True), ("btts_no", False), ("over_2_5", True), ("under_2_5", False)):
        vals = {}
        for base in ("seasonFTSPercentage", "seasonCSPercentage"):
            vals[(base,"h")] = _metric(home, base, "home"); vals[(base,"a")] = _metric(away, base, "away"); vals[(base,"hm")] = _metric_median(teams, base, "home"); vals[(base,"am")] = _metric_median(teams, base, "away")
        if any(v is None for v in vals.values()): st = UNAVAILABLE
        else:
            low_fts = vals[("seasonFTSPercentage","h")] < vals[("seasonFTSPercentage","hm")] and vals[("seasonFTSPercentage","a")] < vals[("seasonFTSPercentage","am")]
            low_cs = vals[("seasonCSPercentage","h")] < vals[("seasonCSPercentage","hm")] and vals[("seasonCSPercentage","a")] < vals[("seasonCSPercentage","am")]
            high_fts = vals[("seasonFTSPercentage","h")] > vals[("seasonFTSPercentage","hm")] and vals[("seasonFTSPercentage","a")] > vals[("seasonFTSPercentage","am")]
            high_cs = vals[("seasonCSPercentage","h")] > vals[("seasonCSPercentage","hm")] and vals[("seasonCSPercentage","a")] > vals[("seasonCSPercentage","am")]
            open_profile = low_fts and low_cs; closed_profile = high_fts and high_cs
            st = SUPPORT if (open_profile if wants_open else closed_profile) else (CONTRADICT if (closed_profile if wants_open else open_profile) else NEUTRAL)
        out.append(_signal("LEAGUE", "CS_FTS_PROFILE", market, st, "CS und FTS müssen gemeinsam dieselbe liga-relative Richtung zeigen; sonst neutral."))
    hxg = _metric(home, "xg_for_avg", "home"); axg = _metric(away, "xg_for_avg", "away"); hxga = _metric(home, "xg_against_avg", "home"); axga = _metric(away, "xg_against_avg", "away")
    hxgm = _metric_median(teams, "xg_for_avg", "home"); axgm = _metric_median(teams, "xg_for_avg", "away"); hxgam = _metric_median(teams, "xg_against_avg", "home"); axgam = _metric_median(teams, "xg_against_avg", "away")
    if None in (hxg, axg, hxga, axga, hxgm, axgm, hxgam, axgam): underlying_result = {m: UNAVAILABLE for m in ("home_win", "draw", "away_win")}
    else:
        home_edges = [_cmp(hxg, hxgm), _cmp(axga, axgam), -(_cmp(axg, axgm) or 0), -(_cmp(hxga, hxgam) or 0)]; net = sum(x or 0 for x in home_edges)
        underlying_result = {"home_win": SUPPORT if net > 0 else (CONTRADICT if net < 0 else NEUTRAL), "away_win": SUPPORT if net < 0 else (CONTRADICT if net > 0 else NEUTRAL), "draw": SUPPORT if net == 0 else NEUTRAL}
    for market in ("home_win", "draw", "away_win"):
        out.append(_signal("LEAGUE", "UNDERLYING_XG", market, underlying_result[market], "Venue-xG/xGA wird ausschließlich relativ zu den Competition-Medianen bewertet.", home_xg=hxg, away_xg=axg, home_xga=hxga, away_xga=axga))
    for market, high in (("btts_yes", True), ("btts_no", False)):
        out.append(_relative_pair_signal("LEAGUE", "ATTACK_XG", market, hxg, hxgm, axg, axgm, high_supports=high, reason="Beide Angriffs-xG-Werte werden relativ zu ihrem Venue-Median geprüft."))
    for market, wants_over in (("over_2_5", True), ("under_2_5", False)):
        if None in (hxg, axg, hxgm, axgm): st = UNAVAILABLE
        else:
            total = hxg + axg; ref = hxgm + axgm; c = _cmp(total, ref); st = NEUTRAL if c == 0 else (SUPPORT if (c > 0) == wants_over else CONTRADICT)
        out.append(_signal("LEAGUE", "TOTAL_XG_PROFILE", market, st, "Summe beider Venue-Angriffs-xG gegen die entsprechende Competition-Referenz.", total_xg=(hxg+axg) if hxg is not None and axg is not None else None, reference=(hxgm+axgm) if hxgm is not None and axgm is not None else None))
    return out


def _form_records(form_wrapper: Any, side: str) -> List[Dict[str, Any]]:
    payload = _payload(form_wrapper)
    if not isinstance(payload, dict): return []
    data = _api_data(payload.get(side))
    return [x for x in data if isinstance(x, dict)] if isinstance(data, list) else []


def _form_window(record: Dict[str, Any]) -> Dict[str, Any]:
    stats = dict(record.get("stats") or {}); n = _num(record.get("last_x_match_num"))
    if n is None: n = _num(stats.get("last_x"))
    return {"sample": int(n) if n is not None else None, "ppg": _num(stats.get("seasonPPG_overall")), "btts": _num(stats.get("seasonBTTSPercentage_overall")), "o25": _num(stats.get("seasonOver25Percentage_overall")), "u25": _num(stats.get("seasonUnder25Percentage_overall")), "gf": _num(stats.get("seasonScoredAVG_overall")), "ga": _num(stats.get("seasonConcededAVG_overall")), "xg": _num(stats.get("xg_for_avg_overall")), "xga": _num(stats.get("xg_against_avg_overall")), "sot": _num(stats.get("shotsOnTargetAVG_overall"))}


def _form_side(form_wrapper: Any, side: str, team_id: int) -> Dict[str, Any]:
    recs = [r for r in _form_records(form_wrapper, side) if int(_num(r.get("id")) or -1) == int(team_id)]; windows = [_form_window(r) for r in recs]; windows = [w for w in windows if w.get("sample")]; windows.sort(key=lambda x:x["sample"])
    return {"available": bool(windows), "windows": windows, "recent": next((w for w in windows if w["sample"]==5), windows[0] if windows else None), "reference": next((w for w in reversed(windows) if w["sample"] in {10,6}), windows[-1] if windows else None)}


def _form_signals(form_wrapper: Any, home_id: int, away_id: int) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    out=[]; home=_form_side(form_wrapper,"home",home_id); away=_form_side(form_wrapper,"away",away_id); cov={"home":home,"away":away}; hr,ar=home.get("recent") or {},away.get("recent") or {}; href,aref=home.get("reference") or {},away.get("reference") or {}
    for market in ("home_win","away_win","draw"):
        hp,ap=_num(hr.get("ppg")),_num(ar.get("ppg")); c=_cmp(hp,ap)
        if c is None: st=UNAVAILABLE
        elif market=="home_win": st=SUPPORT if c>0 else (CONTRADICT if c<0 else NEUTRAL)
        elif market=="away_win": st=SUPPORT if c<0 else (CONTRADICT if c>0 else NEUTRAL)
        else: st=SUPPORT if c==0 else NEUTRAL
        out.append(_signal("FORM","CURRENT_FORM_PPG",market,st,"Aktuelles Last-5-PPG beider Teams wird direkt verglichen; Competition-COLD-START schließt Formdaten nicht aus.",home_last5=hp,away_last5=ap))
    for market,metric,high in (("btts_yes","btts",True),("btts_no","btts",False),("over_2_5","o25",True),("under_2_5","u25",True)):
        hd=(_num(hr.get(metric))-_num(href.get(metric))) if _num(hr.get(metric)) is not None and _num(href.get(metric)) is not None else None; ad=(_num(ar.get(metric))-_num(aref.get(metric))) if _num(ar.get(metric)) is not None and _num(aref.get(metric)) is not None else None
        if hd is None or ad is None: st=UNAVAILABLE
        else:
            if market=="btts_no": hd,ad=-hd,-ad
            st=SUPPORT if hd>0 and ad>0 else (CONTRADICT if hd<0 and ad<0 else NEUTRAL)
        out.append(_signal("FORM","FORM_5_VS_LONGER",market,st,"Last 5 wird gegen das längste verfügbare Last-6/10-Fenster je Team geprüft.",home_delta=hd,away_delta=ad))
    return out,cov


def _table_data(table_wrapper: Any) -> Dict[str, Any]:
    data=_api_data(_payload(table_wrapper)); return data if isinstance(data,dict) else {}

def _table_row(rows: Any, team_id: int) -> Optional[Dict[str, Any]]:
    if not isinstance(rows,list): return None
    return next((r for r in rows if isinstance(r,dict) and int(_num(r.get("id")) or -1)==int(team_id)),None)

def _row_ppg(row: Optional[Dict[str, Any]]) -> Optional[float]:
    if not row:return None
    matches=_num(row.get("matchesPlayed"));points=_num(row.get("points"));return points/matches if matches and matches>0 and points is not None else None

def _table_signals(table_wrapper: Any, home_id: int, away_id: int) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    data=_table_data(table_wrapper);hrow=_table_row(data.get("all_matches_table_home"),home_id);arow=_table_row(data.get("all_matches_table_away"),away_id);mode="VENUE"
    if hrow is None or arow is None: hrow=_table_row(data.get("all_matches_table_overall"),home_id);arow=_table_row(data.get("all_matches_table_overall"),away_id);mode="OVERALL"
    hp,ap=_row_ppg(hrow),_row_ppg(arow);hr=int(_num((hrow or {}).get("position")) or 0) or None;ar=int(_num((arow or {}).get("position")) or 0) or None;out=[]
    if hp is None or ap is None: statuses={m:UNAVAILABLE for m in ("home_win","draw","away_win")}
    else:
        pc=_cmp(hp,ap);rc=None if hr is None or ar is None else (-1 if hr<ar else (1 if hr>ar else 0));votes=(1 if pc and pc>0 else (-1 if pc and pc<0 else 0))+(1 if rc is not None and rc<0 else (-1 if rc is not None and rc>0 else 0));statuses={"home_win":SUPPORT if votes>0 else (CONTRADICT if votes<0 else NEUTRAL),"away_win":SUPPORT if votes<0 else (CONTRADICT if votes>0 else NEUTRAL),"draw":SUPPORT if votes==0 else NEUTRAL}
    for market in ("home_win","draw","away_win"):out.append(_signal("TABLE","RELATIVE_TABLE_STRENGTH",market,statuses[market],f"{mode}-Tabelle: PPG und Position werden gemeinsam geprüft; fehlende Venue-Tabelle wird nicht als 0 interpretiert.",mode=mode,home_ppg=hp,away_ppg=ap,home_position=hr,away_position=ar))
    return out,{"mode":mode,"home_available":hrow is not None,"away_available":arow is not None}


def _player_rows(player_wrapper: Any) -> List[Dict[str, Any]]:
    payload=_payload(player_wrapper);return _page_rows(payload.get("pages")) if isinstance(payload,dict) else []
def _player_team(rows: List[Dict[str, Any]],team_id:int)->List[Dict[str,Any]]:
    return [r for r in rows if any(v is not None and int(v)==int(team_id) for v in (_num(r.get("club_team_id")),_num(r.get("club_team_2_id"))))]
def _player_summary(players: List[Dict[str,Any]])->Dict[str,Any]:
    if not players:return {"available":False,"players_found":0}
    mins=[_num(p.get("minutes_played_overall")) or 0.0 for p in players];inv=[_num(p.get("goals_involved_per_90_overall")) for p in players if (_num(p.get("minutes_played_overall")) or 0)>0];inv=[v for v in inv if v is not None]
    return {"available":True,"players_found":len(players),"minutes_total":round(sum(mins),1),"minutes_mean":round(sum(mins)/len(mins),2) if mins else None,"involvement_per90_mean":round(sum(inv)/len(inv),4) if inv else None}
def _player_signals(player_wrapper: Any,home_id:int,away_id:int)->Tuple[List[Dict[str,Any]],Dict[str,Any]]:
    rows=_player_rows(player_wrapper);hs=_player_summary(_player_team(rows,home_id));aw=_player_summary(_player_team(rows,away_id));out=[]
    if not(hs["available"] and aw["available"]):
        for market in ("home_win","draw","away_win","btts_yes","btts_no","over_2_5","under_2_5"):out.append(_signal("PLAYER","PLAYER_COVERAGE",market,UNAVAILABLE,"Mindestens ein Team fehlt in PlayerDaten; fehlende Spieler werden niemals als 0-Stärke gewertet.",home_players=hs["players_found"],away_players=aw["players_found"]))
        return out,{"home":hs,"away":aw}
    dc=_cmp(_num(hs["players_found"]),_num(aw["players_found"]));mc=_cmp(_num(hs["minutes_total"]),_num(aw["minutes_total"]))
    for market in ("home_win","away_win","draw"):
        votes=[v for v in (dc,mc) if v is not None]
        if market=="home_win":st=SUPPORT if votes and all(v>0 for v in votes) else (CONTRADICT if votes and all(v<0 for v in votes) else NEUTRAL)
        elif market=="away_win":st=SUPPORT if votes and all(v<0 for v in votes) else (CONTRADICT if votes and all(v>0 for v in votes) else NEUTRAL)
        else:st=SUPPORT if votes and all(v==0 for v in votes) else NEUTRAL
        out.append(_signal("PLAYER","PLAYER_DEPTH",market,st,"Kaderabdeckung nutzt Spielerzahl und Minuten; keine Aufstellungsannahme.",home=hs,away=aw))
    hi,ai=_num(hs.get("involvement_per90_mean")),_num(aw.get("involvement_per90_mean"));by_club={}
    for row in rows:
        cid=_num(row.get("club_team_id"));
        if cid is not None and cid>0:by_club.setdefault(int(cid),[]).append(row)
    club_means=[]
    for plist in by_club.values():
        v=_num(_player_summary(plist).get("involvement_per90_mean"));
        if v is not None:club_means.append(v)
    ref=_median(club_means)
    for market,high in (("btts_yes",True),("btts_no",False),("over_2_5",True),("under_2_5",False)):out.append(_relative_pair_signal("PLAYER","PLAYER_ATTACK_CONTRIBUTION",market,hi,ref,ai,ref,high_supports=high,reason="Mittlere Goal-Involvement/90 beider Kader wird relativ zum Competition-Player-Kontext geprüft."))
    return out,{"home":hs,"away":aw,"competition_involvement_median":ref}


def _h2h_signals(match: Dict[str,Any])->List[Dict[str,Any]]:
    h2h=match.get("h2h") if isinstance(match.get("h2h"),dict) else {};previous=h2h.get("previous_matches_results") if isinstance(h2h.get("previous_matches_results"),dict) else {};stats=h2h.get("betting_stats") if isinstance(h2h.get("betting_stats"),dict) else {};total=_num(previous.get("totalMatches")) or _num(stats.get("totalMatches"));out=[];hw=_num(previous.get("team_a_wins"));aw=_num(previous.get("team_b_wins"));dr=_num(previous.get("draw"))
    for market in ("home_win","draw","away_win"):
        vals={"home_win":hw,"draw":dr,"away_win":aw};sel=vals[market];known=[v for v in vals.values() if v is not None]
        st=UNAVAILABLE if not total or sel is None or len(known)<2 else (SUPPORT if sel==max(known) and known.count(max(known))==1 else (CONTRADICT if sel<max(known) else NEUTRAL));out.append(_signal("H2H","H2H_RESULT",market,st,"H2H ist ausschließlich sekundäre Evidenz und kann allein kein SPIELEN erzeugen.",total_matches=total,home_wins=hw,draws=dr,away_wins=aw))
    btts=_num(stats.get("btts"));o25=_num(stats.get("over25"))
    for market,count in (("btts_yes",btts),("btts_no",None),("over_2_5",o25),("under_2_5",None)):
        if not total:st=UNAVAILABLE
        else:
            if market=="btts_no" and btts is not None:count=total-btts
            if market=="under_2_5" and o25 is not None:count=total-o25
            st=UNAVAILABLE if count is None else (SUPPORT if count>total/2 else (CONTRADICT if count<total/2 else NEUTRAL))
        out.append(_signal("H2H","H2H_GOAL_PROFILE",market,st,"Nur Mehrheitsrichtung der vorhandenen H2H-Spiele; sekundär, ohne globale Wettgrenze.",total_matches=total,selected_count=count))
    return out


def _temporal_audit(files:Dict[str,Dict[str,Any]],kickoff:int)->Dict[str,Any]:
    expected={"match":("/match",False),"league":("/league-season",True),"form":("/lastx",False),"table":("/league-tables",True),"player":("/league-players",True)};out={}
    for kind,(endpoint,needs_max) in expected.items():
        meta=_meta(files[kind]["data"]);capture=_num(meta.get("captured_at_unix"));max_time=_num(meta.get("max_time"));ep=str(meta.get("endpoint") or "");endpoint_ok=ep==endpoint;capture_ok=capture is not None and capture<kickoff;max_ok=(not needs_max) or (max_time is not None and int(max_time)==kickoff-1);strict=endpoint_ok and capture_ok and max_ok;out[kind]={"strict":strict,"endpoint_ok":endpoint_ok,"capture_before_kickoff":capture_ok,"max_time_ok":max_ok,"endpoint":ep or None,"captured_at_unix":capture,"max_time":max_time}
    return out

def _pagination_audit(files:Dict[str,Dict[str,Any]])->Dict[str,Any]:
    league=files["league"]["data"];lm=_meta(league);lp=_payload(league);team_pages=_pages((lp or {}).get("team_pages") if isinstance(lp,dict) else None);lpo=bool(team_pages)
    if team_pages:
        p=_pager(team_pages[-1]);cur,mx=_num(p.get("current_page")),_num(p.get("max_page"));lpo=cur is not None and mx is not None and int(cur)==int(mx)
    lc=_truthy_bool(lm.get("team_pagination_complete")) and lpo
    player=files["player"]["data"];pm=_meta(player);pp=_payload(player);pages=_pages((pp or {}).get("pages") if isinstance(pp,dict) else None);seen=[];max_pages=[]
    for page in pages:
        p=_pager(page);cur,mx=_num(p.get("current_page")),_num(p.get("max_page"));
        if cur is not None:seen.append(int(cur))
        if mx is not None:max_pages.append(int(mx))
    em=max(max_pages) if max_pages else None;set_ok=em is not None and set(seen)>=set(range(1,em+1));pc=_truthy_bool(pm.get("pagination_complete")) and set_ok
    return {"league_teams":{"complete":lc,"pages_seen":len(team_pages)},"players":{"complete":pc,"pages_seen":seen,"max_page":em}}

def _aggregate(signals:List[Dict[str,Any]],market:str)->Dict[str,Any]:
    selected=[s for s in signals if s["market"]==market];support=[s for s in selected if s["status"]==SUPPORT];contradict=[s for s in selected if s["status"]==CONTRADICT];neutral=[s for s in selected if s["status"]==NEUTRAL];unavailable=[s for s in selected if s["status"]==UNAVAILABLE];central=sorted({s["source"] for s in support if s["source"] in CENTRAL_SOURCES});available=len(selected)-len(unavailable)
    action="SPIELEN" if len(support)>=3 and not contradict and len(central)>=3 else ("BEOBACHTEN" if len(support)>=2 and len(support)>len(contradict) else "AUSLASSEN")
    return {"key":market,"label":LABELS[market],"action":action,"support_count":len(support),"contradiction_count":len(contradict),"neutral_count":len(neutral),"unavailable_count":len(unavailable),"available_signal_count":available,"central_support_sources":central,"net_evidence":len(support)-len(contradict),"signals":selected}


def analyze_bundle(parsed_files:List[Dict[str,Any]])->Dict[str,Any]:
    pair=_pair(parsed_files)
    if not pair.get("ok"):return pair
    files=pair["files"];match=pair["match"];identity=pair["identity"];kickoff=identity["kickoff_unix"];temporal=_temporal_audit(files,kickoff);pagination=_pagination_audit(files);strict_all=all(v["strict"] for v in temporal.values());pagination_all=pagination["league_teams"]["complete"] and pagination["players"]["complete"]
    if not strict_all or not pagination_all:return {"ok":False,"decision":"ANALYSE NICHT MÖGLICH","phase":"SPEC11_INTEGRITY_FAILED","error":"SPEC v1.1 Integritätsprüfung nicht bestanden. Keine Fallback-Analyse wird ausgeführt.","spec_version":SPEC_VERSION,"engine":ENGINE_NAME,"temporal_audit":temporal,"pagination":pagination,"fallback_used":False}
    teams=_league_team_rows(files["league"]["data"]);home_team=_team_by_id(teams,identity["home_id"]);away_team=_team_by_id(teams,identity["away_id"])
    if home_team is None or away_team is None:return {"ok":False,"decision":"ANALYSE NICHT MÖGLICH","phase":"SPEC11_TEAM_PAIRING_FAILED","error":"LeagueDaten enthält nicht beide Zielteams. Keine Fallback-Analyse.","fallback_used":False}
    hs=_sample(home_team,"overall");aws=_sample(away_team,"overall");sample_state={"home":{"matches":hs,"class":_sample_class(hs)},"away":{"matches":aws,"class":_sample_class(aws)},"policy":"0 Spiele=COLD START; 1-3=LOW SAMPLE; niemals automatischer Ausschluss."};league_ctx=_league_context(files["league"]["data"]);signals=[];signals.extend(_match_signals(match,hs,aws,league_ctx,teams));signals.extend(_league_signals(teams,home_team,away_team));fs,fc=_form_signals(files["form"]["data"],identity["home_id"],identity["away_id"]);signals.extend(fs);ts,tc=_table_signals(files["table"]["data"],identity["home_id"],identity["away_id"]);signals.extend(ts);ps,pc=_player_signals(files["player"]["data"],identity["home_id"],identity["away_id"]);signals.extend(ps);signals.extend(_h2h_signals(match));markets=[_aggregate(signals,key) for key,_ in MARKETS];order={"SPIELEN":2,"BEOBACHTEN":1,"AUSLASSEN":0};markets.sort(key=lambda m:(order[m["action"]],m["net_evidence"],m["support_count"],-m["contradiction_count"],m["available_signal_count"]),reverse=True)
    for i,m in enumerate(markets,1):m["rank"]=i
    top=markets[0];final="AUSLASSEN / KEIN BET" if top["action"]=="AUSLASSEN" else top["action"];file_names={k:i["name"] for k,i in files.items()};audit_match={"match_id":identity["match_id"],"home_id":identity["home_id"],"away_id":identity["away_id"],"competition_id":identity["competition_id"],"kickoff_unix":kickoff,"home_name":match.get("home_name"),"away_name":match.get("away_name"),"season":match.get("season")}
    return {"ok":True,"engine":ENGINE_NAME,"engine_version":ENGINE_VERSION,"spec_version":SPEC_VERSION,"decision":final,"recommended_market":{"key":top["key"],"label":top["label"],"action":top["action"],"support_count":top["support_count"],"contradiction_count":top["contradiction_count"],"available_signal_count":top["available_signal_count"]},"markets":markets,"sample_state":sample_state,"data_coverage":{"form":fc,"table":tc,"player":pc,"league_team_count":len(teams)},"integrity":{"strict_prematch":strict_all,"temporal":temporal,"pagination":pagination},"pairing":{**identity,"files":file_names},"audit":{"valid":True,"errors":[],"match":audit_match},"input_sources":file_names,"method":{"architecture":"SPEC_V1_1_NATIVE_QUALITATIVE_DECISION","probability_core":"NONE","v043_used":False,"v042_used":False,"fallback":"NONE","odds_used":False,"missing_values":"NICHT VERFÜGBAR; niemals als 0-Stärke oder Ersatzwert","cold_start_exclusion":False,"decision_policy":"3+ bestätigende Signale, 0 Widersprüche und 3+ zentrale Quellen => SPIELEN; 2+ Bestätigungen mit positiver Evidenzbilanz => BEOBACHTEN; sonst AUSLASSEN.","calibration_status":"INITIAL_DETERMINISTIC_POLICY_NOT_YET_RESULT_CALIBRATED"},"notes":["Keine Wahrscheinlichkeiten werden aus V0.4.3/V0.4.2 übernommen.","COLD START und LOW SAMPLE werden analysiert; fehlende Competition-Signale werden lediglich NICHT VERFÜGBAR.","H2H ist sekundär und zählt nicht als zentrale Quelle für SPIELEN."]}
