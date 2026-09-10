"""Regression tests for SPEC v1.1 / Engine v1.1.5 draw-parity semantics."""
import app  # applies production patch stack
import spec11_strongest_market_engine as engine
from spec11_draw_parity_patch import _neutralize_generic_draw_parity
from spec11_native_engine import SUPPORT, CONTRADICT, NEUTRAL


def by_market(rows, domain):
    return {s["market"]: s["status"] for s in rows if s.get("domain") == domain}


# Venezia/Fiorentina LOW SAMPLE pattern: PPG equal, xG clearly home-side.
match = {
    "pre_match_home_ppg": 0,
    "pre_match_away_ppg": 0,
    "team_a_xg_prematch": 2.14,
    "team_b_xg_prematch": 1.12,
}
rows = engine._match_signals(match, 3, 3, {}, [])
st = by_market(rows, "PREMATCH_STRENGTH")
assert st["home_win"] == SUPPORT, st
assert st["draw"] == NEUTRAL, st
assert st["away_win"] == CONTRADICT, st

# Equal overall PPG is parity, not draw evidence.
rows = engine.extended_match(
    {"pre_match_teamA_overall_ppg": 0, "pre_match_teamB_overall_ppg": 0},
    3, 3, {}, []
)
st = by_market(rows, "OVERALL_PREMATCH_PPG")
assert st["home_win"] == NEUTRAL, st
assert st["draw"] == NEUTRAL, st
assert st["away_win"] == NEUTRAL, st

# Opposing generic strength indicators are conflicting/neutral, not a draw vote.
match_conflict = {
    "pre_match_home_ppg": 1.5,
    "pre_match_away_ppg": 1.0,
    "team_a_xg_prematch": 1.1,
    "team_b_xg_prematch": 1.6,
}
rows = engine._match_signals(match_conflict, 3, 3, {}, [])
st = by_market(rows, "PREMATCH_STRENGTH")
assert st == {"home_win": NEUTRAL, "away_win": NEUTRAL, "draw": NEUTRAL} or st == {"home_win": NEUTRAL, "draw": NEUTRAL, "away_win": NEUTRAL}, st

# Generic parity gets neutralized, but explicit draw/WDL evidence is preserved.
sample = [
    {"market": "draw", "domain": "VENUE_PPG", "status": SUPPORT, "reason": "x"},
    {"market": "draw", "domain": "VENUE_WDL_PROFILE", "status": SUPPORT, "reason": "draw-specific"},
    {"market": "draw", "domain": "TARGET_PLAYER_DEPTH", "status": SUPPORT, "reason": "x"},
]
_neutralize_generic_draw_parity(sample)
assert sample[0]["status"] == NEUTRAL
assert sample[1]["status"] == SUPPORT
assert sample[2]["status"] == NEUTRAL

health = next(r.endpoint for r in app.app.router.routes if getattr(r, "path", None) == "/api/health")()
assert app.app.version == "1.1.5-draw-parity"
assert engine.ENGINE_VERSION == "1.1.5-draw-parity"
assert health["draw_parity_guard"] is True
assert health["generic_strength_parity_is_draw_evidence"] is False

print("SPEC v1.1 / Engine v1.1.5 draw-parity regression OK")
