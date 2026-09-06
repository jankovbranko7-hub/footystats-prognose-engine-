"""V1 FULL-DATA challenger on frozen V0.4.3 FULL-5.

Only Gate V1 changes a decision rule. New data signals are diagnostic/research
until result-joined OOS validation approves a weight.
"""
from __future__ import annotations
import math, re
from contextvars import ContextVar
from typing import Any, Dict, Iterable, List, Optional
import v043_engine

VERSION="V1-FULL-DATA"; BASE_VERSION="0.4.3"
_PD: ContextVar[Optional[Any]]=ContextVar("v1_player_detail",default=None)

def _n(v):
    try:
        if v is None or isinstance(v,bool): return None
        x=float(v); return x if math.isfinite(x) else None
    except Exception:return None

def _walk(x):
    if isinstance(x,dict):
        yield x
        for v in x.values(): yield from _walk(v)
    elif isinstance(x,list):
        for v in x: yield from _walk(v)

def _stat(r,*keys):
    s=r.get("stats") if isinstance(r.get("stats"),dict) else r
    for k in keys:
        x=_n(s.get(k)) if isinstance(s,dict) else None
        if x is not None:return x
    return None

def _team_records(data,tid):
    tid=_n(tid); out=[]
    if tid is None:return out
    for d in _walk(data):
        if _n(d.get("id")) is not None and int(_n(d.get("id")))==int(tid) and (isinstance(d.get("stats"),dict) or "last_x_match_num" in d): out.append(d)
    return out

def _form(data,tid,venue):
    wins={}
    fields={"btts":"seasonBTTSPercentage","fh_btts":"seasonBTTSPercentageHT","fts":"seasonFTSPercentage","cs":"seasonCSPercentage","o25":"seasonOver25Percentage","xg":"xg_for_avg","xga":"xg_against_avg","gf":"seasonScoredAVG","ga":"seasonConcededAVG"}
    for r in _team_records(data,tid):
        z=_n(r.get("last_x_match_num"))
        if z is None or int(z) not in (5,6,10):continue
        wins[str(int(z))]={k:_stat(r,f"{base}_{venue}",f"{base}_overall") for k,base in fields.items()}
    def delta(k):
        a=(wins.get("5") or {}).get(k); b=(wins.get("10") or {}).get(k); return a-b if a is not None and b is not None else None
    def stability(k):
        vals=[(wins.get(w) or {}).get(k) for w in ("5","6","10")]; vals=[float(v) for v in vals if v is not None]
        return {"windows":len(vals),"spread":max(vals)-min(vals) if len(vals)>1 else None,"mean":sum(vals)/len(vals) if vals else None}
    return {"windows":wins,"momentum_5_minus_10":{k:delta(k) for k in fields},"stability":{k:stability(k) for k in fields}}

def _team(legacy,data,tid):
    try:return legacy.team_obj(data,tid)
    except Exception:return None

def _league_side(legacy,t,venue):
    if not isinstance(t,dict):return {}
    def g(*keys):
        try:return _n(legacy.firstnum(t,list(keys)))
        except Exception:
            for d in _walk(t):
                for k in keys:
                    x=_n(d.get(k))
                    if x is not None:return x
            return None
    shots=g(f"shotsAVG_{venue}"); sot=g(f"shotsOnTargetAVG_{venue}"); xg=g(f"xg_for_avg_{venue}"); gf=g(f"seasonScoredAVG_{venue}",f"seasonGoalsAVG_{venue}"); attacks=g(f"attacks_avg_{venue}"); danger=g(f"dangerous_attacks_avg_{venue}")
    return {"goal_regime":{"btts":g(f"seasonBTTSPercentage_{venue}"),"fh_btts":g(f"seasonBTTSPercentageHT_{venue}"),"fts":g(f"seasonFTSPercentage_{venue}"),"cs":g(f"seasonCSPercentage_{venue}"),"o25":g(f"seasonOver25Percentage_{venue}"),"avg_1h":g(f"AVGHT_{venue}"),"avg_2h":g(f"AVG_2hg_{venue}")},"chance_quality":{"shots":shots,"sot":sot,"xg":xg,"goals":gf,"sot_per_shot":sot/shots if sot is not None and shots else None,"xg_per_shot":xg/shots if xg is not None and shots else None,"goals_per_sot":gf/sot if gf is not None and sot else None,"dangerous_attack_share":danger/attacks if danger is not None and attacks else None}}

def _belongs(p,tid):
    tid=_n(tid)
    return tid is not None and any(_n(p.get(k)) is not None and int(_n(p.get(k)))==int(tid) for k in ("club_team_id","club_team_2_id"))

def _players(data):
    out={}
    for d in _walk(data):
        if _n(d.get("id")) is not None and "club_team_id" in d: out.setdefault((int(_n(d["id"])),d.get("competition_id")),d)
    return list(out.values())

def _share(v,n):
    v=[x for x in v if x>0]; s=sum(v); return sum(sorted(v,reverse=True)[:n])/s if s else None

def _depth(v):
    v=[x for x in v if x>0]; s=sum(v)
    if not s:return None
    h=sum((x/s)**2 for x in v); return 1/h if h else None

def _player_side(rows,tid):
    r=[p for p in rows if _belongs(p,tid)]; goals=[_n(p.get("goals_overall")) or 0 for p in r]; assists=[_n(p.get("assists_overall")) or 0 for p in r]; c=[a+b for a,b in zip(goals,assists)]; mins=[_n(p.get("minutes_played_overall")) or 0 for p in r]
    return {"players_found":len(r),"players_with_minutes":sum(x>0 for x in mins),"minutes":sum(mins),"top1_goal_share":_share(goals,1),"top3_goal_share":_share(goals,3),"top3_contribution_share":_share(c,3),"goal_effective_depth":_depth(goals),"contribution_effective_depth":_depth(c)}

def _pd_rows(data,tid,comp):
    out={}; comp=_n(comp)
    if comp is None:return []
    for d in _walk(data):
        if _n(d.get("id")) is None or _n(d.get("competition_id")) is None or int(_n(d["competition_id"]))!=int(comp) or not _belongs(d,tid) or not isinstance(d.get("detailed"),dict):continue
        out.setdefault((int(_n(d["id"])),int(comp)),d)
    return list(out.values())

def _wm(rows,key):
    v=[(_n((p.get("detailed") or {}).get(key)),_n(p.get("minutes_played_overall"))) for p in rows]; v=[(x,w) for x,w in v if x is not None and w is not None and w>0]; s=sum(w for _,w in v); return sum(x*w for x,w in v)/s if s else None

def _pd_side(rows):
    gk=[p for p in rows if str(p.get("position") or "").lower()=="goalkeeper"]; g=max(gk,key=lambda p:_n(p.get("minutes_played_overall")) or 0) if gk else {}; d=g.get("detailed") or {}
    return {"players_with_detailed":len(rows),"minutes":sum(_n(p.get("minutes_played_overall")) or 0 for p in rows),"npxg_per90":_wm(rows,"npxg_per_90_overall"),"xa_per90":_wm(rows,"xa_per_90_overall"),"xg_per90":_wm(rows,"xg_per_90_overall"),"key_passes_per90":_wm(rows,"key_passes_per_90_overall"),"shots_per90":_wm(rows,"shots_per_90_overall"),"sot_per90":_wm(rows,"shots_on_target_per_90_overall"),"progressive_passes":sum(_n((p.get("detailed") or {}).get("progressive_passes_total_overall")) or 0 for p in rows),"goalkeeper":{"id":int(_n(g.get("id"))) if _n(g.get("id")) is not None else None,"save_pct":_n(d.get("save_percentage_overall")),"saves_per90":_n(d.get("saves_per_90_overall")),"shots_faced_per90":_n(d.get("shots_faced_per_90_overall")),"conceded_per90":_n(g.get("conceded_per_90_overall"))}}

def _overall_table(data):
    root=data.get("data") if isinstance(data,dict) and isinstance(data.get("data"),dict) else data
    if isinstance(root,dict):
        for k in ("all_matches_table_overall","league_table"):
            if isinstance(root.get(k),list) and root[k]:return root[k]
    return []

def _table_side(rows,tid):
    r=next((x for x in rows if _n(x.get("id")) is not None and int(_n(x["id"]))==int(_n(tid) or -1)),None)
    if not r:return {}
    p=_n(r.get("position")); size=len(rows); n=_n(r.get("matchesPlayed")); gf=_n(r.get("seasonGoals")); ga=_n(r.get("seasonConceded")); norm=(p-1)/(size-1) if p is not None and size>1 else None
    return {"position":p,"league_size":size,"normalized_position_0_best":norm,"position_strength":1-norm if norm is not None else None,"matches_played":n,"ppg":_n(r.get("ppg_overall")) or ((_n(r.get("points"))/n) if _n(r.get("points")) is not None and n else None),"gd_per_match":(gf-ga)/n if gf is not None and ga is not None and n else None,"reliability":n/(n+6) if n else None,"reliability_formula":"n/(n+6), diagnostic only"}

def _trend_side(rows):
    texts=[x[1] for x in rows or [] if isinstance(x,(list,tuple)) and len(x)>1 and isinstance(x[1],str)]; blob=" ".join(texts)
    def g(p):
        m=re.search(p,blob,re.I); return _n(m.group(1)) if m else None
    return {"count":len(texts),"last5_points":g(r"picked up\s+([0-9.]+)\s+points from the last 5"),"last5_ppg":g(r"That's\s+([0-9.]+)\s+points per game"),"last5_btts":g(r"BTTS has landed[^.]*?([0-5])\s+of those games"),"last5_goals":g(r"has scored\s+([0-9.]+)\s+times in the last 5"),"season_btts_pct":g(r"That's\s+([0-9.]+)%\s+of all matches"),"scoring_streak":g(r"netted in the last\s+([0-9]+)\s+games"),"raw":texts}

def _match(data):
    m=next((d for d in _walk(data) if ("homeID" in d or "home_id" in d) and ("awayID" in d or "away_id" in d)),{}); h=m.get("h2h") or {}; b=h.get("betting_stats") or {}; r=h.get("previous_matches_results") or {}; ids=h.get("previous_matches_ids") or []; tr=m.get("trends") or {}
    return {"h2h":{"sample":_n(r.get("totalMatches")) or len(ids),"avg_goals":_n(b.get("avg_goals")),"btts_pct":_n(b.get("bttsPercentage")),"o25_pct":_n(b.get("over25Percentage")),"home_side_win_pct":_n(r.get("team_a_win_percent")),"away_side_win_pct":_n(r.get("team_b_win_percent")),"most_recent_unix":max([_n(x.get("date_unix")) or 0 for x in ids if isinstance(x,dict)] or [0]) or None},"trends":{"available":bool(tr),"home":_trend_side(tr.get("home") if isinstance(tr,dict) else []),"away":_trend_side(tr.get("away") if isinstance(tr,dict) else [])},"timing":{"recorded":_n(m.get("goal_timings_recorded")),"home":m.get("homeGoals_timings"),"away":m.get("awayGoals_timings")}}

def full_data(legacy,match,league,form,table,player,pd):
    x=legacy.mf(match); h=x.get("home_id"); a=x.get("away_id"); c=x.get("competition_id"); pr=_players(player) if player is not None else []; rows=_overall_table(table) if table is not None else []
    return {"status":"RESEARCH_LAYER_ACTIVE","probability_weighting":"NONE_UNTIL_BACKTEST","decision_weighting":"NONE_EXCEPT_GATE_V1","form":{"home":_form(form,h,"home") if form else {},"away":_form(form,a,"away") if form else {}},"player":{"home":_player_side(pr,h),"away":_player_side(pr,a)},"league":{"home":_league_side(legacy,_team(legacy,league,h),"home") if league else {},"away":_league_side(legacy,_team(legacy,league,a),"away") if league else {}},"table":{"home":_table_side(rows,h),"away":_table_side(rows,a)},"match":_match(match),"player_detail":{"home":_pd_side(_pd_rows(pd,h,c)),"away":_pd_side(_pd_rows(pd,a,c))} if pd else {},"source_presence":{"match":match is not None,"league":league is not None,"form":form is not None,"table":table is not None,"player":player is not None,"player_detail":pd is not None}}

def _family(k):
    if k in ("btts_yes","btts_no"):return "BTTS"
    if k in ("home_win","away_win"):return "1X2"
    if k in ("over_2_5","under_2_5"):return "OU_2_5"

def gate_v1(result,protocol):
    o=dict(protocol); gates=dict(o.get("gates") or {}); multi=dict(gates.get("multi_block_confirmation") or {}); conf=list(o.get("confirming_blocks") or []); counters=list(o.get("counter_blocks") or []); key=(result.get("strongest_market") or {}).get("key"); fam=_family(key); sample=(result.get("samples") or {}).get("security") or (result.get("diagnostics") or {}).get("sample_security"); orig=int(multi.get("required") or (4 if sample=="NIEDRIG" else 3)); applicable={"BTTS":3,"1X2":4,"OU_2_5":4}.get(fam,orig); req=min(orig,applicable); strength=_n((gates.get("probability_family_strength") or {}).get("strength_pct")); eligible=fam=="BTTS" and sample=="NIEDRIG" and strength is not None and strength>=30 and len(conf)>=req and not counters and gates.get("robustness")!="NICHT BESTANDEN" and gates.get("data_quality")!="NIEDRIG" and (gates.get("coherence") or {}).get("passed") is not False and (gates.get("pre_match_integrity") or {}).get("strict_pre_match") is not False
    multi.update({"original_required":orig,"required":req,"structural_applicable_blocks":applicable,"gate_v1_applied":req!=orig,"status":"BESTANDEN" if len(conf)>=req and conf else multi.get("status")}); gates["multi_block_confirmation"]=multi; o["gates"]=gates; before=o.get("final_decision"); changed=eligible and before=="BEOBACHTEN"
    if changed:o.update({"final_decision":"SPIELEN","decision_reasons":["Gate V1: Low-Sample-BTTS 3/3 strukturell anwendbare Confirmations; keine weiteren Blocker."],"decision_cap_applied":False,"decision_cap_reasons":[]})
    o["gate_v1"]={"family":fam,"sample_security":sample,"confirmations":len(conf),"original_required":orig,"applicable":applicable,"v1_required":req,"eligible":eligible,"decision_changed":bool(changed),"original_decision":before,"v1_decision":o.get("final_decision")}; o["version"]="V1 FULL-DATA / V0.4.3 FULL-5 + Gate V1"; return o

def apply_patch(legacy):
    app=v043_engine.apply_patch(legacy); old_kind=legacy._source_kind; old_pair=legacy.select_pair; old_an=legacy._analyze_bundle; old_sup=legacy.supplemental_report; old_protocol=legacy.elite_protocol_report; old_attach=legacy._attach_supplemental
    def kind(name): return "player_detail" if "playerdetaildaten" in (name or "").lower().replace(" ","") else old_kind(name)
    legacy._source_kind=kind; legacy._ARCHIVE_SOURCE_KINDS=("match","league","form","table","player","player_detail")
    def pair(files):
        p=dict(old_pair(files));
        if not p.get("ok"):return p
        e=dict(p.get("supplemental_data") or {}); s=dict(p.get("source_files") or {})
        for i in files:
            if kind(i.get("name") or "")=="player_detail":e["player_detail"]=i.get("data"); s["player_detail"]=i.get("name"); break
        p["supplemental_data"]=e; p["source_files"]=s; return p
    legacy.select_pair=pair
    def sup(match,league=None,form=None,table=None,player=None):
        r=dict(old_sup(match,league,form,table,player)); pd=_PD.get(); r["full_data"]=full_data(legacy,match,league,form,table,player,pd); rec=dict(r.get("received") or {}); rec["player_detail"]=pd is not None; r["received"]=rec; return r
    legacy.supplemental_report=sup
    legacy.elite_protocol_report=lambda result,report:gate_v1(result,old_protocol(result,report))
    def attach(result,report,sources):
        o=dict(old_attach(result,report,sources)); o["model_version"]=VERSION; o["base_model_version"]=BASE_VERSION; o["full_data_layer"]=report.get("full_data") or {}; o.setdefault("notes",[]); o["notes"]=list(o["notes"])+["Gate V1 changes only Low-Sample-BTTS confirmation requirement 4/3 -> structural 3/3.","FULL-DATA signals do not alter V0.4.3 probabilities before OOS approval."]; return o
    legacy._attach_supplemental=attach
    def analyze(files):
        p=pair(files)
        if not p.get("ok"):return p
        token=_PD.set((p.get("supplemental_data") or {}).get("player_detail"))
        try:return old_an(files)
        finally:_PD.reset(token)
    legacy._analyze_bundle=analyze; legacy.app.version=VERSION; legacy.app.title="FootyStats Gate V1 FULL-DATA Challenger"; legacy.INDEX_HTML=legacy.INDEX_HTML.replace("genau MatchDaten, LeagueDaten, FormDaten, TableDaten und PlayerDaten eines Matches","MatchDaten, LeagueDaten, FormDaten, TableDaten, PlayerDaten und optional PlayerDetailDaten eines Matches").replace("alle fünf JSON-Dateien gleichzeitig","alle sechs JSON-Dateien gleichzeitig (PlayerDetailDaten optional während der Übergangsphase)")
    legacy.app.router.routes=[r for r in legacy.app.router.routes if getattr(r,"path",None)!="/api/health"]
    legacy.app.add_api_route("/api/health",lambda:{"ok":True,"version":VERSION,"base":BASE_VERSION,"production":False,"challenger":True,"gate_v1":True,"player_detail_supported":True,"probabilities_locked_to_v043":True},methods=["GET"])
    legacy.app.add_api_route("/api/v1/feature-manifest",lambda:{"version":VERSION,"signals":{"form":["FH-BTTS","FTS/CS","momentum","stability"],"player":["depth","concentration"],"league":["goal regime","chance quality"],"table":["normalized strength","reliability"],"match":["H2H","trends","timing"],"player_detail":["npxG/xA/xG","key passes","shots/SOT","GK"]},"weighting":"research only except Gate V1"},methods=["GET"]); return app
