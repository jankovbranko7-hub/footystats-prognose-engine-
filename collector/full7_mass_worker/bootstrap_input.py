#!/usr/bin/env python3
"""Reconstruct the exact 17,685-match collector input from FootyStats and verify it
against cryptographic hashes derived from the user's original workbook.

This bootstrap uses current/full season match responses only to reconstruct target
identity + labels. It is NOT a feature source. If any season differs from the
original manifest, it aborts instead of guessing.
"""
from __future__ import annotations

import csv
import gzip
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

API_BASE = "https://api.football-data-api.com"
API_KEY = os.environ.get("FOOTYSTATS_API_KEY", "")
EXPECTED_TOTAL = int(os.environ.get("FULL7_EXPECTED_TOTAL", "17685"))
OUT_CSV = Path(os.environ.get("FULL7_CSV", "/var/data/full7/input/backtest_50_ligen.csv"))
ROOT = Path(os.environ.get("FULL7_ROOT", "/var/data/full7/output"))
HERE = Path(__file__).resolve().parent
MANIFEST_DIR = HERE / "target_manifest"
AUDIT_PATH = ROOT / "bootstrap_target_audit.json"
VERIFIED_PATH = ROOT / "bootstrap_target_verified.json"
FAILURE_PATH = ROOT / "bootstrap_target_failure.json"
RAW_DIR = ROOT / "bootstrap_raw"

SESSION = requests.Session()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def load_manifest() -> tuple[list[dict], dict[str, str]]:
    seasons: list[dict] = []
    for path in sorted(MANIFEST_DIR.glob("part*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise RuntimeError(f"Invalid manifest part: {path}")
        seasons.extend(data)
    row_hash = json.loads((MANIFEST_DIR / "row_hashes.json").read_text(encoding="utf-8"))
    hashes = row_hash.get("rows_sha256") or {}
    if len(seasons) != 100:
        raise RuntimeError(f"Expected 100 season manifest rows, got {len(seasons)}")
    if len({int(x["season_id"]) for x in seasons}) != 100:
        raise RuntimeError("Duplicate season_id in manifest")
    if len(hashes) != 100:
        raise RuntimeError(f"Expected 100 row hashes, got {len(hashes)}")
    if sum(int(x["count"]) for x in seasons) != EXPECTED_TOTAL:
        raise RuntimeError("Manifest total does not equal FULL7_EXPECTED_TOTAL")
    return seasons, hashes


def request_json(endpoint: str, params: dict) -> tuple[dict, str]:
    q = dict(params)
    q["key"] = API_KEY
    last = None
    for attempt in range(7):
        try:
            resp = SESSION.get(f"{API_BASE}/{endpoint}", params=q, timeout=90)
            if resp.status_code == 429:
                time.sleep(3 + attempt * 4)
                continue
            resp.raise_for_status()
            raw = resp.content
            digest = hashlib.sha256(raw).hexdigest()
            RAW_DIR.mkdir(parents=True, exist_ok=True)
            raw_path = RAW_DIR / f"{digest}.json.gz"
            if not raw_path.exists():
                with gzip.open(raw_path, "wb") as fh:
                    fh.write(raw)
            js = json.loads(raw.decode("utf-8"))
            if not isinstance(js, dict) or not js.get("success"):
                raise RuntimeError(str((js or {}).get("message")))
            return js, digest
        except Exception as exc:
            last = exc
            time.sleep(1 + attempt * 2)
    raise RuntimeError(f"{endpoint} failed: {last}")


def season_matches(season_id: int) -> tuple[list[dict], list[str]]:
    rows: list[dict] = []
    hashes: list[str] = []
    page = 1
    while True:
        params = {"season_id": season_id, "max_per_page": 1000, "page": page}
        js, digest = request_json("league-matches", params)
        hashes.append(digest)
        rows.extend(js.get("data") or [])
        pager = js.get("pager") or {}
        max_page = int(pager.get("max_page") or 1)
        if page >= max_page:
            break
        page += 1
    return rows, hashes


def i(v):
    if v is None or v == "":
        return None
    return int(float(v))


def name(m: dict, side: str) -> str:
    candidates = (
        f"{side}_name",
        f"{side}Name",
        f"{side}_team_name",
        "home_name" if side == "home" else "away_name",
    )
    for key in candidates:
        value = m.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def reconstruct_one(spec: dict, expected_row_hash: str) -> tuple[list[dict], dict]:
    sid = int(spec["season_id"])
    all_rows, raw_hashes = season_matches(sid)
    min_k = int(spec["min_kickoff"])
    max_k = int(spec["max_kickoff"])

    selected: list[dict] = []
    for m in all_rows:
        ts = i(m.get("date_unix"))
        mid = i(m.get("id"))
        hg = i(m.get("homeGoalCount"))
        ag = i(m.get("awayGoalCount"))
        hid = i(m.get("homeID"))
        aid = i(m.get("awayID"))
        if None in (ts, mid, hg, ag, hid, aid):
            continue
        if min_k <= ts <= max_k:
            selected.append({
                "_source": m,
                "match_id": mid,
                "season_id": sid,
                "kickoff_unix": ts,
                "heim_id": hid,
                "auswaerts_id": aid,
                "tore_heim": hg,
                "tore_auswaerts": ag,
            })

    selected.sort(key=lambda x: x["match_id"])
    ids_canonical = ",".join(str(x["match_id"]) for x in selected)
    labels_canonical = ";".join(
        f'{x["match_id"]}:{x["tore_heim"]}:{x["tore_auswaerts"]}' for x in selected
    )
    rows_canonical = ";".join(
        f'{x["match_id"]}|{x["kickoff_unix"]}|{x["heim_id"]}|{x["auswaerts_id"]}|{x["tore_heim"]}|{x["tore_auswaerts"]}'
        for x in selected
    )

    observed = {
        "count": len(selected),
        "ids_sha256": sha256_text(ids_canonical),
        "labels_sha256": sha256_text(labels_canonical),
        "rows_sha256": sha256_text(rows_canonical),
    }
    checks = {
        "count": observed["count"] == int(spec["count"]),
        "ids_sha256": observed["ids_sha256"] == spec["ids_sha256"],
        "labels_sha256": observed["labels_sha256"] == spec["labels_sha256"],
        "rows_sha256": observed["rows_sha256"] == expected_row_hash,
    }
    audit = {
        "season_id": sid,
        "league": spec["league"],
        "window": [min_k, max_k],
        "expected_count": int(spec["count"]),
        "observed": observed,
        "checks": checks,
        "raw_response_sha256": raw_hashes,
        "pass": all(checks.values()),
    }
    if not audit["pass"]:
        return [], audit

    out: list[dict] = []
    for x in selected:
        m = x["_source"]
        hg, ag = x["tore_heim"], x["tore_auswaerts"]
        out.append({
            "match_id": x["match_id"],
            "season_id": sid,
            "datum_utc": datetime.fromtimestamp(x["kickoff_unix"], timezone.utc).isoformat(),
            "liga": spec["league"],
            "heim": name(m, "home"),
            "auswaerts": name(m, "away"),
            "heim_id": x["heim_id"],
            "auswaerts_id": x["auswaerts_id"],
            "tore_heim": hg,
            "tore_auswaerts": ag,
            "actual_1x2": "H" if hg > ag else ("A" if ag > hg else "D"),
            "actual_over25": 1 if hg + ag >= 3 else 0,
            "actual_btts": 1 if hg > 0 and ag > 0 else 0,
        })
    return out, audit


def atomic_json(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def main() -> None:
    if not API_KEY:
        print("FOOTYSTATS_API_KEY fehlt", file=sys.stderr)
        sys.exit(2)

    ROOT.mkdir(parents=True, exist_ok=True)
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)

    # Reuse a previously verified input on persistent disk.
    if OUT_CSV.exists() and VERIFIED_PATH.exists():
        try:
            meta = json.loads(VERIFIED_PATH.read_text(encoding="utf-8"))
            digest = hashlib.sha256(OUT_CSV.read_bytes()).hexdigest()
            if meta.get("csv_sha256") == digest and int(meta.get("rows", -1)) == EXPECTED_TOTAL:
                print(f"BOOTSTRAP VERIFIED INPUT REUSED rows={EXPECTED_TOTAL} sha256={digest}", flush=True)
                return
        except Exception:
            pass

    seasons, row_hashes = load_manifest()
    all_out: list[dict] = []
    audits: list[dict] = []
    failed = False

    for idx, spec in enumerate(seasons, start=1):
        sid = int(spec["season_id"])
        rows, audit = reconstruct_one(spec, row_hashes[str(sid)])
        audits.append(audit)
        if not audit["pass"]:
            failed = True
            print(f"BOOTSTRAP MANIFEST MISMATCH season={sid} {audit['checks']}", flush=True)
        else:
            all_out.extend(rows)
            print(f"BOOTSTRAP {idx}/100 season={sid} rows={len(rows)} VERIFIED", flush=True)

    audit_doc = {
        "version": "FULL7_TARGET_BOOTSTRAP_1.0",
        "expected_total": EXPECTED_TOTAL,
        "season_count": len(seasons),
        "all_seasons_pass": not failed,
        "reconstructed_rows": len(all_out),
        "seasons": audits,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    atomic_json(AUDIT_PATH, audit_doc)

    if failed or len(all_out) != EXPECTED_TOTAL:
        atomic_json(FAILURE_PATH, {
            "error": "target_manifest_verification_failed",
            "expected_total": EXPECTED_TOTAL,
            "reconstructed_rows": len(all_out),
            "audit_path": str(AUDIT_PATH),
        })
        print("BOOTSTRAP FAILED — target set differs from original workbook manifest", file=sys.stderr)
        sys.exit(4)

    # Exact duplicate check before writing.
    ids = [int(r["match_id"]) for r in all_out]
    if len(ids) != len(set(ids)):
        atomic_json(FAILURE_PATH, {"error": "duplicate_match_id_after_bootstrap"})
        sys.exit(4)

    all_out.sort(key=lambda r: (int(r["season_id"]), r["datum_utc"], int(r["match_id"])))
    fields = [
        "match_id", "season_id", "datum_utc", "liga", "heim", "auswaerts",
        "heim_id", "auswaerts_id", "tore_heim", "tore_auswaerts",
        "actual_1x2", "actual_over25", "actual_btts",
    ]
    tmp = OUT_CSV.with_suffix(".csv.tmp")
    with tmp.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(all_out)
    tmp.replace(OUT_CSV)

    csv_digest = hashlib.sha256(OUT_CSV.read_bytes()).hexdigest()
    atomic_json(VERIFIED_PATH, {
        "version": "FULL7_TARGET_BOOTSTRAP_1.0",
        "rows": len(all_out),
        "unique_match_ids": len(set(ids)),
        "seasons": len(seasons),
        "csv_sha256": csv_digest,
        "source": "FootyStats league-matches identity/labels verified against original-workbook cryptographic manifest",
        "feature_source": False,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    })
    print(f"BOOTSTRAP FINISHED rows={len(all_out)} sha256={csv_digest}", flush=True)


if __name__ == "__main__":
    main()
