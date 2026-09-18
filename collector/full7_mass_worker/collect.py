#!/usr/bin/env python3
"""FULL-7 V3 Massensammler 1.2.

Input manifest contains only match_id + season_id.
A current/historical-complete league-matches fetch is used strictly for target
DISCOVERY (kickoff, team identities and final label). It is never used as a
pre-match feature source. Every feature snapshot is separately fetched with
max_time = kickoff - 1 and validated.
"""
from __future__ import annotations

import csv
import gc
import hashlib
import json
import os
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import requests

from config import (
    API_BASE, API_KEY_ENV, ROOT, CSV_PATH, RAW_DIR, MATCH_DIR, QUAR_DIR,
    STATE_PATH, DONE_PATH, PROGRESS_PATH, CACHE_INDEX, SLEEP_S,
    REQUEST_TIMEOUT, EXPECTED_TOTAL, MIN_FREE_GB, REQUIRED_CSV_COLUMNS,
)
from raw_cache import RawCache
from strict_validator import validate_match_bundle

MATCH_ALLOW = {
    "id", "season", "competition_id", "homeID", "awayID", "home_name", "away_name",
    "date_unix", "game_week", "roundID", "revised_game_week", "refereeID",
    "coach_a_ID", "coach_b_ID", "stadium_name", "stadium_location", "no_home_away",
    "matches_completed_minimum",
}
PRE_OPT = [
    "team_a_xg_prematch", "team_b_xg_prematch", "pre_match_home_ppg", "pre_match_away_ppg",
    "o25_potential", "btts_potential", "avg_potential",
]
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
CORE_TEAM = {
    "id", "name", "cleanName", "seasonMatchesPlayed_overall", "seasonMatchesPlayed_home",
    "seasonMatchesPlayed_away", "seasonPPG_overall", "seasonPPG_home", "seasonPPG_away",
    "seasonWins", "seasonDraws", "seasonLosses", "seasonGoalDifference", "seasonGoals",
    "seasonConceded", "table_position", "country",
}

SESSION = requests.Session()
CACHE: RawCache | None = None
KEY = os.environ.get(API_KEY_ENV, "")
DISCOVERY_MEMO = {"sid": None, "value": None}


def utc_iso(ts: int) -> str:
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat()


def _to_int(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def target_outcomes(target: dict) -> tuple[int, int, str, int, int]:
    hg = _to_int(target.get("homeGoalCount"))
    ag = _to_int(target.get("awayGoalCount"))
    if hg is None or ag is None:
        raise ValueError("discovery_target_has_no_final_score")
    x12 = "H" if hg > ag else ("A" if ag > hg else "D")
    return hg, ag, x12, int(hg >= 1 and ag >= 1), int(hg + ag >= 3)


def bundle_complete(mid: int) -> bool:
    d = MATCH_DIR / str(mid)
    if not d.is_dir():
        return False
    names = {p.name for p in d.glob("*.json")}
    need = {
        f"{mid}_MatchDaten.json", f"{mid}_FormDaten.json", f"{mid}_TableDaten.json",
        f"{mid}_PlayerDaten.json", f"{mid}_ResultTarget.json", f"{mid}_Metadata.json",
    }
    if not need.issubset(names):
        return False
    return any(n.endswith(f"_{mid}_LeagueDaten.json") for n in names)


def load_done_ids() -> set[int]:
    done: set[int] = set()
    if DONE_PATH.exists():
        for tok in DONE_PATH.read_text().split():
            if tok.isdigit():
                done.add(int(tok))
    if MATCH_DIR.exists():
        for p in MATCH_DIR.iterdir():
            if p.is_dir() and p.name.isdigit() and bundle_complete(int(p.name)):
                done.add(int(p.name))
    return done


def load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text())
    return {
        "processed": 0, "strict_pass": 0, "quarantined": 0,
        "api_requests": 0, "cache_hits": 0, "unique_raw_responses": 0,
        "failed_requests": 0, "retry_count": 0,
    }


def reconcile_state(st: dict, done: set[int]) -> dict:
    strict = 0
    for mid in done:
        mp = MATCH_DIR / str(mid) / f"{mid}_Metadata.json"
        try:
            meta = json.loads(mp.read_text()) if mp.exists() else {}
        except Exception:
            meta = {}
        if meta.get("strict_prematch") is True:
            strict += 1
    st["processed"] = len(done)
    st["strict_pass"] = strict
    st["quarantined"] = len(done) - strict
    return st


def save_state(st: dict, done: set[int]) -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, indent=2))
    tmp.replace(STATE_PATH)
    tmp_done = DONE_PATH.with_suffix(".tmp")
    tmp_done.write_text("\n".join(str(i) for i in sorted(done)))
    tmp_done.replace(DONE_PATH)


def fetch(endpoint: str, params: dict, state: dict) -> tuple[dict, dict]:
    rec, js = CACHE.lookup(endpoint, params)
    if rec is not None and isinstance(js, dict) and js.get("success"):
        state["cache_hits"] += 1
        return js, rec

    q = dict(params)
    q["key"] = KEY
    last = None
    for attempt in range(6):
        try:
            r = SESSION.get(f"{API_BASE}/{endpoint}", params=q, timeout=REQUEST_TIMEOUT)
            if r.status_code == 429:
                state["retry_count"] += 1
                time.sleep(2 + attempt * 3)
                continue
            r.raise_for_status()
            rec, js = CACHE.store(r.content, endpoint=endpoint, params=params)
            if rec.get("cache_created"):
                state["unique_raw_responses"] += 1
            state["api_requests"] += 1
            if not isinstance(js, dict) or not js.get("success"):
                raise RuntimeError(str((js or {}).get("message")))
            time.sleep(SLEEP_S)
            return js, rec
        except Exception as exc:
            last = exc
            state["retry_count"] += 1
            time.sleep(1 + attempt * 2)

    state["failed_requests"] += 1
    raise RuntimeError(f"{endpoint} failed: {last}")


def cached(key, endpoint, params, state):
    # Raw responses already have a persistent SHA cache on disk. Keeping every
    # historical snapshot in RAM caused unbounded growth on the 512 MB worker.
    # Repeated identical requests are served by RawCache.lookup() without a new API call.
    return fetch(endpoint, params, state)


def discover_season_matches(sid: int, state: dict) -> tuple[list[dict], list[dict]]:
    """Complete season list used ONLY to discover target identity/kickoff/final label.

    The input is sorted by season_id, so holding only the current season is enough.
    """
    if DISCOVERY_MEMO["sid"] == sid and DISCOVERY_MEMO["value"] is not None:
        state["cache_hits"] += 1
        return DISCOVERY_MEMO["value"]

    params = {"season_id": sid, "max_per_page": 1000, "page": 1}
    js, rec = fetch("league-matches", params, state)
    rows = list(js.get("data") or [])
    recs = [rec]
    pager = js.get("pager") or {}
    max_page = int(pager.get("max_page") or 1)
    for page in range(2, max_page + 1):
        js2, rec2 = fetch(
            "league-matches",
            {"season_id": sid, "max_per_page": 1000, "page": page},
            state,
        )
        rows.extend(js2.get("data") or [])
        recs.append(rec2)

    DISCOVERY_MEMO["sid"] = sid
    DISCOVERY_MEMO["value"] = (rows, recs)
    return rows, recs


def prior_matches(matches, kick: int, target_id: int) -> list[dict]:
    out = []
    for m in matches:
        ts = _to_int(m.get("date_unix")) or 0
        if ts <= 0 or ts >= kick:
            continue
        if _to_int(m.get("id")) == target_id:
            continue
        if m.get("homeGoalCount") is None or m.get("awayGoalCount") is None:
            continue
        out.append(m)
    out.sort(key=lambda x: _to_int(x.get("date_unix")) or 0)
    return out


def pack_team(ms, team_id):
    n = len(ms)
    if n == 0:
        return {"n": 0}
    gf = ga = btts = o25 = cs = fts = 0.0
    xgs, xgas = [], []
    for m in ms:
        hid = _to_int(m.get("homeID"))
        hg = float(m.get("homeGoalCount") or 0)
        ag = float(m.get("awayGoalCount") or 0)
        if hid == team_id:
            g, gc, xg, xga = hg, ag, m.get("team_a_xg"), m.get("team_b_xg")
        else:
            g, gc, xg, xga = ag, hg, m.get("team_b_xg"), m.get("team_a_xg")
        gf += g
        ga += gc
        btts += int(g >= 1 and gc >= 1)
        o25 += int(g + gc >= 3)
        cs += int(gc == 0)
        fts += int(g == 0)
        if xg is not None:
            xgs.append(float(xg))
        if xga is not None:
            xgas.append(float(xga))
    return {
        "n": n,
        "goals_for_avg": round(gf / n, 3),
        "goals_against_avg": round(ga / n, 3),
        "btts_rate": round(btts / n, 3),
        "over25_rate": round(o25 / n, 3),
        "cs_rate": round(cs / n, 3),
        "fts_rate": round(fts / n, 3),
        "xg_avg": None if not xgs else round(sum(xgs) / len(xgs), 3),
        "xga_avg": None if not xgas else round(sum(xgas) / len(xgas), 3),
    }


def src_rows(ms, team_id):
    rows = []
    for m in ms:
        hid = _to_int(m.get("homeID"))
        hg = float(m.get("homeGoalCount") or 0)
        ag = float(m.get("awayGoalCount") or 0)
        if hid == team_id:
            g, gc, xg, xga, venue = hg, ag, m.get("team_a_xg"), m.get("team_b_xg"), "home"
        else:
            g, gc, xg, xga, venue = ag, hg, m.get("team_b_xg"), m.get("team_a_xg"), "away"
        rows.append({
            "match_id": _to_int(m.get("id")),
            "date_unix": _to_int(m.get("date_unix")) or 0,
            "homeID": _to_int(m.get("homeID")),
            "awayID": _to_int(m.get("awayID")),
            "home_goals": hg, "away_goals": ag,
            "gf": g, "ga": gc, "venue": venue, "xg": xg, "xga": xga,
        })
    return rows


def league_derived(prior):
    n = len(prior)
    if n == 0:
        return {
            "league_source_count": 0,
            "league_source_match_ids": [],
            "league_source_max_timestamp": None,
            "goals_avg": None, "home_goals_avg": None, "away_goals_avg": None,
            "btts_rate": None, "over25_rate": None,
            "xg_total_avg": None, "xg_recorded_n": 0,
            "corners_avg": None, "corners_recorded_n": 0,
        }
    goals = btts = o25 = hg = ag = 0.0
    corners = corners_n = 0.0
    xg = xg_n = 0.0
    ids = []
    for m in prior:
        h = float(m.get("homeGoalCount") or 0)
        a = float(m.get("awayGoalCount") or 0)
        goals += h + a
        hg += h
        ag += a
        btts += int(h >= 1 and a >= 1)
        o25 += int(h + a >= 3)
        ids.append(_to_int(m.get("id")))
        tc = m.get("totalCornerCount")
        if tc is not None:
            try:
                corners += float(tc)
                corners_n += 1
            except Exception:
                pass
        xa, xb = m.get("team_a_xg"), m.get("team_b_xg")
        if xa is not None and xb is not None:
            try:
                xg += float(xa) + float(xb)
                xg_n += 1
            except Exception:
                pass
    return {
        "league_source_count": n,
        "league_source_match_ids": ids,
        "league_source_max_timestamp": max(_to_int(m.get("date_unix")) or 0 for m in prior),
        "goals_avg": round(goals / n, 3),
        "home_goals_avg": round(hg / n, 3),
        "away_goals_avg": round(ag / n, 3),
        "btts_rate": round(btts / n, 3),
        "over25_rate": round(o25 / n, 3),
        "xg_total_avg": None if not xg_n else round(xg / xg_n, 3),
        "xg_recorded_n": int(xg_n),
        "corners_avg": None if not corners_n else round(corners / corners_n, 3),
        "corners_recorded_n": int(corners_n),
    }


def load_players(sid, mt, state):
    recs = []
    js, rec = cached(
        ("pl", sid, mt, 1),
        "league-players",
        {"season_id": sid, "include": "stats", "max_time": mt, "page": 1},
        state,
    )
    recs.append(rec)
    pager = js.get("pager") or {}
    max_page = int(pager.get("max_page") or 1)
    total = int(pager.get("total_results") or 0)
    rows = list(js.get("data") or [])
    for page in range(2, max_page + 1):
        js2, rec2 = cached(
            ("pl", sid, mt, page),
            "league-players",
            {"season_id": sid, "include": "stats", "max_time": mt, "page": page},
            state,
        )
        recs.append(rec2)
        rows.extend(js2.get("data") or [])
    complete = max_page >= 1 and (len(rows) == total if total else True)
    return rows, {
        "max_page": max_page, "loaded_pages": max_page,
        "loaded_rows": len(rows), "total_results": total,
        "pagination_complete": bool(complete),
    }, recs


def write_json(path: Path, obj) -> None:
    # Machine artifacts are stored compactly to conserve persistent-disk space.
    path.write_text(json.dumps(obj, ensure_ascii=False, default=str, separators=(",", ":")))


def process_one(r, state):
    mid = int(r.match_id)
    sid = int(r.season_id)
    reasons: list[str] = []
    ddir = MATCH_DIR / str(mid)
    ddir.mkdir(parents=True, exist_ok=True)

    # DISCOVERY ONLY: no fields from this response enter the feature builder.
    discovery_rows, discovery_recs = discover_season_matches(sid, state)
    discovered = next((m for m in discovery_rows if _to_int(m.get("id")) == mid), None)
    if not discovered:
        raise RuntimeError("target_missing_in_discovery")
    kick = _to_int(discovered.get("date_unix"))
    hid = _to_int(discovered.get("homeID"))
    aid = _to_int(discovered.get("awayID"))
    if not kick or hid is None or aid is None:
        raise RuntimeError("discovery_missing_kickoff_or_team_ids")
    hg, ag, actual_1x2, actual_btts, actual_over25 = target_outcomes(discovered)
    mt = kick - 1

    provenance = []
    # STRICT FEATURE SOURCE starts here.
    js_m, rec_m = cached(
        ("m", sid, mt),
        "league-matches",
        {"season_id": sid, "max_time": mt, "max_per_page": 1000},
        state,
    )
    provenance.append(rec_m)
    matches = js_m.get("data") or []
    hist_target = next((m for m in matches if _to_int(m.get("id")) == mid), None)
    if not hist_target:
        identity = {"found": False}
        reasons.append("target_missing_in_historical_snapshot")
    else:
        ident = {k: hist_target.get(k) for k in MATCH_ALLOW if k in hist_target}
        ident["match_id"] = mid
        identity = {
            "found": True,
            "identity": ident,
            "prematch_optional": {k: hist_target.get(k) for k in PRE_OPT if k in hist_target},
            "stored_postmatch": False,
        }
    write_json(ddir / f"{mid}_MatchDaten.json", identity)

    prior = prior_matches(matches, kick, mid)

    js_s, rec_s = cached(("s", sid, mt), "league-season", {"season_id": sid, "max_time": mt}, state)
    js_tm, rec_tm = cached(
        ("t", sid, mt),
        "league-teams",
        {"season_id": sid, "include": "stats", "max_time": mt},
        state,
    )
    provenance.extend([rec_s, rec_tm])
    season = js_s.get("data") or {}
    season_safe = {k: season.get(k) for k in SEASON_SAFE_EXACT if k in season}
    excluded = sorted(k for k in season if "recorded" in k.lower())
    season_candidates = {
        k: v for k, v in season.items()
        if k not in season_safe and k not in excluded
    }

    teams = js_tm.get("data") or []
    keep_full, keep_core = [], []
    for t in teams:
        tid = _to_int(t.get("id") or t.get("team_id"))
        if tid in (hid, aid):
            keep_full.append(t)
            keep_core.append({k: t.get(k) for k in t if k in CORE_TEAM})

    derived = league_derived(prior)
    write_json(ddir / f"{sid}_{mid}_LeagueDaten.json", {
        "season_safe_identity": season_safe,
        "season_candidate_unvalidated": season_candidates,
        "season_excluded_recorded_keys": excluded,
        "teams_core_home_away": keep_core,
        "teams_full_home_away": keep_full,
        "league_aggregates_derived": derived,
        "feature_policy": {
            "season_safe_identity": "eligible_after_feature_audit",
            "league_aggregates_derived": "strict_derived_prior_matches",
            "teams_full_home_away": "candidate_after_feature_audit",
            "season_candidate_unvalidated": "NOT_ELIGIBLE_UNTIL_SEPARATE_PROVENANCE_AUDIT",
        },
    })

    def team_form(tid):
        tm = [m for m in prior if _to_int(m.get("homeID")) == tid or _to_int(m.get("awayID")) == tid]
        src = src_rows(tm, tid)
        return {
            "sample_all": len(tm),
            "max_source_match_timestamp": max((x["date_unix"] for x in src), default=None),
            "source_ok": all(x["date_unix"] < kick for x in src),
            "source_matches": src,
            "last5": pack_team(tm[-5:], tid),
            "last6": pack_team(tm[-6:], tid),
            "last10": pack_team(tm[-10:], tid),
            "home_split": pack_team([m for m in tm if _to_int(m.get("homeID")) == tid][-10:], tid),
            "away_split": pack_team([m for m in tm if _to_int(m.get("awayID")) == tid][-10:], tid),
        }

    hf, af = team_form(hid), team_form(aid)
    write_json(ddir / f"{mid}_FormDaten.json", {
        "home_id": hid, "away_id": aid, "kickoff_unix": kick,
        "rule": "date_unix < kickoff AND id != target",
        "home": hf, "away": af,
    })

    js_tab, rec_tab = cached(
        ("tab", sid, mt),
        "league-tables",
        {"season_id": sid, "max_time": mt},
        state,
    )
    provenance.append(rec_tab)
    tables = js_tab.get("data") or {}
    overall = tables.get("league_table") or tables.get("all_matches_table_overall") or []

    def table_row(tid):
        for x in overall:
            xid = _to_int(x.get("id") or x.get("team_id") or x.get("teamID"))
            if xid == tid:
                return x
        return None

    hr, ar = table_row(hid), table_row(aid)
    write_json(ddir / f"{mid}_TableDaten.json", {"home_row": hr, "away_row": ar})

    def keep_played(tid):
        for t in keep_core:
            if _to_int(t.get("id")) == tid:
                return _to_int(t.get("seasonMatchesPlayed_overall"))
        return None

    def table_played(row):
        if not row:
            return None
        return _to_int(row.get("matchesPlayed") or row.get("played"))

    table_ok = True
    if keep_played(hid) is not None and table_played(hr) is not None and keep_played(hid) != table_played(hr):
        table_ok = False
        reasons.append("table_team_mismatch_home")
    if keep_played(aid) is not None and table_played(ar) is not None and keep_played(aid) != table_played(ar):
        table_ok = False
        reasons.append("table_team_mismatch_away")

    players, pag, player_recs = load_players(sid, mt, state)
    provenance.extend(player_recs)
    kept = []
    for pl in players:
        cid = _to_int(pl.get("club_team_id") or pl.get("team_id"))
        if cid in (hid, aid):
            kept.append(pl)
    write_json(ddir / f"{mid}_PlayerDaten.json", {
        "pagination": pag,
        "n_kept_home_away": len(kept),
        "available_fields": sorted({k for pl in kept for k in pl}),
        "players": kept,
    })

    result_target = {
        "match_id": mid,
        "home_goals": hg,
        "away_goals": ag,
        "actual_1x2": actual_1x2,
        "actual_btts": actual_btts,
        "actual_over25": actual_over25,
        "note": "LABEL ONLY — derived from discovery response; never a feature source",
    }
    write_json(ddir / f"{mid}_ResultTarget.json", result_target)

    verdict = validate_match_bundle({
        "match_id": mid,
        "kickoff_unix": kick,
        "requested_max_time": mt,
        "match": identity,
        "form": {"home": hf, "away": af},
        "league": {"league_aggregates_derived": derived},
        "league_expected_matches_completed": _to_int(season_safe.get("matchesCompleted")),
        "player": {"pagination": pag},
        "result_in_features": False,
        "odds_used_as_feature": False,
        "table_team_consistent": table_ok,
    })
    if verdict["reason_if_false"]:
        for reason in verdict["reason_if_false"]:
            if reason not in reasons:
                reasons.append(reason)

    strict = bool(verdict["strict_prematch"]) and not reasons
    home_name = discovered.get("home_name") or discovered.get("homeName") or str(hid)
    away_name = discovered.get("away_name") or discovered.get("awayName") or str(aid)
    league_name = season_safe.get("name") or season_safe.get("division") or str(sid)

    meta = {
        "match_id": mid, "season_id": sid, "liga": league_name,
        "home": home_name, "away": away_name,
        "home_id": hid, "away_id": aid,
        "kickoff_utc": utc_iso(kick), "kickoff_unix": kick,
        "requested_max_time": mt,
        "strict_prematch": bool(strict),
        "reason_if_false": None if strict else reasons,
        "discovery_policy": "IDENTITY_AND_LABEL_ONLY_NOT_FEATURES",
        "discovery_raw_sha256": [r.get("raw_response_sha256") for r in discovery_recs if r],
        "league_source_count": derived.get("league_source_count"),
        "league_source_max_timestamp": derived.get("league_source_max_timestamp"),
        "player_pagination_complete": pag.get("pagination_complete"),
        "collector_version": "FULL7_V3_COLLECTOR_1.3_BOUNDED_MEMORY",
        "request_provenance": [
            {k: rec.get(k) for k in (
                "endpoint", "params", "requested_max_time", "raw_response_sha256",
                "page", "max_page", "raw_row_count"
            )}
            for rec in provenance if rec
        ],
        "fetched_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    # Hash all payload files, then write metadata last.
    meta["files_sha256"] = {
        fp.name: hashlib.sha256(fp.read_bytes()).hexdigest()
        for fp in sorted(ddir.glob("*.json"))
        if fp.name != f"{mid}_Metadata.json"
    }
    write_json(ddir / f"{mid}_Metadata.json", meta)

    if not strict:
        qdir = QUAR_DIR / str(mid)
        qdir.mkdir(parents=True, exist_ok=True)
        write_json(qdir / "reason.json", meta)
    return strict, reasons


def main():
    global CACHE
    if not KEY:
        print(f"{API_KEY_ENV} fehlt", file=sys.stderr)
        sys.exit(2)
    if not CSV_PATH.exists():
        print(f"CSV fehlt: {CSV_PATH}", file=sys.stderr)
        sys.exit(2)

    ROOT.mkdir(parents=True, exist_ok=True)
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    MATCH_DIR.mkdir(parents=True, exist_ok=True)
    QUAR_DIR.mkdir(parents=True, exist_ok=True)
    CACHE = RawCache(RAW_DIR, CACHE_INDEX)

    # The manifest is only two integer columns. csv.DictReader avoids loading
    # pandas/numpy into the worker, saving a large amount of baseline RAM.
    targets = []
    seen_ids = set()
    duplicate_ids = []
    with CSV_PATH.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        fieldnames = reader.fieldnames or []
        missing = [name for name in REQUIRED_CSV_COLUMNS if name not in fieldnames]
        if missing:
            print("CSV-Spalten fehlen:", missing, file=sys.stderr)
            sys.exit(2)
        for row in reader:
            try:
                mid = int(row["match_id"])
                sid = int(row["season_id"])
            except (TypeError, ValueError, KeyError):
                print("CSV enthält ungültige match_id/season_id", file=sys.stderr)
                sys.exit(2)
            if mid in seen_ids:
                if len(duplicate_ids) < 10:
                    duplicate_ids.append(mid)
                continue
            seen_ids.add(mid)
            targets.append(SimpleNamespace(match_id=mid, season_id=sid))
    if duplicate_ids:
        print(f"CSV enthält doppelte match_id, Beispiele: {duplicate_ids}", file=sys.stderr)
        sys.exit(2)

    targets.sort(key=lambda r: (r.season_id, r.match_id))
    total = len(targets)
    if EXPECTED_TOTAL and total != EXPECTED_TOTAL:
        print(f"Unerwartete Zielanzahl: {total}, erwartet {EXPECTED_TOTAL}", file=sys.stderr)
        sys.exit(2)

    st = reconcile_state(load_state(), load_done_ids())
    done = load_done_ids()
    st = reconcile_state(st, done)
    print(f"start total={total} already_done={len(done)} root={ROOT}", flush=True)

    since_progress = 0
    for r in targets:
        mid = int(r.match_id)
        if mid in done:
            continue
        try:
            ok, reasons = process_one(r, st)
        except Exception as exc:
            ok, reasons = False, [f"exception:{type(exc).__name__}:{exc}"]
            qdir = QUAR_DIR / str(mid)
            qdir.mkdir(parents=True, exist_ok=True)
            write_json(qdir / "reason.json", {
                "match_id": mid,
                "season_id": int(r.season_id),
                "strict_prematch": False,
                "reason_if_false": reasons,
                "collector_version": "FULL7_V3_COLLECTOR_1.3_BOUNDED_MEMORY",
                "ts": datetime.now(timezone.utc).isoformat(),
            })

        st["processed"] += 1
        if ok:
            st["strict_pass"] += 1
        else:
            st["quarantined"] += 1
        done.add(mid)
        since_progress += 1
        save_state(st, done)

        # Fail closed before the persistent disk fills. Resume is safe because
        # state + done_ids were atomically checkpointed above.
        disk = shutil.disk_usage(ROOT)
        free_gb = disk.free / (1024 ** 3)
        if free_gb < MIN_FREE_GB:
            print(
                "DISK_LOW",
                {"free_gb": round(free_gb, 3), "min_free_gb": MIN_FREE_GB,
                 "processed": st["processed"], "last_id": mid},
                flush=True,
            )
            sys.exit(4)

        if since_progress >= 10:
            line = {
                "ts": datetime.now(timezone.utc).isoformat(),
                "processed": st["processed"],
                "strict_pass": st["strict_pass"],
                "quarantined": st["quarantined"],
                "api_requests": st["api_requests"],
                "cache_hits": st["cache_hits"],
                "unique_raw": st["unique_raw_responses"],
                "failed": st["failed_requests"],
                "retry": st["retry_count"],
                "last_id": mid,
                "done_total": len(done),
                "disk_free_gb": round(shutil.disk_usage(ROOT).free / (1024 ** 3), 3),
            }
            with PROGRESS_PATH.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(line) + "\n")
            print(line, flush=True)
            since_progress = 0
            # Explicitly collect cyclic garbage between progress batches.
            gc.collect()

    st = reconcile_state(st, done)
    save_state(st, done)
    if len(done) != total or st["processed"] != total:
        print("INCOMPLETE", st, "done", len(done), "total", total, flush=True)
        sys.exit(3)
    print("FINISHED", st, "done", len(done), flush=True)


if __name__ == "__main__":
    main()
