import copy
from fastapi import FastAPI

from research.context_snapshot_archive import build_context_snapshot_record
from research.current_context_runtime import build_runtime_context
from research.research_context_engine import build_analysis_with_current_context, install_research_context

MATCH={"data":[{"id":123,"homeID":10,"awayID":20,"home_name":"Home FC","away_name":"Away FC","date_unix":1791554400,"competition_id":1}]}
FORM={"teams":[
    {"data":[
        {"id":10,"last_x_match_num":5,"last_x_home_away_or_overall":0,"stats":{"xg":1.8,"ppg":2.0,"btts":60}},
        {"id":10,"last_x_match_num":6,"last_x_home_away_or_overall":0,"stats":{"xg":1.7,"ppg":1.8,"btts":50}},
        {"id":10,"last_x_match_num":10,"last_x_home_away_or_overall":0,"stats":{"xg":1.5,"ppg":1.6,"btts":40}},
    ]},
    {"data":[
        {"id":20,"last_x_match_num":5,"last_x_home_away_or_overall":0,"stats":{"xg":1.1,"ppg":1.0,"btts":40}},
        {"id":20,"last_x_match_num":6,"last_x_home_away_or_overall":0,"stats":{"xg":1.2,"ppg":1.1,"btts":50}},
        {"id":20,"last_x_match_num":10,"last_x_home_away_or_overall":0,"stats":{"xg":1.3,"ppg":1.2,"btts":60}},
    ]},
]}
SNAPSHOT="2026-10-09T10:00:00Z"
ctx=build_runtime_context(MATCH,FORM,generated_at_utc=SNAPSHOT)
assert ctx["integrity"]["valid"] is True
assert ctx["trend"]["home"]["form_windows"]["windows"] == [5,6,10]
assert "stats.xg" in ctx["trend"]["home"]["form_windows"]["metrics"]
assert "trend_score" not in str(ctx)

PAIR={"ok":True,"match_file":"a.json","league_file":"b.json","match_data":MATCH,"league_data":{"league":"x"},"supplemental_data":{"form":FORM,"table":{"table":"x"},"player":{"player":"x"}},"source_files":{"match":"a.json","league":"b.json","form":"c.json","table":"d.json","player":"e.json"}}
PARSED=[
    {"name":"a.json","data":MATCH},
    {"name":"b.json","data":PAIR["league_data"]},
    {"name":"c.json","data":FORM},
    {"name":"d.json","data":PAIR["supplemental_data"]["table"]},
    {"name":"e.json","data":PAIR["supplemental_data"]["player"]},
]
BASELINE={"ok":True,"model_version":"0.4.3","probabilities":{"home_win":0.41,"draw":0.29,"away_win":0.30,"btts_yes":0.55,"over_2_5":0.51},"expected_goals":{"home":1.4,"away":1.1},"markets":[],"strongest_market":{"label":"BTTS YES","probability_pct":55},"decision":"BEOBACHTEN","method":{"full5_alpha":3.0}}
class Legacy:
    app=FastAPI()
    def select_pair(self, parsed_files): return copy.deepcopy(PAIR)
    def _analyze_bundle(self, parsed_files): return copy.deepcopy(BASELINE)
legacy=Legacy()
out=build_analysis_with_current_context(legacy,PARSED,generated_at_utc=SNAPSHOT,fetch_external=False)
assert out["probabilities"] == BASELINE["probabilities"]
assert out["decision"] == BASELINE["decision"]
assert out["research_context"]["probabilities_modified_by_current_context"] is False
assert out["research_context"]["iphone_file_count"] == 5
record=build_context_snapshot_record(PARSED,PAIR,out)
assert record["snapshot_schema"] == "footystats-current-context-v1"
assert set(record["five_file_sources"]) == {"match","league","form","table","player"}
assert record["policies"]["target_result_in_snapshot"] is False
assert record["policies"]["server_side_persistence_claimed"] is False
assert record["frozen_v043_output"]["probabilities"] == BASELINE["probabilities"]
assert len(record["record_sha256"]) == 64
assert "actual_1x2" not in str(record)
install_research_context(legacy)
paths={getattr(route,"path",None) for route in legacy.app.router.routes}
assert "/api/research/predict-context" in paths
assert "/api/research/context-archive-bundle" in paths
assert "/api/research/context-health" in paths
print("research context + snapshot archive smoke passed")
