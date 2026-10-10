"""FootyStats-only read-only MCP bridge for ChatGPT."""
from __future__ import annotations

import json
import os
import re
from datetime import date as date_type
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from contextlib import asynccontextmanager
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

API_BASE = "https://api.football-data-api.com/"
HOSTNAME = "footystats-prognose-engine.onrender.com"
ROUTE_TOKEN = os.environ.get("MCP_ROUTE_TOKEN", "").strip()
API_KEY = os.environ.get("FOOTYSTATS_KEY", "").strip()

mcp = FastMCP(
    "FootyStats Live",
    instructions=(
        "Read-only FootyStats API connection. First use todays_matches to identify "
        "the exact fixture by both team names and date. Then use analyze_match_data "
        "for that match. Never estimate missing fields. The returned verification "
        "must be all_identical=true before any bet can be considered. Shared pre-match "
        "fields are context only, never the basis for the bet."
    ),
)


def _api_get(endpoint: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    if not API_KEY:
        return {"success": False, "error": "FOOTYSTATS_KEY is not configured on Render."}
    query = dict(params or {})
    query["key"] = API_KEY
    url = API_BASE + endpoint + "?" + urlencode(query)
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "FootyStats-ChatGPT-Bridge/1.0",
        },
    )
    try:
        with urlopen(request, timeout=25) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        return {"success": False, "error": "FootyStats HTTP error.", "http_status": exc.code}
    except (URLError, TimeoutError, ValueError, OSError) as exc:
        return {"success": False, "error": "FootyStats request failed.", "error_type": type(exc).__name__}
    if not isinstance(payload, dict):
        return {"success": False, "error": "Unexpected response format from FootyStats."}
    return payload


def _records(payload: dict[str, Any]) -> list[dict[str, Any]]:
    data = payload.get("data")
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        return [data]
    if any(k in payload for k in ("id", "homeID", "awayID", "name")):
        return [payload]
    return []


def _first_record(payload: dict[str, Any]) -> dict[str, Any]:
    rows = _records(payload)
    return rows[0] if rows else {}


def _id_value(record: dict[str, Any], *names: str) -> int | None:
    for name in names:
        value = record.get(name)
        if value not in (None, "", -1, "-1"):
            try:
                return int(value)
            except (TypeError, ValueError):
                continue
    return None


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def _match_summary(record: dict[str, Any]) -> dict[str, Any]:
    important = {
        "id", "homeID", "awayID", "home_name", "away_name", "homeName", "awayName",
        "home_team_name", "away_team_name", "homeTeam", "awayTeam", "home_team", "away_team",
        "team_a", "team_b", "status", "date", "date_unix", "competition_id", "season_id",
        "league_id", "league_name", "competition_name", "country_name", "season", "game_week",
        "homeGoalCount", "awayGoalCount", "totalGoalCount", "team_a_shotsOnTarget",
        "team_b_shotsOnTarget", "team_a_shots", "team_b_shots", "team_a_possession",
        "team_b_possession", "minute", "elapsed", "match_status",
    }
    result = {k: v for k, v in record.items() if k in important}
    for k, v in record.items():
        low = k.lower()
        if k not in result and any(part in low for part in ("home_name", "away_name", "team_a_name", "team_b_name")):
            result[k] = v
    return result


def _team_record(payload: dict[str, Any], team_id: int | None) -> dict[str, Any]:
    if team_id is None:
        return {}
    for row in _records(payload):
        row_id = _id_value(row, "id", "team_id", "teamID")
        if row_id == team_id:
            return row
    return {}


@mcp.tool()
def todays_matches(
    date: str = "",
    timezone: str = "Europe/Vienna",
    page: int = 1,
) -> dict[str, Any]:
    """List FootyStats matches for a date, with IDs needed to select the exact fixture."""
    params: dict[str, Any] = {"timezone": timezone, "page": max(1, min(int(page), 10))}
    if date.strip():
        try:
            date_type.fromisoformat(date.strip())
        except ValueError:
            return {"success": False, "error": "date must use YYYY-MM-DD."}
        params["date"] = date.strip()
    payload = _api_get("todays-matches", params)
    if payload.get("success") is False:
        return payload
    rows = _records(payload)
    pager = payload.get("pager") if isinstance(payload.get("pager"), dict) else {}
    return {
        "success": payload.get("success", True),
        "requested_date": date.strip() or "FootyStats default date",
        "timezone": timezone,
        "page": params["page"],
        "total_results": pager.get("total_results", len(rows)),
        "matches": [_match_summary(row) for row in rows],
        "note": "Use exact home and away names plus match ID; similar names are not interchangeable.",
    }


@mcp.tool()
def analyze_match_data(
    match_id: int,
    season_id: int | None = None,
    home_team_id: int | None = None,
    away_team_id: int | None = None,
) -> dict[str, Any]:
    """Fetch match, both teams' Overall/Home/Away stats, and last-X stats; re-read all inputs and verify stability."""
    # First pass: match, home team, away team, then last-X home and away.
    match_first_payload = _api_get("match", {"match_id": int(match_id)})
    if match_first_payload.get("success") is False:
        return {"success": False, "phase": "MATCH_LOOKUP", "error": match_first_payload.get("error", "Match lookup failed.")}
    match_first = _first_record(match_first_payload)
    if not match_first:
        return {"success": False, "phase": "MATCH_LOOKUP", "error": "No match record returned."}

    home_id = _id_value(match_first, "homeID", "home_id") or home_team_id
    away_id = _id_value(match_first, "awayID", "away_id") or away_team_id
    league_season_id = (
        _id_value(match_first, "competition_id", "season_id", "league_id", "leagueID")
        or season_id
    )
    if home_id is None or away_id is None:
        return {
            "success": False,
            "phase": "TEAM_IDENTIFICATION",
            "error": "Home/away team IDs are missing; provide the IDs from the exact todays_matches result.",
            "match": _match_summary(match_first),
        }
    if league_season_id is None:
        return {
            "success": False,
            "phase": "SEASON_IDENTIFICATION",
            "error": "Season ID is missing; provide the season/competition ID from todays_matches.",
            "match": _match_summary(match_first),
            "home_team_id": home_id,
            "away_team_id": away_id,
        }

    league_first_payload = _api_get("league-teams", {"season_id": league_season_id, "include": "stats"})
    if league_first_payload.get("success") is False:
        return {"success": False, "phase": "LEAGUE_TEAMS", "error": league_first_payload.get("error", "League team lookup failed.")}
    home_first = _team_record(league_first_payload, home_id)
    away_first = _team_record(league_first_payload, away_id)

    last_home_first_payload = _api_get("lastx", {"team_id": home_id})
    last_away_first_payload = _api_get("lastx", {"team_id": away_id})
    last_home_first = _team_record(last_home_first_payload, home_id)
    last_away_first = _team_record(last_away_first_payload, away_id)

    # Second pass: same endpoints and IDs, in the same order, for exact comparison.
    match_second_payload = _api_get("match", {"match_id": int(match_id)})
    league_second_payload = _api_get("league-teams", {"season_id": league_season_id, "include": "stats"})
    last_home_second_payload = _api_get("lastx", {"team_id": home_id})
    last_away_second_payload = _api_get("lastx", {"team_id": away_id})

    match_second = _first_record(match_second_payload)
    home_second = _team_record(league_second_payload, home_id)
    away_second = _team_record(league_second_payload, away_id)
    last_home_second = _team_record(last_home_second_payload, home_id)
    last_away_second = _team_record(last_away_second_payload, away_id)

    checks = {
        "match_identical": bool(match_first) and _canonical(match_first) == _canonical(match_second),
        "home_team_identical": bool(home_first) and _canonical(home_first) == _canonical(home_second),
        "away_team_identical": bool(away_first) and _canonical(away_first) == _canonical(away_second),
        "home_lastx_identical": bool(last_home_first) and _canonical(last_home_first) == _canonical(last_home_second),
        "away_lastx_identical": bool(last_away_first) and _canonical(last_away_first) == _canonical(last_away_second),
    }
    all_identical = all(checks.values())
    context_keys = (
        "pre_match_home_xg", "pre_match_away_xg", "btts_potential",
        "o25_potential", "u25_potential", "over25", "under25", "btts",
        "homeGoalCount", "awayGoalCount", "totalGoalCount", "status",
        "team_a_shotsOnTarget", "team_b_shotsOnTarget", "team_a_shots",
        "team_b_shots", "team_a_possession", "team_b_possession",
    )
    context = {k: match_first[k] for k in context_keys if k in match_first}

    result: dict[str, Any] = {
        "success": True,
        "match_id": int(match_id),
        "match": _match_summary(match_first),
        "home_team": {
            "team_id": home_id,
            "full_stats_overall_home_away": home_first or None,
            "lastx": last_home_first or None,
        },
        "away_team": {
            "team_id": away_id,
            "full_stats_overall_home_away": away_first or None,
            "lastx": last_away_first or None,
        },
        "shared_fields_context_only": context,
        "verification": {
            "checks": checks,
            "all_identical": all_identical,
            "wager_allowed_by_stability_check": all_identical,
            "rule": "If any check is false, no bet. Missing fields remain missing and must not be estimated.",
        },
    }
    if not all_identical:
        result["verification"]["note"] = "At least one second read differs or required team data is missing; do not place a bet."
        result["changed_second_read"] = {
            "match": _match_summary(match_second),
            "home_team": home_second or None,
            "away_team": away_second or None,
            "home_lastx": last_home_second or None,
            "away_lastx": last_away_second or None,
        }
    return result


@mcp.tool()
def footystats_connection_status() -> dict[str, Any]:
    """Check whether the server has a FootyStats key and can reach the API without revealing the key."""
    if not API_KEY:
        return {"connected": False, "error": "FOOTYSTATS_KEY is missing in Render environment."}
    payload = _api_get("todays-matches", {"timezone": "Europe/Vienna", "page": 1})
    if payload.get("success") is False:
        return {
            "connected": False,
            "api_key_configured": True,
            "error": payload.get("error", "FootyStats API returned an error."),
            "http_status": payload.get("http_status"),
        }
    return {
        "connected": True,
        "api_key_configured": True,
        "endpoint": "todays-matches",
        "matches_returned": len(_records(payload)),
        "message": "FootyStats API responded successfully. Key value is not returned.",
    }


async def health(request):
    return JSONResponse({
        "ok": True,
        "service": "FootyStats Live MCP",
        "api_key_configured": bool(API_KEY),
        "mcp_route_configured": bool(ROUTE_TOKEN),
    })


@asynccontextmanager
async def lifespan(app):
    async with mcp.session_manager.run():
        yield


if not ROUTE_TOKEN:
    raise RuntimeError("MCP_ROUTE_TOKEN must be configured in Render.")

security = TransportSecuritySettings(
    allowed_hosts=[HOSTNAME, HOSTNAME + ":*"],
    allowed_origins=["https://chatgpt.com", "https://chat.openai.com"],
)
mcp_app = mcp.streamable_http_app(
    json_response=True,
    stateless_http=True,
    transport_security=security,
)
app = Starlette(
    routes=[
        Route("/health", health, methods=["GET"]),
        Mount("/" + ROUTE_TOKEN, app=mcp_app),
    ],
    lifespan=lifespan,
)
