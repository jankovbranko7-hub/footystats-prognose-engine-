"""SPEC v1.1 full-signal strongest-market layer. No V0.4.x, odds, fallback or decision engine."""
from typing import Any, Dict, List
import spec11_strongest_market_engine as base
from spec11_native_engine import SUPPORT,CONTRADICT,NEUTRAL,UNAVAILABLE,MARKETS,LABELS,CENTRAL_SOURCES,_pair,_num,_stats,_metric,_metric_median,_cmp,_league_context,_league_team_rows,_team_by_id,_page_rows,_payload,_api_data
ENGINE_NAME="FOOTYSTATS_SPEC_V1_1_FULL_SIGNAL_STRONGEST_MARKET"
ENGINE_VERSION="1.1.2-full-signal-breadth"
SPEC_VERSION="1.1"
def sig(src,dom,m,st,why,ranking=True,**v):return {"source":src,"domain":dom,"market":m,"status":st,"reason":why,"ranking_eligible":ranking,"values":v}
def trip(src,dom,d,why,**v):
 s={"home_win":UNAVAILABLE,"draw":UNAVAILABLE,"away_win":UNAVAILABLE} if d is None else ({"home_win":SUPPORT,"draw":NEUTRAL,"away_win":CONTRADICT} if d>0 else ({"home_win":CONTRADICT,"draw":NEUTRAL,"away_win":SUPPORT} if d<0 else {"home_win":NEUTRAL,"draw":SUPPORT,"away_win":NEUTRAL}));return [sig(src,dom,m,s[m],why,**v) for m in ("home_win","draw","away_win")]
def status(c,high=True):return UNAVAILABLE if c is None else (NEUTRAL if c==0 else (SUPPORT if (c>0)==high else CONTRADICT))
def extras(match,hs,aws,ctx,teams,h,a,form,table,player,hid,aid):
 o=[]
 hp=_num(match.get("pre_match_teamA_overall_ppg")) if (hs or 0)>0 else None;ap=_num(match.get("pre_match_teamB_overall_ppg")) if (aws or 0)>0 else None;o+=trip("MATCH","OVERALL_PREMATCH_PPG",_cmp(hp,ap),"Overall-Pre-Match-PPG; 0 Competition-Spiele bleiben NICHT VERFÜGBAR.")
 ref=_num(ctx.get("seasonAVG_overall")) or _metric_median(teams,"seasonAVG","overall");avg=_num(match.get("avg_potential"));tx=_num(match.get("total_xg_prematch"));hx=_num(match.get("team_a_xg_prematch"));ax=_num(match.get("team_b_xg_prematch"));tx=tx if hx and hx>0 and ax and ax>0 else None
 for m,hi in (("over_2_5",True),("under_2_5",False)):
  o.append(sig("MATCH","AVG_GOALS_POTENTIAL",m,status(_cmp(avg,ref),hi),"avg_potential gegen Competition-Torschnitt."));o.append(sig("MATCH","TOTAL_XG_PREMATCH",m,status(_cmp(tx,ref),hi),"total_xg_prematch nur bei echten Team-xG."))
 pts=[]
 for x in (15,25,35,45):
  ov,un=_num(match.get(f"o{x}_potential")),_num(match.get(f"u{x}_potential"));pts += [] if ov is None or un is None else [_cmp(ov,un) or 0]
 for m,hi in (("over_2_5",True),("under_2_5",False)):o.append(sig("MATCH","GOALS_POTENTIAL_LADDER",m,status(_cmp(sum(pts),0) if pts else None,hi),"O/U 1.5–4.5 als ein gemeinsamer Potential-Block."))
 for m,parts in {"home_win":[("winPercentage",h,"home"),("losePercentage",a,"away")],"away_win":[("winPercentage",a,"away"),("losePercentage",h,"home")],"draw":[("drawPercentage",h,"home"),("drawPercentage",a,"away")]}.items():
  cs=[_cmp(_metric(t,b,s),_metric_median(teams,b,s)) for b,t,s in parts];st=UNAVAILABLE if any(x is None for x in cs) else (SUPPORT if all(x>0 for x in cs) else (CONTRADICT if all(x<0 for x in cs) else NEUTRAL));o.append(sig("LEAGUE","VENUE_WDL_PROFILE",m,st,"Win/Draw/Lose Venue-Familien liga-relativ."))
 vals=[];refs=[]
 for b in ("seasonScoredAVG","seasonConcededAVG"):
  vals += [_metric(h,b,"home"),_metric(a,b,"away")];refs += [_metric_median(teams,b,"home"),_metric_median(teams,b,"away")]
 for m,hi in (("btts_yes",True),("btts_no",False),("over_2_5",True),("under_2_5",False)):
  c=None if any(v is None for v in vals+refs) else _cmp(sum(vals),sum(refs));o.append(sig("LEAGUE","SCORING_CONCEDING_ENVIRONMENT",m,status(c,hi),"ScoredAVG + ConcededAVG als gemeinsamer Venue-Block."))
 ladder=[]
 for x in (5,15,25,35,45,55):
  for t,s in ((h,"home"),(a,"away")):
   ov,un=_metric(t,f"seasonOver{x:02d}Percentage",s),_metric(t,f"seasonUnder{x:02d}Percentage",s);orm,urm=_metric_median(teams,f"seasonOver{x:02d}Percentage",s),_metric_median(teams,f"seasonUnder{x:02d}Percentage",s)
   if None not in (ov,un,orm,urm):ladder.append((_cmp(ov,orm) or 0)-(_cmp(un,urm) or 0))
 for m,hi in (("over_2_5",True),("under_2_5",False)):o.append(sig("LEAGUE","OVER_UNDER_LADDER",m,status(_cmp(sum(ladder),0) if ladder else None,hi),"O/U 0.5–5.5 gemeinsam liga-relativ."))
 hh,ah=_metric(h,"HTPPG","home"),_metric(a,"HTPPG","away");hr,ar=_metric_median(teams,"HTPPG","home"),_metric_median(teams,"HTPPG","away");o+=trip("LEAGUE","HALF_TIME_PPG",None if None in (hh,ah,hr,ar) else _cmp(hh-hr,ah-ar),"HTPPG liga-relativ.")
 for dom,bases in (("HALF_GOAL_ENVIRONMENT",("AVGHT","AVG_2hg")),("CHANCE_VOLUME",("shotsAVG","shotsOnTargetAVG"))):
  vv=[];rr=[]
  for b in bases:vv += [_metric(h,b,"home"),_metric(a,b,"away")];rr += [_metric_median(teams,b,"home"),_metric_median(teams,b,"away")]
  for m,hi in (("btts_yes",True),("btts_no",False),("over_2_5",True),("under_2_5",False)):o.append(sig("LEAGUE",dom,m,status(None if any(v is None for v in vv+rr) else _cmp(sum(vv),sum(rr)),hi),f"{dom} als gruppierter liga-relativer Block."))
 p=_payload(form)
 def fr(side,tid,n):
  d=_api_data(p.get(side)) if isinstance(p,dict) else [];return next((r for r in d if isinstance(r,dict) and int(_num(r.get("id")) or -1)==tid and int(_num(r.get("last_x_match_num")) or 0)==n),None) if isinstance(d,list) else None
 def fm(r,k):return _num(_stats(r).get(k)) if r else None
 H,H10=fr("home",hid,5),fr("home",hid,10) or fr("home",hid,6);A,A10=fr("away",aid,5),fr("away",aid,10) or fr("away",aid,6)
 for dom,keys in (("SCORING_FORM",("seasonScoredAVG_overall","seasonConcededAVG_overall","seasonAVG_overall")),("XG_FORM",("xg_for_avg_overall","xg_against_avg_overall")),("CHANCE_FORM",("shotsAVG_overall","shotsOnTargetAVG_overall"))):
  ds=[]
  for k in keys:
   for x,y in ((H,H10),(A,A10)):
    q,r=fm(x,k),fm(y,k);ds.append(None if q is None or r is None else q-r)
  for m,hi in (("btts_yes",True),("btts_no",False),("over_2_5",True),("under_2_5",False)):o.append(sig("FORM",dom,m,status(None if any(v is None for v in ds) else _cmp(sum(ds),0),hi),"Last 5 gegen Last 10/6; verwandte Felder als ein Block."))
 pp=_payload(player);rows=_page_rows(pp.get("pages")) if isinstance(pp,dict) else [];target=lambda tid:[r for r in rows if any(v is not None and int(v)==tid for v in (_num(r.get("club_team_id")),_num(r.get("club_team_2_id"))))];ph,pa=target(hid),target(aid)
 if not ph or not pa:
  for m,_ in MARKETS:o.append(sig("PLAYER","TARGET_PLAYER_SCOPE",m,UNAVAILABLE,"Mindestens ein Zielteam fehlt; kein 0-Stärke-Ersatz."))
 else:
  def ps(x):
   mins=sum(_num(r.get("minutes_played_overall")) or 0 for r in x);apps=sum(_num(r.get("appearances_overall")) or 0 for r in x);g=sum(_num(r.get("goals_overall")) or 0 for r in x);aa=sum(_num(r.get("assists_overall")) or 0 for r in x);return {"active":sum(1 for r in x if (_num(r.get("minutes_played_overall")) or 0)>0),"minutes":mins,"appearances":apps,"involvement90":(g+aa)*90/mins if mins>0 else None}
  sh,sa=ps(ph),ps(pa);o+=trip("PLAYER","PLAYER_DEPTH",_cmp(sh["minutes"],sa["minutes"]),"Nur Zielteams: Player-Minuten/Abdeckung.");o+=trip("PLAYER","PLAYER_ATTACKING_OUTPUT",_cmp(sh["involvement90"],sa["involvement90"]),"Nur Zielteams: Goals+Assists/90.")
 for m,_ in MARKETS:o.append(sig("PLAYER","PLAYER_SCOPE_AUDIT",m,NEUTRAL,"Alle Seiten werden geladen; Analyse nutzt nur Heim-/Auswärtsteam-Spieler.",False,raw_players=len(rows),analysis_players=len(ph)+len(pa)))
 return o,{"raw_league_players":len(rows),"analysis_players":len(ph)+len(pa),"home_players":len(ph),"away_players":len(pa),"analysis_scope":"ONLY_HOME_AND_AWAY_TARGET_PLAYERS"}
def agg(signals,m):
 s=[x for x in signals if x.get("market")==m];e=[x for x in s if x.get("ranking_eligible",True)];su=[x for x in e if x.get("status")==SUPPORT];co=[x for x in e if x.get("status")==CONTRADICT];un=[x for x in e if x.get("status")==UNAVAILABLE];ps=[];ns=[]
 for src in CENTRAL_SOURCES:
  z=[x for x in e if x.get("source")==src and x.get("status")!=UNAVAILABLE];n=sum(x.get("status")==SUPPORT for x in z)-sum(x.get("status")==CONTRADICT for x in z)
  if n>0:ps.append(src)
  elif n<0:ns.append(src)
 av=len(e)-len(un);return {"key":m,"label":LABELS[m],"support_count":len(su),"contradiction_count":len(co),"neutral_count":sum(x.get("status")==NEUTRAL for x in e),"unavailable_count":len(un),"available_signal_count":av,"ranking_signal_count":len(e),"diagnostic_signal_count":len(s)-len(e),"net_evidence":len(su)-len(co),"evidence_balance":round((len(su)-len(co))/av,6) if av else None,"central_support_sources":sorted(ps),"central_contradiction_sources":sorted(ns),"source_net_evidence":len(ps)-len(ns),"signals":s}
def rk(x):return (x["source_net_evidence"],len(x["central_support_sources"]),-len(x["central_contradiction_sources"]),x["net_evidence"],-x["contradiction_count"],x["available_signal_count"])
def analyze_bundle(parsed:List[Dict[str,Any]])->Dict[str,Any]:
 r=base.analyze_bundle(parsed)
 if not r.get("ok"):return r
 p=_pair(parsed);f=p["files"];i=p["identity"];teams=_league_team_rows(f["league"]["data"]);h=_team_by_id(teams,i["home_id"]);a=_team_by_id(teams,i["away_id"]);signals=[]
 for mm in r["markets"]:
  for x in mm["signals"]:
   if x in signals or x.get("source")=="PLAYER":continue
   y=dict(x);y["ranking_eligible"]=False if y.get("source")=="H2H" else True;signals.append(y)
 ex,pc=extras(p["match"],r["sample_state"]["home"]["matches"],r["sample_state"]["away"]["matches"],_league_context(f["league"]["data"]),teams,h,a,f["form"]["data"],f["table"]["data"],f["player"]["data"],i["home_id"],i["away_id"]);signals+=ex
 markets=[agg(signals,k) for k,_ in MARKETS];markets.sort(key=rk,reverse=True)
 for n,m in enumerate(markets,1):m["rank"]=n
 t=markets[0];clear=t["source_net_evidence"]>0 and len(t["central_support_sources"])>=2 and rk(t)!=rk(markets[1]);top={k:t[k] for k in ("key","label","support_count","contradiction_count","neutral_count","unavailable_count","available_signal_count","ranking_signal_count","diagnostic_signal_count","net_evidence","evidence_balance","central_support_sources","central_contradiction_sources","source_net_evidence")};top["clear_lead"]=clear
 r.update({"engine":ENGINE_NAME,"engine_version":ENGINE_VERSION,"markets":markets,"strongest_market":top,"recommendation":t["label"] if clear else "KEINE KLARE EMPFEHLUNG","recommendation_reason":f"{t['label']} hat im vollständigen SPEC-v1.1-Signalvergleich die stärkste quellenübergreifende Evidenz." if clear else "Keine eindeutig führende positive quellenübergreifende SPEC-v1.1-Evidenz."});r["data_coverage"]["player"]=pc;r["data_coverage"]["signal_domain_count"]=len({x["domain"] for x in signals});r["method"].update({"architecture":"SPEC_V1_1_FULL_SIGNAL_COMPARISON","decision_engine":"NONE","probability_core":"NONE","v043_used":False,"v042_used":False,"fallback":"NONE","player_analysis_scope":"ONLY_HOME_AND_AWAY_TARGET_PLAYERS","signal_scope":"ALL_MEANINGFUL_REGISTERED_SPEC_V1_1_FAMILIES_GROUPED"});return r
