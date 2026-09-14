"""Read the observed five-file Shortcut envelope, without approving training inputs.

Raw bytes stay with the caller. The returned views are references to decoded data,
not a model feature matrix. Use classify_fields for an exclusion audit.
"""
from __future__ import annotations
import re
from .audit import DataError, SOURCES, decode, leaves

ENDPOINT = {"MATCH": "/match", "LEAGUE": "/league-season", "FORM": "/lastx",
            "TABLE": "/league-tables", "PLAYER": "/league-players"}
TABLES = ("all_matches_table_overall", "all_matches_table_home", "all_matches_table_away")
MATCH_CANDIDATES = frozenset({
    "team_a_xg_prematch", "team_b_xg_prematch", "total_xg_prematch",
    "pre_match_home_ppg", "pre_match_away_ppg", "btts_potential",
    "o25_potential", "u25_potential", "matches_completed_minimum",
})
MATCH_CONTEXT = frozenset({
    "id", "homeID", "awayID", "competition_id", "date_unix", "status",
    "home_name", "away_name", "season", "no_home_away", "roundID", "game_week",
})


def integer(value, code, *, positive=True):
    if type(value) is int:
        number = value
    elif isinstance(value, str) and re.fullmatch(r"[0-9]+", value):
        number = int(value)
    else:
        raise DataError(code)
    if positive and number <= 0:
        raise DataError(code)
    return number


def require(condition, code):
    if not condition:
        raise DataError(code)


def obj(value):
    require(isinstance(value, dict), "EXPECTED_OBJECT")
    return value


def response(value):
    value = obj(value)
    require(value.get("success") is True and "data" in value, "PROVIDER_RESPONSE_INVALID")
    return value["data"]


def paged(value):
    """Check observed response object OR response list against every pager."""
    pages = value if isinstance(value, list) else [value]
    require(bool(pages), "EMPTY_PAGES")
    rows, seen_pages, totals, maxima = [], set(), set(), set()
    for page in pages:
        data = response(page)
        require(isinstance(data, list), "EXPECTED_ROW_LIST")
        pager = obj(page.get("pager"))
        current = integer(pager.get("current_page"), "INVALID_PAGE")
        maximum = integer(pager.get("max_page"), "INVALID_PAGE")
        total = integer(pager.get("total_results"), "INVALID_TOTAL", positive=False)
        require(total >= 0, "INVALID_TOTAL")
        require(current not in seen_pages, "DUPLICATE_PAGE")
        seen_pages.add(current)
        totals.add(total)
        maxima.add(maximum)
        rows.extend(data)
    require(len(maxima) == len(totals) == 1, "CONFLICTING_PAGINATION")
    maximum = next(iter(maxima))
    require(maximum == len(pages) and seen_pages == set(range(1, maximum + 1)),
            "INCOMPLETE_PAGINATION")
    require(len(rows) == next(iter(totals)), "ROW_COUNT_MISMATCH")
    ids = [integer(obj(row).get("id"), "INVALID_ROW_ID") for row in rows]
    require(len(set(ids)) == len(ids), "DUPLICATE_ROW_ID")
    return rows


def classify_fields(source, document):
    """Every leaf retained in audit; statuses are not learned feature weights."""
    require(source in SOURCES, "UNKNOWN_SOURCE")
    rows = []
    for path, value in leaves(document):
        parts = path.split("/")[1:]
        status = "PENDING_SCHEMA_REVIEW"
        if any(part.lower().startswith("odds") for part in parts):
            status = "ODDS_BLOCKED"
        elif any(part.lower().startswith("gpt") or part == "trends" for part in parts):
            status = "PROVIDER_TEXT_BLOCKED"
        elif parts and parts[0] == "_footystats_meta":
            status = "PROVENANCE_METADATA"
        elif any(part in {"metadata", "pager", "message", "success"} for part in parts):
            status = "TRANSPORT_METADATA"
        elif source == "MATCH" and len(parts) >= 3 and parts[:2] == ["payload", "data"]:
            field = parts[2]
            if field in MATCH_CANDIDATES and len(parts) == 3:
                status = "CANDIDATE_REQUIRES_VALIDATION"
            elif field in MATCH_CONTEXT:
                status = "MATCH_CONTEXT"
            elif field == "h2h":
                status = "H2H_REQUIRES_TEMPORAL_REVIEW"
            else:
                # Includes current-match xG, goals and events, even zero placeholders.
                status = "MATCH_FIELD_NOT_APPROVED"
        rows.append({"pointer": path, "status": status, "is_null": value is None})
    return rows


def adapt(files: dict[str, bytes], *, now_unix: int) -> dict:
    require(set(files) == SOURCES, "EXACTLY_FIVE_SOURCES_REQUIRED")
    now_unix = integer(now_unix, "INVALID_NOW")
    docs = {source: decode(raw) for source, raw in files.items()}
    metas, payloads = {}, {}
    for source, doc in docs.items():
        obj(doc)
        meta = obj(doc.get("_footystats_meta"))
        require(meta.get("endpoint") == ENDPOINT[source], "SOURCE_ENDPOINT_MISMATCH")
        metas[source], payloads[source] = meta, obj(doc.get("payload"))
    match = obj(response(payloads["MATCH"]))
    match_id = integer(match.get("id"), "INVALID_MATCH_ID")
    home = integer(match.get("homeID"), "INVALID_TEAM_ID")
    away = integer(match.get("awayID"), "INVALID_TEAM_ID")
    season = integer(match.get("competition_id"), "INVALID_SEASON_ID")
    kickoff = integer(match.get("date_unix"), "INVALID_KICKOFF")
    require(home != away, "IDENTICAL_TEAMS")
    require(match.get("status") == "incomplete", "MATCH_NOT_PREMATCH")
    captures = {}
    for source, meta in metas.items():
        require(integer(meta.get("kickoff_unix"), "INVALID_KICKOFF") == kickoff,
                "CONFLICTING_KICKOFF")
        captured = integer(meta.get("captured_at_unix"), "INVALID_CAPTURE")
        require(captured <= now_unix, "FUTURE_CAPTURE")
        require(captured < kickoff, "CAPTURE_NOT_PREMATCH")
        captures[source] = captured
        if "match_id" in meta:
            require(integer(meta["match_id"], "INVALID_MATCH_ID") == match_id,
                    "CONFLICTING_MATCH_ID")
        if source in {"LEAGUE", "TABLE", "PLAYER"}:
            require(integer(meta.get("season_id"), "INVALID_SEASON_ID") == season,
                    "CONFLICTING_SEASON_ID")
            cutoff = integer(meta.get("max_time"), "INVALID_CUTOFF")
            require(cutoff < kickoff, "CUTOFF_NOT_PREMATCH")
        if source == "FORM":
            require("max_time" not in meta, "LASTX_CUTOFF_UNSUPPORTED")
    league_payload = payloads["LEAGUE"]
    league = obj(response(league_payload.get("league")))
    require(integer(league.get("id"), "INVALID_SEASON_ID") == season, "LEAGUE_ID_MISMATCH")
    teams = paged(league_payload.get("team_pages"))
    selected_teams = {}
    for side, team_id in (("home", home), ("away", away)):
        selected = [row for row in teams if integer(row["id"], "INVALID_TEAM_ID") == team_id]
        require(len(selected) == 1, "TARGET_TEAM_MISSING")
        obj(selected[0].get("stats"))
        selected_teams[side] = selected[0]
    form = {}
    for side, team_id in (("home", home), ("away", away)):
        rows = response(payloads["FORM"].get(side))
        require(isinstance(rows, list) and bool(rows), "EMPTY_FORM")
        windows = set()
        for row in rows:
            obj(row)
            require(integer(row.get("id"), "INVALID_TEAM_ID") == team_id, "FORM_TEAM_MISMATCH")
            key = (integer(row.get("last_x_match_num"), "INVALID_FORM_WINDOW"),
                   integer(row.get("last_x_home_away_or_overall"), "INVALID_FORM_SPLIT", positive=False))
            require(key not in windows, "DUPLICATE_FORM_WINDOW")
            windows.add(key)
            updated = integer(row.get("last_updated_match_timestamp"), "INVALID_FORM_TIME", positive=False)
            require(updated >= 0 and updated <= captures["FORM"] and updated < kickoff,
                    "FORM_CONTAINS_FUTURE_MATCH")
            obj(row.get("stats"))
        form[side] = rows
    tables = obj(response(payloads["TABLE"]))
    for table in TABLES:
        rows = tables.get(table)
        require(isinstance(rows, list), "MISSING_TABLE")
        ids = [integer(obj(row).get("id"), "INVALID_TEAM_ID") for row in rows]
        require(len(ids) == len(set(ids)), "DUPLICATE_TABLE_TEAM")
        require(home in ids and away in ids, "TARGET_TEAM_MISSING")
    players = paged(payloads["PLAYER"].get("pages"))
    for player in players:
        require(integer(player.get("competition_id"), "INVALID_SEASON_ID") == season,
                "PLAYER_SEASON_MISMATCH")
        last = integer(player.get("last_match_timestamp"), "INVALID_PLAYER_TIME", positive=False)
        require(last >= 0 and last <= captures["PLAYER"] and last < kickoff,
                "PLAYER_CONTAINS_FUTURE_MATCH")
    selected_players = {side: [p for p in players if
                               integer(p.get("club_team_id"), "INVALID_CLUB_ID", positive=False) == team_id]
                        for side, team_id in (("home", home), ("away", away))}
    return {
        "match_id": match_id, "season_id": season, "home_id": home, "away_id": away,
        "kickoff_unix": kickoff, "capture_times": captures,
        "source_views": {"match": match, "league": league, "teams": selected_teams,
                         "form": form, "tables": tables, "players": selected_players},
        "counts": {"league_teams": len(teams), "league_players": len(players),
                   "home_players": len(selected_players["home"]),
                   "away_players": len(selected_players["away"])},
        "field_audit": {s: classify_fields(s, doc) for s, doc in docs.items()},
        "training_ready": False, "strict_prematch_certified": False,
        "decision": "AUSLASSEN", "reason": "PROVENANCE_AND_FEATURE_VALIDATION_PENDING",
    }
