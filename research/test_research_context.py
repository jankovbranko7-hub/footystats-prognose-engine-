import copy
from fastapi import FastAPI

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

PAIR={"ok":True,"match_data":MATCH,"league_data":{},"supplemental_data":{"form":FORM,"table":{},"player":{}},"source_files":{"match":"a","league":"b","form":"c","table":"d","player":"e"}}
BASELINE={"ok":True,"model_version":"0.4.3","probabilities":{"home_win":0.41,"draw":0.29,"away_win":0.30,"btts_yes":0.55,"over_2_5":0.51},"decision":"BEOBACHTEN"}
class Legacy:
    app=FastAPI()
    def select_pair(self, parsed_files): return copy.deepcopy(PAIR)
    def _analyze_bundle(self, parsed_files): return copy.deepcopy(BASELINE)
legacy=Legacy()
out=build_analysis_with_current_context(legacy,[],generated_at_utc=SNAPSHOT,fetch_external=False)
assert out["probabilities"] == BASELINE["probabilities"]
assert out["decision"] == BASELINE["decision"]
assert out["research_context"]["probabilities_modified_by_current_context"] is False
assert out["research_context"]["iphone_file_count"] == 5
install_research_context(legacy)
paths={getattr(route,"path",None) for route in legacy.app.router.routes}
assert "/api/research/predict-context" in paths
assert "/api/research/context-health" in paths
print("research context smoke passed")
