#!/usr/bin/env python3
"""Targeted, reversible repair for HTTP-417 quarantine cases.

This tool retries only matches whose active quarantine reason contains
"417 Client Error". It never selects current STRICT_PASS matches. Before a
retry, the active quarantine directory is moved to a history directory, so the
original reason is preserved. Run --preflight first.
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from types import SimpleNamespace

import collect
from config import ROOT, CSV_PATH, RAW_DIR, MATCH_DIR, QUAR_DIR, STATE_PATH, CACHE_INDEX, EXPECTED_TOTAL
from raw_cache import RawCache

EXPECTED_HTTP417 = 309


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, default=str, separators=(",", ":")), encoding="utf-8")


def load_targets():
    out = {}
    with CSV_PATH.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            mid = int(row["match_id"])
            out[mid] = SimpleNamespace(match_id=mid, season_id=int(row["season_id"]))
    return out


def get_http417_population():
    ids, seasons = [], {}
    for rp in QUAR_DIR.glob("*/reason.json"):
        try:
            obj = read_json(rp)
        except Exception:
            continue
        reasons = obj.get("reason_if_false") or []
        if not isinstance(reasons, list):
            reasons = [str(reasons)]
        if any("417 Client Error" in str(x) for x in reasons):
            mid = int(obj.get("match_id") or rp.parent.name)
            ids.append(mid)
            seasons[mid] = int(obj.get("season_id"))
    return sorted(set(ids)), seasons


def load_state():
    if STATE_PATH.exists():
        return read_json(STATE_PATH)
    return {
        "processed": 0, "strict_pass": 0, "quarantined": 0,
        "api_requests": 0, "cache_hits": 0, "unique_raw_responses": 0,
        "failed_requests": 0, "retry_count": 0,
    }


def preflight(ids, seasons, state):
    sample = {}
    for mid in ids:
        sample.setdefault(seasons[mid], mid)
    result = {}
    for sid, mid in sorted(sample.items()):
        collect.DISCOVERY_MEMO["sid"] = None
        collect.DISCOVERY_MEMO["value"] = None
        try:
            rows, _ = collect.discover_season_matches(sid, state)
            found = any(int(float(x.get("id"))) == mid for x in rows if x.get("id") is not None)
            result[str(sid)] = {"ok": True, "sample_match_id": mid, "target_found": found, "rows": len(rows)}
        except Exception as exc:
            result[str(sid)] = {"ok": False, "sample_match_id": mid, "error": f"{type(exc).__name__}:{exc}"}
    return result


def move_old_quarantine_to_history(mid: int):
    src = QUAR_DIR / str(mid)
    if not src.exists():
        return None
    dst = ROOT / "quarantine_history" / "http417_before_retry" / str(mid)
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        raise RuntimeError(f"history_already_exists_for_{mid}")
    src.rename(dst)
    return dst


def main():
    ap = argparse.ArgumentParser()
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--preflight", action="store_true")
    mode.add_argument("--execute", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    ids, seasons = get_http417_population()
    targets = load_targets()

    if len(ids) != EXPECTED_HTTP417:
        raise SystemExit(f"STOP: HTTP417 population={len(ids)} expected={EXPECTED_HTTP417}")
    if any(mid not in targets for mid in ids):
        raise SystemExit("STOP: at least one HTTP417 id is absent from manifest")
    if not collect.KEY:
        raise SystemExit("STOP: FOOTYSTATS_API_KEY missing")

    print(json.dumps({
        "http417_ids": len(ids),
        "seasons": {str(s): sum(1 for mid in ids if seasons[mid] == s) for s in sorted(set(seasons.values()))},
    }, sort_keys=True), flush=True)

    collect.CACHE = RawCache(RAW_DIR, CACHE_INDEX)
    state = load_state()

    if args.preflight:
        result = preflight(ids, seasons, state)
        write_json(ROOT / "final_audit" / "http417_preflight.json", result)
        print(json.dumps(result, indent=2, sort_keys=True), flush=True)
        if not all(v.get("ok") and v.get("target_found") for v in result.values()):
            raise SystemExit("STOP: HTTP417 preflight failed")
        print("HTTP417_PREFLIGHT_PASS", flush=True)
        return

    done = collect.load_done_ids()
    if len(done) != EXPECTED_TOTAL:
        raise SystemExit(f"STOP: done_ids={len(done)} expected={EXPECTED_TOTAL}")

    chosen = ids[:args.limit] if args.limit else ids
    results = []
    repaired = 0
    still_quarantined = 0

    for pos, mid in enumerate(chosen, 1):
        meta_path = MATCH_DIR / str(mid) / f"{mid}_Metadata.json"
        if meta_path.exists():
            try:
                old_meta = read_json(meta_path)
            except Exception:
                old_meta = {}
            if old_meta.get("strict_prematch") is True:
                raise SystemExit(f"STOP: {mid} is already STRICT_PASS")

        move_old_quarantine_to_history(mid)
        target = targets[mid]
        collect.DISCOVERY_MEMO["sid"] = None
        collect.DISCOVERY_MEMO["value"] = None

        try:
            ok, reasons = collect.process_one(target, state)
        except Exception as exc:
            ok = False
            reasons = [f"exception:{type(exc).__name__}:{exc}"]
            write_json(
                QUAR_DIR / str(mid) / "reason.json",
                {
                    "match_id": mid,
                    "season_id": int(target.season_id),
                    "strict_prematch": False,
                    "reason_if_false": reasons,
                    "collector_version": "FULL7_V3_COLLECTOR_1.3_BOUNDED_MEMORY_HTTP417_RETRY",
                },
            )

        repaired += int(bool(ok))
        still_quarantined += int(not ok)
        results.append({
            "match_id": mid,
            "season_id": int(target.season_id),
            "strict_after_retry": bool(ok),
            "reasons": reasons,
        })

        if pos % 10 == 0 or pos == len(chosen):
            print({"retried": pos, "total": len(chosen), "repaired": repaired, "still_quarantined": still_quarantined}, flush=True)

    state = collect.reconcile_state(state, done)
    collect.save_state(state, done)
    write_json(
        ROOT / "final_audit" / "http417_retry_results.json",
        {
            "attempted": len(chosen),
            "repaired": repaired,
            "still_quarantined": still_quarantined,
            "state_after": state,
            "results": results,
        },
    )
    print("HTTP417_RETRY_FINISHED", {
        "attempted": len(chosen),
        "repaired": repaired,
        "still_quarantined": still_quarantined,
        "strict_pass": state.get("strict_pass"),
        "quarantined": state.get("quarantined"),
    }, flush=True)


if __name__ == "__main__":
    main()
