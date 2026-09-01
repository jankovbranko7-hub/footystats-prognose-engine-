#!/usr/bin/env python3
"""FootyStats V0.5.0 SHADOW research runner.

Research-only. Reads archived five-file analysis packages, keeps the V0.4.0
baseline untouched, and tests three hypotheses: family-relative edge, bounded
recent-form adjustment, and parallel probability thresholds with sensitivity
bands. It does not deploy to Render and does not change the V2 Shortcut.
"""
from __future__ import annotations
import argparse,csv,json,math,os,re,statistics,zipfile
from typing import Any,Dict,Iterable,List,Optional,Tuple

SHADOW_VERSION="0.5.0-shadow.1"
THRESHOLDS=(0.60,0.62,0.65,0.67)
MARKETS=("home_win","away_win","btts_yes","btts_no","over_2_5","under_2_5")
LABELS={"home_win":"Sieg Heim","away_win":"Sieg Auswärts","btts_yes":"BTTS Yes","btts_no":"BTTS No","over_2_5":"Over 2,5","under_2_5":"Under 2,5"}

def num(v):
    if v is None or isinstance(v,bool):return None
    try:
        x=float(str(v).strip().replace(",",".").replace("%",""))
        return x if math.isfinite(x) else None
    except:return None

def clamp(x,lo,hi):return max(lo,min(hi,x))

def poisson(hl,al,cap=10):
    ph=[math.exp(-hl)*hl**i/math.factorial(i) for i in range(cap+1)]
    pa=[math.exp(-al)*al**j/math.factorial(j) for j in range(cap+1)]
    mass=sum(ph)*sum(pa);hw=dr=aw=btts=o25=0.0
    for i,x in enumerate(ph):
        for j,y in enumerate(pa):
            q=x*y/mass
            if i>j:hw+=q
            elif i==j:dr+=q
            else:aw+=q
            if i and j:btts+=q
            if i+j>=3:o25+=q
    return {"home_win":hw,"draw":dr,"away_win":aw,"btts_yes":btts,"btts_no":1-btts,"over_2_5":o25,"under_2_5":1-o25}

def same_id(a,b):
    na,nb=num(a),num(b)
    return na is not None and nb is not None and int(na)==int(nb)

def form_records(data):
    out=[]
    if not isinstance(data,dict):return out
    for page in data.get("teams") or []:
        if isinstance(page,dict):out.extend(x for x in (page.get("data") or []) if isinstance(x,dict))
    return out

def form_window(item):
    s=item.get("stats") or {};sample=num(item.get("last_x_match_num")) or num(s.get("last_x"))
    return {"sample":int(sample) if sample is not None else None,"ppg":num(s.get("seasonPPG_overall")),"xg":num(s.get("xg_for_avg_overall")),"xga":num(s.get("xg_against_avg_overall")),"gf":num(s.get("seasonScoredAVG_overall")),"ga":num(s.get("seasonConcededAVG_overall")),"sot":num(s.get("shotsOnTargetAVG_overall")),"btts":num(s.get("seasonBTTSPercentage_overall")),"o25":num(s.get("seasonOver25Percentage_overall")),"u25":num(s.get("seasonUnder25Percentage_overall"))}

def team_form(data,team_id):
    w=[form_window(x) for x in form_records(data) if same_id(x.get("id"),team_id)];w=[x for x in w if x.get("sample")]
    if not w:return {"available":False}
    w.sort(key=lambda x:x["sample"]);recent=next((x for x in w if x["sample"]==5),w[0]);refs=[x for x in w if (x["sample"] or 0)>=8];reference=refs[-1] if refs else w[-1]
    return {"available":True,"recent":recent,"reference":reference,"windows":w}

def relative_delta(recent,reference):
    if recent is None or reference is None or reference<=0:return None
    return clamp((recent-reference)/max(reference,.35),-.50,.50)

def signal_agreement(recent,reference,key):
    dx=relative_delta(num(recent.get(key)),num(reference.get(key)));ds=relative_delta(num(recent.get("sot")),num(reference.get("sot")))
    if dx is None or ds is None:return None
    if abs(dx)<.03 or abs(ds)<.03:return True
    return (dx>0)==(ds>0)

def regression_diagnostic(recent,attack=True):
    actual=num(recent.get("gf" if attack else "ga"));expected=num(recent.get("xg" if attack else "xga"))
    if actual is None or expected is None or expected<=0:return {"available":False}
    diff=actual-expected;ratio=actual/expected
    status="STARKE ÜBERPERFORMANCE" if diff>=.45 else ("STARKE UNTERPERFORMANCE" if diff<=-.45 else ("MODERATE ABWEICHUNG" if abs(diff)>=.25 else "NAHE UNDERLYING"))
    return {"available":True,"actual":round(actual,3),"expected":round(expected,3),"difference":round(diff,3),"ratio":round(ratio,3),"status":status}

def form_adjustment(data,home_id,away_id):
    home,away=team_form(data,home_id),team_form(data,away_id)
    if not(home.get("available") and away.get("available")):return {"available":False,"home_factor":1.0,"away_factor":1.0,"reason":"Formfenster nicht für beide Teams verfügbar."}
    hr,hb,ar,ab=home["recent"],home["reference"],away["recent"],away["reference"]
    ha=relative_delta(num(hr.get("xg")),num(hb.get("xg")));ad=relative_delta(num(ar.get("xga")),num(ab.get("xga")));aa=relative_delta(num(ar.get("xg")),num(ab.get("xg")));hd=relative_delta(num(hr.get("xga")),num(hb.get("xga")))
    def combine(a,b,agree_a,agree_b):
        vals=[x for x in (a,b) if x is not None]
        if not vals:return 0.0,{"raw":None,"scaled":0.0,"agreement_modifier":0.0}
        raw=statistics.mean(vals);scaled=clamp(raw*.25,-.10,.10);agreements=[x for x in (agree_a,agree_b) if x is not None];modifier=1.0 if not agreements or all(agreements) else .75
        return scaled*modifier,{"raw":round(raw,4),"scaled_before_agreement":round(scaled,4),"agreement_modifier":modifier}
    h_adj,h_detail=combine(ha,ad,signal_agreement(hr,hb,"xg"),signal_agreement(ar,ab,"xga"));a_adj,a_detail=combine(aa,hd,signal_agreement(ar,ab,"xg"),signal_agreement(hr,hb,"xga"))
    return {"available":True,"home_factor":round(1+h_adj,6),"away_factor":round(1+a_adj,6),"home_adjustment_pct":round(h_adj*100,2),"away_adjustment_pct":round(a_adj*100,2),"home_components":{"home_attack_xg_delta":ha,"away_defence_xga_delta":ad,**h_detail},"away_components":{"away_attack_xg_delta":aa,"home_defence_xga_delta":hd,**a_detail},"regression":{"home_attack":regression_diagnostic(hr,True),"home_defence":regression_diagnostic(hr,False),"away_attack":regression_diagnostic(ar,True),"away_defence":regression_diagnostic(ar,False)},"windows":{"home_recent":hr.get("sample"),"home_reference":hb.get("sample"),"away_recent":ar.get("sample"),"away_reference":ab.get("sample")}}

def reliability_from_analysis(a):
    model=((a.get("expected_goals") or {}).get("league_relative_model") or {});pool=model.get("partial_pooling") or {};vals=[]
    for block in ("home_attack","away_defence","away_attack","home_defence"):
        r=num((pool.get(block) or {}).get("reliability"))
        if r is not None:vals.append(clamp(r,0,1))
    if vals:rel=statistics.mean(vals)
    else:rel={"HOCH":.85,"MITTEL":.65,"NIEDRIG":.40}.get(str((a.get("samples") or {}).get("security") or "").upper(),.50)
    return rel,{"block_reliabilities":vals}

def sensitivity_bands(hl,al,reliability):
    spread=clamp(.04+.10*(1-reliability),.04,.14);grids=[poisson(max(.05,hl*hf),max(.05,al*af)) for hf in (1-spread,1+spread) for af in (1-spread,1+spread)];out={}
    for m in MARKETS:
        v=[g[m] for g in grids];out[m]={"low_pct":round(min(v)*100,1),"high_pct":round(max(v)*100,1),"width_pp":round((max(v)-min(v))*100,1)}
    out["_meta"]={"lambda_spread_pct":round(spread*100,1),"calibrated_ci":False};return out

def family_competitor(m,p):
    if m=="btts_yes":return "btts_no",p["btts_no"]
    if m=="btts_no":return "btts_yes",p["btts_yes"]
    if m=="over_2_5":return "under_2_5",p["under_2_5"]
    if m=="under_2_5":return "over_2_5",p["over_2_5"]
    if m=="home_win":return max((("draw",p["draw"]),("away_win",p["away_win"])),key=lambda x:x[1])
    if m=="away_win":return max((("draw",p["draw"]),("home_win",p["home_win"])),key=lambda x:x[1])
    raise KeyError(m)

def family_edge(m,p):
    competitor,cp=family_competitor(m,p);edge=(p[m]-cp)*100;status="KLAR" if edge>=5 else ("KNAPP" if edge>=2 else "NICHT VORHANDEN")
    return {"status":status,"edge_pp":round(edge,1),"competitor":competitor,"competitor_pct":round(cp*100,1)}

def cross_family_confirmation(rank):
    if len(rank)<2:return {"status":"NICHT VERFÜGBAR"}
    a,b=rank[0],rank[1];pair={a[0],b[0]};coherent=pair in ({"btts_yes","over_2_5"},{"btts_no","under_2_5"});strong=min(a[1],b[1])>=.60
    return {"status":"BESTÄTIGEND" if coherent and strong else ("SCHWACH BESTÄTIGEND" if coherent else "NEUTRAL"),"markets":[a[0],b[0]],"probabilities_pct":[round(a[1]*100,1),round(b[1]*100,1)],"same_game_picture":coherent}

def threshold_scenarios(probs,top,edge,bands,analysis):
    d=analysis.get("diagnostics") or {};quality=str(d.get("data_quality") or "MITTEL");sample=str(d.get("sample_security") or (analysis.get("samples") or {}).get("security") or "MITTEL");same_top=top==((analysis.get("strongest_market") or {}).get("key"));rob=str(d.get("robustness_status") or "NICHT PRÜFBAR");low=num((bands.get(top) or {}).get("low_pct"));out={}
    for threshold in THRESHOLDS:
        reasons=[]
        if probs[top]<threshold:reasons.append("probability")
        if quality=="NIEDRIG":reasons.append("data_quality")
        if sample=="NIEDRIG":reasons.append("sample")
        if edge.get("status")!="KLAR":reasons.append("family_edge")
        if low is not None and low<max(55.0,threshold*100-7.0):reasons.append("sensitivity")
        removal="V0.4 PROXY" if same_top else "NEU ZU BERECHNEN"
        if same_top and ("NICHT BESTANDEN" in rob or "INSTABIL" in rob):reasons.append("v04_removal_proxy")
        out[str(int(threshold*100))]={"status":"SHADOW_KANDIDAT" if not reasons else "KEIN_KANDIDAT","failed":reasons,"removal_test":removal}
    return out

def archive_sources(a):return {k:v["content"] for k,v in (a.get("sources") or {}).items() if isinstance(v,dict) and "content" in v}

def analyze_archive(archive,name=""):
    a=archive.get("analysis") or {};match=archive.get("match") or ((a.get("audit") or {}).get("match") or {})
    if not a.get("ok"):return {"ok":False,"archive":name,"reason":"baseline_analysis_not_ok"}
    e=a.get("expected_goals") or {};hl0,al0=num(e.get("home")),num(e.get("away"))
    if hl0 is None or al0 is None or hl0<=0 or al0<=0:return {"ok":False,"archive":name,"reason":"missing_v04_lambdas"}
    pair=a.get("pairing") or {};sources=archive_sources(archive);form=form_adjustment(sources.get("form"),match.get("home_id") or pair.get("home_id"),match.get("away_id") or pair.get("away_id"));hl=clamp(hl0*num(form.get("home_factor") or 1),.18,3.8);al=clamp(al0*num(form.get("away_factor") or 1),.18,3.8);p=poisson(hl,al);rank=sorted(((m,p[m]) for m in MARKETS),key=lambda x:x[1],reverse=True);top,tp=rank[0];second,sp=rank[1];edge=family_edge(top,p);rel,rel_detail=reliability_from_analysis(a);bands=sensitivity_bands(hl,al,rel);confirm=cross_family_confirmation(rank);scenarios=threshold_scenarios(p,top,edge,bands,a)
    old_top=(a.get("strongest_market") or {}).get("key");old_tp=num((a.get("strongest_market") or {}).get("probability_pct"));old_second=(a.get("second_market") or {}).get("key");sp0=num((a.get("second_market") or {}).get("probability_pct"));old_edge=old_tp-sp0 if old_tp is not None and sp0 is not None else None
    return {"ok":True,"shadow_version":SHADOW_VERSION,"non_production":True,"archive":name,"match":{"match_id":match.get("match_id") or pair.get("match_id"),"home_name":match.get("home_name"),"away_name":match.get("away_name"),"competition_id":match.get("competition_id") or pair.get("competition_id"),"season":match.get("season"),"created_at":archive.get("created_at")},"baseline_v04":{"model_version":a.get("model_version"),"lambda_home":round(hl0,4),"lambda_away":round(al0,4),"top_market":old_top,"top_probability_pct":old_tp,"second_market":old_second,"old_cross_market_edge_pp":round(old_edge,1) if old_edge is not None else None,"decision":a.get("decision")},"shadow_v05":{"lambda_home":round(hl,4),"lambda_away":round(al,4),"form_adjustment":form,"probabilities":{k:round(v,8) for k,v in p.items()},"markets":[{"rank":i+1,"key":k,"label":LABELS[k],"probability_pct":round(v*100,1)} for i,(k,v) in enumerate(rank)],"top_market":top,"top_probability_pct":round(tp*100,1),"second_market":second,"second_probability_pct":round(sp*100,1),"family_edge":edge,"cross_family_confirmation":confirm,"sensitivity_bands":bands,"reliability":{"mean":round(rel,4),**rel_detail},"threshold_scenarios":scenarios},"comparison":{"top_market_changed":top!=old_top,"top_probability_change_pp":round(tp*100-old_tp,1) if old_tp is not None else None,"hypothesis_1_family_edge_replaces_unrelated_edge":True,"hypothesis_2_thresholds_are_parallel_scenarios":[60,62,65,67],"hypothesis_3_over_signal_is_measured_not_hardcoded":True},"research_policy":{"production_v04_untouched":True,"shortcut_unchanged":True,"render_unchanged":True,"odds_used":False,"external_match_data_used":False,"sensitivity_band_is_not_calibrated_confidence_interval":True,"promotion_requires_out_of_sample_validation":True}}

def iter_archives(path):
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as z:
            for name in z.namelist():
                if not name.lower().endswith(".json") or "__MACOSX" in name:continue
                try:yield name,json.loads(z.read(name).decode("utf-8"))
                except:continue
    elif os.path.isdir(path):
        for root,_,files in os.walk(path):
            for fn in files:
                if not fn.lower().endswith(".json"):continue
                p=os.path.join(root,fn)
                try:
                    with open(p,encoding="utf-8") as f:yield p,json.load(f)
                except:continue
    else:
        with open(path,encoding="utf-8") as f:yield path,json.load(f)

def run(input_path,output_dir):
    os.makedirs(output_dir,exist_ok=True);rows=[];details=[]
    for name,archive in iter_archives(input_path):
        r=analyze_archive(archive,name)
        if not r.get("ok"):continue
        details.append(r);m=r["match"];b=r["baseline_v04"];s=r["shadow_v05"]
        rows.append({"match_id":m.get("match_id"),"home":m.get("home_name"),"away":m.get("away_name"),"baseline_version":b.get("model_version"),"v04_top":b.get("top_market"),"v04_pct":b.get("top_probability_pct"),"v04_decision":b.get("decision"),"v04_cross_market_edge_pp":b.get("old_cross_market_edge_pp"),"v05_top":s.get("top_market"),"v05_pct":s.get("top_probability_pct"),"v05_family_edge_pp":(s.get("family_edge") or {}).get("edge_pp"),"v05_family_edge_status":(s.get("family_edge") or {}).get("status"),"cross_family_confirmation":(s.get("cross_family_confirmation") or {}).get("status"),"home_form_adj_pct":(s.get("form_adjustment") or {}).get("home_adjustment_pct"),"away_form_adj_pct":(s.get("form_adjustment") or {}).get("away_adjustment_pct"),"top_changed":r["comparison"].get("top_market_changed"),"candidate_60":(s.get("threshold_scenarios") or {}).get("60",{}).get("status"),"candidate_62":(s.get("threshold_scenarios") or {}).get("62",{}).get("status"),"candidate_65":(s.get("threshold_scenarios") or {}).get("65",{}).get("status"),"candidate_67":(s.get("threshold_scenarios") or {}).get("67",{}).get("status")})
    csv_path=os.path.join(output_dir,"v05_shadow_comparison.csv")
    if rows:
        with open(csv_path,"w",encoding="utf-8",newline="") as f:w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    details_path=os.path.join(output_dir,"v05_shadow_details.json");json.dump(details,open(details_path,"w",encoding="utf-8"),ensure_ascii=False,indent=2)
    versions={}
    for r in rows:versions[str(r.get("baseline_version"))]=versions.get(str(r.get("baseline_version")),0)+1
    summary={"shadow_version":SHADOW_VERSION,"archives_analyzed":len(rows),"baseline_versions":versions,"top_market_changed":sum(bool(r.get("top_changed")) for r in rows),"family_edge_clear":sum(r.get("v05_family_edge_status")=="KLAR" for r in rows),"cross_family_confirming":sum(r.get("cross_family_confirmation")=="BESTÄTIGEND" for r in rows),"threshold_candidates":{str(t):sum(r.get(f"candidate_{t}")=="SHADOW_KANDIDAT" for r in rows) for t in (60,62,65,67)},"mean_abs_home_form_adjustment_pct":round(statistics.mean(abs(num(r.get("home_form_adj_pct")) or 0) for r in rows),3) if rows else None,"mean_abs_away_form_adjustment_pct":round(statistics.mean(abs(num(r.get("away_form_adj_pct")) or 0) for r in rows),3) if rows else None,"policy":"Research-only. No production threshold or model change is authorized by this output."}
    summary_path=os.path.join(output_dir,"v05_shadow_summary.json");json.dump(summary,open(summary_path,"w",encoding="utf-8"),ensure_ascii=False,indent=2);return summary

def main():
    ap=argparse.ArgumentParser();ap.add_argument("input");ap.add_argument("--output",default="shadow_v05_output");args=ap.parse_args();print(json.dumps(run(args.input,args.output),ensure_ascii=False,indent=2))
if __name__=="__main__":main()
