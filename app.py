
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

def predict(match,league):
    a=audit(match,league)
    if not a['valid']:return {'ok':False,'phase':'DATA_AUDIT_FAILED','audit':{k:v for k,v in a.items() if k not in {'home_team','away_team'}},'decision':'ANALYSE NICHT MÖGLICH'}
    m=a['match'];h=profile(a['home_team'],'home');aw=profile(a['away_team'],'away')
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
    return {
      'ok':True,'model_version':'0.1.0','deterministic':True,'audit':{'valid':True,'errors':[],'match':m,'pager':a['pager']},
      'samples':{'home_venue':hn,'home_class':sclass(hn),'away_venue':an,'away_class':sclass(an),'security':ss},
      'expected_goals':{'home':hl,'away':al,'total':hl+al,'matchup_xg_diagnostic':mx},
      'probabilities':p,'markets':[{'rank':i+1,'key':x,'label':LABEL[x],'probability_pct':round(q*100,1)} for i,(x,q) in enumerate(rank)],
      'strongest_market':{'key':top,'label':LABEL[top],'probability_pct':round(tp*100,1)},
      'second_market':{'key':second,'label':LABEL[second],'probability_pct':round(sp*100,1)},
      'diagnostics':{'data_quality':quality,'sample_security':ss,'result_vs_underlying':rv,'relative_edge':ed,'counterargument':counter,'single_point_of_failure':spof,'influence_stress_probability_pct':round(i*100,1),'fragility_stress_probability_pct':round(f*100,1),'robustness_status':rob},
      'decision':dec,
      'notes':['Odds werden vollständig ignoriert.','Gleiche Inputs liefern gleiche Outputs.','Version 0.1 ist noch nicht historisch kalibriert.']
    }



# ---- Web/API layer ----
import json
from typing import Any, Dict
from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

app = FastAPI(title="FootyStats Prognose Engine", version="0.1.0")

class Payload(BaseModel):
    matchData: Dict[str, Any]
    leagueData: Dict[str, Any]

INDEX_HTML = r"""<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>FootyStats Prognose Engine</title>
<style>
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:#f3f4f6;margin:0;color:#111827}
.w{max-width:900px;margin:auto;padding:18px}.c{background:#fff;border-radius:15px;padding:17px;margin:12px 0;box-shadow:0 1px 5px #0001}
.g{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:9px}.m{border:1px solid #e5e7eb;border-radius:11px;padding:11px}
.b{font-size:1.2rem;font-weight:700}.s{font-size:.85rem;color:#6b7280}button{width:100%;padding:13px;border:0;border-radius:11px;background:#111827;color:#fff;font-weight:700}
input{width:100%;margin:7px 0 14px}table{width:100%;border-collapse:collapse}td,th{padding:8px;border-bottom:1px solid #eee;text-align:left}
pre{white-space:pre-wrap;word-break:break-word;font-size:.75rem}.bad{color:#b91c1c}
</style>
</head>
<body>
<div class="w">
<div class="c">
<h2>FootyStats Prognose Engine v0.1</h2>
<div class="s">Deterministisch · keine Odds · keine externen Daten</div>
<p>MatchDaten.json</p><input id="matchFile" type="file" accept=".json,application/json">
<p>LeagueDaten.json</p><input id="leagueFile" type="file" accept=".json,application/json">
<button id="go">Analyse starten</button>
</div>
<div id="out"></div>
</div>
<script>
document.getElementById('go').onclick=async()=>{
 const mf=document.getElementById('matchFile').files[0], lf=document.getElementById('leagueFile').files[0];
 const out=document.getElementById('out');
 if(!mf||!lf){out.innerHTML='<div class="c bad">Bitte beide JSON-Dateien auswählen.</div>';return}
 out.innerHTML='<div class="c">Analysiere…</div>';
 try{
   const form=new FormData();
   form.append('match_file',mf); form.append('league_file',lf);
   const r=await fetch('/api/predict-files',{method:'POST',body:form});
   const d=await r.json();
   if(!d.ok){out.innerHTML='<div class="c"><h3 class="bad">Analyse nicht möglich</h3><pre>'+JSON.stringify(d,null,2)+'</pre></div>';return}
   const g=d.diagnostics,x=d.expected_goals;
   const rows=d.markets.map(z=>`<tr><td>${z.rank}</td><td>${z.label}</td><td><b>${z.probability_pct}%</b></td></tr>`).join('');
   out.innerHTML=`
   <div class="c"><h3>Kurzentscheidung</h3><div class="g">
   <div class="m"><div class="s">Bester Markt</div><div class="b">${d.strongest_market.label}</div></div>
   <div class="m"><div class="s">Wahrscheinlichkeit</div><div class="b">${d.strongest_market.probability_pct}%</div></div>
   <div class="m"><div class="s">Entscheidung</div><div class="b">${d.decision}</div></div>
   <div class="m"><div class="s">Result vs Underlying</div><b>${g.result_vs_underlying}</b></div>
   <div class="m"><div class="s">Robustheit</div><b>${g.robustness_status}</b></div>
   <div class="m"><div class="s">Relative Edge</div><b>${g.relative_edge}</b></div>
   <div class="m"><div class="s">Datenqualität</div><b>${g.data_quality}</b></div>
   <div class="m"><div class="s">Stichprobe</div><b>${g.sample_security}</b></div>
   </div></div>
   <div class="c"><h3>Alle Märkte</h3><table><tr><th>Rang</th><th>Markt</th><th>Modell</th></tr>${rows}</table></div>
   <div class="c"><h3>Goal Model</h3>
   <p>Heim: <b>${x.home.toFixed(2)}</b> · Auswärts: <b>${x.away.toFixed(2)}</b> · Gesamt: <b>${x.total.toFixed(2)}</b></p>
   <p>Influence Stress: <b>${g.influence_stress_probability_pct}%</b> · Fragility Stress: <b>${g.fragility_stress_probability_pct}%</b></p>
   <p>Gegenargument: <b>${g.counterargument}</b></p></div>
   <div class="c"><details><summary>Technische Diagnose</summary><pre>${JSON.stringify(d,null,2)}</pre></details></div>`;
 }catch(e){out.innerHTML='<div class="c bad">Fehler: '+String(e)+'</div>'}
}
</script>
</body></html>"""

@app.get("/", response_class=HTMLResponse)
def index():
    return INDEX_HTML

@app.get("/api/health")
def health():
    return {"ok": True, "version": "0.1.0"}

@app.post("/api/predict")
def predict_json(payload: Payload):
    return predict(payload.matchData, payload.leagueData)

@app.post("/api/predict-files")
async def predict_files(
    match_file: UploadFile = File(...),
    league_file: UploadFile = File(...)
):
    try:
        match_data = json.loads((await match_file.read()).decode("utf-8"))
        league_data = json.loads((await league_file.read()).decode("utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Ungültige JSON-Datei: {exc}")
    return predict(match_data, league_data)
