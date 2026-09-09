from __future__ import annotations
import json, unicodedata, re, urllib.parse, urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

BASE_URL='https://v3.football.api-sports.io'

def _utc(v:str)->datetime:
    s=v.replace('Z','+00:00'); d=datetime.fromisoformat(s)
    if d.tzinfo is None: d=d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)

def normalize_team_name(name:str)->str:
    s=unicodedata.normalize('NFKD',str(name)).encode('ascii','ignore').decode('ascii').lower()
    s=re.sub(r'[^a-z0-9]+',' ',s)
    return ' '.join(s.split())

class ApiFootballClient:
    def __init__(self, api_key:str, base_url:str=BASE_URL, timeout:float=15.0):
        if not api_key: raise ValueError('API-Football key required')
        self.api_key=api_key; self.base_url=base_url.rstrip('/'); self.timeout=timeout
    def get(self,path:str,params:Dict[str,Any])->Dict[str,Any]:
        q=urllib.parse.urlencode(params)
        url=f"{self.base_url}/{path.lstrip('/')}?{q}"
        req=urllib.request.Request(url,headers={'x-apisports-key':self.api_key,'Accept':'application/json','User-Agent':'FootyStats-New-Architecture/0.8'})
        with urllib.request.urlopen(req,timeout=self.timeout) as r:
            data=json.loads(r.read().decode('utf-8'))
        if data.get('errors'):
            raise RuntimeError(f"API-Football error: {data['errors']}")
        return data
    def fixtures_by_date(self,date_utc:str): return self.get('fixtures',{'date':date_utc})
    def injuries_by_fixture(self,fixture_id:int): return self.get('injuries',{'fixture':fixture_id})
    def lineups_by_fixture(self,fixture_id:int): return self.get('fixtures/lineups',{'fixture':fixture_id})

def resolve_fixture_strict(match:Dict[str,Any], fixtures_response:Dict[str,Any], alias_map:Optional[Dict[str,str]]=None,
                           kickoff_tolerance_seconds:int=120)->Dict[str,Any]:
    alias_map=alias_map or {}
    h_raw=str(match['home_team']); a_raw=str(match['away_team'])
    h_alias=alias_map.get(h_raw,h_raw); a_alias=alias_map.get(a_raw,a_raw)
    hn=normalize_team_name(h_alias); an=normalize_team_name(a_alias)
    ko=_utc(match['kickoff_at_utc'])
    candidates=[]
    for item in fixtures_response.get('response',[]) or []:
        home=((item.get('teams') or {}).get('home') or {})
        away=((item.get('teams') or {}).get('away') or {})
        fx=item.get('fixture') or {}
        if normalize_team_name(home.get('name','')) != hn: continue
        if normalize_team_name(away.get('name','')) != an: continue
        if not fx.get('date'): continue
        delta=abs((_utc(fx['date'])-ko).total_seconds())
        if delta <= kickoff_tolerance_seconds:
            candidates.append(item)
    if len(candidates)!=1:
        raise LookupError(f"strict fixture resolution expected 1 candidate, found {len(candidates)}")
    return candidates[0]

def map_injuries_to_context_events(injuries_response:Dict[str,Any], fixture:Dict[str,Any], observed_at_utc:str)->List[Dict[str,Any]]:
    teams=fixture.get('teams') or {}; hid=((teams.get('home') or {}).get('id')); aid=((teams.get('away') or {}).get('id'))
    fxid=(fixture.get('fixture') or {}).get('id')
    events=[]
    for item in injuries_response.get('response',[]) or []:
        team=item.get('team') or {}; player=item.get('player') or {}
        tid=team.get('id')
        side='home' if tid==hid else 'away' if tid==aid else None
        if side is None: continue
        typ=str(item.get('type') or '').strip(); reason=str(item.get('reason') or '').strip()
        et='SUSPENSION' if 'susp' in typ.lower() else 'INJURY'
        original=' | '.join(x for x in [typ,reason] if x) or 'API-Football availability record'
        events.append({
            'team_side':side,'event_type':et,'player_id':player.get('id'),'player_name':player.get('name'),
            'provider_team_id':tid,'provider_team_name':team.get('name'),'provider_type':typ or None,
            'provider_reason':reason or None,'observed_at_utc':observed_at_utc,
            'timestamp_basis':'OBSERVED_AT_API_FETCH','source_provider':'API_FOOTBALL',
            'source_url':f'{BASE_URL}/injuries?fixture={fxid}','original_text':original
        })
    return events

def map_lineups_to_context(lineups_response:Dict[str,Any], fixture:Dict[str,Any], observed_at_utc:str)->Dict[str,Any]:
    teams=fixture.get('teams') or {}; hid=((teams.get('home') or {}).get('id')); aid=((teams.get('away') or {}).get('id'))
    fxid=(fixture.get('fixture') or {}).get('id')
    home_players=[]; away_players=[]; formations={}; coaches={}; found_sides=set()
    for item in lineups_response.get('response',[]) or []:
        team=item.get('team') or {}; tid=team.get('id')
        side='home' if tid==hid else 'away' if tid==aid else None
        if side is None: continue
        found_sides.add(side); formations[side]=item.get('formation'); coaches[side]=item.get('coach')
        target=home_players if side=='home' else away_players
        for x in item.get('startXI',[]) or []:
            p=x.get('player') or x
            target.append({'player_id':p.get('id'),'name':p.get('name'),'number':p.get('number'),'position':p.get('pos'),'grid':p.get('grid')})
    if not found_sides:
        return {'status':'UNAVAILABLE'}
    complete=('home' in found_sides and 'away' in found_sides and len(home_players)>0 and len(away_players)>0)
    return {
        'status':'CONFIRMED' if complete else 'PARTIAL','observed_at_utc':observed_at_utc,
        'timestamp_basis':'OBSERVED_AT_API_FETCH','source_provider':'API_FOOTBALL',
        'source_url':f'{BASE_URL}/fixtures/lineups?fixture={fxid}','home_players':home_players,
        'away_players':away_players,'formations':formations,'coaches':coaches
    }

def build_api_football_context_layers(match:Dict[str,Any], fixtures_response:Dict[str,Any], injuries_response:Optional[Dict[str,Any]],
                                      lineups_response:Optional[Dict[str,Any]], observed_at_utc:str,
                                      alias_map:Optional[Dict[str,str]]=None)->Tuple[Dict[str,Any],Dict[str,Any],Dict[str,Any]]:
    fixture=resolve_fixture_strict(match,fixtures_response,alias_map=alias_map)
    events=map_injuries_to_context_events(injuries_response or {'response':[]},fixture,observed_at_utc)
    news_availability={
        'status':'AVAILABLE' if injuries_response is not None else 'UNAVAILABLE',
        'source_provider':'API_FOOTBALL' if injuries_response is not None else None,
        'observed_at_utc':observed_at_utc if injuries_response is not None else None,
        'events':events
    }
    lineup=map_lineups_to_context(lineups_response or {'response':[]},fixture,observed_at_utc) if lineups_response is not None else {'status':'UNAVAILABLE'}
    return fixture,news_availability,lineup
