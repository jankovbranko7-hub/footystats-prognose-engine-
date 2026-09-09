import copy
from fastapi import FastAPI

from research.context_snapshot_archive import build_context_snapshot_record
from research.context_snapshot_store import persist_context_snapshot, snapshot_store_config
from research.current_context_runtime import build_runtime_context
from research.learned_reliability_policy import POLICY_SOURCE, learned_action
from research.research_context_engine import build_analysis_with_current_context, install_context_production, install_research_context

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
PLAYER={"pages":[{"data":[
    {"id":1001,"club_team_id":10,"full_name":"Max Striker","known_as":"Max Striker","position":"Forward","appearances_overall":8,"minutes_played_overall":650,"goals_overall":5,"assists_overall":2,"goals_per_90_overall":0.69,"assists_per_90_overall":0.28,"goals_involved_per_90_overall":0.97,"rank_in_club_top_scorer":1},
    {"id":1002,"club_team_id":10,"full_name":"Other Forward","known_as":"Other Forward","position":"Forward","appearances_overall":7,"minutes_played_overall":420,"goals_overall":2,"assists_overall":1,"goals_per_90_overall":0.43,"assists_per_90_overall":0.21,"goals_involved_per_90_overall":0.64,"rank_in_club_top_scorer":2},
    {"id":2001,"club_team_id":20,"full_name":"Away Player","known_as":"Away Player","position":"Forward","appearances_overall":8,"minutes_played_overall":600,"goals_overall":3,"assists_overall":1,"goals_per_90_overall":0.45,"assists_per_90_overall":0.15,"goals_involved_per_90_overall":0.60,"rank_in_club_top_scorer":1},
]}]}
SNAPSHOT="2026-10-09T10:00:00Z"
ctx=build_runtime_context(MATCH,FORM,generated_at_utc=SNAPSHOT)
assert ctx["integrity"]["valid"] is True
assert ctx["trend"]["home"]["form_windows"]["windows"] == [5,6,10]
assert "stats.xg" in ctx["trend"]["home"]["form_windows"]["metrics"]
assert "trend_score" not in str(ctx)

PAIR={"ok":True,"match_file":"a.json","league_file":"b.json","match_data":MATCH,"league_data":{"league":"x"},"supplemental_data":{"form":FORM,"table":{"table":"x"},"player":PLAYER},"source_files":{"match":"a.json","league":"b.json","form":"c.json","table":"d.json","player":"e.json"}}
PARSED=[
    {"name":"a.json","data":MATCH},
    {"name":"b.json","data":PAIR["league_data"]},
    {"name":"c.json","data":FORM},
    {"name":"d.json","data":PAIR["supplemental_data"]["table"]},
    {"name":"e.json","data":PLAYER},
]
BASELINE={"ok":True,"model_version":"0.4.3","probabilities":{"home_win":0.41,"draw":0.29,"away_win":0.30,"btts_yes":0.55,"btts_no":0.45,"over_2_5":0.51,"under_2_5":0.49},"expected_goals":{"home":1.4,"away":1.1},"markets":[],"strongest_market":{"label":"BTTS YES","probability_pct":55},"decision":"BEOBACHTEN","method":{"full5_alpha":3.0}}
class Legacy:
    def __init__(self): self.app=FastAPI()
    def select_pair(self, parsed_files): return copy.deepcopy(PAIR)
    def _analyze_bundle(self, parsed_files): return copy.deepcopy(BASELINE)
legacy=Legacy()
out=build_analysis_with_current_context(legacy,PARSED,generated_at_utc=SNAPSHOT,fetch_external=False)
assert out["probabilities"] == BASELINE["probabilities"]
assert out["legacy_v043_decision_diagnostic"] == "BEOBACHTEN"
assert out["decision"] == "AUSLASSEN / KEIN BET"
assert out["final_decision_source"] == POLICY_SOURCE
assert out["manual_performance_gates"] == "NONE"
assert out["research_context"]["probabilities_modified_by_current_context"] is False
assert out["research_context"]["iphone_file_count"] == 5
assert out["context_interpretation"]["manual_injury_penalty"] is False
assert out["context_interpretation"]["manual_news_score"] is False
assert "news_score" not in str(out["context_interpretation"])
assert learned_action(0.80)["decision"] == "SPIELEN"
assert learned_action(0.68)["decision"] == "BEOBACHTEN"
assert learned_action(0.59)["decision"] == "AUSLASSEN / KEIN BET"

record=build_context_snapshot_record(PARSED,PAIR,out)
assert record["snapshot_schema"] == "footystats-current-context-v1"
assert set(record["five_file_sources"]) == {"match","league","form","table","player"}
assert record["policies"]["target_result_in_snapshot"] is False
assert record["policies"]["server_side_persistence_claimed"] is False
assert record["frozen_v043_output"]["probabilities"] == BASELINE["probabilities"]
assert len(record["record_sha256"]) == 64
assert "actual_1x2" not in str(record)

assert snapshot_store_config({}) == {"valid":True,"mode":"NONE","durable":False}
assert persist_context_snapshot(record,environ={})["status"] == "DISABLED"
config_error=persist_context_snapshot(record,environ={"CONTEXT_SNAPSHOT_STORE":"SUPABASE"})
assert config_error["status"] == "CONFIG_ERROR"

class DummyResponse:
    status=201
    def __enter__(self): return self
    def __exit__(self,*args): return False
captured={}
def dummy_opener(request, timeout=15.0):
    captured["url"]=request.full_url
    captured["authorization"]=request.headers.get("Authorization")
    captured["body"]=request.data
    return DummyResponse()
env={"CONTEXT_SNAPSHOT_STORE":"SUPABASE","SUPABASE_URL":"https://example.supabase.co","SUPABASE_SERVICE_ROLE_KEY":"server-secret","CONTEXT_SNAPSHOT_TABLE":"footystats_context_snapshots"}
persisted=persist_context_snapshot(record,environ=env,opener=dummy_opener)
assert persisted["status"] == "PERSISTED"
assert persisted["record_sha256"] == record["record_sha256"]
assert "server-secret" not in str(persisted)
assert captured["authorization"] == "Bearer server-secret"
assert b'"record_sha256"' in captured["body"]

install_research_context(legacy)
paths={getattr(route,"path",None) for route in legacy.app.router.routes}
assert "/api/research/predict-context" in paths
assert "/api/research/context-archive-bundle" in paths
assert "/api/research/context-health" in paths

prod=Legacy()
# Production installer must preserve a frozen baseline closure and replace only
# the bundle/health/archive delivery path.
prod.app.add_api_route("/api/health",lambda:{"old":True},methods=["GET"])
install_context_production(prod)
prod_paths={getattr(route,"path",None) for route in prod.app.router.routes}
assert "/api/health" in prod_paths
assert "/api/archive-bundle" in prod_paths
assert prod.app.version == "0.5.0"
print("context-aware learned-policy smoke passed")
