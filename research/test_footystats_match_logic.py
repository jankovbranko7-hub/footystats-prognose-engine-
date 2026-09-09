from research.footystats_match_logic import (
    CONTRADICT,
    SUPPORT,
    resolve_action,
)


def signals(market, status):
    required = (
        ("VENUE_PROFILE", "FIRST_HALF_BTTS", "CS_FTS_PROFILE", "CURRENT_FORM")
        if market in {"btts_yes", "btts_no", "over_2_5", "under_2_5"}
        else ("VENUE_PROFILE", "CURRENT_FORM", "RELATIVE_TABLE_STRENGTH", "PLAYER_DEPTH")
    )
    return [{"domain": domain, "status": status} for domain in required]


r = resolve_action("BEOBACHTEN", "btts_yes", signals("btts_yes", SUPPORT))
assert r["final_action"] == "SPIELEN"
assert r["mode"] == "UNANIMOUS_CONTEXT_CONFIRMATION"
assert r["unanimous_support"] is True

r = resolve_action("SPIELEN", "btts_yes", [
    {"domain": "VENUE_PROFILE", "status": SUPPORT},
    {"domain": "FIRST_HALF_BTTS", "status": CONTRADICT},
    {"domain": "CS_FTS_PROFILE", "status": SUPPORT},
    {"domain": "CURRENT_FORM", "status": SUPPORT},
])
assert r["final_action"] == "BEOBACHTEN"
assert r["mode"] == "CONTEXT_VETO"
assert r["contradicting_domains"] == ["FIRST_HALF_BTTS"]

r = resolve_action("BEOBACHTEN", "home_win", [
    {"domain": "VENUE_PROFILE", "status": SUPPORT},
    {"domain": "CURRENT_FORM", "status": "NEUTRAL"},
    {"domain": "RELATIVE_TABLE_STRENGTH", "status": SUPPORT},
    {"domain": "PLAYER_DEPTH", "status": "NICHT VERFÜGBAR"},
])
assert r["final_action"] == "BEOBACHTEN"
assert r["mode"] == "RELIABILITY_ACTION_PRESERVED"

assert resolve_action("AUSLASSEN / KEIN BET", "over_2_5", signals("over_2_5", CONTRADICT))["final_action"] == "AUSLASSEN / KEIN BET"
assert resolve_action("SPIELEN", "under_2_5", signals("under_2_5", SUPPORT))["final_action"] == "SPIELEN"

print("FootyStats unified qualitative match logic tests passed")
