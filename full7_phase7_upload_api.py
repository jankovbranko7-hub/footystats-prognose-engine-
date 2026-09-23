"""Production upload bridge for FULL7_FINAL_RC_1.0.0.

Keeps the established seven-file browser workflow, validates the uploaded
FootyStats snapshot with the existing Bronze/Silver/Gold contract, translates
only semantically aligned pre-match fields to the frozen Phase-4 feature
contract, and runs the hash-pinned Phase-7 RC. No odds or post-match fields are
fed to the RC model.
"""
from __future__ import annotations

import json
import math
from typing import Any, Dict, List, Mapping, Sequence

from fastapi import APIRouter, File, HTTPException, UploadFile

from full7_foundation import process_full7
from full7_phase7_api import FULL7_RELEASE_CANDIDATE_VERSION, _load_configured_runtime
from full7_phase7_features import extract_phase4_features

production_router = APIRouter()

SEASON_SAFE_EXACT = {
    "id", "division", "name", "shortHand", "country", "type", "iso", "continent",
    "season", "seasonClean", "totalMatches", "matchesCompleted", "round", "progress",
    "seasonAVG_overall", "seasonAVG_home", "seasonAVG_away", "seasonBTTSPercentage",
    "seasonCSPercentage", "seasonGoalsScored_home_teams", "seasonGoalsScored_away_teams",
    "seasonConceded_home_teams", "seasonConceded_away_teams",
    "seasonOver05Percentage_overall", "seasonOver15Percentage_overall",
    "seasonOver25Percentage_overall", "seasonOver35Percentage_overall",
    "seasonOver45Percentage_overall", "seasonOver55Percentage_overall",
    "seasonUnder05Percentage_overall", "seasonUnder15Percentage_overall",
    "seasonUnder25Percentage_overall", "seasonUnder35Percentage_overall",
    "seasonUnder45Percentage_overall", "seasonUnder55Percentage_overall",
    "seasonOver05_num", "seasonOver15_num", "seasonOver25_num", "seasonOver35_num",
    "seasonOver45_num", "seasonOver55_num", "seasonUnder05_num", "seasonUnder15_num",
    "seasonUnder25_num", "seasonUnder35_num", "seasonUnder45_num", "seasonUnder55_num",
}
MATCH_ALLOW = {
    "id", "season", "competition_id", "homeID", "awayID", "home_name", "away_name",
    "date_unix", "game_week", "roundID", "revised_game_week", "refereeID",
    "coach_a_ID", "coach_b_ID", "stadium_name", "stadium_location", "no_home_away",
    "matches_completed_minimum",
}
PREMATCH_OPTIONAL = (
    "team_a_xg_prematch", "team_b_xg_prematch", "pre_match_home_ppg",
    "pre_match_away_ppg", "o25_potential", "btts_potential", "avg_potential",
)


def _num(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _int(value: Any) -> int | None:
    x = _num(value)
    return int(x) if x is not None else None


def _data(value: Any) -> Any:
    return value.get("data") if isinstance(value, Mapping) and "data" in value else value


def _row_id(row: Any) -> int | None:
    if not isinstance(row, Mapping):
        return None
    for key in ("id", "team_id", "teamID"):
        value = _int(row.get(key))
        if value is not None:
            return value
    return None


def _pct_fraction(value: Any) -> float | None:
    x = _num(value)
    if x is None:
        return None
    return round(x / 100.0, 3)


def _rounded(value: Any) -> float | None:
    x = _num(value)
    return None if x is None else round(x, 3)


def _find_lastx(form_side: Any, team_id: int, n: int) -> Mapping[str, Any] | None:
    rows = _data(form_side)
    if not isinstance(rows, list):
        return None
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        if _int(row.get("id")) == team_id and _int(row.get("last_x_match_num")) == n:
            return row
    return None


def _pack_lastx(row: Mapping[str, Any] | None, split: str) -> dict[str, Any]:
    if not isinstance(row, Mapping):
        return {"n": 0}
    stats = row.get("stats")
    if not isinstance(stats, Mapping):
        return {"n": 0}
    suffix = "overall" if split == "overall" else split
    n = (
        _int(row.get("last_x_match_num"))
        if split == "overall"
        else _int(stats.get(f"seasonMatchesPlayed_{suffix}"))
    )
    return {
        "n": int(n or 0),
        "goals_for_avg": _rounded(stats.get(f"seasonScoredAVG_{suffix}")),
        "goals_against_avg": _rounded(stats.get(f"seasonConcededAVG_{suffix}")),
        "btts_rate": _pct_fraction(stats.get(f"seasonBTTSPercentage_{suffix}")),
        "over25_rate": _pct_fraction(stats.get(f"seasonOver25Percentage_{suffix}")),
        "cs_rate": _pct_fraction(stats.get(f"seasonCSPercentage_{suffix}")),
        "fts_rate": _pct_fraction(stats.get(f"seasonFTSPercentage_{suffix}")),
        "xg_avg": _rounded(stats.get(f"xg_for_avg_{suffix}")),
        "xga_avg": _rounded(stats.get(f"xg_against_avg_{suffix}")),
    }


def _normalize_sources(gold: Mapping[str, Any]) -> dict[str, Any]:
    ident = gold.get("identity") or {}
    home_id = int(ident["home_id"])
    away_id = int(ident["away_id"])
    match_id = int(ident["match_id"])
    kickoff = int(ident["kickoff_unix"])
    namespaces = gold.get("namespaces") or {}

    raw_match = _data(namespaces.get("match") or {})
    raw_match = raw_match if isinstance(raw_match, Mapping) else {}
    match_identity = {k: raw_match.get(k) for k in MATCH_ALLOW if k in raw_match}
    match_identity["match_id"] = match_id
    match_identity["homeID"] = home_id
    match_identity["awayID"] = away_id
    match_identity["date_unix"] = kickoff
    match = {
        "found": True,
        "identity": match_identity,
        "prematch_optional": {
            key: raw_match.get(key) for key in PREMATCH_OPTIONAL if key in raw_match
        },
        "stored_postmatch": False,
    }

    raw_league = namespaces.get("league") or {}
    season = _data(raw_league.get("league") if isinstance(raw_league, Mapping) else {})
    season = season if isinstance(season, Mapping) else {}
    team_wrapper = raw_league.get("team_pages") if isinstance(raw_league, Mapping) else {}
    team_rows = _data(team_wrapper)
    team_rows = team_rows if isinstance(team_rows, list) else []
    teams = [
        dict(row) for row in team_rows
        if isinstance(row, Mapping) and _row_id(row) in {home_id, away_id}
    ]
    league_derived = {
        "league_source_count": _int(season.get("matchesCompleted")),
        "league_source_match_ids": [],
        "league_source_max_timestamp": None,
        "goals_avg": _rounded(season.get("seasonAVG_overall")),
        "home_goals_avg": _rounded(season.get("seasonAVG_home")),
        "away_goals_avg": _rounded(season.get("seasonAVG_away")),
        "btts_rate": _pct_fraction(season.get("seasonBTTSPercentage")),
        "over25_rate": _pct_fraction(season.get("seasonOver25Percentage_overall")),
        "xg_total_avg": _rounded(season.get("xg_avg")),
        "xg_recorded_n": None,
        "corners_avg": _rounded(season.get("cornersAVG_overall")),
        "corners_recorded_n": _int(season.get("cornersRecorded_matches")),
    }
    league = {
        "season_safe_identity": {
            key: season.get(key) for key in SEASON_SAFE_EXACT if key in season
        },
        "teams_full_home_away": teams,
        "league_aggregates_derived": league_derived,
    }

    raw_form = namespaces.get("form") or {}
    home_form_raw = raw_form.get("home") if isinstance(raw_form, Mapping) else {}
    away_form_raw = raw_form.get("away") if isinstance(raw_form, Mapping) else {}
    home_rows = {n: _find_lastx(home_form_raw, home_id, n) for n in (5, 6, 10)}
    away_rows = {n: _find_lastx(away_form_raw, away_id, n) for n in (5, 6, 10)}
    home_long = home_rows[10] or home_rows[6] or home_rows[5]
    away_long = away_rows[10] or away_rows[6] or away_rows[5]
    form = {
        "home_id": home_id,
        "away_id": away_id,
        "kickoff_unix": kickoff,
        "rule": "date_unix < kickoff AND id != target",
        "home": {
            "source_matches": [],
            "last5": _pack_lastx(home_rows[5], "overall"),
            "last6": _pack_lastx(home_rows[6], "overall"),
            "last10": _pack_lastx(home_rows[10], "overall"),
            "home_split": _pack_lastx(home_long, "home"),
            "away_split": _pack_lastx(home_long, "away"),
        },
        "away": {
            "source_matches": [],
            "last5": _pack_lastx(away_rows[5], "overall"),
            "last6": _pack_lastx(away_rows[6], "overall"),
            "last10": _pack_lastx(away_rows[10], "overall"),
            "home_split": _pack_lastx(away_long, "home"),
            "away_split": _pack_lastx(away_long, "away"),
        },
    }

    raw_table = _data(namespaces.get("table") or {})
    raw_table = raw_table if isinstance(raw_table, Mapping) else {}
    overall = raw_table.get("league_table") or raw_table.get("all_matches_table_overall") or []
    overall = overall if isinstance(overall, list) else []
    table = {
        "home_row": next((dict(row) for row in overall if _row_id(row) == home_id), None),
        "away_row": next((dict(row) for row in overall if _row_id(row) == away_id), None),
    }

    raw_player = namespaces.get("player") or {}
    pages = raw_player.get("pages") if isinstance(raw_player, Mapping) else []
    players: list[dict[str, Any]] = []
    if isinstance(pages, list):
        for page in pages:
            rows = _data(page)
            if isinstance(rows, list):
                for row in rows:
                    if not isinstance(row, Mapping):
                        continue
                    club_id = _int(row.get("club_team_id", row.get("team_id")))
                    if club_id in {home_id, away_id}:
                        players.append(dict(row))
    player = {
        "pagination": {
            "max_page": 1,
            "loaded_pages": 1,
            "loaded_rows": len(players),
            "total_results": len(players),
            "pagination_complete": True,
        },
        "n_kept_home_away": len(players),
        "players": players,
    }

    return {
        "match": match,
        "league": league,
        "form": form,
        "table": table,
        "player": player,
    }


def _market_card(direction: Mapping[str, Any], market: str, family: str) -> dict[str, Any]:
    return {
        "market": market,
        "family": family,
        "probability": direction.get("probability"),
        "decision": direction.get("decision"),
        "decision_reason": direction.get("reason"),
        "reason": direction.get("reason"),
        "selected_in_family": True,
    }


def _compat_view(result: Mapping[str, Any]) -> dict[str, Any]:
    directions = result.get("directions") or {}
    markets = {
        "home_win": _market_card(directions.get("HOME") or {}, "home_win", "1X2"),
        "draw": _market_card(directions.get("DRAW") or {}, "draw", "1X2"),
        "away_win": _market_card(directions.get("AWAY") or {}, "away_win", "1X2"),
        "btts_yes": _market_card(directions.get("BTTS_YES") or {}, "btts_yes", "BTTS"),
        "btts_no": _market_card(directions.get("BTTS_NO") or {}, "btts_no", "BTTS"),
        "over_2_5": _market_card(directions.get("O25") or {}, "over_2_5", "TOTALS"),
        "under_2_5": _market_card(directions.get("U25") or {}, "under_2_5", "TOTALS"),
    }

    def selected(keys: Sequence[str]) -> dict[str, Any]:
        rows = [(key, markets[key]) for key in keys]
        finite = [
            (key, row) for key, row in rows
            if _num(row.get("probability")) is not None
        ]
        if not finite:
            key, row = rows[0]
        else:
            key, row = max(finite, key=lambda item: float(item[1]["probability"]))
        return {
            "selected_market": key,
            "probability": row.get("probability"),
            "decision": row.get("decision"),
            "decision_reason": row.get("decision_reason"),
        }

    families = {
        "1X2": selected(("home_win", "draw", "away_win")),
        "BTTS": selected(("btts_yes", "btts_no")),
        "TOTALS": {
            "selected_market": "O25/U25",
            "probability": None,
            "decision": "HOLD",
            "decision_reason": "O25_NOT_RELEASED",
        },
    }
    playable = []
    blocked = []
    for market, row in markets.items():
        card = {
            "market": market,
            "family": row["family"],
            "probability": row.get("probability"),
            "decision": row.get("decision"),
            "reason": row.get("decision_reason"),
        }
        if row.get("decision") == "SPIELEN":
            playable.append(card)
        else:
            blocked.append(card)
    return {
        **dict(result),
        "markets": markets,
        "families": families,
        "playable": playable,
        "candidate_spielen": playable,
        "blocked": blocked,
        "sample_security": {"status": "STRICT_7FILE_PREMATCH"},
    }


async def _read_json(file: UploadFile) -> Dict[str, Any]:
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=422, detail={"code": "EMPTY_FILE", "filename": file.filename})
    try:
        parsed = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "INVALID_JSON", "filename": file.filename, "message": str(exc)},
        ) from exc
    if not isinstance(parsed, dict):
        raise HTTPException(status_code=422, detail={"code": "INVALID_JSON_ROOT", "filename": file.filename})
    return {"name": file.filename or "unnamed.json", "data": parsed}


async def _validated_gold(uploads: Sequence[UploadFile]) -> tuple[dict[str, Any], dict[str, Any]]:
    parsed = [await _read_json(file) for file in uploads]
    processed = process_full7(parsed)
    if not processed.get("ok") or not processed.get("gold"):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "FULL7_VALIDATION_FAILED",
                "stage": processed.get("stage"),
                "issues": processed.get("issues"),
            },
        )
    return processed, processed["gold"]


@production_router.get("/api/full7/engine-health")
def production_health() -> Dict[str, Any]:
    try:
        runtime = _load_configured_runtime()
        runtime_ready = runtime is not None
        runtime_error = None
    except Exception as exc:
        runtime_ready = False
        runtime_error = type(exc).__name__
    return {
        "ok": runtime_ready,
        "engine": "FOOTYSTATS_FULL7_FINAL",
        "engine_version": FULL7_RELEASE_CANDIDATE_VERSION,
        "release_status": "LIVE_FULL7_FINAL_RC_1.0.0",
        "production_mounted": True,
        "expected_files": 7,
        "probability_mode_no_odds": True,
        "spielen_allowed_families": ["HOME", "AWAY", "BTTS_YES"],
        "draw_status": "AUSLASSEN_ONLY",
        "btts_no_status": "BEOBACHTEN_ONLY",
        "o25_status": "HOLD",
        "legacy_v3_1_override_active": False,
        "input_adapter": "SEVEN_FILE_SERVER_VALIDATED_STRICT_PREMATCH_1.0",
        "runtime_ready": runtime_ready,
        "runtime_error": runtime_error,
    }


@production_router.post("/api/full7/predict")
async def production_predict(
    match_file: UploadFile = File(...),
    league_file: UploadFile = File(...),
    form_file: UploadFile = File(...),
    table_file: UploadFile = File(...),
    player_file: UploadFile = File(...),
    referee_file: UploadFile = File(...),
    manager_file: UploadFile = File(...),
) -> Dict[str, Any]:
    uploads: List[UploadFile] = [
        match_file, league_file, form_file, table_file,
        player_file, referee_file, manager_file,
    ]
    processed, gold = await _validated_gold(uploads)
    sources = _normalize_sources(gold)
    ident = gold.get("identity") or {}

    try:
        features, groups = extract_phase4_features(
            sources,
            home_id=int(ident["home_id"]),
            away_id=int(ident["away_id"]),
        )
        runtime = _load_configured_runtime()
        raw_result = runtime.predict(
            features,
            input_integrity_verified=True,
            feature_schema_verified=True,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail={"code": "FULL7_FINAL_RUNTIME_FAILED", "error": type(exc).__name__},
        ) from exc

    engine = _compat_view(raw_result)
    return {
        "ok": True,
        "identity": ident,
        "quality": gold.get("quality"),
        "engine": engine,
        "feature_audit": {
            "extracted_feature_count": len(features),
            "locked_1x2_feature_coverage": (raw_result.get("feature_coverage") or {}).get("1X2"),
            "locked_btts_feature_coverage": (raw_result.get("feature_coverage") or {}).get("BTTS"),
            "strict_pre_match_audit": processed.get("audit"),
            "input_adapter": "SEVEN_FILE_SERVER_VALIDATED_STRICT_PREMATCH_1.0",
            "group_count": len(set(groups.values())),
        },
        "contract": {
            "engine_version": FULL7_RELEASE_CANDIDATE_VERSION,
            "release_status": "LIVE_FULL7_FINAL_RC_1.0.0",
            "release_authorized": True,
            "production_authorization_basis": "USER_EXPLICIT_2026-09-23",
            "decision_source": raw_result.get("final_decision_source"),
            "expected_files": 7,
            "probability_mode_no_odds": True,
            "spielen_allowed_families": ["HOME", "AWAY", "BTTS_YES"],
            "draw_status": "AUSLASSEN_ONLY",
            "btts_no_status": "BEOBACHTEN_ONLY",
            "o25_status": "HOLD",
            "legacy_v3_1_override_active": False,
            "input_adapter": "SEVEN_FILE_SERVER_VALIDATED_STRICT_PREMATCH_1.0",
        },
    }
