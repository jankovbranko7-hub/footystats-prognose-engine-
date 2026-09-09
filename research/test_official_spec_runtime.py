"""Smoke tests for FootyStats Official Analysis Spec v1.1."""
import app_v040 as legacy

from research.footystats_official_spec import (
    SPEC_VERSION,
    build_official_spec_report,
    load_field_registry,
    load_shortcut_schema,
)

registry = load_field_registry()
shortcut = load_shortcut_schema()
assert SPEC_VERSION == "1.1"
assert registry["schema_version"] == "1.1"
assert shortcut["schema_version"] == "1.1"
assert shortcut["render_upload"]["exact_file_count"] == 5
assert registry["files"]["FormDaten"]["max_time_supported"] is False
assert registry["files"]["PlayerDaten"]["pagination"]["max_players_per_page"] == 200

kickoff = 2_000_000_000
match_data = {
    "_footystats_meta": {
        "endpoint": "/match",
        "captured_at_unix": kickoff - 120,
        "kickoff_unix": kickoff,
        "temporal_mode": "PREMATCH_FIELD_WHITELIST",
    },
    "payload": {
        "id": 123,
        "homeID": 1,
        "awayID": 2,
        "competition_id": 99,
        "date_unix": kickoff,
        "status": "incomplete",
        "btts_potential": 70,
        "avg_potential": 1.7,
        "home_ppg": 1.4,
        "away_ppg": 1.6,
        "pre_match_home_ppg": 1.4,
        "pre_match_away_ppg": 1.6,
    },
}
league_data = {
    "_footystats_meta": {
        "endpoint": "/league-season",
        "captured_at_unix": kickoff - 120,
        "kickoff_unix": kickoff,
        "max_time": kickoff - 1,
    },
    "payload": {},
}
form_data = {
    "_footystats_meta": {
        "endpoint": "/lastx",
        "captured_at_unix": kickoff - 120,
        "kickoff_unix": kickoff,
    },
    "payload": {"home": {}, "away": {}},
}
table_data = {
    "_footystats_meta": {
        "endpoint": "/league-tables",
        "captured_at_unix": kickoff - 120,
        "kickoff_unix": kickoff,
        "max_time": kickoff - 1,
    },
    "payload": {},
}
player_data = {
    "_footystats_meta": {
        "endpoint": "/league-players",
        "captured_at_unix": kickoff - 120,
        "kickoff_unix": kickoff,
        "max_time": kickoff - 1,
        "pagination_complete": True,
    },
    "payload": {},
}

pair = {
    "ok": True,
    "match_data": match_data,
    "league_data": league_data,
    "supplemental_data": {
        "form": form_data,
        "table": table_data,
        "player": player_data,
    },
}
report = build_official_spec_report(legacy, pair, now_unix=kickoff - 60)
assert report["version"] == "1.1"
assert report["probability_core_modified"] is False
assert report["final_decision_modified"] is False
assert report["official_tutorial_examples"]["btts_yes_example"]["live_status"] == "PASS"
assert report["official_tutorial_examples"]["btts_yes_example"]["strict_historical_status"] == "PASS"
assert report["official_tutorial_examples"]["low_scoring_example"]["live_status"] == "FAIL"
assert report["temporal_safety"]["overall"] == "STRICT_PREMATCH_VERIFIED"
assert report["player_pagination"]["status"] == "COMPLETE"
assert report["target_match_leakage"]["postmatch_target_fields_present"] == []

print("FootyStats Official Analysis Spec v1.1 smoke passed")
