from __future__ import annotations

import math
from statistics import median
from typing import Any, Dict, Iterable, List, Optional, Tuple

TEAM_METRICS = (
    "xg_for_avg", "xg_against_avg", "seasonPPG", "seasonScoredAVG", "seasonConcededAVG",
    "seasonBTTSPercentage", "seasonOver25Percentage", "seasonUnder25Percentage",
    "seasonCSPercentage", "seasonFTSPercentage", "shotsAVG", "shotsOnTargetAVG",
    "shotsOffTargetAVG", "possessionAVG", "cornersAVG", "cornersAgainstAVG",
    "seasonBTTSPercentageHT", "seasonCSPercentageHT", "seasonFTSPercentageHT",
    "scoredAVGHT", "concededAVGHT", "AVGHT", "scored_2hg", "conceded_2hg",
    "btts_2hg_percentage", "fts_2hg_percentage", "seasonOver25PercentageHT",
)

FORM_METRICS = (
    "seasonPPG_overall", "xg_for_avg_overall", "xg_against_avg_overall",
    "seasonScoredAVG_overall", "seasonConcededAVG_overall",
    "seasonBTTSPercentage_overall", "seasonOver25Percentage_overall",
    "seasonUnder25Percentage_overall", "seasonCSPercentage_overall",
    "seasonFTSPercentage_overall", "shotsAVG_overall", "shotsOnTargetAVG_overall",
    "seasonBTTSPercentageHT_overall", "seasonCSPercentageHT_overall",
    "seasonFTSPercentageHT_overall", "scoredAVGHT_overall", "concededAVGHT_overall",
    "scored_2hg_overall", "conceded_2hg_overall", "btts_2hg_percentage_overall",
    "fts_2hg_percentage_overall",
)

REFEREE_METRICS = (
    "wins_per_home", "wins_per_away", "draws_per", "btts_percentage",
    "goals_per_match_overall", "goals_per_match_home", "goals_per_match_away",
    "penalties_given_per_match_overall", "cards_per_match_overall",
    "yellow_cards_overall", "red_cards_overall", "min_per_goal_overall", "min_per_card_overall",
)

MANAGER_METRICS = (
    "wins_per_overall", "wins_per_home", "wins_per_away",
    "draws_per_overall", "draws_per_home", "draws_per_away",
    "losses_per_overall", "losses_per_home", "losses_per_away",
    "cs_overall", "cs_home", "cs_away", "btts_overall", "btts_home", "btts_away",
    "over25_overall", "over25_home", "over25_away",
)


def num(v: Any) -> Optional[float]:
    if v is None or isinstance(v, bool): return None
    try: x = float(v)
    except (TypeError, ValueError): return None
    return x if math.isfinite(x) else None


def intv(v: Any) -> Optional[int]:
    x = num(v); return int(x) if x is not None else None


def api_data(v: Any) -> Any:
    return v.get("data") if isinstance(v, dict) and "data" in v else v


def dicts(v: Any) -> Iterable[Dict[str, Any]]:
    if isinstance(v, dict):
        yield v
        for x in v.values(): yield from dicts(x)
    elif isinstance(v, list):
        for x in v: yield from dicts(x)


def team_rows(league: Any) -> List[Dict[str, Any]]:
    if not isinstance(league, dict): return []
    tp = league.get("team_pages")
    rows: List[Dict[str, Any]] = []
    if isinstance(tp, dict):
        d = api_data(tp)
        if isinstance(d, list): rows.extend(x for x in d if isinstance(x, dict))
    elif isinstance(tp, list):
        for page in tp:
            d = api_data(page)
            if isinstance(d, list): rows.extend(x for x in d if isinstance(x, dict))
    out: Dict[int, Dict[str, Any]] = {}
    for row in rows:
        tid = intv(row.get("id"))
        if tid is not None: out.setdefault(tid, row)
    return list(out.values())


def by_id(rows: Iterable[Dict[str, Any]], wanted: int) -> Optional[Dict[str, Any]]:
    return next((r for r in rows if intv(r.get("id")) == int(wanted)), None)


def stats(team: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    s = (team or {}).get("stats")
    return s if isinstance(s, dict) else {}


def split_sample(team: Optional[Dict[str, Any]], split: str) -> Optional[float]:
    return num(stats(team).get(f"seasonMatchesPlayed_{split}"))


def team_metric(team: Optional[Dict[str, Any]], metric: str, split: str) -> Optional[float]:
    n = split_sample(team, split)
    if n is None or n <= 0: return None
    return num(stats(team).get(f"{metric}_{split}"))


def weighted_mean(rows: Iterable[Tuple[Optional[float], Optional[float]]]) -> Optional[float]:
    valid = [(float(v), float(w)) for v, w in rows if v is not None and w is not None and w > 0]
    if not valid: return None
    den = sum(w for _, w in valid)
    return sum(v*w for v,w in valid)/den if den else None


def league_mean(teams: List[Dict[str, Any]], metric: str, split: str) -> Optional[float]:
    return weighted_mean((team_metric(t, metric, split), split_sample(t, split)) for t in teams)


def put(features: Dict[str, float], name: str, value: Any) -> None:
    x = num(value)
    if x is not None: features[name] = x


def add_diff(features: Dict[str, float], name: str, a: Optional[float], b: Optional[float]) -> None:
    if a is not None and b is not None: features[name] = a - b


def block_result(name: str, features: Dict[str, float], notes: Optional[List[str]]=None) -> Dict[str, Any]:
    return {"name": name, "feature_count": len(features), "available": bool(features), "features": features, "notes": notes or []}


def match_block(match: Dict[str, Any]) -> Dict[str, Any]:
    f: Dict[str, float] = {}
    for out,key in (
        ("prematch_xg_home","team_a_xg_prematch"), ("prematch_xg_away","team_b_xg_prematch"),
        ("prematch_xg_total","total_xg_prematch"), ("prematch_ppg_home","pre_match_home_ppg"),
        ("prematch_ppg_away","pre_match_away_ppg"), ("prematch_ppg_home_overall","pre_match_teamA_overall_ppg"),
        ("prematch_ppg_away_overall","pre_match_teamB_overall_ppg"),
    ): put(f,out,match.get(key))
    add_diff(f,"prematch_xg_diff",num(match.get("team_a_xg_prematch")),num(match.get("team_b_xg_prematch")))
    add_diff(f,"prematch_ppg_diff",num(match.get("pre_match_home_ppg")),num(match.get("pre_match_away_ppg")))
    return block_result("match_prematch",f,["Odds, actual/live statistics and provider narrative are excluded."])


def league_blocks(league: Dict[str, Any], home_id: int, away_id: int) -> List[Dict[str, Any]]:
    teams=team_rows(league); h=by_id(teams,home_id); a=by_id(teams,away_id)
    f: Dict[str,float]={}; rel: Dict[str,float]={}; samples: Dict[str,float]={}
    for side,team,venue in (("home",h,"home"),("away",a,"away")):
        for split in ("overall",venue):
            n=split_sample(team,split); put(samples,f"{side}_{split}_matches",n)
            for metric in TEAM_METRICS:
                v=team_metric(team,metric,split); put(f,f"{side}_{split}_{metric}",v)
                ref=league_mean(teams,metric,split)
                if v is not None and ref is not None:
                    rel[f"{side}_{split}_{metric}_vs_league"] = v-ref
    for metric in TEAM_METRICS:
        hv=team_metric(h,metric,"home"); av=team_metric(a,metric,"away")
        add_diff(rel,f"venue_{metric}_home_minus_away",hv,av)
    return [block_result("league_team_profiles",f),block_result("league_relative",rel),block_result("sample_exposure",samples)]


def form_records(form: Dict[str, Any], side: str, team_id: int) -> Dict[int,Dict[str,Any]]:
    response=form.get(side) if isinstance(form,dict) else None
    rows=api_data(response)
    out={}
    if isinstance(rows,list):
        for r in rows:
            if isinstance(r,dict) and intv(r.get("id"))==team_id:
                n=intv(r.get("last_x_match_num"))
                if n: out[n]=r
    return out


def form_blocks(form: Dict[str,Any], home_id:int, away_id:int) -> List[Dict[str,Any]]:
    f:Dict[str,float]={}; d:Dict[str,float]={}; exposure:Dict[str,float]={}
    home_records=form_records(form,"home",home_id); away_records=form_records(form,"away",away_id)
    for side,recs in (("home",home_records),("away",away_records)):
        for n in (5,6,10):
            r=recs.get(n); st=stats(r); put(exposure,f"{side}_form_last{n}_sample",n if r else None)
            if r:
                for metric in FORM_METRICS: put(f,f"{side}_last{n}_{metric}",st.get(metric))
        r5=recs.get(5); r10=recs.get(10) or recs.get(6)
        if r5 and r10:
            s5,s10=stats(r5),stats(r10)
            for metric in FORM_METRICS:
                a,b=num(s5.get(metric)),num(s10.get(metric))
                if a is not None and b is not None: d[f"{side}_form_delta_{metric}"]=a-b
    for n in (5,6,10):
        hr=home_records.get(n); ar=away_records.get(n)
        if hr and ar:
            hs,as_=stats(hr),stats(ar)
            for metric in FORM_METRICS:
                a,b=num(hs.get(metric)),num(as_.get(metric))
                if a is not None and b is not None: d[f"form_last{n}_{metric}_home_minus_away"]=a-b
    return [block_result("form_windows",f),block_result("form_deltas",d),block_result("form_exposure",exposure)]


def table_rows(table: Dict[str,Any], key:str) -> List[Dict[str,Any]]:
    d=api_data(table)
    if not isinstance(d,dict): return []
    v=d.get(key); return [x for x in v if isinstance(x,dict)] if isinstance(v,list) else []


def table_ppg(row: Optional[Dict[str,Any]]) -> Optional[float]:
    if not row:return None
    direct=num(row.get("ppg_overall"))
    if direct is not None:return direct
    pts,n=num(row.get("points")),num(row.get("matchesPlayed"))
    return pts/n if pts is not None and n and n>0 else None


def table_rank_pct(row:Optional[Dict[str,Any]], total:int)->Optional[float]:
    pos=num((row or {}).get("position"))
    if pos is None or total<=1:return None
    return 1.0-(pos-1)/(total-1)


def table_block(table:Dict[str,Any],home_id:int,away_id:int)->Dict[str,Any]:
    f:Dict[str,float]={}
    specs=(("overall","all_matches_table_overall"),("home","all_matches_table_home"),("away","all_matches_table_away"))
    rows_by={name:table_rows(table,key) for name,key in specs}
    for side,tid in (("home",home_id),("away",away_id)):
        for split,rows in rows_by.items():
            row=by_id(rows,tid)
            if not row: continue
            put(f,f"{side}_table_{split}_position",row.get("position")); put(f,f"{side}_table_{split}_ppg",table_ppg(row)); put(f,f"{side}_table_{split}_points",row.get("points")); put(f,f"{side}_table_{split}_matches",row.get("matchesPlayed")); put(f,f"{side}_table_{split}_rank_percentile",table_rank_pct(row,len(rows)))
            put(f,f"{side}_table_{split}_goal_difference",row.get("seasonGoalDifference"))
    for split in ("overall","home","away"):
        add_diff(f,f"table_{split}_ppg_diff",f.get(f"home_table_{split}_ppg"),f.get(f"away_table_{split}_ppg"))
        add_diff(f,f"table_{split}_rank_pct_diff",f.get(f"home_table_{split}_rank_percentile"),f.get(f"away_table_{split}_rank_percentile"))
    return block_result("table_relative_strength",f)


def player_rows(player:Dict[str,Any])->List[Dict[str,Any]]:
    pages=player.get("pages") if isinstance(player,dict) else None; rows=[]
    if isinstance(pages,list):
        for page in pages:
            d=api_data(page)
            if isinstance(d,list): rows.extend(x for x in d if isinstance(x,dict))
    return rows


def player_team(rows:List[Dict[str,Any]],tid:int)->List[Dict[str,Any]]:
    return [r for r in rows if tid in [x for x in (intv(r.get("club_team_id")),intv(r.get("club_team_2_id"))) if x is not None]]


def weighted_player_rate(players:List[Dict[str,Any]],key:str)->Optional[float]:
    vals=[]
    for p in players:
        mins=num(p.get("minutes_played_overall")); v=num(p.get(key))
        if mins is not None and mins>0 and v is not None: vals.append((v,mins))
    return weighted_mean(vals)


def shares(players:List[Dict[str,Any]], key:str)->Tuple[Optional[float],Optional[float],Optional[float]]:
    vals=sorted([num(p.get(key)) or 0 for p in players],reverse=True); total=sum(vals)
    if total<=0:return None,None,None
    return tuple(sum(vals[:n])/total for n in (1,2,3))


def player_block(player:Dict[str,Any],home_id:int,away_id:int)->Dict[str,Any]:
    rows=player_rows(player); f:Dict[str,float]={}
    for side,tid in (("home",home_id),("away",away_id)):
        ps=player_team(rows,tid); mins=[num(p.get("minutes_played_overall")) or 0 for p in ps]
        put(f,f"{side}_players_found",len(ps)); put(f,f"{side}_player_minutes_total",sum(mins)); put(f,f"{side}_player_minutes_mean",sum(mins)/len(mins) if mins else None)
        put(f,f"{side}_goals_per90_minutes_weighted",weighted_player_rate(ps,"goals_per_90_overall")); put(f,f"{side}_assists_per90_minutes_weighted",weighted_player_rate(ps,"assists_per_90_overall")); put(f,f"{side}_involvement_per90_minutes_weighted",weighted_player_rate(ps,"goals_involved_per_90_overall"))
        for key,label in (("goals_overall","goal"),("assists_overall","assist")):
            s=shares(ps,key)
            for n,v in zip((1,2,3),s): put(f,f"{side}_top{n}_{label}_share",v)
        invol=[dict(p, __inv=(num(p.get("goals_overall")) or 0)+(num(p.get("assists_overall")) or 0)) for p in ps]
        s=shares(invol,"__inv")
        for n,v in zip((1,2,3),s): put(f,f"{side}_top{n}_involvement_share",v)
        for pos in ("Goalkeeper","Defender","Midfielder","Forward"):
            pp=[p for p in ps if p.get("position")==pos]; put(f,f"{side}_{pos.lower()}_count",len(pp)); put(f,f"{side}_{pos.lower()}_minutes",sum(num(p.get("minutes_played_overall")) or 0 for p in pp))
    for metric in ("players_found","player_minutes_total","player_minutes_mean","goals_per90_minutes_weighted","assists_per90_minutes_weighted","involvement_per90_minutes_weighted","top1_goal_share","top2_goal_share","top3_goal_share","top1_involvement_share","top2_involvement_share","top3_involvement_share"):
        add_diff(f,f"player_{metric}_home_minus_away",f.get(f"home_{metric}"),f.get(f"away_{metric}"))
    return block_result("player_depth_quality_concentration",f,["Player stats are aggregated; no injury or lineup inference is made."])


def h2h_block(match:Dict[str,Any])->Dict[str,Any]:
    h=match.get("h2h"); f:Dict[str,float]={}
    if not isinstance(h,dict):return block_result("h2h_secondary",f,["H2H absent"])
    prev=h.get("previous_matches_results") or {}; bet=h.get("betting_stats") or {}
    for out,k in (("matches","totalMatches"),("home_team_win_pct","team_a_win_percent"),("away_team_win_pct","team_b_win_percent")): put(f,out,prev.get(k))
    for k in ("avg_goals","over15Percentage","over25Percentage","over35Percentage","clubACSPercentage","clubBCSPercentage"):
        put(f,k,bet.get(k))
    return block_result("h2h_secondary",f,["Secondary only; sample size is retained and H2H is never a standalone core vote."])


def referee_block(referee:Dict[str,Any],referee_id:Optional[int])->Dict[str,Any]:
    f:Dict[str,float]={}
    if referee_id is None:return block_result("referee",f,["No referee assigned in MatchDaten."])
    rows=[]
    if isinstance(referee,dict):
        d=api_data(referee)
        if isinstance(d,list):rows=d
        elif isinstance(referee.get("pages"),list):
            for p in referee["pages"]:
                dd=api_data(p)
                if isinstance(dd,list):rows.extend(dd)
    target=by_id(rows,referee_id)
    if not target:return block_result("referee",f,["Assigned referee not found in RefereeDaten."])
    put(f,"referee_appearances",target.get("appearances_overall"))
    for metric in REFEREE_METRICS:
        v=num(target.get(metric)); put(f,f"referee_{metric}",v)
        known=[num(r.get(metric)) for r in rows if num(r.get(metric)) is not None]
        ref=median(known) if known else None
        if v is not None and ref is not None: f[f"referee_{metric}_vs_league_median"]=v-ref
    return block_result("referee",f)


def manager_rows(side_payload:Any)->List[Dict[str,Any]]:
    if isinstance(side_payload,dict):
        d=api_data(side_payload)
        if isinstance(d,list):return [x for x in d if isinstance(x,dict)]
        if isinstance(d,dict):return [d]
    if isinstance(side_payload,list):return [x for x in side_payload if isinstance(x,dict)]
    return []


def manager_pick(rows:List[Dict[str,Any]],team_id:int,season_id:int)->Optional[Dict[str,Any]]:
    exact=[r for r in rows if intv(r.get("competition_id"))==season_id and team_id in [x for x in (intv(r.get("club_team_id")),intv(r.get("club_team_2_id"))) if x is not None]]
    if exact:return max(exact,key=lambda r:num(r.get("appearances_overall")) or 0)
    return None


def manager_block(manager:Dict[str,Any],home_id:int,away_id:int,season_id:int)->Dict[str,Any]:
    f:Dict[str,float]={}; notes=[]
    for side,tid in (("home",home_id),("away",away_id)):
        rows=manager_rows(manager.get(side) if isinstance(manager,dict) else None); row=manager_pick(rows,tid,season_id)
        if not row: notes.append(f"{side} manager season/team row unavailable"); continue
        put(f,f"{side}_manager_appearances_overall",row.get("appearances_overall")); put(f,f"{side}_manager_total_matches_managed",row.get("total_matches_managed")); put(f,f"{side}_manager_last_match_timestamp",row.get("last_match_timestamp"))
        for metric in MANAGER_METRICS: put(f,f"{side}_manager_{metric}",row.get(metric))
    for metric in MANAGER_METRICS:
        add_diff(f,f"manager_{metric}_home_minus_away",f.get(f"home_manager_{metric}"),f.get(f"away_manager_{metric}"))
    return block_result("manager",f,notes)


def build_gold_features(gold:Dict[str,Any])->Dict[str,Any]:
    ident=gold.get("identity") or {}; ns=gold.get("namespaces") or {}
    match=api_data(ns.get("match")); match=match if isinstance(match,dict) else {}
    blocks=[]
    blocks.append(match_block(match))
    blocks.extend(league_blocks(ns.get("league") or {},ident["home_id"],ident["away_id"]))
    blocks.extend(form_blocks(ns.get("form") or {},ident["home_id"],ident["away_id"]))
    blocks.append(table_block(ns.get("table") or {},ident["home_id"],ident["away_id"]))
    blocks.append(player_block(ns.get("player") or {},ident["home_id"],ident["away_id"]))
    blocks.append(h2h_block(match))
    blocks.append(referee_block(ns.get("referee") or {},ident.get("referee_id")))
    blocks.append(manager_block(ns.get("manager") or {},ident["home_id"],ident["away_id"],ident["season_id"]))
    flat:Dict[str,float]={}; owners={}
    for b in blocks:
        for k,v in b["features"].items():
            if k in flat: raise ValueError(f"duplicate gold feature: {k}")
            flat[k]=v; owners[k]=b["name"]
    return {
        "feature_builder_version":"0.1.0",
        "identity":ident,
        "feature_count":len(flat),
        "available_block_count":sum(1 for b in blocks if b["available"]),
        "blocks":blocks,
        "features":flat,
        "feature_owners":owners,
        "policies":{
            "no_odds":True,"no_actual_match_stats":True,"no_imputation":True,
            "form_windows_overlap":"kept as correlated numerical features; never independent evidence votes",
            "table_overlap":"relative table features preferred; result totals are not independent evidence",
            "player_interpretation":"aggregate production/depth only; no injury or lineup inference",
            "referee_manager":"sample exposure retained; later shrinkage/OOS validation required",
        },
    }
