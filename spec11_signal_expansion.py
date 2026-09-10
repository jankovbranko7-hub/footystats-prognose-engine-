"""Extra SPEC v1.1 evidence blocks for strongest-market analysis.

Only fields already present in the five FootyStats files are used. Related raw
families are collapsed into one block so highly correlated columns cannot act
as dozens of independent votes.
"""
from __future__ import annotations
from typing import Any, Dict, List, Tuple
from spec11_native_engine import (
    SUPPORT, CONTRADICT, NEUTRAL, UNAVAILABLE, MARKETS,
    _num, _stats, _metric, _metric_median, _cmp, _median,
    _payload, _api_data, _page_rows,
)


def sig(src, dom, market, status, reason, tier="SUPPORT", ranking=True, **values):
    return {"source":src,"domain":dom,"market":market,"status":status,"reason":reason,"tier":tier,"ranking_eligible":ranking,"values":values}


def triplet(src, dom, direction, reason, tier="SUPPORT", **values):
    if direction is None: st={m:UNAVAILABLE for m in ("home_win","draw","away_win")}
    elif direction>0: st={"home_win":SUPPORT,"draw":NEUTRAL,"away_win":CONTRADICT}
    elif direction<0: st={"home_win":CONTRADICT,"draw":NEUTRAL,"away_win":SUPPORT}
    else: st={"home_win":NEUTRAL,"draw":SUPPORT,"away_win":NEUTRAL}
    return [sig(src,dom,m,st[m],reason,tier,True,**values) for m in ("home_win","draw","away_win")]


def normalize_existing(rows):
    for s in rows:
        s.setdefault("tier","CORE")
        if s.get("source")=="H2H":
            s["tier"]="DIAGNOSTIC_SECONDARY";s["ranking_eligible"]=False
        else:s.setdefault("ranking_eligible",True)
    return rows


def _hi(v, r, high=True):
    c=_cmp(v,r)
    if c is None:return UNAVAILABLE
    if c==0:return NEUTRAL
    return SUPPORT if (c>0)==high else CONTRADICT


def _pair(src,dom,m,hv,hr,av,ar,high,reason,tier="SUPPORT"):
    if None in (hv,hr,av,ar):return sig(src,dom,m,UNAVAILABLE,reason+" Mindestens ein Wert fehlt.",tier)
    hc,ac=_cmp(hv,hr),_cmp(av,ar)
    if not high:hc,ac=-hc,-ac
    st=SUPPORT if hc>0 and ac>0 else (CONTRADICT if hc<0 and ac<0 else NEUTRAL)
    return sig(src,dom,m,st,reason,tier,True,home=hv,home_ref=hr,away=av,away_ref=ar)


def extended_match(match, hs, aws, league_ctx, teams):
    out=[]
    hop=_num(match.get("pre_match_teamA_overall_ppg")) if (hs or 0)>0 else None
    aop=_num(match.get("pre_match_teamB_overall_ppg")) if (aws or 0)>0 else None
    out+=triplet("MATCH","OVERALL_PREMATCH_PPG",_cmp(hop,aop),"Overall-PPG vor dem Zielspiel; 0-Spiel-Werte sind NICHT VERFÜGBAR.","SUPPORT",home=hop,away=aop)
    avgp=_num(match.get("avg_potential"));ref=_num(league_ctx.get("seasonAVG_overall")) or _metric_median(teams,"seasonAVG","overall")
    for m,high in (("over_2_5",True),("under_2_5",False)):
        out.append(sig("MATCH","AVG_GOALS_POTENTIAL",m,_hi(avgp,ref,high),"avg_potential relativ zum Competition-Torschnitt.","CORE",True,value=avgp,reference=ref))
    hx=_num(match.get("team_a_xg_prematch"));ax=_num(match.get("team_b_xg_prematch"));hx=hx if hx and hx>0 else None;ax=ax if ax and ax>0 else None
    tx=_num(match.get("total_xg_prematch")) if hx is not None and ax is not None else None
    for m,high in (("over_2_5",True),("under_2_5",False)):
        out.append(sig("MATCH","TOTAL_XG_PREMATCH",m,_hi(tx,ref,high),"total_xg_prematch nur bei echten Team-xG-Werten.","SUPPORT_HIGH",True,value=tx,reference=ref))
    comps=[]
    for line in (15,25,35,45):
        o,u=_num(match.get(f"o{line}_potential")),_num(match.get(f"u{line}_potential"))
        if o is not None and u is not None:comps.append(_cmp(o,u) or 0)
    score=sum(comps) if comps else None
    for m,high in (("over_2_5",True),("under_2_5",False)):
        st=UNAVAILABLE if score is None else (NEUTRAL if score==0 else (SUPPORT if (score>0)==high else CONTRADICT))
        out.append(sig("MATCH","GOALS_POTENTIAL_LADDER",m,st,"O/U-Potentialfamilie 1.5–4.5 als ein gemeinsamer Block.","CORE",True,components=len(comps),net=score))
    ap=_num(match.get("pre_match_away_ppg")) if (aws or 0)>0 else None;b=_num(match.get("btts_potential"));flag=None if b is None or ap is None else b>=65 and ap>=1.5
    out.append(sig("MATCH","FOOTYSTATS_TUTORIAL_BTTS","btts_yes",UNAVAILABLE if flag is None else (SUPPORT if flag else NEUTRAL),"FootyStats-Tutorial-Beispiel nur als Evidenz-Flag.","OFFICIAL_EXAMPLE",True,flag=flag))
    hp=_num(match.get("pre_match_home_ppg")) if (hs or 0)>0 else None;low=None if avgp is None or hp is None or ap is None else avgp<=1.8 and hp<=1.5 and ap<=1.5
    out.append(sig("MATCH","FOOTYSTATS_TUTORIAL_LOW_SCORING","under_2_5",UNAVAILABLE if low is None else (SUPPORT if low else NEUTRAL),"FootyStats-Low-Scoring-Beispiel nur als Evidenz-Flag.","OFFICIAL_EXAMPLE",True,flag=low))
    for m,_ in MARKETS:out.append(sig("MATCH","TEXT_TRENDS",m,NEUTRAL if match.get("trends") else UNAVAILABLE,"Text-Trends nur Diagnostik.","DIAGNOSTIC",False,present=bool(match.get("trends"))))
    return out


def extended_league(teams, home, away):
    out=[]
    for m,base in (("home_win","winPercentage"),("draw","drawPercentage"),("away_win","winPercentage")):
        if m=="home_win": vals=(_metric(home,base,"home"),_metric_median(teams,base,"home"),_metric(away,"losePercentage","away"),_metric_median(teams,"losePercentage","away"))
        elif m=="away_win": vals=(_metric(away,base,"away"),_metric_median(teams,base,"away"),_metric(home,"losePercentage","home"),_metric_median(teams,"losePercentage","home"))
        else: vals=(_metric(home,base,"home"),_metric_median(teams,base,"home"),_metric(away,base,"away"),_metric_median(teams,base,"away"))
        if None in vals:st=UNAVAILABLE
        else:
            a,b,c,d=vals;st=SUPPORT if a>b and c>d else (CONTRADICT if a<b and c<d else NEUTRAL)
        out.append(sig("LEAGUE","VENUE_WDL_PROFILE",m,st,"Win/Draw/Lose-Familien beider Venue-Splits liga-relativ.","CORE_1X2"))
    hs,as_=_metric(home,"seasonScoredAVG","home"),_metric(away,"seasonScoredAVG","away");hc,ac=_metric(home,"seasonConcededAVG","home"),_metric(away,"seasonConcededAVG","away")
    hsr,asr=_metric_median(teams,"seasonScoredAVG","home"),_metric_median(teams,"seasonScoredAVG","away");hcr,acr=_metric_median(teams,"seasonConcededAVG","home"),_metric_median(teams,"seasonConcededAVG","away")
    hd=None if None in (hs,hsr,ac,acr) else (_cmp(hs,hsr) or 0)+(_cmp(ac,acr) or 0);ad=None if None in (as_,asr,hc,hcr) else (_cmp(as_,asr) or 0)+(_cmp(hc,hcr) or 0)
    out+=triplet("LEAGUE","SCORING_CONCEDING_STRENGTH",None if hd is None or ad is None else _cmp(hd,ad),"ScoredAVG + gegnerisches ConcededAVG als Venue-Stärkeblock.","CORE_SCORING")
    vals=(hs,as_,hc,ac);refs=(hsr,asr,hcr,acr)
    for m,high in (("btts_yes",True),("btts_no",False),("over_2_5",True),("under_2_5",False)):
        if None in vals+refs:st=UNAVAILABLE
        else:
            c=_cmp(sum(vals),sum(refs));st=NEUTRAL if c==0 else (SUPPORT if (c>0)==high else CONTRADICT)
        out.append(sig("LEAGUE","SCORING_CONCEDING_ENVIRONMENT",m,st,"ScoredAVG/ConcededAVG als gemeinsames Torumfeld.","CORE_SCORING"))
    havg,aavg=_metric(home,"seasonAVG","home"),_metric(away,"seasonAVG","away");hr,ar=_metric_median(teams,"seasonAVG","home"),_metric_median(teams,"seasonAVG","away")
    for m,high in (("over_2_5",True),("under_2_5",False)):out.append(_pair("LEAGUE","VENUE_TOTAL_GOAL_AVG",m,havg,hr,aavg,ar,high,"seasonAVG beider Venue-Splits liga-relativ.","CORE_GOALS"))
    points=[]
    for line in (5,15,25,35,45,55):
        ob=f"seasonOver{line:02d}Percentage";ub=f"seasonUnder{line:02d}Percentage"
        for t,sp in ((home,"home"),(away,"away")):
            o,u=_metric(t,ob,sp),_metric(t,ub,sp);orr,urr=_metric_median(teams,ob,sp),_metric_median(teams,ub,sp)
            if None not in (o,u,orr,urr):points.append((_cmp(o,orr) or 0)-(_cmp(u,urr) or 0))
    sc=sum(points) if points else None
    for m,high in (("over_2_5",True),("under_2_5",False)):
        st=UNAVAILABLE if sc is None else (NEUTRAL if sc==0 else (SUPPORT if (sc>0)==high else CONTRADICT))
        out.append(sig("LEAGUE","OVER_UNDER_LADDER",m,st,"O/U 0.5–5.5 gemeinsam gegen Venue-Competition-Referenzen.","CORE_GOALS",True,components=len(points),net=sc))
    for dom,bases in (("HT_CS_FTS_PROFILE",("seasonCSPercentageHT","seasonFTSPercentageHT")),("CS_FTS_EXTENDED",("seasonCSPercentage","seasonFTSPercentage"))):
        pairs=[]
        for base in bases:
            for t,sp in ((home,"home"),(away,"away")):pairs.append((_metric(t,base,sp),_metric_median(teams,base,sp)))
        for m,open_ in (("btts_yes",True),("btts_no",False),("over_2_5",True),("under_2_5",False)):
            if any(v is None or r is None for v,r in pairs):st=UNAVAILABLE
            else:
                low=all(v<r for v,r in pairs);high=all(v>r for v,r in pairs);st=SUPPORT if (low if open_ else high) else (CONTRADICT if (high if open_ else low) else NEUTRAL)
            out.append(sig("LEAGUE",dom,m,st,"CS/FTS gemeinsam liga-relativ.","SUPPORT"))
    hht,aht=_metric(home,"HTPPG","home"),_metric(away,"HTPPG","away");hhr,aar=_metric_median(teams,"HTPPG","home"),_metric_median(teams,"HTPPG","away")
    out+=triplet("LEAGUE","HALF_TIME_PPG",None if None in (hht,aht,hhr,aar) else _cmp(hht-hhr,aht-aar),"HTPPG liga-relativ.","SUPPORT")
    for dom,bases in (("FIRST_HALF_GOAL_ENVIRONMENT",("AVGHT","scoredAVGHT","concededAVGHT")),("SECOND_HALF_GOAL_ENVIRONMENT",("AVG_2hg","scored_2hg_avg","conceded_2hg_avg")),("CHANCE_VOLUME",("shotsAVG","shotsOnTargetAVG"))):
        actual=[];reference=[]
        for base in bases:
            actual += [_metric(home,base,"home"),_metric(away,base,"away")];reference += [_metric_median(teams,base,"home"),_metric_median(teams,base,"away")]
        for m,high in (("btts_yes",True),("btts_no",False),("over_2_5",True),("under_2_5",False)):
            if any(x is None for x in actual+reference):st=UNAVAILABLE
            else:
                c=_cmp(sum(actual),sum(reference));st=NEUTRAL if c==0 else (SUPPORT if (c>0)==high else CONTRADICT)
            out.append(sig("LEAGUE",dom,m,st,"Verwandte Halbzeit-/Chance-Felder als ein liga-relativer Block.","SUPPORT"))
    hp,ap=_metric(home,"possessionAVG","home"),_metric(away,"possessionAVG","away")
    for m in ("home_win","draw","away_win"):out.append(sig("LEAGUE","POSSESSION_CONTEXT",m,NEUTRAL if hp is not None and ap is not None else UNAVAILABLE,"Possession ist Diagnostik, keine Ranking-Stimme.","DIAGNOSTIC",False,home=hp,away=ap))
    hst,ast=_stats(home),_stats(away);hn=sum(k.startswith("goals_scored_min_") and _num(v) is not None for k,v in hst.items());an=sum(k.startswith("goals_scored_min_") and _num(v) is not None for k,v in ast.items())
    for m in ("btts_yes","btts_no","over_2_5","under_2_5"):out.append(sig("LEAGUE","GOAL_TIMING_CONTEXT",m,NEUTRAL if hn and an else UNAVAILABLE,"Goal-Timing erfasst, ohne künstliche Marktrichtung.","DIAGNOSTIC_TIMING",False,home_fields=hn,away_fields=an))
    return out


def _records(w,side):
    p=_payload(w);d=_api_data(p.get(side)) if isinstance(p,dict) else None
    return [x for x in d if isinstance(x,dict)] if isinstance(d,list) else []
def _sel(w,side,tid):
    rows=[r for r in _records(w,side) if int(_num(r.get("id")) or -1)==int(tid)]
    n=lambda r:int(_num(r.get("last_x_match_num")) or _num(_stats(r).get("last_x")) or 0)
    return next((r for r in rows if n(r)==5),None),next((r for r in rows if n(r)==10),None) or next((r for r in rows if n(r)==6),None)
def _delta(a,b,k):
    x,y=(_num(_stats(a).get(k)) if a else None),(_num(_stats(b).get(k)) if b else None);return None if x is None or y is None else x-y


def extended_form(w,home_id,away_id):
    out=[];h,hr=_sel(w,"home",home_id);a,ar=_sel(w,"away",away_id)
    hw,aw,hl,al=_delta(h,hr,"winPercentage_overall"),_delta(a,ar,"winPercentage_overall"),_delta(h,hr,"losePercentage_overall"),_delta(a,ar,"losePercentage_overall")
    out+=triplet("FORM","RESULT_FORM_TREND",None if None in (hw,aw,hl,al) else _cmp(hw-al,aw-hl),"Win/Lose Last 5 gegen Last 10/6.","RECENT_FORM")
    hh,ah=_delta(h,hr,"HTPPG_overall"),_delta(a,ar,"HTPPG_overall");out+=triplet("FORM","HTPPG_FORM_TREND",None if hh is None or ah is None else _cmp(hh,ah),"HTPPG Last 5 gegen Last 10/6.","RECENT_FORM")
    for dom,keys in (("FIRST_HALF_BTTS_FORM_TREND",("seasonBTTSPercentageHT_overall",)),("SCORING_CONCEDING_FORM_TREND",("seasonScoredAVG_overall","seasonConcededAVG_overall","seasonAVG_overall")),("XG_XGA_FORM_TREND",("xg_for_avg_overall","xg_against_avg_overall")),("FIRST_HALF_GOALS_FORM_TREND",("AVGHT_overall","scoredAVGHT_overall","concededAVGHT_overall")),("SECOND_HALF_GOALS_FORM_TREND",("AVG_2hg_overall","scored_2hg_avg_overall","conceded_2hg_avg_overall")),("CHANCE_VOLUME_FORM_TREND",("shotsAVG_overall","shotsOnTargetAVG_overall"))):
        ds=[]
        for k in keys:ds += [_delta(h,hr,k),_delta(a,ar,k)]
        for m,high in (("btts_yes",True),("btts_no",False),("over_2_5",True),("under_2_5",False)):
            if any(v is None for v in ds):st=UNAVAILABLE
            else:
                sc=sum(ds);st=NEUTRAL if abs(sc)<1e-9 else (SUPPORT if (sc>0)==high else CONTRADICT)
            out.append(sig("FORM",dom,m,st,"Verwandte Last-5-vs-Last-10/6-Felder als ein Block.","RECENT_FORM",True,deltas=ds))
    cs=[_delta(h,hr,"seasonCSPercentage_overall"),_delta(a,ar,"seasonCSPercentage_overall")];fts=[_delta(h,hr,"seasonFTSPercentage_overall"),_delta(a,ar,"seasonFTSPercentage_overall")]
    for m,open_ in (("btts_yes",True),("btts_no",False),("over_2_5",True),("under_2_5",False)):
        if any(v is None for v in cs+fts):st=UNAVAILABLE
        else:
            op=all(v<0 for v in cs+fts);cl=all(v>0 for v in cs+fts);st=SUPPORT if (op if open_ else cl) else (CONTRADICT if (cl if open_ else op) else NEUTRAL)
        out.append(sig("FORM","CS_FTS_FORM_TREND",m,st,"CS/FTS Last 5 gegen Last 10/6.","RECENT_FORM"))
    return out


def extended_table(w,home_id,away_id):
    d=_api_data(_payload(w));d=d if isinstance(d,dict) else {}
    def row(rows,tid):return next((r for r in rows if isinstance(r,dict) and int(_num(r.get("id")) or -1)==int(tid)),None) if isinstance(rows,list) else None
    h=row(d.get("all_matches_table_home"),home_id);a=row(d.get("all_matches_table_away"),away_id);mode="VENUE"
    if h is None or a is None:h=row(d.get("all_matches_table_overall"),home_id);a=row(d.get("all_matches_table_overall"),away_id);mode="OVERALL"
    def gd(r):
        n=_num((r or {}).get("matchesPlayed"));x=_num((r or {}).get("seasonGoalDifference"));return x/n if n and n>0 and x is not None else None
    out=triplet("TABLE","GOAL_DIFFERENCE_PER_MATCH",_cmp(gd(h),gd(a)),f"{mode}-Tabelle: Tordifferenz pro realem Match.","TABLE_CONTEXT")
    structures={k:(len(v) if isinstance(v,list) else (1 if v else 0)) for k,v in d.items() if k in {"league_table","all_matches_table_overall","all_matches_table_home","all_matches_table_away","specific_tables"}}
    for m,_ in MARKETS:out.append(sig("TABLE","TABLE_STRUCTURE_COVERAGE",m,NEUTRAL,"Tabellenstrukturen auditiert, nicht als Ranking-Stimme.","DIAGNOSTIC",False,structures=structures))
    return out


def _prows(w):
    p=_payload(w);return _page_rows(p.get("pages")) if isinstance(p,dict) else []
def _target(rows,tid):return [r for r in rows if any(v is not None and int(v)==int(tid) for v in (_num(r.get("club_team_id")),_num(r.get("club_team_2_id"))))]
def _ps(players):
    if not players:return {"available":False,"players_found":0}
    mins=[_num(p.get("minutes_played_overall")) for p in players];gv=[_num(p.get("goals_overall")) for p in players];av=[_num(p.get("assists_overall")) for p in players]
    mt=sum(v for v in mins if v is not None);complete=all(v is not None for v in gv+av);invol=(sum(gv)+sum(av))*90/mt if complete and mt>0 else None
    advanced={k:_median([_num(p.get(k)) for p in players if _num(p.get(k)) is not None]) for k in ("xg_per_90_overall","npxg_per_90_overall","xa_per_90_overall","shots","shots_on_target")}
    def shares(v):
        v=sorted(v,reverse=True);t=sum(v);return {"top1":v[0]/t if t and v else None,"top2":sum(v[:2])/t if t else None,"top3":sum(v[:3])/t if t else None}
    iv=[g+a for g,a in zip(gv,av)] if complete else []
    return {"available":True,"players_found":len(players),"minutes_total":mt,"production_fields_complete":complete,"involvement_per90":invol,"advanced":advanced,"goal_concentration":shares(gv) if complete else {},"involvement_concentration":shares(iv) if complete else {}}


def extended_player(w,home_id,away_id):
    rows=_prows(w);hp,ap=_target(rows,home_id),_target(rows,away_id);h,a=_ps(hp),_ps(ap);out=[]
    scope={"raw_league_players":len(rows),"analysis_players":len(hp)+len(ap),"home_players":len(hp),"away_players":len(ap)}
    if not(h["available"] and a["available"]):
        for m,_ in MARKETS:out.append(sig("PLAYER","TARGET_PLAYER_SCOPE",m,UNAVAILABLE,"Nur Zielteams werden analysiert; fehlt eines, ist der Block NICHT VERFÜGBAR.","PLAYER"))
        return out,scope
    out+=triplet("PLAYER","TARGET_GOAL_INVOLVEMENT",_cmp(h["involvement_per90"],a["involvement_per90"]),"Nur Zielteams: aggregierte Goals+Assists/90.","PLAYER_PRODUCTION")
    byclub={}
    for r in rows:
        cid=_num(r.get("club_team_id"))
        if cid is not None and cid>0:byclub.setdefault(int(cid),[]).append(r)
    refs=[_ps(v)["involvement_per90"] for v in byclub.values() if _ps(v)["involvement_per90"] is not None];ref=_median(refs)
    for m,high in (("btts_yes",True),("btts_no",False),("over_2_5",True),("under_2_5",False)):out.append(_pair("PLAYER","TARGET_ATTACK_PRODUCTION",m,h["involvement_per90"],ref,a["involvement_per90"],ref,high,"Zielteam-Produktion gegen Competition-Club-Median; andere Spieler nur Referenz.","PLAYER_PRODUCTION"))
    for key in h["advanced"]:
        hv,av=h["advanced"][key],a["advanced"][key];rv=_median([_ps(v)["advanced"][key] for v in byclub.values() if _ps(v)["advanced"][key] is not None])
        for m,high in (("btts_yes",True),("btts_no",False),("over_2_5",True),("under_2_5",False)):out.append(_pair("PLAYER",f"TARGET_{key.upper()}",m,hv,rv,av,rv,high,"Advanced Player-Feld nur bei echter FootyStats-Coverage.","PLAYER_CHANCE_QUALITY"))
    for m,_ in MARKETS:out.append(sig("PLAYER","PLAYER_CONCENTRATION",m,NEUTRAL,"Top1/2/3-Konzentration sichtbar, ohne Lineup-Annahme keine Ranking-Stimme.","DIAGNOSTIC",False,home_goals=h["goal_concentration"],away_goals=a["goal_concentration"],home_involvement=h["involvement_concentration"],away_involvement=a["involvement_concentration"]))
    return out,scope
