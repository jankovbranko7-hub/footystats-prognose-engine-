#!/usr/bin/env python3
"""FULL-7 V3 Massensammler: Collector + Strict-Validator + SHA-Raw-Cache.
Resume: done_ids.txt + fertige Match-Ordner. Cache: raw_cache_index + *.json.gz.
Keine Kalibrierung, kein Training, keine Ersatzwerte.
"""
from __future__ import annotations
import json, os, sys, time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

from config import (
    API_BASE, API_KEY_ENV, ROOT, CSV_PATH, RAW_DIR, MATCH_DIR, QUAR_DIR,
    STATE_PATH, DONE_PATH, PROGRESS_PATH, CACHE_INDEX, SLEEP_S,
    REQUEST_TIMEOUT, EXPECTED_TOTAL, REQUIRED_CSV_COLUMNS,
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


def kick_unix(s) -> int:
    dt = datetime.fromisoformat(str(s))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


def match_files(mid: int) -> list[str]:
    sid_glob = list((MATCH_DIR / str(mid)).glob(f"*_{mid}_LeagueDaten.json"))
    league = sid_glob[0].name if sid_glob else f"UNKNOWN_{mid}_LeagueDaten.json"
    return [
        f"{mid}_MatchDaten.json",
        league,
        f"{mid}_FormDaten.json",
        f"{mid}_TableDaten.json",
        f"{mid}_PlayerDaten.json",
        f"{mid}_ResultTarget.json",
        f"{mid}_Metadata.json",
    ]


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
    return any(n.endswith(f"_{mid}_LeagueDaten.json") or n.endswith("LeagueDaten.json") for n in names)


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
        st = json.loads(STATE_PATH.read_text())
    else:
        st = {
            "processed": 0, "strict_pass": 0, "quarantined": 0,
            "api_requests": 0, "cache_hits": 0, "unique_raw_responses": 0,
            "failed_requests": 0, "retry_count": 0,
        }
    return st


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
    tmp.write_text(json.dumps({k: st[k] for k in st if k != "done_ids"}, indent=2))
    tmp.replace(STATE_PATH)
    DONE_PATH.write_text("\n".join(str(i) for i in sorted(done)))


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


MEMO: dict = {}


def cached(key, endpoint, params, state):
    if key in MEMO:
        state["cache_hits"] += 1
        return MEMO[key]
    js, rec = fetch(endpoint, params, state)
    MEMO[key] = (js, rec)
    return MEMO[key]


def prior_matches(matches, kick, target_id):
    out = []
    for m in matches:
        ts = int(m.get("date_unix") or 0)
        if ts <= 0 or ts >= kick:
            continue
        if int(m.get("id") or 0) == int(target_id):
            continue
        if m.get("homeGoalCount") is None or m.get("awayGoalCount") is None:
            continue
        out.append(m)
    out.sort(key=lambda x: int(x.get("date_unix") or 0))
    return out


def pack_team(ms, team_id):
    n = len(ms)
    if n == 0:
        return {"n": 0}
    gf = ga = btts = o25 = cs = fts = 0
    xgs, xgas = [], []
    for m in ms:
        hid = m.get("homeID")
        hg = float(m.get("homeGoalCount") or 0)
        ag = float(m.get("awayGoalCount") or 0)
        if hid == team_id:
            g, gc, xg, xga = hg, ag, m.get("team_a_xg"), m.get("team_b_xg")
        else:
            g, gc, xg, xga = ag, hg, m.get("team_b_xg"), m.get("team_a_xg")
        gf += g
        ga += gc
        if g >= 1 and gc >= 1:
            btts += 1
        if g + gc >= 3:
            o25 += 1
        if gc == 0:
            cs += 1
        if g == 0:
            fts += 1
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
        hid = m.get("homeID")
        hg = float(m.get("homeGoalCount") or 0)
        ag = float(m.get("awayGoalCount") or 0)
        if hid == team_id:
            g, gc, xg, xga, venue = hg, ag, m.get("team_a_xg"), m.get("team_b_xg"), "home"
        else:
            g, gc, xg, xga, venue = ag, hg, m.get("team_b_xg"), m.get("team_a_xg"), "away"
        rows.append({
            "match_id": m.get("id"), "date_unix": int(m.get("date_unix") or 0),
            "homeID": hid, "awayID": m.get("awayID"),
            "home_goals": hg, "away_goals": ag, "gf": g, "ga": gc,
            "venue": venue, "xg": xg, "xga": xga,
        })
    return rows


def league_derived(prior):
    n = len(prior)
    if n == 0:
        return {"league_source_count": 0, "league_source_match_ids": [], "league_source_max_timestamp": None}
    goals = btts = o25 = hg = ag = 0
    corners = corners_n = 0
    xg = xg_n = 0
    ids = []
    for m in prior:
        h = float(m.get("homeGoalCount") or 0)
        a = float(m.get("awayGoalCount") or 0)
        goals += h + a
        hg += h
        ag += a
        if h >= 1 and a >= 1:
            btts += 1
        if h + a >= 3:
            o25 += 1
        ids.append(int(m.get("id")))
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
    max_ts = max(int(m.get("date_unix") or 0) for m in prior)
    return {
        "league_source_count": n,
        "league_source_match_ids": ids,
        "league_source_max_timestamp": max_ts,
        "goals_avg": round(goals / n, 3),
        "home_goals_avg": round(hg / n, 3),
        "away_goals_avg": round(ag / n, 3),
        "btts_rate": round(btts / n, 3),
        "over25_rate": round(o25 / n, 3),
        "xg_total_avg": None if xg_n == 0 else round(xg / xg_n, 3),
        "xg_recorded_n": xg_n,
        "corners_avg": None if corners_n == 0 else round(corners / corners_n, 3),
        "corners_recorded_n": corners_n,
    }


def load_players(sid, mt, state):
    recs = []
    js, rec = cached(("pl", sid, mt, 1), "league-players",
                     {"season_id": sid, "include": "stats", "max_time": mt, "page": 1}, state)
    recs.append(rec)
    pager = js.get("pager") or {}
    max_page = int(pager.get("max_page") or 1)
    total = int(pager.get("total_results") or 0)
    rows = list(js.get("data") or [])
    for p in range(2, max_page + 1):
        js2, rec2 = cached(("pl", sid, mt, p), "league-players",
                           {"season_id": sid, "include": "stats", "max_time": mt, "page": p}, state)
        recs.append(rec2)
        rows.extend(js2.get("data") or [])
    complete = (max_page >= 1) and ((len(rows) == total) if total else True)
    return rows, {
        "max_page": max_page,
        "loaded_pages": max_page,
        "loaded_rows": len(rows),
        "total_results": total,
        "pagination_complete": bool(complete),
    }, recs


def write_json(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, indent=2, default=str))


def process_one(r, state):
    mid = int(r.match_id)
    sid = int(r.season_id)
    kick = kick_unix(r.datum_utc)
    mt = kick - 1
    reasons = []
    ddir = MATCH_DIR / str(mid)
    ddir.mkdir(parents=True, exist_ok=True)

    provenance = []
    js_m, rec_m = cached(("m", sid, mt), "league-matches",
                         {"season_id": sid, "max_time": mt, "max_per_page": 1000}, state)
    provenance.append(rec_m)
    matches = js_m.get("data") or []
    target = next((m for m in matches if int(m.get("id") or 0) == mid), None)
    if not target:
        identity = {"found": False}
        reasons.append("target_missing")
        hid, aid = int(r.heim_id), int(r.auswaerts_id)
    else:
        hid = int(target.get("homeID"))
        aid = int(target.get("awayID"))
        ident = {k: target.get(k) for k in MATCH_ALLOW if k in target}
        ident["match_id"] = mid
        identity = {
            "found": True,
            "identity": ident,
            "prematch_optional": {k: target.get(k) for k in PRE_OPT if k in target},
            "stored_postmatch": False,
        }
    write_json(ddir / f"{mid}_MatchDaten.json", identity)

    prior = prior_matches(matches, kick, mid)
    js_s, rec_s = cached(("s", sid, mt), "league-season", {"season_id": sid, "max_time": mt}, state)
    js_tm, rec_tm = cached(("t", sid, mt), "league-teams",
                           {"season_id": sid, "include": "stats", "max_time": mt}, state)
    provenance.extend([rec_s, rec_tm])
    season = js_s.get("data") or {}
    season_safe = {k: season.get(k) for k in SEASON_SAFE_EXACT if k in season}
    excluded = sorted(k for k in season if "recorded" in k.lower())
    season_candidates = {k: v for k, v in season.items()
                         if k not in season_safe and k not in excluded}
    teams = js_tm.get("data") or []
    keep_full = []
    keep_core = []
    for t in teams:
        tid = t.get("id") or t.get("team_id")
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
    })

    def team_form(tid):
        tm = [m for m in prior if m.get("homeID") == tid or m.get("awayID") == tid]
        src = src_rows(tm, tid)
        return {
            "sample_all": len(tm),
            "max_source_match_timestamp": max((x["date_unix"] for x in src), default=None),
            "source_ok": all(x["date_unix"] < kick for x in src),
            "source_matches": src,
            "last5": pack_team(tm[-5:], tid),
            "last6": pack_team(tm[-6:], tid),
            "last10": pack_team(tm[-10:], tid),
            "home_split": pack_team([m for m in tm if m.get("homeID") == tid][-10:], tid),
            "away_split": pack_team([m for m in tm if m.get("awayID") == tid][-10:], tid),
        }

    hf, af = team_form(hid), team_form(aid)
    write_json(ddir / f"{mid}_FormDaten.json", {
        "home_id": hid, "away_id": aid, "kickoff_unix": kick,
        "rule": "date_unix < kickoff AND id != target",
        "home": hf, "away": af,
    })

    js_tab, rec_tab = cached(("tab", sid, mt), "league-tables", {"season_id": sid, "max_time": mt}, state)
    provenance.append(rec_tab)
    tables = js_tab.get("data") or {}
    overall = tables.get("league_table") or tables.get("all_matches_table_overall") or []

    def row(tid):
        for x in overall:
            if (x.get("id") or x.get("team_id") or x.get("teamID")) == tid:
                return x
        return None

    hr, ar = row(hid), row(aid)
    write_json(ddir / f"{mid}_TableDaten.json", {"home_row": hr, "away_row": ar})

    def keep_played(tid):
        for t in keep_core:
            if t.get("id") == tid:
                return t.get("seasonMatchesPlayed_overall")
        return None

    def tplayed(rw):
        if not rw:
            return None
        return rw.get("matchesPlayed") or rw.get("played")

    table_ok = True
    if keep_played(hid) is not None and tplayed(hr) is not None and keep_played(hid) != tplayed(hr):
        table_ok = False
        reasons.append("table_team_mismatch_home")
    if keep_played(aid) is not None and tplayed(ar) is not None and keep_played(aid) != tplayed(ar):
        table_ok = False
        reasons.append("table_team_mismatch_away")

    players, pag, player_recs = load_players(sid, mt, state)
    provenance.extend(player_recs)
    kept = []
    for pl in players:
        cid = pl.get("club_team_id") or pl.get("team_id")
        if cid in (hid, aid):
            kept.append(pl)
    available_player_fields = sorted({k for pl in kept for k in pl.keys()})
    write_json(ddir / f"{mid}_PlayerDaten.json", {
        "pagination": pag,
        "n_kept_home_away": len(kept),
        "available_fields": available_player_fields,
        "players": kept,
    })

    write_json(ddir / f"{mid}_ResultTarget.json", {
        "match_id": mid,
        "home_goals": None if pd.isna(r.tore_heim) else int(r.tore_heim),
        "away_goals": None if pd.isna(r.tore_auswaerts) else int(r.tore_auswaerts),
        "actual_1x2": r.actual_1x2,
        "actual_btts": int(r.actual_btts),
        "actual_over25": int(r.actual_over25),
        "note": "LABEL ONLY",
    })

    verdict = validate_match_bundle({
        "match_id": mid,
        "kickoff_unix": kick,
        "requested_max_time": mt,
        "match": identity,
        "form": {"home": hf, "away": af},
        "league": {"league_aggregates_derived": derived},
        "league_expected_matches_completed": season_safe.get("matchesCompleted"),
        "player": {"pagination": pag},
        "result_in_features": False,
        "odds_used_as_feature": False,
        "table_team_consistent": table_ok,
    })
    if verdict["reason_if_false"]:
        for rsn in verdict["reason_if_false"]:
            if rsn not in reasons:
                reasons.append(rsn)
    strict = bool(verdict["strict_prematch"]) and not reasons
    import hashlib
    meta = {
        "match_id": mid, "season_id": sid, "liga": r.liga,
        "home": r.heim, "away": r.auswaerts,
        "kickoff_utc": str(r.datum_utc), "kickoff_unix": kick,
        "requested_max_time": mt,
        "strict_prematch": bool(strict),
        "reason_if_false": None if strict else reasons,
        "league_source_count": derived.get("league_source_count"),
        "league_source_max_timestamp": derived.get("league_source_max_timestamp"),
        "player_pagination_complete": pag.get("pagination_complete"),
        "collector_version": "FULL7_V3_COLLECTOR_1.1",
        "request_provenance": [
            {k: rec.get(k) for k in ("endpoint", "params", "requested_max_time", "raw_response_sha256", "page", "max_page", "raw_row_count")}
            for rec in provenance if rec
        ],
        "fetched_at_utc": datetime.now(timezone.utc).isoformat(),
        "files_sha256": {fp.name: hashlib.sha256(fp.read_bytes()).hexdigest()
                         for fp in sorted(ddir.glob("*.json"))},
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

    df = pd.read_csv(CSV_PATH)
    missing = [c for c in REQUIRED_CSV_COLUMNS if c not in df.columns]
    if missing:
        print("CSV-Spalten fehlen:", missing, file=sys.stderr)
        sys.exit(2)
    if df["match_id"].isna().any():
        print("CSV enthält leere match_id", file=sys.stderr)
        sys.exit(2)
    if df["match_id"].duplicated().any():
        dups = df.loc[df["match_id"].duplicated(), "match_id"].head(10).tolist()
        print(f"CSV enthält doppelte match_id, Beispiele: {dups}", file=sys.stderr)
        sys.exit(2)
    df = df.sort_values(["season_id", "datum_utc", "match_id"])
    total = len(df)
    if EXPECTED_TOTAL and total != EXPECTED_TOTAL:
        print(f"Unerwartete Zielanzahl: {total}, erwartet {EXPECTED_TOTAL}", file=sys.stderr)
        sys.exit(2)
    st = load_state()
    done = load_done_ids()
    st = reconcile_state(st, done)
    print(f"start total={total} already_done={len(done)} root={ROOT}", flush=True)
    n = 0
    for _, r in df.iterrows():
        mid = int(r.match_id)
        if mid in done:
            continue
        try:
            ok, reasons = process_one(r, st)
        except Exception as exc:
            ok, reasons = False, [f"exception:{exc}"]
            qdir = QUAR_DIR / str(mid)
            qdir.mkdir(parents=True, exist_ok=True)
            write_json(qdir / "reason.json", {"match_id": mid, "error": str(exc)})
        st["processed"] += 1
        if ok:
            st["strict_pass"] += 1
        else:
            st["quarantined"] += 1
        done.add(mid)
        n += 1
        save_state(st, done)
        if n % 10 == 0:
            line = {
                "ts": datetime.now(timezone.utc).isoformat(),
                "processed": st["processed"], "strict_pass": st["strict_pass"],
                "quarantined": st["quarantined"], "api_requests": st["api_requests"],
                "cache_hits": st["cache_hits"], "unique_raw": st["unique_raw_responses"],
                "failed": st["failed_requests"], "retry": st["retry_count"],
                "last_id": mid, "done_total": len(done),
            }
            with PROGRESS_PATH.open("a") as fh:
                fh.write(json.dumps(line) + "\n")
            print(line, flush=True)
    st = reconcile_state(st, done)
    save_state(st, done)
    if len(done) != total or st["processed"] != total:
        print("INCOMPLETE", {k: st[k] for k in st}, "done", len(done), "total", total, flush=True)
        sys.exit(3)
    print("FINISHED", {k: st[k] for k in st}, "done", len(done), flush=True)


if __name__ == "__main__":
    main()
