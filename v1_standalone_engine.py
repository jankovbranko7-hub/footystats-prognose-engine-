"""FootyStats V1 FULL-DATA — independent engine line.

V1 owns its probability, score-distribution, evidence and decision logic. It does
not import or execute V0.4.x application/engine modules. FULL-DATA enrichments are
used for analysis and contradiction diagnostics; they receive no invented learned
coefficients before result-joined OOS validation.
"""
from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

from v1_score_core import dixon_coles, RHO

VERSION = "1.0.0-FULL-DATA"
PRIOR_MATCHES = 2.0


def _num(v: Any) -> Optional[float]:
    if v is None or isinstance(v, bool): return None
    try:
        x=float(str(v).strip().replace(",", ".").replace("%", ""))
        return x if math.isfinite(x) else None
    except Exception: return None


def _walk(x: Any) -> Iterable[Dict[str, Any]]:
    if isinstance(x, dict):
        yield x
        for v in x.values(): yield from _walk(v)
    elif isinstance(x, list):
        for v in x: yield from _walk(v)


def _firstnum(obj: Any, keys: Iterable[str]) -> Optional[float]:
    wanted={str(k).lower() for k in keys}
    for d in _walk(obj):
        for k,v in d.items():
            if str(k).lower() in wanted:
                n=_num(v)
                if n is not None:return n
    return None


def _match_obj(data: Any) -> Dict[str, Any]:
    for d in _walk(data):
        keys={str(k).lower().replace("_","") for k in d}
        if "homeid" in keys and "awayid" in keys:return d
    return data if isinstance(data,dict) else {}


def match_fields(data: Any) -> Dict[str, Any]:
    m=_match_obj(data)
    def n(*k): return _firstnum(m,k)
    def raw(*keys):
        low={x.lower() for x in keys}
        for k,v in m.items():
            if str(k).lower() in low:return v
        return None
    out={
        "match_id":n("id","match_id"), "home_id":n("homeID","home_id"), "away_id":n("awayID","away_id"),
        "competition_id":n("competition_id","competitionID"), "home_name":raw("home_name","homeName"), "away_name":raw("away_name","awayName"),
        "home_prematch_xg":n("team_a_xg_prematch"), "away_prematch_xg":n("team_b_xg_prematch"), "total_prematch_xg":n("total_xg_prematch"),
        "home_ppg":n("pre_match_home_ppg"), "away_ppg":n("pre_match_away_ppg"), "kickoff_unix":n("date_unix","kickoff_unix","kickoff_timestamp")
    }
    for k in ("match_id","home_id","away_id","competition_id"):
        if out[k] is not None: out[k]=int(out[k])
    return out


def _team_obj(data: Any, team_id: Any) -> Optional[Dict[str, Any]]:
    tid=_num(team_id)
    if tid is None:return None
    for d in _walk(data):
        did=_num(d.get("id") if "id" in d else d.get("team_id"))
        if did is not None and int(did)==int(tid) and isinstance(d.get("stats"),dict):return d
    return None


def _metric(team: Optional[Dict[str, Any]], base: str, venue: str) -> Optional[float]:
    if not team:return None
    aliases={
        "matches":[f"seasonMatchesPlayed_{venue}"], "ppg":[f"seasonPPG_{venue}"], "xg":[f"xg_for_avg_{venue}"], "xga":[f"xg_against_avg_{venue}"],
        "gf":[f"seasonScoredAVG_{venue}",f"seasonGoalsAVG_{venue}"], "ga":[f"seasonConcededAVG_{venue}"], "shots":[f"shotsAVG_{venue}"],
        "sot":[f"shotsOnTargetAVG_{venue}"], "btts":[f"seasonBTTSPercentage_{venue}"], "fh_btts":[f"seasonBTTSPercentageHT_{venue}"],
        "fts":[f"seasonFTSPercentage_{venue}"], "cs":[f"seasonCSPercentage_{venue}"], "o25":[f"seasonOver25Percentage_{venue}"]
    }
    return _firstnum(team, aliases.get(base,[base]))


def _league_teams(data: Any) -> List[Dict[str, Any]]:
    found={}
    for d in _walk(data):
        if not isinstance(d.get("stats"),dict):continue
        i=_num(d.get("id"))
        if i is not None:found.setdefault(int(i),d)
    return list(found.values())


def _weighted_mean(rows: List[Tuple[float,float]]) -> Optional[float]:
    rows=[(v,w) for v,w in rows if v is not None and w is not None and w>0]
    den=sum(w for _,w in rows)
    return sum(v*w for v,w in rows)/den if den else None


def _league_mean(teams: List[Dict[str,Any]], metric: str, venue: str) -> Optional[float]:
    rows=[]
    for t in teams:
        v=_metric(t,metric,venue); n=_metric(t,"matches",venue)
        if v is not None and n is not None and n>0:rows.append((v,n))
    return _weighted_mean(rows)


def _shrink(value: Optional[float], matches: Optional[float], mean: Optional[float]) -> Optional[float]:
    if value is None:return mean
    if mean is None:return value
    n=max(0.0, float(matches or 0))
    return (n*value + PRIOR_MATCHES*mean)/(n+PRIOR_MATCHES)


def _gmean(values: Iterable[Optional[float]]) -> Optional[float]:
    vals=[float(v) for v in values if v is not None and v>0]
    if not vals:return None
    return math.exp(sum(math.log(v) for v in vals)/len(vals))


def _form_records(data: Any, team_id: Any) -> Dict[str,Dict[str,Any]]:
    tid=_num(team_id); out={}
    if tid is None:return out
    for d in _walk(data):
        did=_num(d.get("id")); w=_num(d.get("last_x_match_num"))
        if did is None or int(did)!=int(tid) or w is None or int(w) not in (5,6,10):continue
        out[str(int(w))]=d
    return out


def _form_metric(records: Dict[str,Dict[str,Any]], window: int, base: str, venue: str) -> Optional[float]:
    r=records.get(str(window))
    if not r:return None
    keys={
        "xg":[f"xg_for_avg_{venue}","xg_for_avg_overall","xg"], "xga":[f"xg_against_avg_{venue}","xg_against_avg_overall","xga"],
        "btts":[f"seasonBTTSPercentage_{venue}","seasonBTTSPercentage_overall"], "fh_btts":[f"seasonBTTSPercentageHT_{venue}","seasonBTTSPercentageHT_overall"],
        "fts":[f"seasonFTSPercentage_{venue}","seasonFTSPercentage_overall"], "cs":[f"seasonCSPercentage_{venue}","seasonCSPercentage_overall"],
        "gf":[f"seasonScoredAVG_{venue}","seasonScoredAVG_overall","goals_for_per_match"], "ga":[f"seasonConcededAVG_{venue}","seasonConcededAVG_overall","goals_against_per_match"]
    }
    return _firstnum(r,keys[base])


def _sample_security(ht:Dict[str,Any],at:Dict[str,Any]) -> str:
    hn=_metric(ht,"matches","home"); an=_metric(at,"matches","away"); ho=_metric(ht,"matches","overall"); ao=_metric(at,"matches","overall")
    if hn is None or an is None:return "NIEDRIG"
    if min(hn,an)>=12 and min(ho or 0,ao or 0)>=20:return "HOCH"
    if min(hn,an)>=4 and min(ho or 0,ao or 0)>=8:return "MITTEL"
    return "NIEDRIG"


def _chance_quality(team:Optional[Dict[str,Any]],venue:str)->Dict[str,Any]:
    sh=_metric(team,"shots",venue); sot=_metric(team,"sot",venue); xg=_metric(team,"xg",venue); gf=_metric(team,"gf",venue)
    attacks=_firstnum(team or {},[f"attacks_avg_{venue}"]); danger=_firstnum(team or {},[f"dangerous_attacks_avg_{venue}"])
    return {"shots":sh,"sot":sot,"xg":xg,"goals":gf,"sot_per_shot":sot/sh if sot is not None and sh else None,"xg_per_shot":xg/sh if xg is not None and sh else None,"goals_per_sot":gf/sot if gf is not None and sot else None,"dangerous_attack_share":danger/attacks if danger is not None and attacks else None}


def expected_goals(match:Any,league:Any,form:Any)->Dict[str,Any]:
    m=match_fields(match); ht=_team_obj(league,m.get("home_id")); at=_team_obj(league,m.get("away_id")); teams=_league_teams(league)
    if not ht or not at or len(teams)<2:raise ValueError("LeagueDaten enthält Zielteams/Ligakontext nicht vollständig.")
    home_mean=_league_mean(teams,"xg","home"); away_mean=_league_mean(teams,"xg","away")
    hxg=_shrink(_metric(ht,"xg","home"),_metric(ht,"matches","home"),home_mean)
    axg=_shrink(_metric(at,"xg","away"),_metric(at,"matches","away"),away_mean)
    hxga=_shrink(_metric(ht,"xga","home"),_metric(ht,"matches","home"),_league_mean(teams,"xga","home"))
    axga=_shrink(_metric(at,"xga","away"),_metric(at,"matches","away"),_league_mean(teams,"xga","away"))
    hf=_form_records(form,m.get("home_id")) if form else {}; af=_form_records(form,m.get("away_id")) if form else {}
    hform=_form_metric(hf,10,"xg","home"); aform=_form_metric(af,10,"xg","away"); hform_def=_form_metric(hf,10,"xga","home"); aform_def=_form_metric(af,10,"xga","away")
    # V1-native transparent component blend. No copied V0.4.3 learned coefficients.
    hl=_gmean([hxg,axga,m.get("home_prematch_xg"),hform,aform_def]); al=_gmean([axg,hxga,m.get("away_prematch_xg"),aform,hform_def])
    if hl is None or al is None:raise ValueError("Nicht genügend unabhängige Pre-Match-Komponenten für V1-Lambda.")
    return {"home":max(.18,min(3.95,hl)),"away":max(.18,min(3.95,al)),"components":{"home_attack":hxg,"away_defence":axga,"home_prematch_xg":m.get("home_prematch_xg"),"home_form10_xg":hform,"away_form10_xga":aform_def,"away_attack":axg,"home_defence":hxga,"away_prematch_xg":m.get("away_prematch_xg"),"away_form10_xg":aform,"home_form10_xga":hform_def},"league_means":{"home_xg":home_mean,"away_xg":away_mean},"method":"V1 independent geometric pre-match component model with league shrinkage"}


def _family_strength(p:float,n:int)->float:
    neutral=1/n; return max(0.0,min(1.0,(p-neutral)/(1-neutral)))


def select_market(p:Dict[str,float])->Dict[str,Any]:
    h,d,a=p["home_win"],p["draw"],p["away_win"]
    one_key,one_p=max((("home_win",h),("away_win",a)),key=lambda z:z[1]); one_s=_family_strength(one_p,3) if one_p>=d else 0.0
    b_key,b_p=max((("btts_yes",p["btts_yes"]),("btts_no",p["btts_no"])),key=lambda z:z[1]); o_key,o_p=max((("over_2_5",p["over_2_5"]),("under_2_5",p["under_2_5"])),key=lambda z:z[1])
    fam=[{"family":"1X2","key":one_key,"probability":one_p,"strength":one_s},{"family":"BTTS","key":b_key,"probability":b_p,"strength":_family_strength(b_p,2)},{"family":"OU_2_5","key":o_key,"probability":o_p,"strength":_family_strength(o_p,2)}]
    return max(fam,key=lambda z:(z["strength"],z["probability"]))


def _signal(name:str,status:str,value:Any=None,detail:str="")->Dict[str,Any]:return {"name":name,"status":status,"value":value,"detail":detail}


def core_evidence(key:str,p:Dict[str,float],m:Dict[str,Any],form:Any)->Dict[str,Any]:
    family="BTTS" if key.startswith("btts") else ("OU_2_5" if key.startswith("over") or key.startswith("under") else "1X2")
    underlying="BESTÄTIGEND" if p[key]>=.65 else ("GEGENARGUMENT" if p[key]<.55 else "NEUTRAL")
    ev={"UNDERLYING":_signal("UNDERLYING",underlying,p[key])}
    if family=="BTTS":
        mn=min(x for x in [m.get("home_prematch_xg"),m.get("away_prematch_xg")] if x is not None) if any(x is not None for x in [m.get("home_prematch_xg"),m.get("away_prematch_xg")]) else None
        if key=="btts_yes": st="BESTÄTIGEND" if mn is not None and mn>=1.0 else ("GEGENARGUMENT" if mn is not None and mn<.7 else "NEUTRAL")
        else: st="BESTÄTIGEND" if mn is not None and mn<.8 else ("GEGENARGUMENT" if mn is not None and mn>=1.15 else "NEUTRAL")
        ev["MATCH"]=_signal("MATCH",st,mn,"minimum team pre-match xG")
        hf=_form_records(form,m.get("home_id")) if form else {}; af=_form_records(form,m.get("away_id")) if form else {}
        rates=[_form_metric(hf,10,"btts","home"),_form_metric(af,10,"btts","away")]; rates=[r for r in rates if r is not None]
        avg=sum(rates)/len(rates) if rates else None
        if key=="btts_yes": st="BESTÄTIGEND" if avg is not None and avg>=55 else ("GEGENARGUMENT" if avg is not None and avg<=40 else "NEUTRAL")
        else: st="BESTÄTIGEND" if avg is not None and avg<=45 else ("GEGENARGUMENT" if avg is not None and avg>=60 else "NEUTRAL")
        ev["FORM"]=_signal("FORM",st,avg,"Last10 venue BTTS mean")
        ev["TABLE"]=_signal("TABLE","NICHT ANWENDBAR"); ev["PLAYER"]=_signal("PLAYER","NICHT ANWENDBAR")
    elif family=="OU_2_5":
        tx=m.get("total_prematch_xg"); yes=key=="over_2_5"; st="BESTÄTIGEND" if tx is not None and ((yes and tx>=2.8) or ((not yes) and tx<=2.2)) else ("GEGENARGUMENT" if tx is not None and ((yes and tx<=2.2) or ((not yes) and tx>=2.8)) else "NEUTRAL")
        ev["MATCH"]=_signal("MATCH",st,tx); ev["FORM"]=_signal("FORM","NEUTRAL"); ev["TABLE"]=_signal("TABLE","NICHT ANWENDBAR"); ev["PLAYER"]=_signal("PLAYER","NEUTRAL")
    else:
        diff=(m.get("home_ppg")-m.get("away_ppg")) if m.get("home_ppg") is not None and m.get("away_ppg") is not None else None; home=key=="home_win"; st="BESTÄTIGEND" if diff is not None and ((home and diff>=.35) or ((not home) and diff<=-.35)) else ("GEGENARGUMENT" if diff is not None and ((home and diff<=-.2) or ((not home) and diff>=.2)) else "NEUTRAL")
        ev["MATCH"]=_signal("MATCH",st,diff); ev["FORM"]=_signal("FORM","NEUTRAL"); ev["TABLE"]=_signal("TABLE","NEUTRAL"); ev["PLAYER"]=_signal("PLAYER","NICHT ANWENDBAR")
    return ev


def _players(data:Any)->List[Dict[str,Any]]:
    out={}
    for d in _walk(data):
        i=_num(d.get("id")); club=_num(d.get("club_team_id"))
        if i is not None and club is not None:out.setdefault(int(i),d)
    return list(out.values())


def _belongs(p:Dict[str,Any],tid:Any)->bool:
    t=_num(tid)
    return t is not None and any(_num(p.get(k)) is not None and int(_num(p.get(k)))==int(t) for k in ("club_team_id","club_team_2_id"))


def _share(vals:List[float],n:int)->Optional[float]:
    vals=[x for x in vals if x>0]; s=sum(vals); return sum(sorted(vals,reverse=True)[:n])/s if s else None


def _player_summary(data:Any,tid:Any)->Dict[str,Any]:
    rows=[p for p in _players(data) if _belongs(p,tid)]; goals=[_num(p.get("goals_overall")) or 0 for p in rows]; assists=[_num(p.get("assists_overall")) or 0 for p in rows]; cont=[a+b for a,b in zip(goals,assists)]; mins=[_num(p.get("minutes_played_overall")) or 0 for p in rows]
    return {"players_found":len(rows),"players_with_minutes":sum(x>0 for x in mins),"top1_goal_share":_share(goals,1),"top3_goal_share":_share(goals,3),"top3_contribution_share":_share(cont,3),"minutes_total":sum(mins)}


def _detail_rows(data:Any,tid:Any,comp:Any)->List[Dict[str,Any]]:
    c=_num(comp); out={}
    if c is None:return []
    for d in _walk(data):
        i=_num(d.get("id")); dc=_num(d.get("competition_id"))
        if i is None or dc is None or int(dc)!=int(c) or not _belongs(d,tid) or not isinstance(d.get("detailed"),dict):continue
        out.setdefault(int(i),d)
    return list(out.values())


def _weighted_detail(rows:List[Dict[str,Any]],key:str)->Optional[float]:
    vals=[]
    for p in rows:
        x=_num((p.get("detailed") or {}).get(key)); w=_num(p.get("minutes_played_overall"))
        if x is not None and w is not None and w>0:vals.append((x,w))
    return _weighted_mean(vals)


def _detail_summary(rows:List[Dict[str,Any]])->Dict[str,Any]:
    gks=[p for p in rows if str(p.get("position") or "").lower()=="goalkeeper"]; g=max(gks,key=lambda x:_num(x.get("minutes_played_overall")) or 0) if gks else {}; gd=g.get("detailed") or {}
    return {"players_with_detail":len(rows),"npxg_per90":_weighted_detail(rows,"npxg_per_90_overall"),"xa_per90":_weighted_detail(rows,"xa_per_90_overall"),"xg_per90":_weighted_detail(rows,"xg_per_90_overall"),"key_passes_per90":_weighted_detail(rows,"key_passes_per_90_overall"),"shots_per90":_weighted_detail(rows,"shots_per_90_overall"),"sot_per90":_weighted_detail(rows,"shots_on_target_per_90_overall"),"goalkeeper":{"save_pct":_num(gd.get("save_percentage_overall")),"saves_per90":_num(gd.get("saves_per_90_overall")),"shots_faced_per90":_num(gd.get("shots_faced_per_90_overall"))}}


def _table_rows(data:Any)->List[Dict[str,Any]]:
    root=data.get("data") if isinstance(data,dict) and isinstance(data.get("data"),dict) else data
    if isinstance(root,dict):
        for k in ("all_matches_table_overall","league_table"):
            if isinstance(root.get(k),list):return root[k]
    return []


def _table_summary(rows:List[Dict[str,Any]],tid:Any)->Dict[str,Any]:
    t=_num(tid); r=next((x for x in rows if _num(x.get("id")) is not None and t is not None and int(_num(x.get("id")))==int(t)),None)
    if not r:return {}
    pos=_num(r.get("position")); n=_num(r.get("matchesPlayed")); gf=_num(r.get("seasonGoals")); ga=_num(r.get("seasonConceded")); size=len(rows); norm=(pos-1)/(size-1) if pos is not None and size>1 else None
    return {"position":pos,"league_size":size,"position_strength":1-norm if norm is not None else None,"normalized_position_0_best":norm,"matches_played":n,"reliability":n/(n+6) if n else None,"ppg":_num(r.get("ppg_overall")),"gd_per_match":(gf-ga)/n if gf is not None and ga is not None and n else None}


def _trend_summary(side:Any)->Dict[str,Any]:
    texts=[x[1] for x in (side or []) if isinstance(x,(list,tuple)) and len(x)>1 and isinstance(x[1],str)]; blob=" ".join(texts)
    def g(p):
        m=re.search(p,blob,re.I); return _num(m.group(1)) if m else None
    return {"count":len(texts),"last5_points":g(r"picked up\s+([0-9.]+)\s+points from the last 5"),"last5_ppg":g(r"That's\s+([0-9.]+)\s+points per game"),"last5_btts":g(r"BTTS has landed[^.]*?([0-5])\s+of those games"),"last5_goals":g(r"has scored\s+([0-9.]+)\s+times in the last 5"),"scoring_streak":g(r"netted in the last\s+([0-9]+)\s+games")}


def full_data_layer(match:Any,league:Any,form:Any,table:Any,player:Any,player_detail:Any)->Dict[str,Any]:
    m=match_fields(match); ht=_team_obj(league,m.get("home_id")); at=_team_obj(league,m.get("away_id")); hf=_form_records(form,m.get("home_id")) if form else {}; af=_form_records(form,m.get("away_id")) if form else {}; tr=_match_obj(match).get("trends") or {}; rows=_table_rows(table) if table else []
    def form_side(rec,venue):
        vals={w:{k:_form_metric(rec,int(w),k,venue) for k in ("xg","xga","btts","fh_btts","fts","cs","gf","ga")} for w in ("5","6","10")}
        def delta(k):
            a=vals["5"].get(k); b=vals["10"].get(k); return a-b if a is not None and b is not None else None
        def stable(k):
            v=[vals[w].get(k) for w in ("5","6","10")]; v=[x for x in v if x is not None]; return {"spread":max(v)-min(v) if len(v)>1 else None,"mean":sum(v)/len(v) if v else None,"windows":len(v)}
        return {"windows":vals,"momentum_5_minus_10":{k:delta(k) for k in vals["10"]},"stability":{k:stable(k) for k in vals["10"]}}
    h2h=_match_obj(match).get("h2h") or {}; bs=h2h.get("betting_stats") or {}; rr=h2h.get("previous_matches_results") or {}
    return {"source_presence":{"match":match is not None,"league":league is not None,"form":form is not None,"table":table is not None,"player":player is not None,"player_detail":player_detail is not None},"form":{"home":form_side(hf,"home"),"away":form_side(af,"away")},"league":{"home":{"goal_regime":{"btts":_metric(ht,"btts","home"),"fh_btts":_metric(ht,"fh_btts","home"),"fts":_metric(ht,"fts","home"),"cs":_metric(ht,"cs","home"),"o25":_metric(ht,"o25","home")},"chance_quality":_chance_quality(ht,"home")},"away":{"goal_regime":{"btts":_metric(at,"btts","away"),"fh_btts":_metric(at,"fh_btts","away"),"fts":_metric(at,"fts","away"),"cs":_metric(at,"cs","away"),"o25":_metric(at,"o25","away")},"chance_quality":_chance_quality(at,"away")}},"player":{"home":_player_summary(player,m.get("home_id")) if player else {},"away":_player_summary(player,m.get("away_id")) if player else {}},"table":{"home":_table_summary(rows,m.get("home_id")),"away":_table_summary(rows,m.get("away_id"))},"match":{"h2h":{"sample":_num(rr.get("totalMatches")),"avg_goals":_num(bs.get("avg_goals")),"btts_pct":_num(bs.get("bttsPercentage")),"o25_pct":_num(bs.get("over25Percentage"))},"trends":{"home":_trend_summary(tr.get("home") if isinstance(tr,dict) else []),"away":_trend_summary(tr.get("away") if isinstance(tr,dict) else [])},"timing":{"recorded":_num(_match_obj(match).get("goal_timings_recorded")),"home":_match_obj(match).get("homeGoals_timings"),"away":_match_obj(match).get("awayGoals_timings")}},"player_detail":{"home":_detail_summary(_detail_rows(player_detail,m.get("home_id"),m.get("competition_id"))) if player_detail else {},"away":_detail_summary(_detail_rows(player_detail,m.get("away_id"),m.get("competition_id"))) if player_detail else {}},"weighting_policy":"FULL-DATA informs diagnostics/contradiction analysis; no learned coefficient is invented before OOS validation"}


def _coherence(p:Dict[str,float])->bool:
    return abs(p["home_win"]+p["draw"]+p["away_win"]-1)<1e-6 and abs(p["btts_yes"]+p["btts_no"]-1)<1e-6 and abs(p["over_2_5"]+p["under_2_5"]-1)<1e-6


def analyze(match:Any,league:Any,form:Any=None,table:Any=None,player:Any=None,player_detail:Any=None)->Dict[str,Any]:
    m=match_fields(match); xg=expected_goals(match,league,form); p=dixon_coles(xg["home"],xg["away"]); sel=select_market(p); ht=_team_obj(league,m.get("home_id")); at=_team_obj(league,m.get("away_id")); sample=_sample_security(ht or {},at or {}); ev=core_evidence(sel["key"],p,m,form)
    confirmations=[k for k,v in ev.items() if v["status"]=="BESTÄTIGEND"]; counters=[k for k,v in ev.items() if v["status"]=="GEGENARGUMENT"]
    structural={"BTTS":3,"1X2":4,"OU_2_5":4}[sel["family"]]; original=4 if sample=="NIEDRIG" else 3; required=min(original,structural); strength=sel["strength"]
    strict=None
    if m.get("kickoff_unix") is not None:strict=datetime.now(timezone.utc).timestamp()<m["kickoff_unix"]
    blockers=[]
    if len(confirmations)<required:blockers.append(f"{len(confirmations)}/{required} Kern-Confirmations")
    if counters:blockers.append("Gegenargument: "+", ".join(counters))
    if not _coherence(p):blockers.append("Probability coherence")
    if strict is False:blockers.append("nicht Strict Pre-Match")
    if strength<.20:decision="AUSLASSEN"
    elif strength<.30:decision="BEOBACHTEN"
    else:decision="SPIELEN" if not blockers else "BEOBACHTEN"
    fd=full_data_layer(match,league,form,table,player,player_detail)
    return {"ok":True,"engine":"FootyStats V1 FULL-DATA","model_version":VERSION,"standalone":True,"runtime_dependency_on_v043":False,"match":m,"expected_goals":{"home":round(xg["home"],4),"away":round(xg["away"],4),"detail":xg},"score_distribution":{"type":"Dixon-Coles","rho":RHO},"probabilities":{k:round(v,6) for k,v in p.items()},"strongest_market":{**sel,"probability_pct":round(sel["probability"]*100,1),"strength_pct":round(strength*100,1)},"sample_security":sample,"core_evidence":ev,"confirming_blocks":confirmations,"counter_blocks":counters,"gate_v1":{"original_required":original,"structural_applicable":structural,"required":required,"applied":required!=original,"core_confirmations":len(confirmations)},"full_data":fd,"decision":decision,"decision_blockers":blockers,"notes":["V1 ist eine eigenständige Engine-Linie und importiert keine V0.4.x Engine zur Laufzeit.","FULL-DATA ist integriert; unvalidierte Zusatzsignale erhalten keine erfundenen gelernten Gewichte."]}
