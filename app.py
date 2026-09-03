import math
import hashlib
import re
from datetime import datetime, timezone

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
        # Match identity belongs to the match object itself. Prefer its direct
        # fields before recursively scanning nested cards, teams or incidents,
        # which can contain unrelated ``id`` values ahead of the fixture ID.
        direct={nkey(key):value for key,value in m.items()} if isinstance(m,dict) else {}
        direct_value=next((direct[nkey(alias)] for alias in a if nkey(alias) in direct and direct[nkey(alias)] not in (None,'',[],{})),None)
        if k in {'home_name','away_name','season','status','date'}:
            out[k]=direct_value if direct_value is not None else first(m,a)
        else:
            out[k]=num(direct_value) if direct_value is not None else firstnum(m,a)
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

# ---- Worldwide league-relative probability core v0.4 / V5.5 ----
#
# The five-file package contains the complete competition context.  Instead of
# applying one fixed global raw-value threshold to every league, this core
# estimates the concrete league's home/away xG baselines and shrinks each
# team's venue rates toward those baselines.  The shrinkage strength is learned
# from the dispersion of the teams in the supplied LeagueDaten file.

def _team_identifier(team):
    for key,value in (team or {}).items():
        if nkey(key) in {'id','teamid','team_id'}:
            identifier=num(value)
            if identifier is not None:return int(identifier)
    return None

def league_team_list(league):
    found={}
    for candidate in dicts(league):
        identifier=_team_identifier(candidate)
        stats=candidate.get('stats') if isinstance(candidate,dict) else None
        if identifier is not None and isinstance(stats,dict) and stats:
            found.setdefault(identifier,candidate)
    if len(found)<2:raise ValueError('LeagueDaten enthält keine vollständige Teamliste für die Liga-Normalisierung.')
    return list(found.values())

def league_metric_rows(teams,split,metric):
    rows=[]
    for team in teams:
        rate=tnum(team,metric,split); matches=tnum(team,'matches',split)
        if rate is not None and matches is not None and rate>=0 and matches>0:
            rows.append((float(rate),float(matches)))
    return rows

def weighted_league_mean(rows):
    denominator=sum(weight for _,weight in rows if weight>0)
    if denominator<=0:raise ValueError('Liga-Mittelwert kann nicht gewichtet berechnet werden.')
    return sum(rate*weight for rate,weight in rows if weight>0)/denominator

def league_shrunk_rate(rate,matches,rows,league_mean):
    if rate is None or matches is None or rate<0 or matches<=0:
        raise ValueError('Zentraler Venue-xG-Wert oder seine Stichprobe fehlt.')
    total_weight=sum(weight for _,weight in rows)
    if len(rows)<2 or total_weight<=0:
        raise ValueError('Zu wenige Liga-Teams für datenabhängiges Shrinkage.')
    variance=sum(weight*(value-league_mean)**2 for value,weight in rows)/total_weight
    if variance<=1e-10:
        posterior=league_mean
        prior_exposure=None
        reliability=1.0
    else:
        prior_shape=league_mean*league_mean/variance
        prior_exposure=league_mean/variance
        posterior=(matches*rate+prior_shape)/(matches+prior_exposure)
        reliability=matches/(matches+prior_exposure)
    return {'raw':float(rate),'league_mean':league_mean,'matches':float(matches),'variance':variance,
            'prior_exposure':prior_exposure,'reliability':reliability,'shrunk':posterior}

def worldwide_lambdas(home_team,away_team,league,neutralize=None):
    teams=league_team_list(league)
    specs={'home_xg':('home','xg'),'away_xg':('away','xg'),
           'home_xga':('home','xga'),'away_xga':('away','xga')}
    rows={name:league_metric_rows(teams,*spec) for name,spec in specs.items()}
    baseline={name:weighted_league_mean(metric_rows) for name,metric_rows in rows.items()}
    required={
      'home_attack':(tnum(home_team,'xg','home'),tnum(home_team,'matches','home'),'home_xg'),
      'away_defence':(tnum(away_team,'xga','away'),tnum(away_team,'matches','away'),'away_xga'),
      'away_attack':(tnum(away_team,'xg','away'),tnum(away_team,'matches','away'),'away_xg'),
      'home_defence':(tnum(home_team,'xga','home'),tnum(home_team,'matches','home'),'home_xga'),
    }
    pooled={}
    for name,(rate,matches,base_name) in required.items():
        pooled[name]=league_shrunk_rate(rate,matches,rows[base_name],baseline[base_name])
    ratios={
      'home_attack':pooled['home_attack']['shrunk']/baseline['home_xg'],
      'away_defence':pooled['away_defence']['shrunk']/baseline['away_xga'],
      'away_attack':pooled['away_attack']['shrunk']/baseline['away_xg'],
      'home_defence':pooled['home_defence']['shrunk']/baseline['home_xga'],
    }
    if neutralize in ratios:ratios[neutralize]=1.0
    home_lambda=baseline['home_xg']*ratios['home_attack']*ratios['away_defence']
    away_lambda=baseline['away_xg']*ratios['away_attack']*ratios['home_defence']
    if not (math.isfinite(home_lambda) and math.isfinite(away_lambda)) or home_lambda<=0 or away_lambda<=0:
        raise ValueError('Liga-relative erwartete Tore sind nicht gültig.')
    detail={
      'method':'league-relative empirical-Bayes Maher/Poisson',
      'league_team_count':len(teams),
      'league_baselines':{key:round(value,6) for key,value in baseline.items()},
      'partial_pooling':{key:{k:(round(v,6) if isinstance(v,(int,float)) else v) for k,v in values.items()} for key,values in pooled.items()},
      'relative_strengths':{key:round(value,6) for key,value in ratios.items()},
      'neutralized_block':neutralize,
      'fixed_global_thresholds_used':False,
      'dixon_coles_fitted':False,
      'dixon_coles_reason':'Im Einzelpaket fehlt ein historischer Score-Korpus; ein Abhängigkeitsparameter wird nicht erfunden.',
    }
    return home_lambda,away_lambda,detail

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
def rvu_detail(h,a,market,underlying_probability,home_lambda,away_lambda):
    result_probability=resultprob(h,a,market)
    status=rvu(h,a,market,underlying_probability)
    difference=None if result_probability is None else (result_probability-underlying_probability)*100
    result_basis={
      'home_win':'Heim-Siegquote des Heimteams im Home-Split',
      'away_win':'Auswärts-Siegquote des Auswärtsteams im Away-Split',
      'btts_yes':'Mittel der historischen Home-/Away-BTTS-Quoten',
      'btts_no':'Komplement der historischen Home-/Away-BTTS-Quoten',
      'over_2_5':'Mittel der historischen Home-/Away-Over-2,5-Quoten',
      'under_2_5':'Mittel der historischen Home-/Away-Under-2,5-Quoten',
    }.get(market,'Historische Resultatquote')
    return {
      'status':status,
      'market':market,
      'result_probability_pct':round(result_probability*100,1) if result_probability is not None else None,
      'underlying_probability_pct':round(underlying_probability*100,1),
      'difference_pp':round(difference,1) if difference is not None else None,
      'result_basis':result_basis,
      'underlying_basis':'Liga-relatives, geschrumpftes Venue-xG-Modell auf kohärentem Poisson-Scoregrid',
      'underlying_expected_goals':{'home':round(home_lambda,3),'away':round(away_lambda,3),'total':round(home_lambda+away_lambda,3)},
    }
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
        return {'ok':False,'model_version':'0.4.0','phase':'INSUFFICIENT_DATA','decision':'ANALYSE NICHT MÖGLICH','error':'Zu wenig belastbare historische Teamdaten für eine seriöse Marktprognose. Placeholder-Nullwerte werden nicht als echte Leistung interpretiert.','audit':{'valid':True,'errors':[],'match':m,'pager':a['pager']},'samples':report['samples'],'diagnostics':{'data_quality':'NIEDRIG','sample_security':'NIEDRIG','result_vs_underlying':'NICHT PRÜFBAR','relative_edge':'NICHT PRÜFBAR','counterargument':'UNZUREICHENDE DATENGRUNDLAGE','single_point_of_failure':True,'robustness_status':'NICHT PRÜFBAR'},'insufficient_data':report,'notes':['Keine Wahrscheinlichkeiten berechnet.','Keine künstlichen Mindest-xG-Werte als Prognose verwendet.','Odds werden vollständig ignoriert.']}
    hn,an=h['home']['matches'],aw['away']['matches'];ho,ao=h['overall']['matches'],aw['overall']['matches']
    ss=sample(hn,an,ho,ao); quality='HOCH'
    if not hn or not an:quality='MITTEL'
    if sum(x is not None for x in [h['overall']['xg'],h['overall']['xga'],aw['overall']['xg'],aw['overall']['xga']])<3:quality='MITTEL'
    try:hl,al,world=worldwide_lambdas(a['home_team'],a['away_team'],league)
    except ValueError as e:return {'ok':False,'phase':'MODEL_INPUT_FAILED','audit':{'valid':True,'errors':[str(e)],'match':m},'decision':'ANALYSE NICHT MÖGLICH'}
    if world.get('league_team_count',0)<6:quality='MITTEL'
    # One coherent score grid drives every market.  FootyStats potentials and
    # odds are not blended into the probabilities, avoiding duplicate evidence.
    p=poisson(hl,al)
    allowed=['home_win','away_win','btts_yes','btts_no','over_2_5','under_2_5']
    rank=sorted([(x,p[x]) for x in allowed],key=lambda z:z[1],reverse=True); top,tp=rank[0]; second,sp=rank[1]
    blocks=['home_attack','away_defence','away_attack','home_defence']; stress={}
    for block in blocks:
        sh,sa,_=worldwide_lambdas(a['home_team'],a['away_team'],league,block)
        stress[block]=poisson(sh,sa)[top]
    influence_block=max(blocks,key=lambda block:abs(stress[block]-tp))
    pooling=world.get('partial_pooling') or {}
    fragility_block=min(blocks,key=lambda block:num((pooling.get(block) or {}).get('reliability')) if num((pooling.get(block) or {}).get('reliability')) is not None else -1)
    influence_p,fragility_p=stress[influence_block],stress[fragility_block]
    rv_detail=rvu_detail(h,aw,top,tp,hl,al);rv=rv_detail['status'];ed=edge(tp,sp)
    flip=(influence_p>=.5)!=(tp>=.5) or (fragility_p>=.5)!=(tp>=.5)
    spof=flip or max(tp-influence_p,tp-fragility_p)>=.10
    if tp>=.65:rob='BESTANDEN' if min(influence_p,fragility_p)>=.63 and not spof and rv in {'KONSISTENT','TEILWEISE KONSISTENT'} else ('EINGESCHRÄNKT' if min(influence_p,fragility_p)>=.60 and not flip else 'NICHT BESTANDEN')
    else:rob='NICHT FÜR SPIELEN — INSTABIL' if spof else ('NICHT FÜR SPIELEN — EINGESCHRÄNKT' if min(influence_p,fragility_p)<.60 or rv=='TEILWEISE WIDERSPRÜCHLICH' else 'NICHT FÜR SPIELEN — STABIL')
    counter='DOMINANTES ZENTRALES GEGENARGUMENT' if rv=='STARK WIDERSPRÜCHLICH' else ('STARKES ZENTRALES GEGENARGUMENT' if rv=='TEILWEISE WIDERSPRÜCHLICH' else ('RELEVANTES ZENTRALES GEGENARGUMENT' if ss=='NIEDRIG' or quality=='NIEDRIG' else 'KEIN RELEVANTES ZENTRALES GEGENARGUMENT'))
    dec='AUSLASSEN' if tp<.60 or rv=='STARK WIDERSPRÜCHLICH' else 'BEOBACHTEN'
    if tp>=.65 and quality in {'HOCH','MITTEL'} and ss!='NIEDRIG' and ed=='KLAR' and rv in {'KONSISTENT','TEILWEISE KONSISTENT'} and not spof and rob=='BESTANDEN':dec='SPIELEN'
    return {'ok':True,'model_version':'0.4.0','deterministic':True,
      'method':{'probability_core':world['method'],'league_relative':True,'empirical_bayes_shrinkage':True,'fixed_global_thresholds_used':False,'odds_used':False,'backtested':False},
      'audit':{'valid':True,'errors':[],'match':m,'pager':a['pager']},
      'samples':{'home_venue':hn,'home_class':sclass(hn),'away_venue':an,'away_class':sclass(an),'security':ss},
      'expected_goals':{'home':hl,'away':al,'total':hl+al,'league_relative_model':world},
      'probabilities':p,
      'markets':[{'rank':rank_index+1,'key':market_key,'label':LABEL[market_key],'probability_pct':round(probability*100,1)} for rank_index,(market_key,probability) in enumerate(rank)],
      'strongest_market':{'key':top,'label':LABEL[top],'probability_pct':round(tp*100,1)},
      'second_market':{'key':second,'label':LABEL[second],'probability_pct':round(sp*100,1)},
      'diagnostics':{'data_quality':quality,'sample_security':ss,'result_vs_underlying':rv,'result_vs_underlying_detail':rv_detail,'relative_edge':ed,'counterargument':counter,'single_point_of_failure':spof,'influence_block':influence_block,'fragility_block':fragility_block,'influence_stress_probability_pct':round(influence_p*100,1),'fragility_stress_probability_pct':round(fragility_p*100,1),'all_central_block_stress':{key:round(value*100,1) for key,value in stress.items()},'robustness_status':rob,'insufficient_data_gate':'BESTANDEN'},
      'decision':dec,
      'notes':['Odds werden vollständig ignoriert.','Alle sechs Märkte stammen aus demselben kohärenten Scoregrid.','Liga-Durchschnitt und Shrinkage werden aus den gelieferten LeagueDaten berechnet.','Version 0.4.0 mit liga-relativem V5.5-Kern, INSUFFICIENT_DATA-Sperre und V5.2-Guardrails.']}

# ---- Web/API layer v0.4 ----
import json
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, File, UploadFile, HTTPException, Form, Request
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel

app = FastAPI(title="FootyStats + Forebet ELITE Analyse", version="0.9.2")

class Payload(BaseModel):
    matchData: Dict[str, Any]
    leagueData: Dict[str, Any]
    formData: Optional[Dict[str, Any]] = None
    tableData: Optional[Dict[str, Any]] = None
    playerData: Optional[Dict[str, Any]] = None
    forebetData: Dict[str, Any]


def _source_kind(filename: str) -> Optional[str]:
    """Classify a V2 export by its filename without inspecting arbitrary JSON."""
    name = (filename or "").lower().replace(" ", "")
    for kind, marker in (("match", "matchdaten"), ("league", "leaguedaten"),
                         ("form", "formdaten"), ("table", "tabledaten"),
                         ("player", "playerdaten"), ("forebet", "forebetdaten")):
        if marker in name:
            return kind
    return None


def _forebet_probability(value: Any, field: str) -> float:
    parsed = num(value)
    if parsed is None:
        raise ValueError(f"Forebet-Feld {field} fehlt oder ist keine Zahl.")
    probability = parsed / 100.0 if parsed > 1 else parsed
    if not 0 <= probability <= 1:
        raise ValueError(f"Forebet-Feld {field} muss zwischen 0 und 100 Prozent liegen.")
    return float(probability)


def _forebet_snapshot(data: Any, match_fields: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(data, dict):
        raise ValueError("ForebetDaten müssen ein JSON-Objekt sein.")
    if data.get("ok") is False:
        reason = str(data.get("error") or "Für dieses Spiel wurden keine sicheren Forebet-Daten gefunden.")
        raise ValueError(f"Forebet-Automatik nicht verfügbar: {reason}")
    raw = data.get("raw_entry") or data.get("raw")
    values = dict(data)
    if isinstance(raw, str) and raw.strip():
        parts = [part.strip() for part in raw.split(";")]
        if len(parts) < 7:
            raise ValueError("Forebet-Eingabe benötigt: 1;X;2;BTTS-Ja;Over-2,5;Ergebnistipp;Ø-Tore[;URL].")
        values.update({
            "home_win": parts[0], "draw": parts[1], "away_win": parts[2],
            "btts_yes": parts[3], "over_2_5": parts[4],
            "predicted_score": parts[5], "average_goals": parts[6],
        })
        if len(parts) > 7 and parts[7]:
            values["source_url"] = parts[7]
    match_id = firstnum(values, ["match_id", "matchID"])
    expected_match_id = num(match_fields.get("match_id"))
    if match_id is None or expected_match_id is None or int(match_id) != int(expected_match_id):
        raise ValueError("ForebetDaten gehören nicht zur Match-ID der FootyStats-Dateien.")
    home = _forebet_probability(first(values, ["home_win", "home_probability", "p1"]), "1")
    draw = _forebet_probability(first(values, ["draw", "draw_probability", "px"]), "X")
    away = _forebet_probability(first(values, ["away_win", "away_probability", "p2"]), "2")
    total = home + draw + away
    if not 0.95 <= total <= 1.05:
        raise ValueError("Forebet-1X2-Werte müssen zusammen ungefähr 100 Prozent ergeben.")
    home, draw, away = home / total, draw / total, away / total
    btts_yes = _forebet_probability(first(values, ["btts_yes", "btts", "both_teams_to_score_yes"]), "BTTS-Ja")
    over_2_5 = _forebet_probability(first(values, ["over_2_5", "over25", "o25"]), "Over 2,5")
    predicted_score = str(first(values, ["predicted_score", "correct_score", "score_prediction"]) or "").strip()
    score_match = re.fullmatch(r"(\d{1,2})\s*[-:]\s*(\d{1,2})", predicted_score)
    if not score_match:
        raise ValueError("Forebet-Ergebnistipp muss wie 2-1 eingegeben werden.")
    score_home, score_away = int(score_match.group(1)), int(score_match.group(2))
    average_goals = num(first(values, ["average_goals", "avg_goals", "expected_goals"] ))
    if average_goals is None or not 0 <= average_goals <= 10:
        raise ValueError("Forebet-Ø-Tore müssen zwischen 0 und 10 liegen.")
    source_url = str(first(values, ["source_url", "forebet_url", "url"]) or "").strip()
    if source_url and not re.match(r"^https://(www\.)?forebet\.com/", source_url, re.I):
        raise ValueError("Forebet-Quelllink muss auf forebet.com verweisen.")
    return {
        "match_id": int(match_id),
        "source": str(values.get("source") or "Forebet public pre-match prediction"),
        "source_url": source_url or None,
        "captured_at": first(values, ["captured_at", "created_at"]),
        "probabilities": {
            "home_win": home, "draw": draw, "away_win": away,
            "btts_yes": btts_yes, "btts_no": 1 - btts_yes,
            "over_2_5": over_2_5, "under_2_5": 1 - over_2_5,
        },
        "predicted_score": f"{score_home}-{score_away}",
        "predicted_score_goals": {"home": score_home, "away": score_away, "total": score_home + score_away},
        "average_goals": float(average_goals),
        "odds_used": False,
    }


def _bounded_probability(value: float) -> float:
    return max(1e-6, min(1 - 1e-6, float(value)))


def _binary_log_opinion_pool(first_probability: float, second_probability: float) -> float:
    first_probability = _bounded_probability(first_probability)
    second_probability = _bounded_probability(second_probability)
    log_odds = 0.5 * math.log(first_probability / (1 - first_probability)) + 0.5 * math.log(second_probability / (1 - second_probability))
    return 1 / (1 + math.exp(-log_odds))


def _multiclass_log_opinion_pool(first_model: Dict[str, float], second_model: Dict[str, float], keys: List[str]) -> Dict[str, float]:
    raw = {key: math.sqrt(_bounded_probability(first_model[key]) * _bounded_probability(second_model[key])) for key in keys}
    total = sum(raw.values())
    return {key: value / total for key, value in raw.items()}


def _forebet_internal_coherence(forebet: Dict[str, Any], market: str) -> Dict[str, Any]:
    """Use Forebet score and average-goals fields as consistency gates, not fake probabilities."""
    score = forebet.get("predicted_score_goals") or {}
    home = int(score.get("home", 0))
    away = int(score.get("away", 0))
    total = home + away
    average_goals = float(forebet.get("average_goals"))
    score_markets = {
        "home_win": home > away,
        "away_win": away > home,
        "btts_yes": home > 0 and away > 0,
        "btts_no": home == 0 or away == 0,
        "over_2_5": total >= 3,
        "under_2_5": total <= 2,
    }
    average_market = None
    if market == "over_2_5":
        average_market = average_goals >= 2.65
    elif market == "under_2_5":
        average_market = average_goals <= 2.35
    score_support = bool(score_markets.get(market))
    passed = score_support and average_market is not False
    return {
        "passed": passed,
        "market": market,
        "predicted_score": forebet.get("predicted_score"),
        "predicted_score_supports_market": score_support,
        "average_goals": average_goals,
        "average_goals_supports_market": average_market,
        "average_goals_neutral_zone": "2.36-2.64" if average_market is None and market in {"over_2_5", "under_2_5"} else None,
        "use": "Kohärenz- und Freigabekontrolle; Ergebnistipp und Ø-Tore werden nicht als zusätzliche Wahrscheinlichkeiten doppelt gewichtet.",
    }


def _attach_forebet_ensemble(result: Dict[str, Any], forebet: Dict[str, Any]) -> Dict[str, Any]:
    if not result.get("ok"):
        return result
    result = dict(result)
    footystats_probabilities = dict(result.get("probabilities") or {})
    footystats_snapshot = {
        "version": "0.4.0",
        "probabilities": footystats_probabilities,
        "markets": list(result.get("markets") or []),
        "strongest_market": dict(result.get("strongest_market") or {}),
        "decision_after_guardrails": result.get("decision"),
        "expected_goals": result.get("expected_goals"),
    }
    forebet_probabilities = forebet["probabilities"]
    fused = _multiclass_log_opinion_pool(
        footystats_probabilities, forebet_probabilities,
        ["home_win", "draw", "away_win"],
    )
    for positive, negative in (("btts_yes", "btts_no"), ("over_2_5", "under_2_5")):
        fused[positive] = _binary_log_opinion_pool(footystats_probabilities[positive], forebet_probabilities[positive])
        fused[negative] = 1 - fused[positive]
    allowed = ["home_win", "away_win", "btts_yes", "btts_no", "over_2_5", "under_2_5"]
    ranking = sorted(((key, fused[key]) for key in allowed), key=lambda item: item[1], reverse=True)
    footystats_top = max(allowed, key=lambda key: footystats_probabilities[key])
    forebet_top = max(allowed, key=lambda key: forebet_probabilities[key])
    fused_top, fused_probability = ranking[0]
    forebet_coherence = _forebet_internal_coherence(forebet, fused_top)
    comparison = []
    for key in allowed:
        difference = abs(footystats_probabilities[key] - forebet_probabilities[key])
        comparison.append({
            "key": key, "label": LABEL[key],
            "footystats_probability_pct": round(footystats_probabilities[key] * 100, 1),
            "forebet_probability_pct": round(forebet_probabilities[key] * 100, 1),
            "combined_probability_pct": round(fused[key] * 100, 1),
            "difference_pp": round(difference * 100, 1),
        })
    top_difference = abs(footystats_probabilities[fused_top] - forebet_probabilities[fused_top])
    top_agreement = footystats_top == forebet_top == fused_top
    base_decision = result.get("decision")
    if fused_probability < 0.60 or top_difference >= 0.18:
        final_decision = "AUSLASSEN"
    elif base_decision == "SPIELEN" and top_agreement and fused_probability >= 0.65 and top_difference <= 0.08 and forebet_coherence["passed"]:
        final_decision = "SPIELEN"
    else:
        final_decision = "BEOBACHTEN"
    agreement_status = "HOCH" if top_agreement and top_difference <= 0.08 else ("MITTEL" if top_difference < 0.18 else "NIEDRIG")
    result["footystats_model"] = footystats_snapshot
    result["forebet_model"] = forebet
    result["probabilities"] = fused
    result["markets"] = [
        {"rank": index + 1, "key": key, "label": LABEL[key], "probability_pct": round(probability * 100, 1)}
        for index, (key, probability) in enumerate(ranking)
    ]
    result["strongest_market"] = {"key": fused_top, "label": LABEL[fused_top], "probability_pct": round(fused_probability * 100, 1)}
    result["second_market"] = {"key": ranking[1][0], "label": LABEL[ranking[1][0]], "probability_pct": round(ranking[1][1] * 100, 1)}
    result["decision_before_forebet_ensemble"] = base_decision
    result["decision"] = final_decision
    result["ensemble"] = {
        "active": True,
        "method": "symmetrischer logarithmischer Opinion-Pool",
        "weights": {"footystats": 0.5, "forebet": 0.5},
        "backtested_weights": False,
        "market_comparison": comparison,
        "footystats_top_market": footystats_top,
        "forebet_top_market": forebet_top,
        "combined_top_market": fused_top,
        "top_market_agreement": top_agreement,
        "top_market_difference_pp": round(top_difference * 100, 1),
        "agreement_status": agreement_status,
        "forebet_internal_coherence": forebet_coherence,
        "decision_rule": "SPIELEN nur bei bestandenem FootyStats-V5.2-Protokoll, gleichem Top-Markt, mindestens 65 % gemeinsam, höchstens 8 Prozentpunkten Differenz und passendem Forebet-Ergebnistipp/Ø-Tore-Kohärenzcheck.",
    }
    result["method"] = {**dict(result.get("method") or {}), "forebet_ensemble": True, "opinion_pool": "equal-weight log pool", "odds_used": False}
    result["model_version"] = "0.9.2"
    result["notes"] = list(result.get("notes") or []) + [
        "Forebet beeinflusst alle sechs Marktwerte über einen symmetrischen logarithmischen Opinion-Pool.",
        "Die Gewichte sind transparent gleich verteilt und noch nicht backtest-kalibriert.",
        "Forebet-Quoten werden nicht übernommen oder verwendet.",
        "Forebet-Ergebnistipp und Average Goals wirken als unabhängige Kohärenz-Gates und werden nicht als erfundene Zusatzwahrscheinlichkeiten doppelt gezählt.",
    ]
    return result


def _same_team_id(value: Any, team_id: Any) -> bool:
    value_num, team_num = num(value), num(team_id)
    return value_num is not None and team_num is not None and int(value_num) == int(team_num)


def _table_row(table_data: Any, table_key: str, team_id: Any) -> Optional[Dict[str, Any]]:
    rows = ((table_data or {}).get("data") or {}).get(table_key) or []
    return next((item for item in rows if isinstance(item, dict) and _same_team_id(item.get("id"), team_id)), None)


def _table_team_summary(table_data: Any, team_id: Any, venue: str) -> Dict[str, Any]:
    table_key = "all_matches_table_home" if venue == "home" else "all_matches_table_away"
    row = _table_row(table_data, table_key, team_id)
    overall = _table_row(table_data, "all_matches_table_overall", team_id)
    if not row:
        return {"available": False, "venue": venue, "overall_available": bool(overall)}
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
        "overall_available": bool(overall),
    }


def _form_records(form_data: Any) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    for page in ((form_data or {}).get("teams") or []):
        if isinstance(page, dict):
            records.extend(item for item in (page.get("data") or []) if isinstance(item, dict))
    return records


def _form_window(item: Dict[str, Any]) -> Dict[str, Any]:
    stats = item.get("stats") or {}
    sample = num(item.get("last_x_match_num")) or num(stats.get("last_x"))
    return {
        "sample": int(sample) if sample is not None else None,
        "ppg": num(stats.get("seasonPPG_overall")),
        "btts_pct": num(stats.get("seasonBTTSPercentage_overall")),
        "over_25_pct": num(stats.get("seasonOver25Percentage_overall")),
        "under_25_pct": num(stats.get("seasonUnder25Percentage_overall")),
        "goals_for_per_match": num(stats.get("seasonScoredAVG_overall")),
        "goals_against_per_match": num(stats.get("seasonConcededAVG_overall")),
        "xg": num(stats.get("xg_for_avg_overall")),
        "xga": num(stats.get("xg_against_avg_overall")),
        "shots_on_target_avg": num(stats.get("shotsOnTargetAVG_overall")),
    }


def _form_team_summary(form_data: Any, team_id: Any) -> Dict[str, Any]:
    candidates = [item for item in _form_records(form_data) if _same_team_id(item.get("id"), team_id)]
    if not candidates:
        return {"available": False}
    windows = [_form_window(item) for item in candidates]
    windows = [window for window in windows if window.get("sample")]
    if not windows:
        return {"available": False}
    windows.sort(key=lambda window: window["sample"])
    recent = next((window for window in windows if window["sample"] == 5), None)
    reference = windows[-1]
    return {
        "available": True,
        "sample": reference["sample"],
        "ppg": reference["ppg"],
        "shots_on_target_avg": reference["shots_on_target_avg"],
        "btts_pct": reference["btts_pct"],
        "windows": {str(window["sample"]): window for window in windows},
        "recent_5": recent,
        "reference": reference,
    }


def _players_for_team(player_data: Any, team_id: Any) -> List[Dict[str, Any]]:
    players: List[Dict[str, Any]] = []
    for page in ((player_data or {}).get("pages") or []):
        if isinstance(page, dict):
            players.extend(item for item in (page.get("data") or []) if isinstance(item, dict) and _same_team_id(item.get("club_team_id"), team_id))
    return players


def _player_team_summary(player_data: Any, team_id: Any, expected_matches: Any = None) -> Dict[str, Any]:
    players = _players_for_team(player_data, team_id)
    minutes = sum(num(player.get("minutes_played_overall")) or 0 for player in players)
    goals = sum(num(player.get("goals_overall")) or 0 for player in players)
    assists = sum(num(player.get("assists_overall")) or 0 for player in players)
    contributions = goals + assists
    goal_ranks = sorted((num(player.get("goals_overall")) or 0 for player in players), reverse=True)
    contribution_ranks = sorted(((num(player.get("goals_overall")) or 0) + (num(player.get("assists_overall")) or 0) for player in players), reverse=True)
    top3_goal_share = sum(goal_ranks[:3]) / goals if goals > 0 else None
    top3_contribution_share = sum(contribution_ranks[:3]) / contributions if contributions > 0 else None
    expected_minutes = (num(expected_matches) or 0) * 11 * 90
    minutes_coverage = min(1.0, minutes / expected_minutes) if expected_minutes > 0 else None
    concentration = "NICHT BEWERTBAR"
    if top3_contribution_share is not None:
        concentration = "HOCH" if top3_contribution_share >= .75 else ("MITTEL" if top3_contribution_share >= .60 else "NIEDRIG")
    return {
        "available": bool(players),
        "players_found": len(players),
        "minutes": round(minutes, 1),
        "minutes_coverage_pct": round(minutes_coverage * 100, 1) if minutes_coverage is not None else None,
        "goals_per_90": round(goals * 90 / minutes, 3) if minutes > 0 else None,
        "assists_per_90": round(assists * 90 / minutes, 3) if minutes > 0 else None,
        "top3_goal_share_pct": round(top3_goal_share * 100, 1) if top3_goal_share is not None else None,
        "top3_contribution_share_pct": round(top3_contribution_share * 100, 1) if top3_contribution_share is not None else None,
        "concentration_risk": concentration,
        "lineups_confirmed": False,
    }


def _overall_matches(league_data: Any, team_id: Any, venue: str) -> Any:
    team = team_obj(league_data, team_id) if league_data is not None and team_id is not None else None
    return profile(team, venue)["overall"].get("matches") if team else None


def supplemental_report(match_data: Any, league_data: Any = None, form_data: Any = None, table_data: Any = None, player_data: Any = None) -> Dict[str, Any]:
    """Use all V2 sources for audit and risk checks, never inventing unbacktested probability weights."""
    match = mf(match_data)
    home_id, away_id = match.get("home_id"), match.get("away_id")
    home_matches = _overall_matches(league_data, home_id, "home")
    away_matches = _overall_matches(league_data, away_id, "away")
    form = {"home": _form_team_summary(form_data, home_id), "away": _form_team_summary(form_data, away_id)}
    table = {"home": _table_team_summary(table_data, home_id, "home"), "away": _table_team_summary(table_data, away_id, "away")}
    player = {
        "home": _player_team_summary(player_data, home_id, home_matches),
        "away": _player_team_summary(player_data, away_id, away_matches),
    }
    return {
        "received": {"form": form_data is not None, "table": table_data is not None, "player": player_data is not None},
        "coverage": {
            "form": {**form, "usable_both": form["home"]["available"] and form["away"]["available"]},
            "table": {**table, "usable_both": table["home"]["available"] and table["away"]["available"]},
            "player": {**player, "usable_both": player["home"]["available"] and player["away"]["available"]},
        },
        "model_use": {
            "table": "IDs sowie Overall-/Home-/Away-Abdeckung werden gegengeprüft; keine doppelte PPG-/Tore-Gewichtung.",
            "form": "Last-5 gegen längeres Formfenster ist ein Gegenargument-/Stabilitätssignal, keine unkalibrierte Wahrscheinlichkeitserhöhung.",
            "player": "Tiefe und Torbeteiligungs-Konzentration werden transparent berichtet; ohne bestätigte Aufstellung keine Match-Score-Gewichtung.",
        },
    }


def _form_delta(team: Dict[str, Any], metric: str) -> Optional[float]:
    recent, reference = team.get("recent_5") or {}, team.get("reference") or {}
    if (reference.get("sample") or 0) < 8:
        return None
    current, baseline = num(recent.get(metric)), num(reference.get(metric))
    return current - baseline if current is not None and baseline is not None else None


def _mean_known(values: List[Optional[float]]) -> Optional[float]:
    known = [value for value in values if value is not None]
    return sum(known) / len(known) if known else None


def _form_market_signal(form_coverage: Dict[str, Any], market: str) -> Dict[str, Any]:
    home, away = form_coverage.get("home") or {}, form_coverage.get("away") or {}
    if not (home.get("available") and away.get("available")):
        return {"status": "NICHT VERFÜGBAR", "reason": "Formfenster nicht für beide Teams vorhanden."}
    if market == "home_win":
        score = _form_delta(home, "ppg")
        away_delta = _form_delta(away, "ppg")
        score = score - away_delta if score is not None and away_delta is not None else None
        positive = score is not None and score >= .50
        negative = score is not None and score <= -.50
    elif market == "away_win":
        score = _form_delta(away, "ppg")
        home_delta = _form_delta(home, "ppg")
        score = score - home_delta if score is not None and home_delta is not None else None
        positive = score is not None and score >= .50
        negative = score is not None and score <= -.50
    elif market in {"btts_yes", "btts_no"}:
        score = _mean_known([_form_delta(home, "btts_pct"), _form_delta(away, "btts_pct")])
        if market == "btts_no" and score is not None:
            score = -score
        positive = score is not None and score >= 15
        negative = score is not None and score <= -15
    else:
        metric = "over_25_pct" if market == "over_2_5" else "under_25_pct"
        score = _mean_known([_form_delta(home, metric), _form_delta(away, metric)])
        positive = score is not None and score >= 15
        negative = score is not None and score <= -15
    status = "BESTÄTIGEND" if positive else ("GEGENARGUMENT" if negative else ("NEUTRAL" if score is not None else "NICHT VERFÜGBAR"))
    return {
        "status": status,
        "reason": "Last-5 gegen längeres Formfenster; nur als unabhängiger Gegencheck verwendet.",
        "delta": round(score, 2) if score is not None else None,
    }


def _coherence_check(probabilities: Dict[str, Any]) -> Dict[str, Any]:
    if not probabilities:
        return {"passed": False, "checks": {}}
    pairs = {
        "btts": (num(probabilities.get("btts_yes")), num(probabilities.get("btts_no"))),
        "goals": (num(probabilities.get("over_2_5")), num(probabilities.get("under_2_5"))),
        "result": (num(probabilities.get("home_win")), num(probabilities.get("draw")), num(probabilities.get("away_win"))),
    }
    checks = {
        "btts": all(value is not None for value in pairs["btts"]) and abs(sum(pairs["btts"]) - 1) <= .002,
        "goals": all(value is not None for value in pairs["goals"]) and abs(sum(pairs["goals"]) - 1) <= .002,
        "result": all(value is not None for value in pairs["result"]) and abs(sum(pairs["result"]) - 1) <= .002,
    }
    return {"passed": all(checks.values()), "checks": checks}


def _central_signal_blocks(result: Dict[str, Any]) -> List[str]:
    blocks: List[str] = []
    expected = result.get("expected_goals") or {}
    if expected.get("home") is not None and expected.get("away") is not None:
        blocks.append("UNDERLYING")
    samples = result.get("samples") or {}
    if (num(samples.get("home_venue")) or 0) >= 4 and (num(samples.get("away_venue")) or 0) >= 4:
        blocks.append("VENUE")
    match = ((result.get("audit") or {}).get("match") or {})
    if any(match.get(key) is not None for key in ("home_prematch_xg", "away_prematch_xg", "btts_potential", "o25_potential", "pre_match_home_ppg", "pre_match_away_ppg")):
        blocks.append("PRE_MATCH")
    if (result.get("diagnostics") or {}).get("result_vs_underlying") in {"KONSISTENT", "TEILWEISE KONSISTENT"}:
        blocks.append("RESULTAT")
    return blocks


def elite_protocol_report(result: Dict[str, Any], report: Dict[str, Any]) -> Dict[str, Any]:
    """V5.2-inspired guardrails; separate correlated sources from independent evidence."""
    if not result.get("ok"):
        return {
            "version": "0.4.0 / V5.5 liga-relativ + V5.2-Guardrails",
            "phase_1_data_audit": "NICHT BESTANDEN",
            "phase_2_all_six_markets": "NEIN",
            "phase_3_decision_gates": "NEIN",
            "final_decision": result.get("decision"),
            "reason": "Kernanalyse war nicht gültig; keine Ersatzprognose aus Zusatzdateien.",
        }
    diagnostics = result.get("diagnostics") or {}
    coverage = report.get("coverage") or {}
    received = report.get("received") or {}
    unusable = [kind for kind, was_received in received.items() if was_received and not (coverage.get(kind) or {}).get("usable_both")]
    quality = diagnostics.get("data_quality") or "MITTEL"
    protocol_quality = "NIEDRIG" if quality == "NIEDRIG" else ("MITTEL" if unusable else quality)
    top = (result.get("strongest_market") or {}).get("key")
    top_probability = num((result.get("strongest_market") or {}).get("probability_pct"))
    form_signal = _form_market_signal(coverage.get("form") or {}, top) if top else {"status": "NICHT VERFÜGBAR"}
    blocks = _central_signal_blocks(result)
    multi_block = "BESTANDEN" if len(blocks) >= 3 else ("EINGESCHRÄNKT" if len(blocks) >= 2 else "NICHT BESTANDEN")
    coherence = _coherence_check(result.get("probabilities") or {})
    candidate = top_probability is not None and top_probability >= 65
    influence = num(diagnostics.get("influence_stress_probability_pct"))
    fragility = num(diagnostics.get("fragility_stress_probability_pct"))
    single_point = bool(diagnostics.get("single_point_of_failure"))
    def removal_status(value: Optional[float]) -> str:
        if not candidate:
            return "NICHT ERFORDERLICH FÜR SPIELEN"
        if value is not None and value >= 63 and not single_point:
            return "BESTANDEN"
        if value is not None and value >= 60:
            return "EINGESCHRÄNKT"
        return "NICHT BESTANDEN"
    influence_status, fragility_status = removal_status(influence), removal_status(fragility)
    sample_security = (result.get("samples") or {}).get("security")
    sample_gate = "BESTANDEN" if sample_security == "HOCH" else ("EINGESCHRÄNKT" if sample_security == "MITTEL" else "NICHT BESTANDEN")
    base_counter = diagnostics.get("counterargument") or "NICHT VERFÜGBAR"
    counter_status = "STARK" if "STARK" in base_counter or "DOMINANT" in base_counter else ("RELEVANT" if form_signal.get("status") == "GEGENARGUMENT" else "KEIN RELEVANTES")
    final_decision = result.get("decision")
    cap_reasons: List[str] = []
    if final_decision == "SPIELEN":
        if multi_block != "BESTANDEN":
            cap_reasons.append("weniger als drei getrennte zentrale Signalblöcke")
        if counter_status in {"STARK", "RELEVANT"}:
            cap_reasons.append("relevantes Gegenargument im V5.2-Gegencheck")
        if influence_status != "BESTANDEN" or fragility_status != "BESTANDEN":
            cap_reasons.append("Removal-Test nicht vollständig bestanden")
        if sample_gate == "NICHT BESTANDEN":
            cap_reasons.append("Venue-Stichprobe nicht ausreichend")
        if protocol_quality == "NIEDRIG":
            cap_reasons.append("Datenqualität zu niedrig")
        if not coherence.get("passed"):
            cap_reasons.append("Wahrscheinlichkeits-Kohärenz fehlgeschlagen")
        if cap_reasons:
            final_decision = "BEOBACHTEN"
    return {
        "version": "0.4.0 / V5.5 liga-relativ + V5.2-Guardrails",
        "scope": "Liga-relative xG-Wahrscheinlichkeiten plus Audit-, Gegenargument- und Robustheitsprotokoll. Form, Tabelle und Spieler bleiben ohne zeitbasierten Backtest diagnostische Gegenchecks.",
        "phase_1_data_audit": "EINGESCHRÄNKT" if unusable else "BESTANDEN",
        "phase_2_all_six_markets": "JA" if len(result.get("markets") or []) == 6 else "NEIN",
        "phase_3_decision_gates": "JA",
        "source_integration": {
            "form": {"received": received.get("form", False), "usable_both": (coverage.get("form") or {}).get("usable_both", False), "use": "Trend-/Gegenargument-Prüfung"},
            "table": {"received": received.get("table", False), "usable_both": (coverage.get("table") or {}).get("usable_both", False), "use": "ID- und Venue-Konsistenzprüfung"},
            "player": {"received": received.get("player", False), "usable_both": (coverage.get("player") or {}).get("usable_both", False), "use": "Kaderabdeckung/-konzentration, keine Aufstellungsannahme"},
            "unusable_received_sources": unusable,
        },
        "gates": {
            "probability": "BESTANDEN" if candidate else ("BEOBACHTEN" if top_probability is not None and top_probability >= 60 else "NICHT BESTANDEN"),
            "multi_block_confirmation": multi_block,
            "counterargument": {"status": counter_status, "base": base_counter, "form": form_signal},
            "influence_removal": {"status": influence_status, "tested_block": diagnostics.get("influence_block") or "NICHT ERMITTELBAR", "probability_pct": influence},
            "fragility_removal": {"status": fragility_status, "tested_block": diagnostics.get("fragility_block") or "NICHT ERMITTELBAR", "probability_pct": fragility},
            "small_sample_stress": sample_gate,
            "result_vs_underlying": diagnostics.get("result_vs_underlying"),
            "relative_edge": diagnostics.get("relative_edge"),
            "data_quality": protocol_quality,
            "coherence": coherence,
        },
        "central_signal_blocks": blocks,
        "final_decision": final_decision,
        "decision_cap_applied": bool(cap_reasons),
        "decision_cap_reasons": cap_reasons,
    }


def _attach_supplemental(result: Dict[str, Any], report: Dict[str, Any], source_files: Dict[str, str]) -> Dict[str, Any]:
    result = dict(result)
    diagnostics = dict(result.get("diagnostics") or {})
    protocol = elite_protocol_report(result, report)
    diagnostics["supplemental_inputs"] = report
    diagnostics["elite_protocol"] = protocol
    result["diagnostics"] = diagnostics
    result["input_sources"] = source_files
    previous_decision = result.get("decision")
    if result.get("ok") and protocol.get("final_decision") and protocol["final_decision"] != previous_decision:
        result["decision_before_v5_2_guardrails"] = previous_decision
        result["decision"] = protocol["final_decision"]
        result["notes"] = list(result.get("notes") or []) + ["V5.2-Guardrails haben die Entscheidung wegen: " + "; ".join(protocol.get("decision_cap_reasons") or []) + "."]
    result["model_version"] = "0.4.0"
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
    by_kind: Dict[str, List[Dict[str, Any]]] = {kind: [] for kind in ("match", "league", "form", "table", "player", "forebet")}
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
    if not by_kind["forebet"]:
        return {"ok":False,"decision":"ANALYSE NICHT MÖGLICH","phase":"FOREBET_DATA_MISSING","error":"ForebetDaten-Datei fehlt. Die Super Analyse benötigt fünf FootyStats-Dateien und eine ForebetDaten-Datei.","match_file":match_file["name"]}
    forebet_file = by_kind["forebet"][0]
    if str(int(match_fields.get("match_id"))) not in forebet_file["name"]:
        return {"ok":False,"decision":"ANALYSE NICHT MÖGLICH","phase":"PAIRING_FAILED","error":"ForebetDaten-Dateiname enthält nicht die Match-ID der FootyStats-Dateien.","match_file":match_file["name"],"forebet_file":forebet_file["name"]}
    source_files = {kind: items[0]["name"] for kind, items in by_kind.items() if items}
    supplemental_data = {kind: items[0]["data"] for kind, items in by_kind.items() if kind in {"form", "table", "player"} and items}
    return {"ok":True,"match_file":match_file["name"],"league_file":best["name"],"forebet_file":forebet_file["name"],"match_data":match_file["data"],"league_data":best["data"],"forebet_data":forebet_file["data"],"supplemental_data":supplemental_data,"source_files":source_files,"pairing":{"match_id":match_fields.get("match_id"),"competition_id":match_fields.get("competition_id"),"home_id":match_fields.get("home_id"),"away_id":match_fields.get("away_id"),"league_score":best["score"],"league_reasons":best["reasons"]}}

# ---- Local iPhone archive package (no server-side persistence) ----
_ARCHIVE_VERSION = "2.0.0"
_ARCHIVE_SOURCE_KINDS = ("match", "league", "form", "table", "player", "forebet")
_ARCHIVE_SECRET_PARTS = ("apikey", "token", "authorization", "password", "secret", "credential")
_ARCHIVE_SENSITIVE_QUERY = re.compile(r"(?i)(api[_-]?key|token|authorization|password|secret)=([^&\s]+)")


def _archive_key_blocked(key: Any) -> bool:
    normal = nkey(str(key)).replace("_", "")
    return "odds" in normal or any(part in normal for part in _ARCHIVE_SECRET_PARTS)


def _archive_sanitize(value: Any) -> Any:
    """Remove odds and secret-like fields before an archive leaves the browser."""
    if isinstance(value, dict):
        return {
            str(key): _archive_sanitize(child)
            for key, child in value.items()
            if not _archive_key_blocked(key)
        }
    if isinstance(value, list):
        return [_archive_sanitize(child) for child in value]
    if isinstance(value, str):
        return _ARCHIVE_SENSITIVE_QUERY.sub(r"\1=REDACTED", value)
    return value


def _archive_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _archive_sha256(value: Any) -> str:
    return hashlib.sha256(_archive_bytes(value)).hexdigest()


def _archive_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _archive_name_piece(value: Any, fallback: str = "unbekannt") -> str:
    piece = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value or fallback)).strip("-")
    return (piece or fallback)[:72]


def _archive_sources(parsed_files: List[Dict[str, Any]], pair: Dict[str, Any]) -> Dict[str, Any]:
    wanted = {
        "match": pair.get("match_file"),
        "league": pair.get("league_file"),
    }
    wanted.update(pair.get("source_files") or {})
    sources: Dict[str, Any] = {}
    for kind in _ARCHIVE_SOURCE_KINDS:
        filename = wanted.get(kind)
        if not filename:
            continue
        item = next((candidate for candidate in parsed_files if candidate.get("name") == filename), None)
        if item is None:
            continue
        content = _archive_sanitize(item.get("data"))
        sources[kind] = {
            "filename": _archive_sanitize(str(filename)),
            "sha256": _archive_sha256(content),
            "content": content,
        }
    return sources


def _archive_package(parsed_files: List[Dict[str, Any]], pair: Dict[str, Any], result: Dict[str, Any]) -> Dict[str, Any]:
    created_at = _archive_now()
    match = dict(((result.get("audit") or {}).get("match") or mf(pair.get("match_data") or {})))
    sources = _archive_sources(parsed_files, pair)
    source_hashes = {kind: item["sha256"] for kind, item in sources.items()}
    fingerprint = _archive_sha256({
        "match_id": match.get("match_id"),
        "created_at": created_at,
        "source_hashes": source_hashes,
        "model_version": result.get("model_version"),
    })
    available = sorted(sources)
    return {
        "archive_schema": "footystats-forebet-ios-archive-v2",
        "archive_version": _ARCHIVE_VERSION,
        "record_id": f"{_archive_name_piece(match.get('match_id'), 'match')}-{created_at.replace(':', '').replace('-', '')}-{fingerprint[:10]}",
        "created_at": created_at,
        "storage": "iphone_or_icloud_only",
        "server_side_persistence": False,
        "match": _archive_sanitize({
            "match_id": match.get("match_id"),
            "home_name": match.get("home_name"),
            "away_name": match.get("away_name"),
            "competition_id": match.get("competition_id"),
            "season": match.get("season"),
            "date": match.get("date"),
        }),
        "analysis": _archive_sanitize(result),
        "sources": sources,
        "source_coverage": {
            "expected": list(_ARCHIVE_SOURCE_KINDS),
            "available": available,
            "missing": [kind for kind in _ARCHIVE_SOURCE_KINDS if kind not in sources],
        },
        "policies": {
            "odds_removed_before_download": True,
            "secret_like_fields_removed_before_download": True,
            "external_data_used": True,
            "forebet_public_prediction_snapshot": True,
            "forebet_odds_used": False,
            "actual_result_pending": True,
        },
    }


def _archive_download_name(package: Dict[str, Any]) -> str:
    match = package.get("match") or {}
    decision = ((package.get("analysis") or {}).get("decision")) or "ANALYSE"
    stamp = str(package.get("created_at") or "").replace(":", "").replace("-", "")
    return "FootyStats-Forebet-Archiv-{}-{}-vs-{}-{}-{}.json".format(
        _archive_name_piece(match.get("match_id"), "match"),
        _archive_name_piece(match.get("home_name"), "heim"),
        _archive_name_piece(match.get("away_name"), "auswaerts"),
        _archive_name_piece(decision, "analyse"),
        _archive_name_piece(stamp, "zeit"),
    )


async def _read_bundle_uploads(files: List[UploadFile]) -> Any:
    parsed: List[Dict[str, Any]] = []
    errors: List[Dict[str, str]] = []
    for upload in files:
        name = upload.filename or "unbekannt.json"
        if not name.lower().endswith(".json"):
            continue
        try:
            raw = await upload.read()
            parsed.append({"name": name, "data": json.loads(raw.decode("utf-8"))})
        except Exception as exc:
            errors.append({"name": name, "error": str(exc)})
    return parsed, errors


def _analyze_bundle(parsed_files: List[Dict[str, Any]]) -> Dict[str, Any]:
    pair = select_pair(parsed_files)
    if not pair.get("ok"):
        return pair
    extras = pair.get("supplemental_data") or {}
    report = supplemental_report(
        pair["match_data"],
        pair["league_data"],
        extras.get("form"),
        extras.get("table"),
        extras.get("player"),
    )
    result = _attach_supplemental(
        predict(pair["match_data"], pair["league_data"]),
        report,
        pair.get("source_files") or {},
    )
    try:
        forebet = _forebet_snapshot(pair["forebet_data"], mf(pair["match_data"]))
    except ValueError as exc:
        return {"ok":False,"model_version":"0.9.2","phase":"FOREBET_VALIDATION_FAILED","decision":"ANALYSE NICHT MÖGLICH","error":str(exc),"pairing":pair.get("pairing"),"input_sources":pair.get("source_files") or {}}
    result = _attach_forebet_ensemble(result, forebet)
    result["pairing"] = {
        **pair["pairing"],
        "match_file": pair["match_file"],
        "league_file": pair["league_file"],
        "forebet_file": pair["forebet_file"],
    }
    result["_archive_pair"] = pair
    return result


INDEX_HTML = r'''<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>FootyStats + Forebet Super Analyse</title>
<style>
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:#f3f4f6;margin:0;color:#111827}
.w{max-width:900px;margin:auto;padding:18px}.c{background:#fff;border-radius:15px;padding:17px;margin:12px 0;box-shadow:0 1px 5px #0001}
.g{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:9px}.m{border:1px solid #e5e7eb;border-radius:11px;padding:11px}
.b{font-size:1.2rem;font-weight:700}.s{font-size:.85rem;color:#6b7280}.ok{color:#047857}.bad{color:#b91c1c}
button{width:100%;padding:13px;border:0;border-radius:11px;background:#111827;color:#fff;font-weight:700;font-size:1rem;margin-top:8px}
button.secondary{background:#2563eb}button:disabled{opacity:.55}input{width:100%;margin:7px 0 14px}
table{width:100%;border-collapse:collapse}td,th{padding:8px;border-bottom:1px solid #eee;text-align:left}
pre{white-space:pre-wrap;word-break:break-word;font-size:.75rem}.sep{border-top:1px solid #e5e7eb;margin:18px 0}
</style>
</head>
<body>
<div class="w">
  <div class="c">
    <h2>FootyStats + Forebet ELITE Analyse v0.9.2</h2>
    <div class="s">FootyStats-V5.5-Kern + Forebet-Konsensmodell · keine Odds · INSUFFICIENT_DATA-Sperre und V5.2-Guardrails aktiv</div>
    <h3>Match-Ordner auswählen</h3>
    <p class="s">Empfohlen: MatchDaten, LeagueDaten, FormDaten, TableDaten, PlayerDaten und ForebetDaten desselben Matches auswählen.</p>
    <input id="folderFiles" type="file" webkitdirectory directory multiple accept=".json,application/json">
    <div class="sep"></div>
    <h3>Fallback: JSON-Dateien gemeinsam auswählen</h3>
    <p class="s">Falls die Ordnerauswahl am iPhone nicht angeboten wird, wähle hier alle sechs JSON-Dateien gleichzeitig aus.</p>
    <input id="bundleFiles" type="file" multiple accept=".json,application/json">
    <button id="go">Analyse starten</button>
  </div>
  <div id="out"></div>
</div>
<script>
function chosenFiles(){
  const folder=[...document.getElementById('folderFiles').files];
  if(folder.length)return folder;
  return [...document.getElementById('bundleFiles').files];
}
function escapeHtml(value){
  return String(value==null?'':value).replace(/[&<>"']/g,function(c){
    return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];
  });
}
function formFor(files){
  const form=new FormData();
  files.forEach(function(file){form.append('files',file,file.webkitRelativePath||file.name);});
  return form;
}
async function downloadArchive(files,status){
  status.className='s';
  status.textContent='Archivpaket wird vorbereitet…';
  const response=await fetch('/api/archive-bundle',{method:'POST',body:formFor(files)});
  const disposition=response.headers.get('content-disposition')||'';
  if(!response.ok||!disposition){
    let message='Archivpaket konnte nicht erstellt werden.';
    try{const problem=await response.json();message=problem.error||problem.detail||message;}catch(ignore){}
    throw new Error(message);
  }
  const blob=await response.blob();
  const match=disposition.match(/filename="([^"]+)"/);
  const name=match?match[1]:'FootyStats-Forebet-Archiv.json';
  const url=URL.createObjectURL(blob);
  const link=document.createElement('a');
  link.href=url;link.download=name;document.body.appendChild(link);link.click();link.remove();
  setTimeout(function(){URL.revokeObjectURL(url);},5000);
  status.className='s ok';
  status.textContent='Archivpaket heruntergeladen. Safari speichert es in deinem eingestellten Downloads-Ordner.';
}
document.getElementById('go').onclick=async function(){
  const files=chosenFiles(),out=document.getElementById('out');
  if(files.length<6){
    out.innerHTML='<div class="c bad"><b>Fünf FootyStats-Dateien und eine ForebetDaten-Datei nötig.</b></div>';return;
  }
  out.innerHTML='<div class="c">Paket wird geprüft und analysiert…</div>';
  try{
    const response=await fetch('/api/predict-bundle',{method:'POST',body:formFor(files)});
    const data=await response.json();
    if(!data.ok){
      out.innerHTML='<div class="c"><h3 class="bad">Analyse nicht möglich</h3><pre>'+escapeHtml(JSON.stringify(data,null,2))+'</pre></div>';return;
    }
    const diag=data.diagnostics||{},goal=data.expected_goals||{},protocol=diag.elite_protocol||{},gates=protocol.gates||{},rvu=diag.result_vs_underlying_detail||{},ensemble=data.ensemble||{},forebet=data.forebet_model||{};
    const rows=(data.markets||[]).map(function(item){
      return '<tr><td>'+escapeHtml(item.rank)+'</td><td>'+escapeHtml(item.label)+'</td><td><b>'+escapeHtml(item.probability_pct)+'%</b></td></tr>';
    }).join('');
    const sources=Object.entries(data.input_sources||{}).map(function(entry){
      return escapeHtml(entry[0])+': '+escapeHtml(entry[1]);
    }).join('<br>');
    const comparison=(ensemble.market_comparison||[]).map(function(item){
      return '<tr><td>'+escapeHtml(item.label)+'</td><td>'+escapeHtml(item.footystats_probability_pct)+'%</td><td>'+escapeHtml(item.forebet_probability_pct)+'%</td><td><b>'+escapeHtml(item.combined_probability_pct)+'%</b></td><td>'+escapeHtml(item.difference_pp)+' PP</td></tr>';
    }).join('');
    out.innerHTML=
      '<div class="c"><div class="ok"><b>Dateien automatisch zugeordnet</b></div><p class="s">'+
      (sources||'Match: '+escapeHtml((data.pairing||{}).match_file)+'<br>League: '+escapeHtml((data.pairing||{}).league_file))+
      '</p></div>'+
      '<div class="c"><h3>Kurzentscheidung</h3><div class="g">'+
      '<div class="m"><div class="s">Bester Markt</div><div class="b">'+escapeHtml((data.strongest_market||{}).label)+'</div></div>'+
      '<div class="m"><div class="s">Wahrscheinlichkeit</div><div class="b">'+escapeHtml((data.strongest_market||{}).probability_pct)+'%</div></div>'+
      '<div class="m"><div class="s">Entscheidung</div><div class="b">'+escapeHtml(data.decision)+'</div></div>'+
      '<div class="m"><div class="s">Datenqualität</div><b>'+escapeHtml(diag.data_quality)+'</b></div>'+
      '<div class="m"><div class="s">Stichprobe</div><b>'+escapeHtml(diag.sample_security)+'</b></div>'+
      '<div class="m"><div class="s">V5.2-Protokoll</div><b>'+escapeHtml(protocol.phase_1_data_audit||'—')+' / '+escapeHtml(protocol.phase_2_all_six_markets||'—')+'</b></div>'+
      '<div class="m"><div class="s">Modellkonsens</div><b>'+escapeHtml(ensemble.agreement_status||'—')+'</b><div class="s">Differenz Top-Markt '+escapeHtml(ensemble.top_market_difference_pp==null?'—':ensemble.top_market_difference_pp+' PP')+'</div></div>'+
      '</div></div>'+
      '<div class="c"><h3>FootyStats + Forebet Vergleich</h3><div class="g">'+
      '<div class="m"><div class="s">Forebet Ergebnistipp</div><div class="b">'+escapeHtml(forebet.predicted_score||'—')+'</div><div class="s">Ø Tore '+escapeHtml(forebet.average_goals==null?'—':forebet.average_goals)+'</div></div>'+
      '<div class="m"><div class="s">FootyStats Top-Markt</div><div class="b">'+escapeHtml(ensemble.footystats_top_market||'—')+'</div></div>'+
      '<div class="m"><div class="s">Forebet Top-Markt</div><div class="b">'+escapeHtml(ensemble.forebet_top_market||'—')+'</div></div>'+
      '<div class="m"><div class="s">Gemeinsamer Top-Markt</div><div class="b">'+escapeHtml(ensemble.combined_top_market||'—')+'</div></div>'+
      '</div><table><tr><th>Markt</th><th>FootyStats</th><th>Forebet</th><th>Gemeinsam</th><th>Differenz</th></tr>'+comparison+'</table></div>'+
      '<div class="c"><h3>FootyStats Result vs Underlying</h3><div class="g">'+
      '<div class="m"><div class="s">Result (historische Quote)</div><div class="b">'+escapeHtml(rvu.result_probability_pct==null?'—':rvu.result_probability_pct+'%')+'</div><div class="s">'+escapeHtml(rvu.result_basis||'Nicht verfügbar')+'</div></div>'+
      '<div class="m"><div class="s">Underlying (xG-Modell)</div><div class="b">'+escapeHtml(rvu.underlying_probability_pct==null?'—':rvu.underlying_probability_pct+'%')+'</div><div class="s">λ Heim '+escapeHtml((rvu.underlying_expected_goals||{}).home||'—')+' · λ Auswärts '+escapeHtml((rvu.underlying_expected_goals||{}).away||'—')+'</div></div>'+
      '<div class="m"><div class="s">Prüfstatus</div><div class="b">'+escapeHtml(rvu.status||diag.result_vs_underlying||'—')+'</div><div class="s">Differenz '+escapeHtml(rvu.difference_pp==null?'—':rvu.difference_pp+' Prozentpunkte')+'</div></div>'+
      '</div></div>'+
      '<div class="c"><h3>Alle Märkte</h3><table><tr><th>Rang</th><th>Markt</th><th>Modell</th></tr>'+rows+'</table></div>'+
      '<div class="c"><h3>Gemeinsames Archiv</h3><p class="s">Speichert die Analyse, alle fünf FootyStats-Quellen und den Forebet-Snapshot gemeinsam. Es wird nichts dauerhaft auf Render gespeichert.</p><button class="secondary" id="archive">Gemeinsames Archiv herunterladen</button><p id="archiveStatus" class="s"></p></div>'+
      '<div class="c"><details><summary>Technische Diagnose</summary><pre>'+escapeHtml(JSON.stringify(data,null,2))+'</pre></details></div>';
    document.getElementById('archive').onclick=async function(){
      const button=document.getElementById('archive'),status=document.getElementById('archiveStatus');
      button.disabled=true;
      try{await downloadArchive(files,status);}
      catch(error){status.className='s bad';status.textContent='Fehler: '+String(error);}
      finally{button.disabled=false;}
    };
  }catch(error){
    out.innerHTML='<div class="c bad">Fehler: '+escapeHtml(String(error))+'</div>';
  }
};
</script>
</body>
</html>'''

@app.get("/",response_class=HTMLResponse)
def index():return INDEX_HTML
@app.get("/api/health")
def health():return {"ok":True,"version":"0.9.2","footystats_backup":"0.4.0","forebet_ensemble":True,"v2_match_selection":True,"single_joint_archive":True,"ios_direct_archive":True,"server_side_forebet_repair":True,"hubsign_format":"AEA1","shortcut_delivery":"pre_signed"}
@app.post("/api/predict")
def predict_json(payload:Payload):
    report = supplemental_report(payload.matchData, payload.leagueData, payload.formData, payload.tableData, payload.playerData)
    result = _attach_supplemental(predict(payload.matchData, payload.leagueData), report, {})
    try:
        forebet = _forebet_snapshot(payload.forebetData, mf(payload.matchData))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return _attach_forebet_ensemble(result, forebet)


def _payload_as_bundle(payload: Payload) -> List[Dict[str, Any]]:
    match_fields = mf(payload.matchData)
    match_id = int(match_fields.get("match_id") or 0)
    competition_id = int(match_fields.get("competition_id") or 0)
    return [
        {"name": f"{match_id}_MatchDaten.json", "data": payload.matchData},
        {"name": f"{competition_id}_LeagueDaten.json", "data": payload.leagueData},
        {"name": f"{match_id}_FormDaten.json", "data": payload.formData or {}},
        {"name": f"{match_id}_TableDaten.json", "data": payload.tableData or {}},
        {"name": f"{match_id}_PlayerDaten.json", "data": payload.playerData or {}},
        {"name": f"{match_id}_ForebetDaten.json", "data": payload.forebetData},
    ]


@app.post("/api/elite-candidate")
def elite_candidate(payload: Payload):
    """Analyze one fixture and expose an archive only after every SPIELEN gate passed."""
    parsed = _payload_as_bundle(payload)
    result = _analyze_bundle(parsed)
    pair = result.pop("_archive_pair", None)
    decision = result.get("decision") or "ANALYSE NICHT MÖGLICH"
    match = mf(payload.matchData)
    response: Dict[str, Any] = {
        "ok": bool(result.get("ok")),
        "save": False,
        "decision": decision,
        "match_id": match.get("match_id"),
        "home_name": match.get("home_name"),
        "away_name": match.get("away_name"),
        "phase": result.get("phase"),
    }
    if result.get("ok") and decision == "SPIELEN" and pair:
        response["save"] = True
        response["archive"] = _archive_package(parsed, pair, result)
    return response


@app.post("/api/selected-analysis")
def selected_analysis(payload: Payload):
    """Analyze the single fixture selected by the user and return one joint archive."""
    parsed = _payload_as_bundle(payload)
    pair = select_pair(parsed)
    result = _analyze_bundle(parsed)
    result.pop("_archive_pair", None)
    if not pair.get("ok"):
        return {
            "ok": False,
            "decision": "ANALYSE NICHT MÖGLICH",
            "phase": pair.get("phase") or "PAIRING_FAILED",
            "error": pair.get("error"),
        }
    package = _archive_package(parsed, pair, result)
    return {
        "ok": bool(result.get("ok")),
        "decision": result.get("decision") or "ANALYSE NICHT MÖGLICH",
        "archive": package,
    }


def _ios_diagnostic_archive(phase: str, error: str, received_types: Dict[str, str]) -> Dict[str, Any]:
    return {
        "archive_schema": "footystats-forebet-ios-diagnostic-v1",
        "created_at": _archive_now(),
        "storage": "iphone_or_icloud_only",
        "server_side_persistence": False,
        "analysis": {
            "ok": False,
            "decision": "ANALYSE NICHT MÖGLICH",
            "phase": phase,
            "error": error,
            "received_types": received_types,
        },
        "source_coverage": {
            "expected": list(_ARCHIVE_SOURCE_KINDS),
            "available": [],
            "missing": list(_ARCHIVE_SOURCE_KINDS),
        },
    }


def _ios_dictionary(value: Any, field: str) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        decoded = json.loads(value)
        if isinstance(decoded, dict):
            return decoded
    raise ValueError(f"{field} wurde vom iPhone nicht als JSON-Wörterbuch übertragen.")


def _forebet_match_date(match_data: Dict[str, Any]) -> Optional[str]:
    """Read the fixture date from FootyStats, including its Unix timestamp form."""
    match = match_obj(match_data) or {}
    raw_date = first(match, ["date", "match_date", "date_iso"])
    if raw_date not in (None, ""):
        text_date = str(raw_date).strip()
        if re.match(r"^\d{4}-\d{2}-\d{2}", text_date):
            return text_date[:10]

    timestamp = firstnum(match, ["date_unix", "dateUnix", "unix_timestamp", "timestamp"])
    if timestamp is None:
        return None
    if timestamp > 10_000_000_000:
        timestamp /= 1000
    try:
        return datetime.fromtimestamp(timestamp, timezone.utc).date().isoformat()
    except (OverflowError, OSError, ValueError):
        return None


def _repair_forebet_from_match_data(
    match_data: Dict[str, Any],
    forebet_data: Dict[str, Any],
) -> tuple[Dict[str, Any], bool]:
    """Replace an invalid iPhone Forebet response using trusted MatchDaten identity."""
    match = mf(match_data)
    try:
        _forebet_snapshot(forebet_data, match)
        return forebet_data, False
    except ValueError as original_error:
        match_id = int(match.get("match_id") or 0)
        home = str(match.get("home_name") or "").strip()
        away = str(match.get("away_name") or "").strip()
        match_date = _forebet_match_date(match_data)
        if not match_id or not home or not away:
            raise ValueError(
                "Forebet konnte nicht repariert werden: Match-ID oder Teamnamen fehlen in MatchDaten."
            ) from original_error

        from forebet_auto import ForebetAutoError
        from forebet_auto_v5 import build_snapshot

        try:
            repaired = build_snapshot(
                match_id=match_id,
                home=home,
                away=away,
                date=match_date,
            )
        except ForebetAutoError as exc:
            return {
                "ok": False,
                "schema": "forebet-auto-error-v1",
                "phase": "FOREBET_SERVER_REPAIR_FAILED",
                "error": str(exc),
                "match_id": match_id,
                "home": home,
                "away": away,
                "match_date": match_date,
                "source_url": "https://www.forebet.com/",
                "odds_used": False,
            }, True
        return {"ok": True, **repaired}, True


@app.post("/api/selected-analysis-file")
async def selected_analysis_file(request: Request):
    """Tolerant iOS transport: always return a directly saveable JSON object."""
    try:
        body = await request.json()
    except Exception as exc:
        print(json.dumps({"event": "ios_selected_analysis", "phase": "INVALID_JSON"}), flush=True)
        return _ios_diagnostic_archive("IOS_REQUEST_INVALID_JSON", str(exc), {})
    if not isinstance(body, dict):
        return _ios_diagnostic_archive(
            "IOS_REQUEST_INVALID_BODY",
            "Der Request-Body ist kein Wörterbuch.",
            {"body": type(body).__name__},
        )

    fields = ("matchData", "leagueData", "formData", "tableData", "playerData", "forebetData")
    received_types = {field: type(body.get(field)).__name__ for field in fields}
    print(json.dumps({"event": "ios_selected_analysis", "received_types": received_types}), flush=True)
    try:
        decoded = {field: _ios_dictionary(body.get(field), field) for field in fields}
    except Exception as exc:
        return _ios_diagnostic_archive("IOS_PAYLOAD_DECODE_FAILED", str(exc), received_types)

    try:
        decoded["forebetData"], repaired = _repair_forebet_from_match_data(
            decoded["matchData"], decoded["forebetData"]
        )
    except Exception as exc:
        return _ios_diagnostic_archive("FOREBET_SERVER_REPAIR_INVALID_MATCH", str(exc), received_types)
    if repaired:
        match = mf(decoded["matchData"])
        print(json.dumps({
            "event": "ios_selected_analysis",
            "phase": "FOREBET_SERVER_REPAIR",
            "match_id": match.get("match_id"),
            "home": match.get("home_name"),
            "away": match.get("away_name"),
            "date": _forebet_match_date(decoded["matchData"]),
            "repair_ok": decoded["forebetData"].get("ok") is not False,
        }), flush=True)

    payload = Payload(**decoded)

    response = selected_analysis(payload)
    package = response.get("archive")
    if isinstance(package, dict):
        print(json.dumps({
            "event": "ios_selected_analysis",
            "phase": "ARCHIVE_READY",
            "decision": response.get("decision"),
            "match_id": (package.get("match") or {}).get("match_id"),
        }), flush=True)
        return package
    return _ios_diagnostic_archive(
        response.get("phase") or "ANALYSIS_FAILED",
        response.get("error") or "Render konnte kein gemeinsames Archiv erzeugen.",
        received_types,
    )


@app.post("/api/predict-files")
async def predict_files(match_file:UploadFile=File(...),league_file:UploadFile=File(...)):
    raise HTTPException(
        status_code=422,
        detail="Die v0.9.2-ELITE-Analyse akzeptiert keinen unvollständigen Zwei-Dateien-Weg. Bitte /api/predict-bundle mit fünf FootyStats-Dateien und einer ForebetDaten-Datei verwenden.",
    )
@app.post("/api/predict-bundle")
async def predict_bundle(files: List[UploadFile] = File(...)):
    parsed, errors = await _read_bundle_uploads(files)
    if errors:
        return {
            "ok": False,
            "decision": "ANALYSE NICHT MÖGLICH",
            "phase": "FILE_READ_FAILED",
            "error": "Mindestens eine JSON-Datei konnte nicht gelesen werden.",
            "files": errors,
        }
    result = _analyze_bundle(parsed)
    result.pop("_archive_pair", None)
    return result


@app.post("/api/archive-bundle")
async def archive_bundle(files: List[UploadFile] = File(...)):
    parsed, errors = await _read_bundle_uploads(files)
    if errors:
        return {
            "ok": False,
            "decision": "ANALYSE NICHT MÖGLICH",
            "phase": "FILE_READ_FAILED",
            "error": "Mindestens eine JSON-Datei konnte nicht gelesen werden.",
            "files": errors,
        }
    result = _analyze_bundle(parsed)
    pair = result.pop("_archive_pair", None)
    if not result.get("ok") or not pair:
        return result
    package = _archive_package(parsed, pair, result)
    return Response(
        content=_archive_bytes(package),
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="{_archive_download_name(package)}"',
            "Cache-Control": "no-store",
        },
    )

# ---- HubSign helper ----
import base64 as _b64
import elite_signed_shortcut as _signed_shortcut

_PREPARED_SHORTCUT_B64 = "YnBsaXN0MDDcAAEAAgADAAQABQAGAAcACAAJAAoACwAMAA0ADgAPABQAFQAWABcC3gLyAvoC+wAWXxAkV0ZXb3JrZmxvd01pbmltdW1DbGllbnRWZXJzaW9uU3RyaW5nXxAeV0ZXb3JrZmxvd01pbmltdW1DbGllbnRWZXJzaW9uXldGV29ya2Zsb3dJY29uXxAXV0ZXb3JrZmxvd0NsaWVudFZlcnNpb25fECJXRldvcmtmbG93T3V0cHV0Q29udGVudEl0ZW1DbGFzc2VzXxAbV0ZXb3JrZmxvd0hhc091dHB1dEZhbGxiYWNrXxARV0ZXb3JrZmxvd0FjdGlvbnNfECFXRldvcmtmbG93SW5wdXRDb250ZW50SXRlbUNsYXNzZXNfEBlXRldvcmtmbG93SW1wb3J0UXVlc3Rpb25zXxAVV0ZRdWlja0FjdGlvblN1cmZhY2VzXxAPV0ZXb3JrZmxvd1R5cGVzXxAjV0ZXb3JrZmxvd0hhc1Nob3J0Y3V0SW5wdXRWYXJpYWJsZXNUMjAyNREH6dIAEAARABIAE18QGFdGV29ya2Zsb3dJY29uU3RhcnRDb2xvcl8QGVdGV29ya2Zsb3dJY29uR2x5cGhOdW1iZXISGb0D/xHwAFQ0NzExoAivEFkAGAAhACkAPgBJAFQAXABgAGYAcQB4AH4AiACYAJwAoACnAK0AtwC8AMIAxwDNANIA2ADeAOUA8QD3AP4BBwESARkBIAElATABNwE8AUIBSAFNAVcBXQFlAWsBdgF+AYIBhQGZAaUBrgG4AcYB0QHZAeIB7AHzAfgCAAIHAgsCGAIiAisCNAI/AkYCUAJZAmICbQJ0AnkCfgKDAogCjQKSApcCnAKnAq4CsgK1AsICzALV0gAZABoAGwAcXxAaV0ZXb3JrZmxvd0FjdGlvbklkZW50aWZpZXJfEBpXRldvcmtmbG93QWN0aW9uUGFyYW1ldGVyc18QG2lzLndvcmtmbG93LmFjdGlvbnMuZ2V0dGV4dNIAHQAeAB8AIFRVVUlEXxAQV0ZUZXh0QWN0aW9uVGV4dF8QJEJBRkIzNzEzLTg4NEYtNDA1Ny05ODMzLUQwNTE1MTA1OEVFNlDSABkAGgAiACNfEBdpcy53b3JrZmxvdy5hY3Rpb25zLmFza9MAJAAlAB0AJgAnAChbV0ZJbnB1dFR5cGVfEBFXRkFza0FjdGlvblByb21wdFRUZXh0XVdlbGNoZXIgVGFnID9fECRCRDM0REVFRi1BRDYxLTQyRUUtQTM0OC1BQTI0NEU2REVFRkXSABkAGgAbACrSAB0AHgArACxfECQ0RkMzQzI4Qy1ENUNELTRDNzgtOTVCRS04RTg4Mzg5OThBNkTSAC0ALgAvAD1VVmFsdWVfEBNXRlNlcmlhbGl6YXRpb25UeXBl0gAwADEAMgAzVnN0cmluZ18QEmF0dGFjaG1lbnRzQnlSYW5nZW8QVABoAHQAdABwAHMAOgAvAC8AYQBwAGkALgBmAG8AbwB0AGIAYQBsAGwALQBkAGEAdABhAC0AYQBwAGkALgBjAG8AbQAvAHQAbwBkAGEAeQBzAC0AbQBhAHQAYwBoAGUAcwA/AGQAYQB0AGUAPf/8ACYAdABpAG0AZQB6AG8AbgBlAD0ARQB1AHIAbwBwAGUALwBWAGkAZQBuAG4AYQAmAGsAZQB5AD3//NIANAA1ADYAPFd7NTQsIDF9V3s4MywgMX3TADcAOAA5ACgAOgA7Wk91dHB1dFVVSURUVHlwZVpPdXRwdXROYW1lXEFjdGlvbk91dHB1dF8QE05hY2ggRWluZ2FiZSBmcmFnZW7TADcAOAA5AB8AOgAmXxARV0ZUZXh0VG9rZW5TdHJpbmfSABkAGgA/AEBfEB9pcy53b3JrZmxvdy5hY3Rpb25zLmRvd25sb2FkdXJs0gBBAB0AQgBIVVdGVVJM0gAtAC4AQwA90gAwADEARABFYf/80QBGAEdWezAsIDF90wA3ADgAOQArADoAJl8QJDIyRDc4MDkzLTMwNUEtNDkxOS04RkEyLTA0NDkzQ0E2Njg3QtIAGQAaAEoAS18QImlzLndvcmtmbG93LmFjdGlvbnMuZ2V0dmFsdWVmb3JrZXnTAEwAHQBNAE4AUgBTV1dGSW5wdXRfEA9XRkRpY3Rpb25hcnlLZXnSAC0ALgBPAFHTADcAOAA5AEgAOgBQXkluaGFsdCBkZXIgVVJMXxAVV0ZUZXh0VG9rZW5BdHRhY2htZW50XxAkRTg2REYwQjItRjQwNy00OTMzLThBQTEtNzc4NjA2NEQyQzcyVGRhdGHSABkAGgBVAFZfEB9pcy53b3JrZmxvdy5hY3Rpb25zLnNldHZhcmlhYmxl0gBMAFcAWABbXldGVmFyaWFibGVOYW1l0gAtAC4AWQBR0wA3ADgAOQBSADoAWm4AVwD2AHIAdABlAHIAYgB1AGMAaAB3AGUAcgB0W1NwaWVsZURhdGVu0gAZABoAXQBeXxAeaXMud29ya2Zsb3cuYWN0aW9ucy5kaWN0aW9uYXJ50QAdAF9fECRGRDNEMkU3Qy04NkQ4LTQ0M0ItOUU2OS05OTc1QTgwNkI5NjfSABkAGgBVAGHSAEwAVwBiAGXSAC0ALgBjAFHTADcAOAA5AF8AOgBkagBXAPYAcgB0AGUAcgBiAHUAYwBoXCAgICBTcGllbE1hcNIAGQAaAGcAaF8QH2lzLndvcmtmbG93LmFjdGlvbnMucmVwZWF0LmVhY2jTAEwAaQBqAGsAbwBwXxASR3JvdXBpbmdJZGVudGlmaWVyXxARV0ZDb250cm9sRmxvd01vZGXSAC0ALgBsAFHSAG0AOABbAG5cVmFyaWFibGVOYW1lWFZhcmlhYmxlXxAkMzM5QTIwM0MtQTM5Ni00OEM2LUJCNkMtNTZEMDhBRjZCQ0VBEADSABkAGgBKAHLTAEwAHQBNAHMAdgB30gAtAC4AdABR0gBtADgAdQBuW1JlcGVhdCBJdGVtXxAkM0ZCRjJBQzItNjJEQy00RTA3LUJFQzYtOTU4MDkwNTU0NTUxWWhvbWVfbmFtZdIAGQAaAEoAedMATABNAB0AegB8AH3SAC0ALgB7AFHSAG0AOAB1AG5ZYXdheV9uYW1lXxAkNjFDQkIyQTMtRUZBQi00ODAzLTk1QjMtREREOUFFRTdGMTk40gAZABoAGwB/0gAdAB4AgACBXxAkMTM3MEY0ODEtMDRCNy00NUQxLUFBOEEtRjA5ODZGN0UwNkNG0gAtAC4AggA90gAwADEAgwCEZv/8ACAAdgBzACD//NIAhQBGAIYAh1Z7NSwgMX3TADcAOAA5AH0AOgBa0wA3ADgAOQB2ADoAWtIAGQAaAIkAil8QImlzLndvcmtmbG93LmFjdGlvbnMuc2V0dmFsdWVmb3JrZXnUAIsAHQCMAE0AjQCRAJIAlF8QEVdGRGljdGlvbmFyeVZhbHVlXFdGRGljdGlvbmFyedIALQAuAI4APdIAMAAxAEQAj9EARgCQ0gBtADgAdQBuXxAkRDQwOTkzNTYtMUM4OS00MEM4LTkzMTktNjFFQkVENDk0NzZB0gAtAC4AkwBR0gBtADgAZQBu0gAtAC4AlQA90gAwADEARACW0QBGAJfTADcAOAA5AIAAOgAm0gAZABoAVQCZ0gBMAFcAmgBl0gAtAC4AmwBR0wA3ADgAOQCRADoAZNIAGQAaAGcAndMAHQBpAGoAngBvAJ9fECQxMENBOUJGMS0xOEJFLTRBREItQjhEOC1FRTI2NUJEREQyOUUQAtIAGQAaAEoAodMATACiAB0AowClAKZfEBhXRkdldERpY3Rpb25hcnlWYWx1ZVR5cGXSAC0ALgCkAFHSAG0AOABlAG5YQWxsIEtleXNfECRFODQ4NUE0My1EOUJDLTQzOTEtOUZFMS05ODAwNUIxMENEQznSABkAGgCoAKlfECJpcy53b3JrZmxvdy5hY3Rpb25zLmNob29zZWZyb21saXN00gBMAB0AqgCs0gAtAC4AqwBR0wA3ADgAOQCmADoAWl8QJDc3MDFFN0FELTNERTMtNDZFMy1BNENGLUU4QjVGN0M2MkMwNNIAGQAaAEoArtMATAAdAE0ArwCxALLSAC0ALgCwAFHSAG0AOABlAG5fECQ3QTkxMzNCOS04MzVFLTRBREEtQUNCQy0yMDYzQjY2ODFDRjPSAC0ALgCzAD3SADAAMQBEALTRAEYAtdMANwA4ADkArAA6ALZvEBMAQQB1AHMAZwBlAHcA5ABoAGwAdABlAHMAIABPAGIAagBlAGsAdNIAGQAaAFUAuNIATABXALkAu9IALQAuALoAUdMANwA4ADkAsQA6AFpfEBcgICAgICAgIEdlZnVuZGVuZXNTcGllbNIAGQAaAEoAvdMATAAdAE0AvgDAAMHSAC0ALgC/AFHSAG0AOAC7AG5fECQwRDAwNkNBRC1FRkExLTRGNDMtQTQ0NC0wOEMzQUY0NzY4NEFeY29tcGV0aXRpb25faWTSABkAGgBVAMPSAEwAVwDEAMbSAC0ALgDFAFHTADcAOAA5AMAAOgBaWFNlYXNvbklE0gAZABoASgDI0wBMAB0ATQDJAMsAzNIALQAuAMoAUdIAbQA4ALsAbl8QJDU3MkE2NTg0LTAwMUItNEExNi1BMDk1LUQ2MkIzQTBDQTc4M1JpZNIAGQAaAFUAztIATABXAM8A0dIALQAuANAAUdMANwA4ADkAywA6AFpXTWF0Y2hJRNIAGQAaAEoA09MATAAdAE0A1ADWANfSAC0ALgDVAFHSAG0AOAC7AG5fECQ2MkIzQkM2RS1DMzZCLTREQjAtQTkzNi1ENzA0Q0Q1MzU1MENWaG9tZUlE0gAZABoASgDZ0wBMAB0ATQDaANwA3dIALQAuANsAUdIAbQA4ALsAbl8QJDlDMDZDQUE5LUZDRTUtNEEyNC05QjgwLUI3OEJENjFBNTk0M1Zhd2F5SUTSABkAGgAbAN/SAB0AHgDgAOFfECQzNUREMjE2OS1CN0FELTQ4NzktQkY4Mi0wNTYxODk1NkVFMzfSAC0ALgDiAD3SADAAMQBEAOPRAEYA5NMANwA4ADkAHwA6ACbSABkAGgDmAOdfECBpcy53b3JrZmxvdy5hY3Rpb25zLnRleHQucmVwbGFjZdQATADoAB0A6QDqAO4A7wDwXxAeV0ZSZXBsYWNlVGV4dFJlZ3VsYXJFeHByZXNzaW9uXxARV0ZSZXBsYWNlVGV4dEZpbmTSAC0ALgDrAD3SADAAMQBEAOzRAEYA7dMANwA4ADkA4AA6ACYJXxAkRTgyQUE1NDctQzgyMC00QkJDLUE2NTktMTI5QUFEQTQ5QUVFU1xzK9IAGQAaAFUA8tIATABXAPMA9tIALQAuAPQAUdMANwA4ADkA7wA6APVfEBNBa3R1YWxpc2llcnRlciBUZXh0VkFQSUtledIAGQAaAPgA+V8QHmlzLndvcmtmbG93LmFjdGlvbnMudGV4dC5zcGxpdNIA+gAdAPsA/VR0ZXh00gAtAC4A/ABR0wA3ADgAOQDvADoA9V8QJEU1MUVCRTRFLUY4M0MtNERBQy1BQjY5LTEzMkJBOUJBNzk4OdIAGQAaAP8BAF8QIGlzLndvcmtmbG93LmFjdGlvbnMudGV4dC5jb21iaW5l0wEBAPoAHQECAQMBBl8QD1dGVGV4dFNlcGFyYXRvclZDdXN0b23SAC0ALgEEAFHTADcAOAA5AP0AOgEFXlRleHQgYXVmdGVpbGVuXxAkNjE4QUU0MzctRjBFMy00N0EzLUJCQzEtQUU2Njc0Q0VCOEU00gAZABoAGwEI0gAdAB4BCQEKXxAkRUFFMkFEMDktQ0RBNi00Q0QwLThDMDEtNjg5MUI5QTIyMzQ10gAtAC4BCwA90gAwADEBDAENbxA4AGgAdAB0AHAAcwA6AC8ALwBhAHAAaQAuAGYAbwBvAHQAYgBh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OTI1NUY1N0NGNzHSAC0ALgLQAD3SADAAMQLRAtJvEBT//AAv//wAXwBQAGwAYQB5AGUAcgBEAGEAdABlAG4ALgBqAHMAbwBu0gBGAbUC0wLU0gBtADgA0QBu0gBtADgA0QBu0gAZABoBuQLW1QBMAbsAHQG8Ab0C1wAWAtkAFgLa0gAtAC4C2ABR0wA3ADgAOQLLADoBwF8QJDIyQjdBQjUzLTdEMzAtNEM2OS1CRjYzLTAyMTk5OTIzNEQ4MNIALQAuAtsAPdIAMAAxAEQC3NEARgLd0wA3ADgAOQLOADoAJq8QEwLfAuAC4QLiAuMC5ALlAuYC5wLoAukC6gLrAuwC7QLuAu8C8ALxXxAQV0ZBcHBDb250ZW50SXRlbV8QGFdGQXBwU3RvcmVBcHBDb250ZW50SXRlbV8QFFdGQXJ0aWNsZUNvbnRlbnRJdGVtXxAUV0ZDb250YWN0Q29udGVudEl0ZW1fEBFXRkRhdGVDb250ZW50SXRlbV8QGVdGRW1haWxBZGRyZXNzQ29udGVudEl0ZW1fEBNXRkZvbGRlckNvbnRlbnRJdGVtXxAYV0ZHZW5lcmljRmlsZUNvbnRlbnRJdGVtXxASV0ZJbWFnZUNvbnRlbnRJdGVtXxAaV0ZpVHVuZXNQcm9kdWN0Q29udGVudEl0ZW1fEBVXRkxvY2F0aW9uQ29udGVudEl0ZW1fEBdXRkRDTWFwc0xpbmtDb250ZW50SXRlbV8QFFdGQVZBc3NldENvbnRlbnRJdGVtXxAQV0ZQREZDb250ZW50SXRlbV8QGFdGUGhvbmVOdW1iZXJDb250ZW50SXRlbV8QFVdGUmljaFRleHRDb250ZW50SXRlbV8QGldGU2FmYXJpV2ViUGFnZUNvbnRlbnRJdGVtXxATV0ZTdHJpbmdDb250ZW50SXRlbV8QEFdGVVJMQ29udGVudEl0ZW2hAvPVAvQC9QL2AvcAJgBwAvgAIAAeAvlbQWN0aW9uSW5kZXhYQ2F0ZWdvcnlcRGVmYXVsdFZhbHVlXFBhcmFtZXRlcktleVlQYXJhbWV0ZXJfEBtGb290eVN0YXRzIEFQSS1LZXkgZWluZ2ViZW6gogL8Av1VV2F0Y2hfEBpXRldvcmtmbG93VHlwZVNob3dJblNlYXJjaAAIADkAYACBAJAAqgDPAO0BAQElAUEBWQFrAZEB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"

_PREPARED_SHORTCUT_V4_B64 = "YnBsaXN0MDDdAAEAAgADAAQABQAGAAcACAAJAAoACwAMAA0ADgAPABAAFQAWABcAGAMIAxwDJAMlABcDKF8QJFdGV29ya2Zsb3dNaW5pbXVtQ2xpZW50VmVyc2lvblN0cmluZ18QHldGV29ya2Zsb3dNaW5pbXVtQ2xpZW50VmVyc2lvbl5XRldvcmtmbG93SWNvbl8QF1dGV29ya2Zsb3dDbGllbnRWZXJzaW9uXxAiV0ZXb3JrZmxvd091dHB1dENvbnRlbnRJdGVtQ2xhc3Nlc18QG1dGV29ya2Zsb3dIYXNPdXRwdXRGYWxsYmFja18QEVdGV29ya2Zsb3dBY3Rpb25zXxAhV0ZXb3JrZmxvd0lucHV0Q29udGVudEl0ZW1DbGFzc2VzXxAZV0ZXb3JrZmxvd0ltcG9ydFF1ZXN0aW9uc18QFVdGUXVpY2tBY3Rpb25TdXJmYWNlc18QD1dGV29ya2Zsb3dUeXBlc18QI1dGV29ya2Zsb3dIYXNTaG9ydGN1dElucHV0VmFyaWFibGVzXldGV29ya2Zsb3dOYW1lVDIwMjURB+nSABEAEgATABRfEBhXRldvcmtmbG93SWNvblN0YXJ0Q29sb3JfEBlXRldvcmtmbG93SWNvbkdseXBoTnVtYmVyEhm9A/8R8ABUNDcxMaAIrxBeABkAIgAqAD8ASgBVAF0AYQBnAHIAeQB/AIkAmQCdAKEAqACuALgAvQDDAMgAzgDTANkA3wDmAPIA+AD/AQgBEwEaASEBJgExATgBPQFDAUkBTgFYAV4BZgFsAXcBfwGDAYYBmgGmAa8BuQHHAdIB2gHjAe0B9AH5AgECCAIMAhkCIwIsAjUCQAJHAlECWgJjAm4CdQJ6An8ChAKJAo4CkwKYAp0CqAKvArMCtgLDAs0C1gLfAuMC7gL4AwHSABoAGwAcAB1fEBpXRldvcmtmbG93QWN0aW9uSWRlbnRpZmllcl8QGldGV29ya2Zsb3dBY3Rpb25QYXJhbWV0ZXJzXxAbaXMud29ya2Zsb3cuYWN0aW9ucy5nZXR0ZXh00gAeAB8AIAAhVFVVSURfEBBXRlRleHRBY3Rpb25UZXh0XxAkQkFGQjM3MTMtODg0Ri00MDU3LTk4MzMtRDA1MTUxMDU4RUU2UNIAGgAbACMAJF8QF2lzLndvcmtmbG93LmFjdGlvbnMuYXNr0wAlACYAHgAnACgAKVtXRklucHV0VHlwZV8QEVdGQXNrQWN0aW9uUHJvbXB0VFRleHRdV2VsY2hlciBUYWcgP18QJEJEMzRERUVGLUFENjEtNDJFRS1BMzQ4LUFBMjQ0RTZERUVGRdIAGgAbABwAK9IAHgAfACwALV8QJDRGQzNDMjhDLUQ1Q0QtNEM3OC05NUJFLThFODgzODk5OEE2RNIALgAvADAAPlVWYWx1ZV8QE1dGU2VyaWFsaXphdGlvblR5cGXSADEAMgAzADRWc3RyaW5nXxASYXR0YWNobWVudHNCeVJhbmdlbxBUAGgAdAB0AHAAcwA6AC8ALwBhAHAAaQAuAGYAbwBvAHQAYgBhAGwAbAAtAGQAYQB0AGEALQBhAHAAaQAuAGMAbwBtAC8AdABvAGQAYQB5AHMALQBtAGEAdABjAGgAZQBzAD8AZABhAHQAZQA9//wAJgB0AGkAbQBlAHoAbwBuAGUAPQBFAHUAcgBvAHAAZQAvAFYAaQBlAG4AbgBhACYAawBlAHkAPf/80gA1ADYANwA9V3s1NCwgMX1XezgzLCAxfdMAOAA5ADoAKQA7ADxaT3V0cHV0VVVJRFRUeXBlWk91dHB1dE5hbWVcQWN0aW9uT3V0cHV0XxATTmFjaCBFaW5nYWJlIGZyYWdlbtMAOAA5ADoAIAA7ACdfEBFXRlRleHRUb2tlblN0cmluZ9IAGgAbAEAAQV8QH2lzLndvcmtmbG93LmFjdGlvbnMuZG93bmxvYWR1cmzSAEIAHgBDAElVV0ZVUkzSAC4ALwBEAD7SADEAMgBFAEZh//zRAEcASFZ7MCwgMX3TADgAOQA6ACwAOwAnXxAkMjJENzgwOTMtMzA1QS00OTE5LThGQTItMDQ0OTNDQTY2ODdC0gAaABsASwBMXxAiaXMud29ya2Zsb3cuYWN0aW9ucy5nZXR2YWx1ZWZvcmtledMATQAeAE4ATwBTAFRXV0ZJbnB1dF8QD1dGRGljdGlvbmFyeUtledIALgAvAFAAUtMAOAA5ADoASQA7AFFeSW5oYWx0IGRlciBVUkxfEBVXRlRleHRUb2tlbkF0dGFjaG1lbnRfECRFODZERjBCMi1GNDA3LTQ5MzMtOEFBMS03Nzg2MDY0RDJDNzJUZGF0YdIAGgAbAFYAV18QH2lzLndvcmtmbG93LmFj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ADsAW1dNYXRjaElE0gAaABsASwDU0wBNAB4ATgDVANcA2NIALgAvANYAUtIAbgA5ALwAb18QJDYyQjNCQzZFLUMzNkItNERCMC1BOTM2LUQ3MDRDRDUzNTUwQ1Zob21lSUTSABoAGwBLANrTAE0AHgBOANsA3QDe0gAuAC8A3ABS0gBuADkAvABvXxAkOUMwNkNBQTktRkNFNS00QTI0LTlCODAtQjc4QkQ2MUE1OTQzVmF3YXlJRNIAGgAbABwA4NIAHgAfAOEA4l8QJDM1REQyMTY5LUI3QUQtNDg3OS1CRjgyLTA1NjE4OTU2RUUzN9IALgAvAOMAPtIAMQAyAEUA5NEARwDl0wA4ADkAOgAgADsAJ9IAGgAbAOcA6F8QIGlzLndvcmtmbG93LmFjdGlvbnMudGV4dC5yZXBsYWNl1ABNAOkAHgDqAOsA7wDwAPFfEB5XRlJlcGxhY2VUZXh0UmVndWxhckV4cHJlc3Npb25fEBFXRlJlcGxhY2VUZXh0RmluZNIALgAvAOwAPtIAMQAyAEUA7dEARwDu0wA4ADkAOgDhADsAJwlfECRFODJBQTU0Ny1DODIwLTRCQkMtQTY1OS0xMjlBQURBNDlBRUVTXHMr0gAaABsAVgDz0gBNAFgA9AD30gAuAC8A9QBS0wA4ADkAOgDwADsA9l8QE0FrdHVhbGlzaWVydGVyIFRleHRWQVBJS2V50gAaABsA+QD6XxAeaXMud29ya2Zsb3cuYWN0aW9ucy50ZXh0LnNwbGl00gD7AB4A/AD+VHRleHTSAC4ALwD9AFLTADgAOQA6APAAOwD2XxAkRTUxRUJFNEUtRjgzQy00REFDLUFCNjktMTMyQkE5QkE3OTg50gAaABsBAAEBXxAgaXMud29ya2Zsb3cuYWN0aW9ucy50ZXh0LmNvbWJpbmXTAQIA+wAeAQMBBAEHXxAPV0ZUZXh0U2VwYXJhdG9yVkN1c3RvbdIALgAvAQUAUtMAOAA5ADoA/gA7AQZeVGV4dCBhdWZ0ZWlsZW5fECQ2MThBRTQzNy1GMEUzLTQ3QTMtQkJDMS1BRTY2NzRDRUI4RTTSABoAGwAcAQnSAB4AHwEKAQtfECRFQUUyQUQwOS1DREE2LTRDRDAtOEMwMS02ODkxQjlBMjIzNDXSAC4ALwEMAD7SADEAMgENAQ5vEDgAaAB0AHQA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AGUAYgBlAHQARABhAHQAZQBuAC4AagBzAG8AbtEARwL30gBuADkA0gBv0gAaABsAHAL50gAeAB8C+gL7XxAkOUJFMEVEMTMtOUJCNS00RUI2LUIwMTktODQzMzdGNzAwMTE10gAuAC8C/AA+0gAxADIC/QL+bxAV//wAL//8AF8ARgBvAHIAZQBiAGUAdABEAGEAdABlAG4ALgBqAHMAbwBu0gBHAbYC/wMA0gBuADkA0gBv0gBuADkA0gBv0gAaABsBugMC1QAeAbwBvQBNAb4DAwAXABcDBAMGXxAkRUVCQzExMzMtMzUyQS00MTM4LUFDNDEtQzdGN0FCRjZDODFC0gAuAC8DBQBS0wA4ADkAOgLwADsBwdIALgAvAwcAUtMAOAA5ADoC+gA7ACevEBMDCQMKAwsDDAMNAw4DDwMQAxEDEgMTAxQDFQMWAxcDGAMZAxoDG18QEFdGQXBwQ29udGVudEl0ZW1fEBhXRkFwcFN0b3JlQXBwQ29udGVudEl0ZW1fEBRXRkFydGljbGVDb250ZW50SXRlbV8QFFdGQ29udGFjdENvbnRlbnRJdGVtXxARV0ZEYXRlQ29udGVudEl0ZW1fEBlXRkVtYWlsQWRkcmVzc0NvbnRlbnRJdGVtXxATV0ZGb2xkZXJDb250ZW50SXRlbV8QGFdGR2VuZXJpY0ZpbGVDb250ZW50SXRlbV8QEldGSW1hZ2VDb250ZW50SXRlbV8QGldGaVR1bmVzUHJvZHVjdENvbnRlbnRJdGVtXxAVV0ZMb2NhdGlvbkNvbnRlbnRJdGVtXxAXV0ZEQ01hcHNMaW5rQ29udGVudEl0ZW1fEBRXRkFWQXNzZXRDb250ZW50SXRlbV8QEFdGUERGQ29udGVudEl0ZW1fEBhXRlBob25lTnVtYmVyQ29udGVudEl0ZW1fEBVXRlJpY2hUZXh0Q29udGVudEl0ZW1fEBpXRlNhZmFyaVdlYlBhZ2VDb250ZW50SXRlbV8QE1dGU3RyaW5nQ29udGVudEl0ZW1fEBBXRlVSTENvbnRlbnRJdGVtoQMd1QMeAx8DIAMhACcAcQMiACEAHwMjW0FjdGlvbkluZGV4WENhdGVnb3J5XERlZmF1bHRWYWx1ZVxQYXJhbWV0ZXJLZXlZUGFyYW1ldGVyXxAbRm9vdHlTdGF0cyBBUEktS2V5IGVp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"

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
<h1>FootyStats + Forebet ELITE V2.1</h1>
<p class="s">Ablauf wie bei V2: Datum eingeben, ein Spiel selbst auswählen und genau dieses Spiel analysieren. Render verbindet dafür fünf FootyStats-Quellen mit Forebet und liefert eine gemeinsame Analyse-Datei. V0.4.0 bleibt unverändert.</p>
<p class="s">Diese Datei wurde bereits mit HubSign signiert. Vor jedem Download prüft der Server den Apple-Dateikopf <code>AEA1</code>; es wird kein API-Key benötigt.</p>
<button id="go">Geprüften Kurzbefehl herunterladen</button>
<p id="status" class="s"></p>
</div></div>
<script>
document.getElementById('go').onclick=async()=>{
  const st=document.getElementById('status');
  st.className='s';st.textContent='Signatur wird geprüft…';
  try{
    const r=await fetch('/api/shortcut-download',{cache:'no-store'});
    if(!r.ok){
      const t=await r.text();
      st.className='s bad';st.textContent='Fehler '+r.status+': '+t.slice(0,500);return;
    }
    const b=await r.blob();
    const magic=String.fromCharCode(...new Uint8Array(await b.slice(0,4).arrayBuffer()));
    if(magic!=='AEA1'){
      st.className='s bad';st.textContent='Signaturprüfung fehlgeschlagen. Es wurde keine Datei heruntergeladen.';return;
    }
    const u=URL.createObjectURL(b);
    const a=document.createElement('a'); a.href=u; a.download='FootyStats + Forebet ELITE V2.1.shortcut';
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(()=>URL.revokeObjectURL(u),5000);
    st.className='s ok';st.textContent='Fertig. AEA1-Signatur geprüft; die gültige .shortcut-Datei wurde heruntergeladen.';
  }catch(e){st.className='s bad';st.textContent='Fehler: '+String(e)}
};
</script></body></html>"""

@app.get("/hubsign-helper", response_class=HTMLResponse)
def hubsign_helper():
    return HTMLResponse(_HUBSIGN_HTML, headers={"Cache-Control":"no-store"})

def _signed_shortcut_response() -> Response:
    signed = _b64.b64decode(_signed_shortcut.SIGNED_ELITE_SHORTCUT_B64)
    if not signed.startswith(b"AEA1"):
        raise HTTPException(status_code=500, detail="Der hinterlegte Kurzbefehl besitzt keinen gültigen AEA1-Dateikopf.")
    return Response(
        content=signed,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": 'attachment; filename="FootyStats + Forebet ELITE V2.1.shortcut"',
            "Cache-Control":"no-store",
        },
    )

@app.get("/api/shortcut-download")
def shortcut_download():
    return _signed_shortcut_response()

@app.post("/api/hubsign-sign")
async def hubsign_sign():
    # Compatibility for helper pages that were opened before v0.9.2 deployed.
    return _signed_shortcut_response()
