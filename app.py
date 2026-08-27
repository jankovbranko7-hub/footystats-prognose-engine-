import math

def nkey(s): return ''.join(c.lower() for c in str(s) if c.isalnum() or c=='_')
def num(v):
    if v is None or isinstance(v,bool): return None
    if isinstance(v,(int,float)): return float(v)
    if isinstance(v,str):
        try: return float(v.strip().replace(',','.').replace('%',''))
        except: return None
    return None

def values(obj, aliases):
    wanted={nkey(x) for x in aliases}; out=[]
    def walk(x):
        if isinstance(x,dict):
            for k,v in x.items():
                if nkey(k) in wanted: out.append(v)
                walk(v)
        elif isinstance(x,list):
            for y in x: walk(y)
    walk(obj); return out

def first(obj, aliases):
    for v in values(obj,aliases):
        if v not in (None,'',[],{}): return v
    return None

def firstnum(obj, aliases):
    for v in values(obj,aliases):
        x=num(v)
        if x is not None: return x
    return None

def dicts(obj):
    if isinstance(obj,dict):
        yield obj
        for v in obj.values(): yield from dicts(v)
    elif isinstance(obj,list):
        for v in obj: yield from dicts(v)

def match_obj(data):
    for d in dicts(data):
        ks={nkey(k) for k in d}
        if ('homeid' in ks or 'home_id' in ks) and ('awayid' in ks or 'away_id' in ks): return d
    return data if isinstance(data,dict) else None

def team_obj(data, tid):
    for d in dicts(data):
        x=None
        for k,v in d.items():
            if nkey(k) in {'id','teamid','team_id'}: x=num(v); break
        if x is not None and int(x)==int(tid):
            ks={nkey(k) for k in d}
            if 'stats' in ks or 'competition_id' in ks or 'competitionid' in ks or 'name' in ks: return d
    return None

def pager(data):
    p=first(data,['pager'])
    if not isinstance(p,dict): return {}
    return {
      'page': int(firstnum(p,['current_page','page']) or 0) or None,
      'max_page': int(firstnum(p,['max_page','last_page']) or 0) or None,
      'per_page': int(firstnum(p,['results_per_page','per_page']) or 0) or None,
      'total_results': int(firstnum(p,['total_results','total']) or 0) or None,
    }

def mf(data):
    m=match_obj(data) or {}
    spec={
      'match_id':['id','match_id'],'home_id':['homeID','home_id'],'away_id':['awayID','away_id'],
      'home_name':['home_name','homeName'],'away_name':['away_name','awayName'],
      'competition_id':['competition_id','competitionID'],'season':['season'],'status':['status'],'date':['date'],
      'home_prematch_xg':['team_a_xg_prematch'],'away_prematch_xg':['team_b_xg_prematch'],
      'total_prematch_xg':['total_xg_prematch'],'btts_potential':['btts_potential'],
      'o25_potential':['o25_potential','over25_potential'],'u25_potential':['u25_potential','under25_potential'],
      'pre_match_home_ppg':['pre_match_home_ppg'],'pre_match_away_ppg':['pre_match_away_ppg']
    }
    out={}
    for k,a in spec.items():
        out[k]=first(m,a) if k in {'home_name','away_name','season','status','date'} else firstnum(m,a)
    for k in ['match_id','home_id','away_id','competition_id']:
        if out.get(k) is not None: out[k]=int(out[k])
    return out

def aliases(metric, split):
    M={
      'matches':[f'seasonMatchesPlayed_{split}'],'ppg':[f'seasonPPG_{split}'],
      'gf':[f'seasonScoredAVG_{split}',f'seasonGoalsAVG_{split}',f'scoredAVG_{split}'],
      'ga':[f'seasonConcededAVG_{split}',f'concededAVG_{split}'],
      'xg':[f'xg_for_avg_{split}'],'xga':[f'xg_against_avg_{split}'],
      'btts':[f'seasonBTTSPercentage_{split}'],'o25':[f'seasonOver25Percentage_{split}'],
      'u25':[f'seasonUnder25Percentage_{split}'],'cs':[f'seasonCSPercentage_{split}'],
      'fts':[f'seasonFTSPercentage_{split}'],'shots':[f'shotsAVG_{split}'],
      'sot':[f'shotsOnTargetAVG_{split}'],'win':[f'winPercentage_{split}'],
    }
    return M[metric]

def tnum(team, metric, split):
    x=firstnum(team,aliases(metric,split))
    if x is not None: return x
    n=firstnum(team,aliases('matches',split))
    if not n: return None
    if metric=='gf':
        a=[f'seasonGoalsTotal_{split}',f'seasonGoals_{split}']
        if split=='overall': a+=['seasonGoals_overall']
        t=firstnum(team,a); return t/n if t is not None else None
    if metric=='ga':
        a=[f'seasonConcededTotal_{split}',f'seasonConceded_{split}']
        if split=='overall': a+=['seasonConceded_overall']
        if split=='home': a+=['seasonConcededNum_home']
        if split=='away': a+=['seasonConcededNum_away']
        t=firstnum(team,a); return t/n if t is not None else None
    return None

def profile(team, venue):
    return {s:{m:tnum(team,m,s) for m in ['matches','ppg','gf','ga','xg','xga','btts','o25','u25','cs','fts','shots','sot','win']}
            for s in ['overall',venue]}

def wmean(items):
    v=[(x,w) for x,w in items if x is not None and w>0]
    return sum(x*w for x,w in v)/sum(w for _,w in v) if v else None
def vw(n): return 0 if not n or n<=0 else n/(n+6)
def ow(n): return 0 if not n or n<=0 else .45+.45*n/(n+10)
def blend(p,m,s,scale=1): return wmean([(p[s].get(m),vw(p[s].get('matches'))*scale),(p['overall'].get(m),ow(p['overall'].get('matches')))])
def pct(x):
    if x is None:return None
    return max(0,min(1,x/100 if x>1 else x))
def sclass(n):
    if n is None:return 'NICHT ERMITTELBAR'
    if n<=0:return 'FEHLEND'
    if n<=3:return 'SEHR NIEDRIG'
    if n<=7:return 'NIEDRIG'
    if n<=11:return 'MITTEL'
    return 'BRAUCHBAR'
def sample(h,a,ho,ao):
    if h is None or a is None:return 'NIEDRIG'
    if min(h,a)>=12 and min(ho or 0,ao or 0)>=20:return 'HOCH'
    if min(h,a)>=4 and min(ho or 0,ao or 0)>=8:return 'MITTEL'
    return 'NIEDRIG'
def shotadj(sh,sot):
    z=0
    if sh is not None:z+=max(-.05,min(.05,(sh-12)*.006))
    if sot is not None:z+=max(-.05,min(.05,(sot-4)*.015))
    return max(-.08,min(.08,z))

def lambdas(h,a,m,venue_scale=1,prematch=True,results=True):
    hxg,hxga,axg,axga=[blend(*x) for x in [(h,'xg','home'),(h,'xga','home'),(a,'xg','away'),(a,'xga','away')]]
    hgf,hga,agf,aga=[blend(*x) for x in [(h,'gf','home'),(h,'ga','home'),(a,'gf','away'),(a,'ga','away')]]
    ha=hxg if hxg is not None else hgf; hd=hxga if hxga is not None else hga
    aa=axg if axg is not None else agf; ad=axga if axga is not None else aga
    hp=m.get('home_prematch_xg') if prematch else None; ap=m.get('away_prematch_xg') if prematch else None
    hpw=.1 if hp is not None and ha is not None and abs(hp-ha)<=.03 else (.35 if hp is not None else 0)
    apw=.1 if ap is not None and aa is not None and abs(ap-aa)<=.03 else (.35 if ap is not None else 0)
    hl=wmean([(ha,1),(ad,1),(hp,hpw)]); al=wmean([(aa,1),(hd,1),(ap,apw)])
    if hl is None or al is None: raise ValueError('Nicht genügend xG/xGA- oder GF/GA-Daten für beide Teams.')
    if results:
        rh=wmean([(hgf,.5),(aga,.5)]); ra=wmean([(agf,.5),(hga,.5)])
        if rh is not None:hl=.82*hl+.18*rh
        if ra is not None:al=.82*al+.18*ra
    hs,hst=blend(h,'shots','home',venue_scale),blend(h,'sot','home',venue_scale)
    aas,ast=blend(a,'shots','away',venue_scale),blend(a,'sot','away',venue_scale)
    hl*=1+shotadj(hs,hst); al*=1+shotadj(aas,ast)
    hppg,appg=blend(h,'ppg','home',venue_scale),blend(a,'ppg','away',venue_scale)
    if hppg is not None and appg is not None:
        d=max(-1.5,min(1.5,hppg-appg));hl*=1+d*.025;al*=1-d*.015
    return max(.18,min(3.8,hl)),max(.18,min(3.8,al))

def poisson(hl,al,cap=10):
    ph=[math.exp(-hl)*hl**i/math.factorial(i) for i in range(cap+1)]
    pa=[math.exp(-al)*al**j/math.factorial(j) for j in range(cap+1)]
    mass=sum(ph)*sum(pa); hw=dr=aw=btts=o25=0
    for i,x in enumerate(ph):
      for j,y in enumerate(pa):
        q=x*y/mass
        if i>j:hw+=q
        elif i==j:dr+=q
        else:aw+=q
        if i and j:btts+=q
        if i+j>=3:o25+=q
    return {'home_win':hw,'draw':dr,'away_win':aw,'btts_yes':btts,'btts_no':1-btts,'over_2_5':o25,'under_2_5':1-o25}

def calibrate(p,m,h,a):
    out=dict(p); hn=h['home'].get('matches') or 0; an=a['away'].get('matches') or 0
    w=.05+.10*min(1,min(hn,an)/10)
    o=pct(m.get('o25_potential')); u=pct(m.get('u25_potential'))
    if o is None and u is not None:o=1-u
    if o is not None:
        o=.5+(o-.5)*.72; out['over_2_5']=(1-w)*p['over_2_5']+w*o;out['under_2_5']=1-out['over_2_5']
    b=pct(m.get('btts_potential'))
    if b is not None:
        b=.5+(b-.5)*.72;out['btts_yes']=(1-w)*p['btts_yes']+w*b;out['btts_no']=1-out['btts_yes']
    return out

def resultprob(h,a,market):
    def bp(p,m,s):
        x=blend(p,m,s);return pct(x) if m in {'o25','u25','btts','win'} else x
    if market in {'over_2_5','under_2_5'}:
        q='o25' if market=='over_2_5' else 'u25';return wmean([(bp(h,q,'home'),1),(bp(a,q,'away'),1)])
    if market in {'btts_yes','btts_no'}:
        x=wmean([(bp(h,'btts','home'),1),(bp(a,'btts','away'),1)])
        return None if x is None else (x if market=='btts_yes' else 1-x)
    if market=='home_win':return bp(h,'win','home')
    if market=='away_win':return bp(a,'win','away')
def rvu(h,a,market,mp):
    rp=resultprob(h,a,market)
    if rp is None:return 'TEILWEISE KONSISTENT'
    if (rp>=.5)==(mp>=.5):return 'KONSISTENT' if abs(rp-mp)<=.08 else 'TEILWEISE KONSISTENT'
    if abs(rp-.5)>=.12 and abs(mp-.5)>=.12:return 'STARK WIDERSPRÜCHLICH'
    return 'TEILWEISE WIDERSPRÜCHLICH'
def edge(a,b):
    d=a-b
    return 'KLAR' if d>=.05 else ('KNAPP' if d>=.02 else 'NICHT VORHANDEN')

LABEL={'home_win':'Sieg Heim','away_win':'Sieg Auswärts','btts_yes':'BTTS Yes','btts_no':'BTTS No','over_2_5':'Over 2,5','under_2_5':'Under 2,5'}

def audit(match,league):
    m=mf(match); errs=[]; p=pager(league)
    if m.get('home_id') is None or m.get('away_id') is None:errs.append('Home-ID oder Away-ID fehlt.')
    ht=team_obj(league,m.get('home_id')) if m.get('home_id') is not None else None
    at=team_obj(league,m.get('away_id')) if m.get('away_id') is not None else None
    if ht is None:
        msg=f"Heimteam-ID {m.get('home_id')} fehlt in LeagueDaten."
        if p.get('max_page') and p.get('page') and p['page']<p['max_page']:msg+=f" Paginierung erkannt: Seite {p['page']} von {p['max_page']}."
        errs.append(msg)
    if at is None:
        msg=f"Auswärtsteam-ID {m.get('away_id')} fehlt in LeagueDaten."
        if p.get('max_page') and p.get('page') and p['page']<p['max_page']:msg+=f" Paginierung erkannt: Seite {p['page']} von {p['max_page']}."
        errs.append(msg)
    return {'valid':not errs,'errors':errs,'match':m,'pager':p,'home_team':ht,'away_team':at}

def _positive_sample(v):
    try:return float(v or 0) if float(v or 0)>0 else 0.0
    except:return 0.0

def _core_signal(p,split):
    b=(p.get(split) or {})
    if _positive_sample(b.get('matches'))<=0:return False
    for metric in ('ppg','gf','ga','xg','xga'):
        x=b.get(metric)
        try:
            if x is not None and float(x)>0:return True
        except:pass
    return False

def _positive_input(v):
    try:return float(v or 0)>0
    except:return False

def insufficient_data_report(m,h,aw):
    hn=_positive_sample((h.get('home') or {}).get('matches'))
    an=_positive_sample((aw.get('away') or {}).get('matches'))
    ho=_positive_sample((h.get('overall') or {}).get('matches'))
    ao=_positive_sample((aw.get('overall') or {}).get('matches'))

    home_venue_ok=hn>0 and _core_signal(h,'home')
    away_venue_ok=an>0 and _core_signal(aw,'away')

    home_prematch_ok=_positive_input(m.get('home_prematch_xg')) or _positive_input(m.get('pre_match_home_ppg'))
    away_prematch_ok=_positive_input(m.get('away_prematch_xg')) or _positive_input(m.get('pre_match_away_ppg'))

    # Overall-Daten dürfen den fehlenden Heim-/Auswärtssplit erst ab einer
    # kleinen Mindeststichprobe ersetzen. Ein einzelnes Saisonspiel reicht nicht.
    home_overall_ok=ho>=4 and _core_signal(h,'overall')
    away_overall_ok=ao>=4 and _core_signal(aw,'overall')

    home_ok=home_venue_ok or home_prematch_ok or home_overall_ok
    away_ok=away_venue_ok or away_prematch_ok or away_overall_ok

    reasons=[]
    if not home_ok:
        reasons.append('Heimteam: kein belastbarer Heim-Split, kein positives Prematch-Signal und Overall-Stichprobe unter 4 bzw. ohne Kernsignal.')
    if not away_ok:
        reasons.append('Auswärtsteam: kein belastbarer Auswärts-Split, kein positives Prematch-Signal und Overall-Stichprobe unter 4 bzw. ohne Kernsignal.')

    return {
      'sufficient':home_ok and away_ok,
      'reasons':reasons,
      'samples':{'home_overall':ho,'home_venue':hn,'away_overall':ao,'away_venue':an},
      'evidence':{
        'home':{'venue_ok':home_venue_ok,'prematch_ok':home_prematch_ok,'overall_fallback_ok':home_overall_ok},
        'away':{'venue_ok':away_venue_ok,'prematch_ok':away_prematch_ok,'overall_fallback_ok':away_overall_ok}
      },
      'prematch_snapshot':{
        'home_prematch_xg':m.get('home_prematch_xg'),
        'away_prematch_xg':m.get('away_prematch_xg'),
        'pre_match_home_ppg':m.get('pre_match_home_ppg'),
        'pre_match_away_ppg':m.get('pre_match_away_ppg'),
        'btts_potential':m.get('btts_potential'),
        'o25_potential':m.get('o25_potential'),
        'u25_potential':m.get('u25_potential')
      }
    }

def predict(match,league):
    a=audit(match,league)
    if not a['valid']:return {'ok':False,'phase':'DATA_AUDIT_FAILED','audit':{k:v for k,v in a.items() if k not in {'home_team','away_team'}},'decision':'ANALYSE NICHT MÖGLICH'}
    m=a['match'];h=profile(a['home_team'],'home');aw=profile(a['away_team'],'away')
    report=insufficient_data_report(m,h,aw)
    if not report['sufficient']:
        return {'ok':False,'model_version':'0.2.2','phase':'INSUFFICIENT_DATA','decision':'ANALYSE NICHT MÖGLICH','error':'Zu wenig belastbare historische Teamdaten für eine seriöse Marktprognose. Placeholder-Nullwerte werden nicht als echte Leistung interpretiert.','audit':{'valid':True,'errors':[],'match':m,'pager':a['pager']},'samples':report['samples'],'diagnostics':{'data_quality':'NIEDRIG','sample_security':'NIEDRIG','result_vs_underlying':'NICHT PRÜFBAR','relative_edge':'NICHT PRÜFBAR','counterargument':'UNZUREICHENDE DATENGRUNDLAGE','single_point_of_failure':True,'robustness_status':'NICHT PRÜFBAR'},'insufficient_data':report,'notes':['Keine Wahrscheinlichkeiten berechnet.','Keine künstlichen Mindest-xG-Werte als Prognose verwendet.','Odds werden vollständig ignoriert.']}
    hn,an=h['home']['matches'],aw['away']['matches'];ho,ao=h['overall']['matches'],aw['overall']['matches']
    ss=sample(hn,an,ho,ao); quality='HOCH'
    if not hn or not an:quality='MITTEL'
    if sum(x is not None for x in [h['overall']['xg'],h['overall']['xga'],aw['overall']['xg'],aw['overall']['xga']])<3:quality='MITTEL'
    try:hl,al=lambdas(h,aw,m)
    except ValueError as e:return {'ok':False,'phase':'MODEL_INPUT_FAILED','audit':{'valid':True,'errors':[str(e)],'match':m},'decision':'ANALYSE NICHT MÖGLICH'}
    raw=poisson(hl,al);p=calibrate(raw,m,h,aw)
    ih,ia=lambdas(h,aw,m,prematch=False);infl=poisson(ih,ia)
    fh,fa=lambdas(h,aw,m,venue_scale=.5,results=False);frag=poisson(fh,fa)
    allowed=['home_win','away_win','btts_yes','btts_no','over_2_5','under_2_5']
    rank=sorted([(x,p[x]) for x in allowed],key=lambda z:z[1],reverse=True); top,tp=rank[0]; second,sp=rank[1]
    rv=rvu(h,aw,top,raw[top]); ed=edge(tp,sp); i,f=infl[top],frag[top]
    flip=(i>=.5)!=(tp>=.5) or (f>=.5)!=(tp>=.5); spof=flip or min(i,f)<.55
    if tp>=.65:rob='BESTANDEN' if min(i,f)>=.63 and not spof and rv in {'KONSISTENT','TEILWEISE KONSISTENT'} else ('EINGESCHRÄNKT' if min(i,f)>=.60 and not flip else 'NICHT BESTANDEN')
    else:rob='NICHT FÜR SPIELEN — INSTABIL' if spof else ('NICHT FÜR SPIELEN — EINGESCHRÄNKT' if min(i,f)<.60 or rv=='TEILWEISE WIDERSPRÜCHLICH' else 'NICHT FÜR SPIELEN — STABIL')
    counter='DOMINANTES ZENTRALES GEGENARGUMENT' if rv=='STARK WIDERSPRÜCHLICH' else ('STARKES ZENTRALES GEGENARGUMENT' if rv=='TEILWEISE WIDERSPRÜCHLICH' else ('RELEVANTES ZENTRALES GEGENARGUMENT' if ss=='NIEDRIG' or quality=='NIEDRIG' else 'KEIN RELEVANTES ZENTRALES GEGENARGUMENT'))
    dec='AUSLASSEN' if tp<.60 or rv=='STARK WIDERSPRÜCHLICH' else 'BEOBACHTEN'
    if tp>=.65 and quality in {'HOCH','MITTEL'} and ss!='NIEDRIG' and ed=='KLAR' and rv in {'KONSISTENT','TEILWEISE KONSISTENT'} and not spof and rob=='BESTANDEN':dec='SPIELEN'
    hxg,hxga,axg,axga=h['home']['xg'],h['home']['xga'],aw['away']['xg'],aw['away']['xga'];mx=None
    if None not in (hxg,hxga,axg,axga):
        hg=(hxg+axga)/2;ag=(axg+hxga)/2;mx={'home_goal_threat':hg,'away_goal_threat':ag,'total':hg+ag}
    return {'ok':True,'model_version':'0.2.2','deterministic':True,'audit':{'valid':True,'errors':[],'match':m,'pager':a['pager']},'samples':{'home_venue':hn,'home_class':sclass(hn),'away_venue':an,'away_class':sclass(an),'security':ss},'expected_goals':{'home':hl,'away':al,'total':hl+al,'matchup_xg_diagnostic':mx},'probabilities':p,'markets':[{'rank':i+1,'key':x,'label':LABEL[x],'probability_pct':round(q*100,1)} for i,(x,q) in enumerate(rank)],'strongest_market':{'key':top,'label':LABEL[top],'probability_pct':round(tp*100,1)},'second_market':{'key':second,'label':LABEL[second],'probability_pct':round(sp*100,1)},'diagnostics':{'data_quality':quality,'sample_security':ss,'result_vs_underlying':rv,'relative_edge':ed,'counterargument':counter,'single_point_of_failure':spof,'influence_stress_probability_pct':round(i*100,1),'fragility_stress_probability_pct':round(f*100,1),'robustness_status':rob,'insufficient_data_gate':'BESTANDEN'},'decision':dec,'notes':['Odds werden vollständig ignoriert.','Gleiche Inputs liefern gleiche Outputs.','Version 0.2.2 mit strenger INSUFFICIENT_DATA-Sperre.']}

# ---- Web/API layer v0.2 ----
import json
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, File, UploadFile, HTTPException, Form
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel

app = FastAPI(title="FootyStats Prognose Engine", version="0.2.3")

class Payload(BaseModel):
    matchData: Dict[str, Any]
    leagueData: Dict[str, Any]
    formData: Optional[Dict[str, Any]] = None
    tableData: Optional[Dict[str, Any]] = None
    playerData: Optional[Dict[str, Any]] = None


def _source_kind(filename: str) -> Optional[str]:
    """Classify a V2 export by its filename without inspecting arbitrary JSON."""
    name = (filename or "").lower().replace(" ", "")
    for kind, marker in (("match", "matchdaten"), ("league", "leaguedaten"),
                         ("form", "formdaten"), ("table", "tabledaten"),
                         ("player", "playerdaten")):
        if marker in name:
            return kind
    return None


def _same_team_id(value: Any, team_id: Any) -> bool:
    value_num, team_num = num(value), num(team_id)
    return value_num is not None and team_num is not None and int(value_num) == int(team_num)


def _table_team_summary(table_data: Any, team_id: Any, venue: str) -> Dict[str, Any]:
    table_key = "all_matches_table_home" if venue == "home" else "all_matches_table_away"
    rows = ((table_data or {}).get("data") or {}).get(table_key) or []
    row = next((item for item in rows if isinstance(item, dict) and _same_team_id(item.get("id"), team_id)), None)
    if not row:
        return {"available": False, "venue": venue}
    matches = num(row.get("matchesPlayed"))
    points = num(row.get("points"))
    goals_for = num(row.get("seasonGoals"))
    goals_against = num(row.get("seasonConceded"))
    per_match = lambda value: round(value / matches, 3) if value is not None and matches and matches > 0 else None
    return {
        "available": True,
        "venue": venue,
        "matches": int(matches) if matches is not None else None,
        "position": int(num(row.get("position"))) if num(row.get("position")) is not None else None,
        "ppg": per_match(points),
        "goals_for_per_match": per_match(goals_for),
        "goals_against_per_match": per_match(goals_against),
    }


def _form_records(form_data: Any) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    for page in ((form_data or {}).get("teams") or []):
        if isinstance(page, dict):
            records.extend(item for item in (page.get("data") or []) if isinstance(item, dict))
    return records


def _form_team_summary(form_data: Any, team_id: Any) -> Dict[str, Any]:
    candidates = [item for item in _form_records(form_data) if _same_team_id(item.get("id"), team_id)]
    if not candidates:
        return {"available": False}
    chosen = max(candidates, key=lambda item: num(item.get("last_x_match_num")) or 0)
    stats = chosen.get("stats") or {}
    sample = num(chosen.get("last_x_match_num")) or num(stats.get("last_x"))
    return {
        "available": True,
        "sample": int(sample) if sample is not None else None,
        "ppg": num(stats.get("seasonPPG_overall")),
        "shots_on_target_avg": num(stats.get("shotsOnTargetAVG_overall")),
        "btts_pct": num(stats.get("seasonBTTSPercentage_overall")),
    }


def _player_team_summary(player_data: Any, team_id: Any) -> Dict[str, Any]:
    pages = ((player_data or {}).get("pages") or [])
    players: List[Dict[str, Any]] = []
    for page in pages:
        if isinstance(page, dict):
            players.extend(item for item in (page.get("data") or []) if isinstance(item, dict) and _same_team_id(item.get("club_team_id"), team_id))
    minutes = sum(num(player.get("minutes_played_overall")) or 0 for player in players)
    goals = sum(num(player.get("goals_overall")) or 0 for player in players)
    assists = sum(num(player.get("assists_overall")) or 0 for player in players)
    return {
        "available": bool(players),
        "players_found": len(players),
        "minutes": round(minutes, 1),
        "goals_per_90": round(goals * 90 / minutes, 3) if minutes > 0 else None,
        "assists_per_90": round(assists * 90 / minutes, 3) if minutes > 0 else None,
    }


def supplemental_report(match_data: Any, form_data: Any = None, table_data: Any = None, player_data: Any = None) -> Dict[str, Any]:
    """Expose V2-only inputs with coverage checks; do not invent unbacktested score weights."""
    match = mf(match_data)
    home_id, away_id = match.get("home_id"), match.get("away_id")
    form = {"home": _form_team_summary(form_data, home_id), "away": _form_team_summary(form_data, away_id)}
    table = {"home": _table_team_summary(table_data, home_id, "home"), "away": _table_team_summary(table_data, away_id, "away")}
    player = {"home": _player_team_summary(player_data, home_id), "away": _player_team_summary(player_data, away_id)}
    return {
        "received": {"form": form_data is not None, "table": table_data is not None, "player": player_data is not None},
        "coverage": {
            "form": {**form, "usable_both": form["home"]["available"] and form["away"]["available"]},
            "table": {**table, "usable_both": table["home"]["available"] and table["away"]["available"]},
            "player": {**player, "usable_both": player["home"]["available"] and player["away"]["available"]},
        },
        "model_use": {
            "table": "Explizite Team-/Venue-Prüfung und Diagnose; Score-Gewichte erst nach zeitbasiertem Backtest.",
            "form": "Nur bei Daten für beide Teams als vollständig markiert; unvollständige Form wird nicht einseitig gewichtet.",
            "player": "Kader-Saisonwerte werden geprüft, aber ohne bestätigte Aufstellung nicht als Match-Score gewichtet.",
        },
    }


def _attach_supplemental(result: Dict[str, Any], report: Dict[str, Any], source_files: Dict[str, str]) -> Dict[str, Any]:
    result = dict(result)
    diagnostics = dict(result.get("diagnostics") or {})
    diagnostics["supplemental_inputs"] = report
    result["diagnostics"] = diagnostics
    result["input_sources"] = source_files
    result["model_version"] = "0.2.3"
    return result


def _is_match_data(data: Any, filename: str = "") -> bool:
    name = (filename or "").lower()
    if "matchdaten" in name:
        return True
    m = mf(data)
    return bool(m.get("match_id") is not None and m.get("home_id") is not None and m.get("away_id") is not None and m.get("competition_id") is not None)


def _league_candidate_score(data: Any, filename: str, match_fields: Dict[str, Any]) -> Dict[str, Any]:
    home_id = match_fields.get("home_id"); away_id = match_fields.get("away_id"); competition_id = match_fields.get("competition_id")
    home_found = team_obj(data, home_id) is not None if home_id is not None else False
    away_found = team_obj(data, away_id) is not None if away_id is not None else False
    score = 0; reasons = []; lname = (filename or "").lower()
    if "leaguedaten" in lname: score += 5; reasons.append("Dateiname=LeagueDaten")
    if competition_id is not None and str(int(competition_id)) in lname: score += 10; reasons.append("Season/Competition-ID im Dateinamen")
    if home_found: score += 40; reasons.append("Heimteam-ID gefunden")
    if away_found: score += 40; reasons.append("Auswärtsteam-ID gefunden")
    if home_found and away_found: score += 100; reasons.append("beide Team-IDs gefunden")
    return {"score": score,"home_found": home_found,"away_found": away_found,"pager": pager(data),"reasons": reasons}


def select_pair(parsed_files: List[Dict[str, Any]]) -> Dict[str, Any]:
    by_kind: Dict[str, List[Dict[str, Any]]] = {kind: [] for kind in ("match", "league", "form", "table", "player")}
    for item in parsed_files:
        kind = _source_kind(item["name"])
        if kind:
            by_kind[kind].append(item)
    duplicate_kinds = [kind for kind, items in by_kind.items() if len(items) > 1]
    if duplicate_kinds:
        return {"ok": False, "decision": "ANALYSE NICHT MÖGLICH", "phase": "PAIRING_FAILED", "error": "Mehrere V2-Dateien desselben Typs erkannt.", "duplicate_types": duplicate_kinds}
    match_candidates = by_kind["match"] or [x for x in parsed_files if _is_match_data(x["data"], x["name"])]
    if len(match_candidates) == 0:return {"ok":False,"decision":"ANALYSE NICHT MÖGLICH","phase":"PAIRING_FAILED","error":"Keine MatchDaten-Datei im ausgewählten Paket erkannt.","files":[x["name"] for x in parsed_files]}
    if len(match_candidates) > 1:return {"ok":False,"decision":"ANALYSE NICHT MÖGLICH","phase":"PAIRING_FAILED","error":"Mehrere MatchDaten-Dateien erkannt. Bitte genau einen Match-Unterordner auswählen.","match_files":[x["name"] for x in match_candidates]}
    match_file=match_candidates[0]; match_fields=mf(match_file["data"])
    # V2 filenames are authoritative. This prevents Form/Table/Player JSON from being
    # misclassified as league data merely because it also contains a team identifier.
    league_candidates = by_kind["league"] or [x for x in parsed_files if x is not match_file and _source_kind(x["name"]) is None]
    if not league_candidates:return {"ok":False,"decision":"ANALYSE NICHT MÖGLICH","phase":"PAIRING_FAILED","error":"Keine LeagueDaten-Datei im ausgewählten Paket gefunden.","match_file":match_file["name"]}
    scored=[]
    for item in league_candidates:
        info=_league_candidate_score(item["data"],item["name"],match_fields);scored.append({**item,**info})
    scored.sort(key=lambda x:x["score"],reverse=True);best=scored[0]
    if not (best["home_found"] and best["away_found"]):return {"ok":False,"decision":"ANALYSE NICHT MÖGLICH","phase":"PAIRING_FAILED","error":"Keine LeagueDaten-Datei enthält beide Teams dieses Matches.","match_file":match_file["name"],"match":match_fields,"checked_league_files":[{"name":x["name"],"home_found":x["home_found"],"away_found":x["away_found"],"pager":x["pager"],"score":x["score"]} for x in scored]}
    source_files = {kind: items[0]["name"] for kind, items in by_kind.items() if items}
    supplemental_data = {kind: items[0]["data"] for kind, items in by_kind.items() if kind in {"form", "table", "player"} and items}
    return {"ok":True,"match_file":match_file["name"],"league_file":best["name"],"match_data":match_file["data"],"league_data":best["data"],"supplemental_data":supplemental_data,"source_files":source_files,"pairing":{"match_id":match_fields.get("match_id"),"competition_id":match_fields.get("competition_id"),"home_id":match_fields.get("home_id"),"away_id":match_fields.get("away_id"),"league_score":best["score"],"league_reasons":best["reasons"]}}

INDEX_HTML = r'''<!doctype html><html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>FootyStats Prognose Engine</title><style>body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:#f3f4f6;margin:0;color:#111827}.w{max-width:900px;margin:auto;padding:18px}.c{background:#fff;border-radius:15px;padding:17px;margin:12px 0;box-shadow:0 1px 5px #0001}.g{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:9px}.m{border:1px solid #e5e7eb;border-radius:11px;padding:11px}.b{font-size:1.2rem;font-weight:700}.s{font-size:.85rem;color:#6b7280}.ok{color:#047857}.bad{color:#b91c1c}button{width:100%;padding:13px;border:0;border-radius:11px;background:#111827;color:#fff;font-weight:700;font-size:1rem}input{width:100%;margin:7px 0 14px}table{width:100%;border-collapse:collapse}td,th{padding:8px;border-bottom:1px solid #eee;text-align:left}pre{white-space:pre-wrap;word-break:break-word;font-size:.75rem}.sep{border-top:1px solid #e5e7eb;margin:18px 0}</style></head><body><div class="w"><div class="c"><h2>FootyStats Prognose Engine v0.2.3</h2><div class="s">Ein Match-Ordner = ein Analyse-Paket · keine Odds · keine externen Daten · INSUFFICIENT_DATA-Sperre aktiv</div><h3>Match-Ordner auswählen</h3><p class="s">Empfohlen: genau MatchDaten, LeagueDaten, FormDaten, TableDaten und PlayerDaten eines Matches auswählen.</p><input id="folderFiles" type="file" webkitdirectory directory multiple accept=".json,application/json"><div class="sep"></div><h3>Fallback: JSON-Dateien gemeinsam auswählen</h3><p class="s">Falls die Ordnerauswahl am iPhone nicht angeboten wird, wähle hier alle fünf JSON-Dateien gleichzeitig aus.</p><input id="bundleFiles" type="file" multiple accept=".json,application/json"><button id="go">Analyse starten</button></div><div id="out"></div></div><script>function chosenFiles(){const folder=[...document.getElementById('folderFiles').files];if(folder.length)return folder;return[...document.getElementById('bundleFiles').files];}document.getElementById('go').onclick=async()=>{const files=chosenFiles(),out=document.getElementById('out');if(files.length<2){out.innerHTML='<div class="c bad"><b>Mindestens zwei JSON-Dateien nötig.</b></div>';return}out.innerHTML='<div class="c">Paket wird geprüft und analysiert…</div>';try{const form=new FormData();files.forEach(f=>form.append('files',f,f.webkitRelativePath||f.name));const r=await fetch('/api/predict-bundle',{method:'POST',body:form});const d=await r.json();if(!d.ok){out.innerHTML='<div class="c"><h3 class="bad">Analyse nicht möglich</h3><pre>'+JSON.stringify(d,null,2)+'</pre></div>';return}const g=d.diagnostics,x=d.expected_goals;const rows=d.markets.map(z=>`<tr><td>${z.rank}</td><td>${z.label}</td><td><b>${z.probability_pct}%</b></td></tr>`).join('');const pairing=d.pairing||{},sources=d.input_sources||{};const sourceList=Object.entries(sources).map(([kind,file])=>`${kind}: ${file}`).join('<br>');out.innerHTML=`<div class="c"><div class="ok"><b>Dateien automatisch zugeordnet</b></div><p class="s">${sourceList||`Match: ${pairing.match_file||''}<br>League: ${pairing.league_file||''}`}</p></div><div class="c"><h3>Kurzentscheidung</h3><div class="g"><div class="m"><div class="s">Bester Markt</div><div class="b">${d.strongest_market.label}</div></div><div class="m"><div class="s">Wahrscheinlichkeit</div><div class="b">${d.strongest_market.probability_pct}%</div></div><div class="m"><div class="s">Entscheidung</div><div class="b">${d.decision}</div></div><div class="m"><div class="s">Result vs Underlying</div><b>${g.result_vs_underlying}</b></div><div class="m"><div class="s">Robustheit</div><b>${g.robustness_status}</b></div><div class="m"><div class="s">Relative Edge</div><b>${g.relative_edge}</b></div><div class="m"><div class="s">Datenqualität</div><b>${g.data_quality}</b></div><div class="m"><div class="s">Stichprobe</div><b>${g.sample_security}</b></div></div></div><div class="c"><h3>Alle Märkte</h3><table><tr><th>Rang</th><th>Markt</th><th>Modell</th></tr>${rows}</table></div><div class="c"><h3>Goal Model</h3><p>Heim: <b>${x.home.toFixed(2)}</b> · Auswärts: <b>${x.away.toFixed(2)}</b> · Gesamt: <b>${x.total.toFixed(2)}</b></p><p>Influence Stress: <b>${g.influence_stress_probability_pct}%</b> · Fragility Stress: <b>${g.fragility_stress_probability_pct}%</b></p><p>Gegenargument: <b>${g.counterargument}</b></p></div><div class="c"><details><summary>Technische Diagnose</summary><pre>${JSON.stringify(d,null,2)}</pre></details></div>`;}catch(e){out.innerHTML='<div class="c bad">Fehler: '+String(e)+'</div>'}}</script></body></html>'''

@app.get("/",response_class=HTMLResponse)
def index():return INDEX_HTML
@app.get("/api/health")
def health():return {"ok":True,"version":"0.2.3"}
@app.post("/api/predict")
def predict_json(payload:Payload):
    report = supplemental_report(payload.matchData, payload.formData, payload.tableData, payload.playerData)
    return _attach_supplemental(predict(payload.matchData, payload.leagueData), report, {})
@app.post("/api/predict-files")
async def predict_files(match_file:UploadFile=File(...),league_file:UploadFile=File(...)):
    try:match_data=json.loads((await match_file.read()).decode("utf-8"));league_data=json.loads((await league_file.read()).decode("utf-8"))
    except Exception as exc:raise HTTPException(status_code=400,detail=f"Ungültige JSON-Datei: {exc}")
    return predict(match_data,league_data)
@app.post("/api/predict-bundle")
async def predict_bundle(files:List[UploadFile]=File(...)):
    parsed=[];errors=[]
    for f in files:
        name=f.filename or "unbekannt.json"
        if not name.lower().endswith(".json"):continue
        try:raw=await f.read();data=json.loads(raw.decode("utf-8"));parsed.append({"name":name,"data":data})
        except Exception as exc:errors.append({"name":name,"error":str(exc)})
    if errors:return {"ok":False,"decision":"ANALYSE NICHT MÖGLICH","phase":"FILE_READ_FAILED","error":"Mindestens eine JSON-Datei konnte nicht gelesen werden.","files":errors}
    pair=select_pair(parsed)
    if not pair.get("ok"):return pair
    extras = pair.get("supplemental_data") or {}
    report = supplemental_report(pair["match_data"], extras.get("form"), extras.get("table"), extras.get("player"))
    result = _attach_supplemental(predict(pair["match_data"], pair["league_data"]), report, pair.get("source_files") or {})
    result["pairing"] = {**pair["pairing"], "match_file": pair["match_file"], "league_file": pair["league_file"]}
    return result


# ---- Temporary HubSign helper ----
# The HubSign key is accepted only for this request, is not persisted,
# and is not included in application logs by this code.
import base64 as _b64
import uuid as _uuid
import urllib.request as _urlreq
import urllib.error as _urlerr

_PREPARED_SHORTCUT_B64 = "YnBsaXN0MDDcAAEAAgADAAQABQAGAAcACAAJAAoACwAMAA0ADgAPABQAFQAWABcC3gLyAvoC+wAWXxAkV0ZXb3JrZmxvd01pbmltdW1DbGllbnRWZXJzaW9uU3RyaW5nXxAeV0ZXb3JrZmxvd01pbmltdW1DbGllbnRWZXJzaW9uXldGV29ya2Zsb3dJY29uXxAXV0ZXb3JrZmxvd0NsaWVudFZlcnNpb25fECJXRldvcmtmbG93T3V0cHV0Q29udGVudEl0ZW1DbGFzc2VzXxAbV0ZXb3JrZmxvd0hhc091dHB1dEZhbGxiYWNrXxARV0ZXb3JrZmxvd0FjdGlvbnNfECFXRldvcmtmbG93SW5wdXRDb250ZW50SXRlbUNsYXNzZXNfEBlXRldvcmtmbG93SW1wb3J0UXVlc3Rpb25zXxAVV0ZRdWlja0FjdGlvblN1cmZhY2VzXxAPV0ZXb3JrZmxvd1R5cGVzXxAjV0ZXb3JrZmxvd0hhc1Nob3J0Y3V0SW5wdXRWYXJpYWJsZXNUMjAyNREH6dIAEAARABIAE18QGFdGV29ya2Zsb3dJY29uU3RhcnRDb2xvcl8QGVdGV29ya2Zsb3dJY29uR2x5cGhOdW1iZXISGb0D/xHwAFQ0NzExoAivEFkAGAAhACkAPgBJAFQAXABgAGYAcQB4AH4AiACYAJwAoACnAK0AtwC8AMIAxwDNANIA2ADeAOUA8QD3AP4BBwESARkBIAElATABNwE8AUIBSAFNAVcBXQFlAWsBdgF+AYIBhQGZAaUBrgG4AcYB0QHZAeIB7AHzAfgCAAIHAgsCGAIiAisCNAI/AkYCUAJZAmICbQJ0AnkCfgKDAogCjQKSApcCnAKnAq4CsgK1AsICzALV0gAZABoAGwAcXxAaV0ZXb3JrZmxvd0FjdGlvbklkZW50aWZpZXJfEBpXRldvcmtmbG93QWN0aW9uUGFyYW1ldGVyc18QG2lzLndvcmtmbG93LmFjdGlvbnMuZ2V0dGV4dNIAHQAeAB8AIFRVVUlEXxAQV0ZUZXh0QWN0aW9uVGV4dF8QJEJBRkIzNzEzLTg4NEYtNDA1Ny05ODMzLUQwNTE1MTA1OEVFNlDSABkAGgAiACNfEBdpcy53b3JrZmxvdy5hY3Rpb25zLmFza9MAJAAlAB0AJgAnAChbV0ZJbnB1dFR5cGVfEBFXRkFza0FjdGlvblByb21wdFRUZXh0XVdlbGNoZXIgVGFnID9fECRCRDM0REVFRi1BRDYxLTQyRUUtQTM0OC1BQTI0NEU2REVFRkXSABkAGgAbACrSAB0AHgArACxfECQ0RkMzQzI4Qy1ENUNELTRDNzgtOTVCRS04RTg4Mzg5OThBNkTSAC0ALgAvAD1VVmFsdWVfEBNXRlNlcmlhbGl6YXRpb25UeXBl0gAwADEAMgAzVnN0cmluZ18QEmF0dGFjaG1lbnRzQnlSYW5nZW8QVABoAHQAdABwAHMAOgAvAC8AYQBwAGkALgBmAG8AbwB0AGIAYQBsAGwALQBkAGEAdABhAC0AYQBwAGkALgBjAG8AbQAvAHQAbwBkAGEAeQBzAC0AbQBhAHQAYwBoAGUAcwA/AGQAYQB0AGUAPf/8ACYAdABpAG0AZQB6AG8AbgBlAD0ARQB1AHIAbwBwAGUALwBWAGkAZQBuAG4AYQAmAGsAZQB5AD3//NIANAA1ADYAPFd7NTQsIDF9V3s4MywgMX3TADcAOAA5ACgAOgA7Wk91dHB1dFVVSURUVHlwZVpPdXRwdXROYW1lXEFjdGlvbk91dHB1dF8QE05hY2ggRWluZ2FiZSBmcmFnZW7TADcAOAA5AB8AOgAmXxARV0ZUZXh0VG9rZW5TdHJpbmfSABkAGgA/AEBfEB9pcy53b3JrZmxvdy5hY3Rpb25zLmRvd25sb2FkdXJs0gBBAB0AQgBIVVdGVVJM0gAtAC4AQwA90gAwADEARABFYf/80QBGAEdWezAsIDF90wA3ADgAOQArADoAJl8QJDIyRDc4MDkzLTMwNUEtNDkxOS04RkEyLTA0NDkzQ0E2Njg3QtIAGQAaAEoAS18QImlzLndvcmtmbG93LmFjdGlvbnMuZ2V0dmFsdWVmb3JrZXnTAEwAHQBNAE4AUgBTV1dGSW5wdXRfEA9XRkRpY3Rpb25hcnlLZXnSAC0ALgBPAFHTADcAOAA5AEgAOgBQXkluaGFsdCBkZXIgVVJMXxAVV0ZUZXh0VG9rZW5BdHRhY2htZW50XxAkRTg2REYwQjItRjQwNy00OTMzLThBQTEtNzc4NjA2NEQyQzcyVGRhdGHSABkAGgBVAFZfEB9pcy53b3JrZmxvdy5hY3Rpb25zLnNldHZhcmlhYmxl0gBMAFcAWABbXldGVmFyaWFibGVOYW1l0gAtAC4AWQBR0wA3ADgAOQBSADoAWm4AVwD2AHIAdABlAHIAYgB1AGMAaAB3AGUAcgB0W1NwaWVsZURhdGVu0gAZABoAXQBeXxAeaXMud29ya2Zsb3cuYWN0aW9ucy5kaWN0aW9uYXJ50QAdAF9fECRGRDNEMkU3Qy04NkQ4LTQ0M0ItOUU2OS05OTc1QTgwNkI5NjfSABkAGgBVAGHSAEwAVwBiAGXSAC0ALgBjAFHTADcAOAA5AF8AOgBkagBXAPYAcgB0AGUAcgBiAHUAYwBoXCAgICBTcGllbE1hcNIAGQAaAGcAaF8QH2lzLndvcmtmbG93LmFjdGlvbnMucmVwZWF0LmVhY2jTAEwAaQBqAGsAbwBwXxASR3JvdXBpbmdJZGVudGlmaWVyXxARV0ZDb250cm9sRmxvd01vZGXSAC0ALgBsAFHSAG0AOABbAG5cVmFyaWFibGVOYW1lWFZhcmlhYmxlXxAkMzM5QTIwM0MtQTM5Ni00OEM2LUJCNkMtNTZEMDhBRjZCQ0VBEADSABkAGgBKAHLTAEwAHQBNAHMAdgB30gAtAC4AdABR0gBtADgAdQBuW1JlcGVhdCBJdGVtXxAkM0ZCRjJBQzItNjJEQy00RTA3LUJFQzYtOTU4MDkwNTU0NTUxWWhvbWVfbmFtZdIAGQAaAEoAedMATABNAB0AegB8AH3SAC0ALgB7AFHSAG0AOAB1AG5ZYXdheV9uYW1lXxAkNjFDQkIyQTMtRUZBQi00ODAzLTk1QjMtREREOUFFRTdGMTk40gAZABoAGwB/0gAdAB4AgACBXxAkMTM3MEY0ODEtMDRCNy00NUQxLUFBOEEtRjA5ODZGN0UwNkNG0gAtAC4AggA90gAwADEAgwCEZv/8ACAAdgBzACD//NIAhQBGAIYAh1Z7NSwgMX3TADcAOAA5AH0AOgBa0wA3ADgAOQB2ADoAWtIAGQAaAIkAil8QImlzLndvcmtmbG93LmFjdGlvbnMuc2V0dmFsdWVmb3JrZXnUAIsAHQCMAE0AjQCRAJIAlF8QEVdGRGljdGlvbmFyeVZhbHVlXFdGRGljdGlvbmFyedIALQAuAI4APdIAMAAxAEQAj9EARgCQ0gBtADgAdQBuXxAkRDQwOTkzNTYtMUM4OS00MEM4LTkzMTktNjFFQkVENDk0NzZB0gAtAC4AkwBR0gBtADgAZQBu0gAtAC4AlQA90gAwADEARACW0QBGAJfTADcAOAA5AIAAOgAm0gAZABoAVQCZ0gBMAFcAmgBl0gAtAC4AmwBR0wA3ADgAOQCRADoAZNIAGQAaAGcAndMAHQBpAGoAngBvAJ9fECQxMENBOUJGMS0xOEJFLTRBREItQjhEOC1FRTI2NUJEREQyOUUQAtIAGQAaAEoAodMATACiAB0AowClAKZfEBhXRkdldERpY3Rpb25hcnlWYWx1ZVR5cGXSAC0ALgCkAFHSAG0AOABlAG5YQWxsIEtleXNfECRFODQ4NUE0My1EOUJDLTQzOTEtOUZFMS05ODAwNUIxMENEQznSABkAGgCoAKlfECJpcy53b3JrZmxvdy5hY3Rpb25zLmNob29zZWZyb21saXN00gBMAB0AqgCs0gAtAC4AqwBR0wA3ADgAOQCmADoAWl8QJDc3MDFFN0FELTNERTMtNDZFMy1BNENGLUU4QjVGN0M2MkMwNNIAGQAaAEoArtMATAAdAE0ArwCxALLSAC0ALgCwAFHSAG0AOABlAG5fECQ3QTkxMzNCOS04MzVFLTRBREEtQUNCQy0yMDYzQjY2ODFDRjPSAC0ALgCzAD3SADAAMQBEALTRAEYAtdMANwA4ADkArAA6ALZvEBMAQQB1AHMAZwBlAHcA5ABoAGwAdABlAHMAIABPAGIAagBlAGsAdNIAGQAaAFUAuNIATABXALkAu9IALQAuALoAUdMANwA4ADkAsQA6AFpfEBcgICAgICAgIEdlZnVuZGVuZXNTcGllbNIAGQAaAEoAvdMATAAdAE0AvgDAAMHSAC0ALgC/AFHSAG0AOAC7AG5fECQwRDAwNkNBRC1FRkExLTRGNDMtQTQ0NC0wOEMzQUY0NzY4NEFeY29tcGV0aXRpb25faWTSABkAGgBVAMPSAEwAVwDEAMbSAC0ALgDFAFHTADcAOAA5AMAAOgBaWFNlYXNvbklE0gAZABoASgDI0wBMAB0ATQDJAMsAzNIALQAuAMoAUdIAbQA4ALsAbl8QJDU3MkE2NTg0LTAwMUItNEExNi1BMDk1LUQ2MkIzQTBDQTc4M1JpZNIAGQAaAFUAztIATABXAM8A0dIALQAuANAAUdMANwA4ADkAywA6AFpXTWF0Y2hJRNIAGQAaAEoA09MATAAdAE0A1ADWANfSAC0ALgDVAFHSAG0AOAC7AG5fECQ2MkIzQkM2RS1DMzZCLTREQjAtQTkzNi1ENzA0Q0Q1MzU1MENWaG9tZUlE0gAZABoASgDZ0wBMAB0ATQDaANwA3dIALQAuANsAUdIAbQA4ALsAbl8QJDlDMDZDQUE5LUZDRTUtNEEyNC05QjgwLUI3OEJENjFBNTk0M1Zhd2F5SUTSABkAGgAbAN/SAB0AHgDgAOFfECQzNUREMjE2OS1CN0FELTQ4NzktQkY4Mi0wNTYxODk1NkVFMzfSAC0ALgDiAD3SADAAMQBEAOPRAEYA5NMANwA4ADkAHwA6ACbSABkAGgDmAOdfECBpcy53b3JrZmxvdy5hY3Rpb25zLnRleHQucmVwbGFjZdQATADoAB0A6QDqAO4A7wDwXxAeV0ZSZXBsYWNlVGV4dFJlZ3VsYXJFeHByZXNzaW9uXxARV0ZSZXBsYWNlVGV4dEZpbmTSAC0ALgDrAD3SADAAMQBEAOzRAEYA7dMANwA4ADkA4AA6ACYJXxAkRTgyQUE1NDctQzgyMC00QkJDLUE2NTktMTI5QUFEQTQ5QUVFU1xzK9IAGQAaAFUA8tIATABXAPMA9tIALQAuAPQAUdMANwA4ADkA7wA6APVfEBNBa3R1YWxpc2llcnRlciBUZXh0VkFQSUtledIAGQAaAPgA+V8QHmlzLndvcmtmbG93LmFjdGlvbnMudGV4dC5zcGxpdNIA+gAdAPsA/VR0ZXh00gAtAC4A/ABR0wA3ADgAOQDvADoA9V8QJEU1MUVCRTRFLUY4M0MtNERBQy1BQjY5LTEzMkJBOUJBNzk4OdIAGQAaAP8BAF8QIGlzLndvcmtmbG93LmFjdGlvbnMudGV4dC5jb21iaW5l0wEBAPoAHQECAQMBBl8QD1dGVGV4dFNlcGFyYXRvclZDdXN0b23SAC0ALgEEAFHTADcAOAA5AP0AOgEFXlRleHQgYXVmdGVpbGVuXxAkNjE4QUU0MzctRjBFMy00N0EzLUJCQzEtQUU2Njc0Q0VCOEU00gAZABoAGwEI0gAdAB4BCQEKXxAkRUFFMkFEMDktQ0RBNi00Q0QwLThDMDEtNjg5MUI5QTIyMzQ10gAtAC4BCwA90gAwADEBDAENbxA4AGgAdAB0AHAAcwA6AC8ALwBhAHAAaQAuAGYAbwBvAHQAYgBh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OTI1NUY1N0NGNzHSAC0ALgLQAD3SADAAMQLRAtJvEBT//AAv//wAXwBQAGwAYQB5AGUAcgBEAGEAdABlAG4ALgBqAHMAbwBu0gBGAbUC0wLU0gBtADgA0QBu0gBtADgA0QBu0gAZABoBuQLW1QBMAbsAHQG8Ab0C1wAWAtkAFgLa0gAtAC4C2ABR0wA3ADgAOQLLADoBwF8QJDIyQjdBQjUzLTdEMzAtNEM2OS1CRjYzLTAyMTk5OTIzNEQ4MNIALQAuAtsAPdIAMAAxAEQC3NEARgLd0wA3ADgAOQLOADoAJq8QEwLfAuAC4QLiAuMC5ALlAuYC5wLoAukC6gLrAuwC7QLuAu8C8ALxXxAQV0ZBcHBDb250ZW50SXRlbV8QGFdGQXBwU3RvcmVBcHBDb250ZW50SXRlbV8QFFdGQXJ0aWNsZUNvbnRlbnRJdGVtXxAUV0ZDb250YWN0Q29udGVudEl0ZW1fEBFXRkRhdGVDb250ZW50SXRlbV8QGVdGRW1haWxBZGRyZXNzQ29udGVudEl0ZW1fEBNXRkZvbGRlckNvbnRlbnRJdGVtXxAYV0ZHZW5lcmljRmlsZUNvbnRlbnRJdGVtXxASV0ZJbWFnZUNvbnRlbnRJdGVtXxAaV0ZpVHVuZXNQcm9kdWN0Q29udGVudEl0ZW1fEBVXRkxvY2F0aW9uQ29udGVudEl0ZW1fEBdXRkRDTWFwc0xpbmtDb250ZW50SXRlbV8QFFdGQVZBc3NldENvbnRlbnRJdGVtXxAQV0ZQREZDb250ZW50SXRlbV8QGFdGUGhvbmVOdW1iZXJDb250ZW50SXRlbV8QFVdGUmljaFRleHRDb250ZW50SXRlbV8QGldGU2FmYXJpV2ViUGFnZUNvbnRlbnRJdGVtXxATV0ZTdHJpbmdDb250ZW50SXRlbV8QEFdGVVJMQ29udGVudEl0ZW2hAvPVAvQC9QL2AvcAJgBwAvgAIAAeAvlbQWN0aW9uSW5kZXhYQ2F0ZWdvcnlcRGVmYXVsdFZhbHVlXFBhcmFtZXRlcktleVlQYXJhbWV0ZXJfEBtGb290eVN0YXRzIEFQSS1LZXkgZWluZ2ViZW6gogL8Av1VV2F0Y2hfEBpXRldvcmtmbG93VHlwZVNob3dJblNlYXJjaAAIADkAYACBAJAAqgDPAO0BAQElAUEBWQFrAZEB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"

_HUBSIGN_HTML = r"""<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>FootyStats HubSign Helfer</title>
<style>
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:#f4f4f5;margin:0;color:#111827}
.w{max-width:620px;margin:auto;padding:20px}
.c{background:white;border-radius:16px;padding:20px;box-shadow:0 1px 7px #0001}
h1{font-size:1.35rem}
label{display:block;font-weight:700;margin-top:16px}
input{box-sizing:border-box;width:100%;padding:13px;border:1px solid #d1d5db;border-radius:10px;font-size:16px;margin-top:7px}
button{width:100%;padding:14px;margin-top:20px;border:0;border-radius:11px;background:#111827;color:white;font-size:17px;font-weight:700}
.s{font-size:.9rem;color:#6b7280;line-height:1.45}.ok{color:#047857}.bad{color:#b91c1c}
</style>
</head>
<body><div class="w"><div class="c">
<h1>FootyStats API Export V2 signieren</h1>
<p class="s">Die vorbereitete Shortcut-Datei ist bereits eingebaut. Du musst keine Datei auswählen.</p>
<label>Name</label>
<input id="name" value="FootyStats API Export V2">
<label>HubSign API-Key</label>
<input id="key" type="password" autocomplete="off" autocapitalize="none" spellcheck="false" placeholder="HubSign-Key hier einfügen">
<p class="s">Der Key wird nicht gespeichert. Er wird nur für diesen Signiervorgang über deinen Render-Dienst an RoutineHub gesendet.</p>
<button id="go">Jetzt signieren</button>
<p id="status" class="s"></p>
</div></div>
<script>
document.getElementById('go').onclick=async()=>{
  const key=document.getElementById('key').value.trim();
  const name=document.getElementById('name').value.trim()||'FootyStats API Export V2';
  const st=document.getElementById('status');
  if(!key){st.className='s bad';st.textContent='HubSign-Key fehlt.';return}
  st.className='s';st.textContent='Signierung läuft…';
  try{
    const fd=new FormData(); fd.append('api_key',key); fd.append('shortcut_name',name);
    const r=await fetch('/api/hubsign-sign',{method:'POST',body:fd});
    if(!r.ok){
      const t=await r.text();
      st.className='s bad';st.textContent='Fehler '+r.status+': '+t.slice(0,500);return;
    }
    const b=await r.blob();
    const u=URL.createObjectURL(b);
    const a=document.createElement('a'); a.href=u; a.download='FootyStats API Export V2.shortcut';
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(()=>URL.revokeObjectURL(u),5000);
    st.className='s ok';st.textContent='Fertig. Die signierte .shortcut-Datei wurde heruntergeladen.';
    document.getElementById('key').value='';
  }catch(e){st.className='s bad';st.textContent='Fehler: '+String(e)}
};
</script></body></html>"""

@app.get("/hubsign-helper", response_class=HTMLResponse)
def hubsign_helper():
    return HTMLResponse(_HUBSIGN_HTML, headers={"Cache-Control":"no-store"})

def _multipart_body(shortcut_name: str, api_key: str):
    boundary = "----FootyStatsHubSign" + _uuid.uuid4().hex
    b = boundary.encode()
    chunks = []
    def field(name, value):
        chunks.extend([
            b"--"+b+b"\r\n",
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
            value.encode("utf-8"),
            b"\r\n",
        ])
    field("shortcut_name", shortcut_name)
    data = _b64.b64decode(_PREPARED_SHORTCUT_B64)
    chunks.extend([
        b"--"+b+b"\r\n",
        b'Content-Disposition: form-data; name="shortcut_file"; filename="FootyStats API Export V2.shortcut"\r\n',
        b"Content-Type: application/octet-stream\r\n\r\n",
        data,
        b"\r\n",
    ])
    field("api_key", api_key)
    chunks.append(b"--"+b+b"--\r\n")
    return boundary, b"".join(chunks)

@app.post("/api/hubsign-sign")
async def hubsign_sign(api_key: str = Form(...), shortcut_name: str = Form("FootyStats API Export V2")):
    api_key = (api_key or "").strip()
    shortcut_name = (shortcut_name or "FootyStats API Export V2").strip()
    if not api_key:
        raise HTTPException(status_code=400, detail="HubSign API-Key fehlt.")
    boundary, body = _multipart_body(shortcut_name, api_key)
    req = _urlreq.Request(
        "https://routinehub.co/api/v1/sign-shortcut",
        data=body,
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Accept": "application/octet-stream",
            "User-Agent": "FootyStats-Prognose-Engine/0.2.2",
        },
        method="POST",
    )
    try:
        with _urlreq.urlopen(req, timeout=60) as r:
            signed = r.read()
            status = getattr(r, "status", 200)
            ctype = r.headers.get("Content-Type", "application/octet-stream")
    except _urlerr.HTTPError as e:
        err = e.read()
        return Response(
            content=err,
            status_code=e.code,
            media_type=e.headers.get("Content-Type", "application/json"),
            headers={"Cache-Control":"no-store"},
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"RoutineHub nicht erreichbar: {e}")
    if status != 200:
        return Response(content=signed, status_code=status, media_type=ctype, headers={"Cache-Control":"no-store"})
    # RoutineHub's current API contract guarantees a signed shortcut on HTTP 200,
    # but does not guarantee the legacy AEA1 magic bytes. Reject obvious
    # error/text responses instead of hard-coding one archive signature format.
    ctype_l = (ctype or "").lower()
    if not signed or "json" in ctype_l or "text/html" in ctype_l:
        return Response(
            content=signed or b"RoutineHub returned an empty response.",
            status_code=502,
            media_type=ctype or "text/plain",
            headers={"Cache-Control":"no-store"},
        )
    return Response(
        content=signed,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": 'attachment; filename="FootyStats API Export V2.shortcut"',
            "Cache-Control":"no-store",
        },
    )
