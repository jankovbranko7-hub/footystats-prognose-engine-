from __future__ import annotations
import copy
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .current_match_context import SCHEMA_VERSION, validate_current_match_context, ContextValidationError

WINDOWS = (5, 6, 10)

def _norm_key(value: Any) -> str:
    return ''.join(ch.lower() for ch in str(value) if ch.isalnum() or ch == '_')

def _walk_dicts(obj: Any) -> Iterable[Dict[str, Any]]:
    if isinstance(obj, dict):
        yield obj
        for v in obj.values(): yield from _walk_dicts(v)
    elif isinstance(obj, list):
        for v in obj: yield from _walk_dicts(v)

def _first(obj: Any, aliases: Iterable[str]) -> Any:
    wanted = {_norm_key(a) for a in aliases}
    for d in _walk_dicts(obj):
        for k, v in d.items():
            if _norm_key(k) in wanted and v not in (None, '', [], {}): return v
    return None

def _first_num(obj: Any, aliases: Iterable[str]) -> Optional[float]:
    v = _first(obj, aliases)
    try:
        if v is None or isinstance(v, bool): return None
        return float(v)
    except Exception: return None

def _iso_from_epoch(value: Any) -> str:
    return datetime.fromtimestamp(float(value), tz=timezone.utc).isoformat().replace('+00:00', 'Z')

def _iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')

def extract_match_identity(match_data: Any) -> Dict[str, Any]:
    match_obj = None
    for d in _walk_dicts(match_data):
        keys = {_norm_key(k) for k in d}
        if ('homeid' in keys or 'home_id' in keys) and ('awayid' in keys or 'away_id' in keys):
            match_obj = d; break
    if match_obj is None: raise ContextValidationError('could not locate target match object')
    match_id = _first_num(match_obj, ['id', 'match_id'])
    home_id = _first_num(match_obj, ['homeID', 'home_id'])
    away_id = _first_num(match_obj, ['awayID', 'away_id'])
    home_name = _first(match_obj, ['home_name', 'homeName'])
    away_name = _first(match_obj, ['away_name', 'awayName'])
    kickoff_epoch = _first_num(match_obj, ['date_unix', 'kickoff_unix', 'timestamp'])
    if None in (match_id, home_id, away_id, kickoff_epoch) or not home_name or not away_name:
        raise ContextValidationError('target match identity is incomplete')
    return {'match_id':int(match_id),'home_id':int(home_id),'away_id':int(away_id),'home_team':str(home_name),'away_team':str(away_name),'kickoff_at_utc':_iso_from_epoch(kickoff_epoch)}

def _flatten_scalars(obj: Any, prefix: str = '') -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            p = f'{prefix}.{k}' if prefix else str(k)
            if isinstance(v, dict): out.update(_flatten_scalars(v, p))
            elif isinstance(v, list): continue
            elif v is None or isinstance(v, (str, int, float, bool)): out[p] = v
    return out

def _form_entries(form_data: Any) -> List[Dict[str, Any]]:
    entries: List[Dict[str, Any]] = []
    if isinstance(form_data, dict) and isinstance(form_data.get('teams'), list):
        for team_block in form_data['teams']:
            if isinstance(team_block, dict) and isinstance(team_block.get('data'), list):
                entries.extend(x for x in team_block['data'] if isinstance(x, dict))
    if entries: return entries
    for d in _walk_dicts(form_data):
        if _first_num(d, ['id','team_id','teamID']) is not None and _first_num(d, ['last_x_match_num']) is not None:
            entries.append(d)
    return entries

def derive_trend_from_raw_form(match_data: Any, form_data: Any, snapshot_at_utc: str) -> Dict[str, Any]:
    identity = extract_match_identity(match_data)
    by_team_window: Dict[Tuple[int, int], Dict[str, Any]] = {}
    for entry in _form_entries(form_data):
        tid = _first_num(entry, ['id','team_id','teamID']); window = _first_num(entry, ['last_x_match_num']); mode = _first_num(entry, ['last_x_home_away_or_overall'])
        if tid is None or window is None: continue
        if mode not in (None, 0.0): continue
        key = (int(tid), int(window))
        if int(window) in WINDOWS and key not in by_team_window: by_team_window[key] = entry
    def side_payload(team_id: int) -> Dict[str, Any]:
        window_maps: Dict[int, Dict[str, Any]] = {}
        for w in WINDOWS:
            entry = by_team_window.get((team_id,w))
            window_maps[w] = _flatten_scalars({'stats':copy.deepcopy((entry or {}).get('stats') or {})}) if entry else {}
        common=set(window_maps[WINDOWS[0]])
        for w in WINDOWS[1:]: common &= set(window_maps[w])
        metrics={metric:{f'w{w}':window_maps[w].get(metric) for w in WINDOWS} for metric in sorted(common)}
        return {'form_windows':{'windows':list(WINDOWS),'metric_count':len(metrics),'metrics':metrics}}
    home=side_payload(identity['home_id']); away=side_payload(identity['away_id'])
    if not home['form_windows']['metrics'] or not away['form_windows']['metrics']: return {'status':'UNAVAILABLE'}
    return {'status':'AVAILABLE','source':'FOOTYSTATS_FIVE_FILE_DERIVED','snapshot_at_utc':snapshot_at_utc,'home':home,'away':away}

def build_runtime_context(match_data: Any, form_data: Any, generated_at_utc: Optional[str] = None,
                          news_availability: Optional[Dict[str, Any]] = None,
                          lineup_context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    generated_at_utc = generated_at_utc or _iso_now()
    identity = extract_match_identity(match_data)
    trend = derive_trend_from_raw_form(match_data, form_data, generated_at_utc)
    ctx={'schema_version':SCHEMA_VERSION,'match':{'match_id':identity['match_id'],'home_team':identity['home_team'],'away_team':identity['away_team'],'kickoff_at_utc':identity['kickoff_at_utc']},'generated_at_utc':generated_at_utc,'trend':trend,'news_availability':copy.deepcopy(news_availability) if news_availability is not None else {'status':'UNAVAILABLE','events':[]},'lineup_context':copy.deepcopy(lineup_context) if lineup_context is not None else {'status':'UNAVAILABLE'}}
    audit=validate_current_match_context(ctx)
    if not audit['valid']: raise ContextValidationError('; '.join(audit['errors']))
    ctx['integrity']={'valid':True,'context_sha256':audit['context_sha256'],'warnings':audit['warnings']}
    return ctx
