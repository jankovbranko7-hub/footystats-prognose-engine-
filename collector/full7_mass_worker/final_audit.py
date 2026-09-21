#!/usr/bin/env python3
"""Read-only final audit for the FULL-7 historical mass collection.

The collector artifacts are treated as immutable inputs. This script writes
only into ROOT/final_audit and never modifies match/quarantine/raw-cache data.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import os
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

EXPECTED_TOTAL_DEFAULT = 17685
POSTMATCH_FORBIDDEN = {
    "homeGoalCount", "awayGoalCount", "overallGoalCount", "totalGoalCount",
    "homeGoals", "awayGoals", "homeGoals_timings", "awayGoals_timings",
    "HTGoalCount", "ht_goals_team_a", "ht_goals_team_b", "winningTeam",
    "attendance", "team_a_shots", "team_b_shots", "team_a_possession",
    "team_b_possession", "totalCornerCount", "actual_1x2", "actual_btts",
    "actual_over25", "hit_ou", "hit_btts",
}


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def walk_keys(obj: Any, prefix: str = ""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            p = f"{prefix}.{k}" if prefix else str(k)
            yield p, str(k), v
            yield from walk_keys(v, p)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from walk_keys(v, f"{prefix}[{i}]")


def load_manifest(csv_path: Path):
    ids, seasons, dup = [], {}, []
    seen = set()
    with csv_path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        if not reader.fieldnames or not {"match_id", "season_id"}.issubset(reader.fieldnames):
            raise RuntimeError("manifest_missing_match_id_or_season_id")
        for row in reader:
            mid = int(row["match_id"])
            sid = int(row["season_id"])
            if mid in seen:
                dup.append(mid)
            else:
                seen.add(mid)
                ids.append(mid)
                seasons[mid] = sid
    return ids, seasons, dup


def load_done(done_path: Path):
    vals = []
    for tok in done_path.read_text(encoding="utf-8").split():
        if tok.strip():
            vals.append(int(tok))
    return vals


def reason_class(reason: str) -> str:
    if "417 Client Error" in reason:
        return "HTTP_417"
    if reason.startswith("league_source_count_mismatch:"):
        return "LEAGUE_SOURCE_COUNT_MISMATCH"
    if reason.startswith("exception:"):
        return "OTHER_EXCEPTION"
    return reason.split(":", 1)[0]


def audit(root: Path, csv_path: Path, expected_total: int, verify_raw: bool) -> dict:
    match_dir = root / "matches"
    quar_dir = root / "quarantine"
    done_path = root / "done_ids.txt"
    state_path = root / "state.json"
    raw_dir = root / "raw_cache"
    raw_index = root / "raw_cache_index.jsonl"

    issues = Counter()
    examples = defaultdict(list)
    q_reason = Counter()
    q_class = Counter()
    q_season = Counter()
    strict = 0
    nonstrict = 0
    verified_payload_hashes = 0
    feature_key_leaks = Counter()
    odds_like_keys = Counter()
    provenance_max_time_violations = 0
    provenance_missing_max_time = 0

    def add_issue(code: str, detail=None):
        issues[code] += 1
        if detail is not None and len(examples[code]) < 20:
            examples[code].append(detail)

    target_ids, target_seasons, manifest_dups = load_manifest(csv_path)
    target_set = set(target_ids)
    for mid in manifest_dups:
        add_issue("manifest_duplicate_match_id", mid)

    if len(target_ids) != expected_total:
        add_issue("manifest_total_mismatch", {"actual": len(target_ids), "expected": expected_total})

    if not done_path.exists():
        raise RuntimeError(f"missing_done_ids:{done_path}")
    done_vals = load_done(done_path)
    done_set = set(done_vals)
    if len(done_vals) != len(done_set):
        add_issue("done_ids_duplicates", len(done_vals) - len(done_set))
    for mid in sorted(target_set - done_set)[:20]:
        add_issue("target_missing_from_done", mid)
    for mid in sorted(done_set - target_set)[:20]:
        add_issue("done_not_in_manifest", mid)
    if len(done_set) != expected_total:
        add_issue("done_total_mismatch", {"actual": len(done_set), "expected": expected_total})

    state = read_json(state_path) if state_path.exists() else {}
    if state.get("processed") != expected_total:
        add_issue("state_processed_mismatch", state.get("processed"))

    match_ids_on_disk = {int(p.name) for p in match_dir.iterdir() if p.is_dir() and p.name.isdigit()} if match_dir.exists() else set()
    for mid in sorted(done_set - match_ids_on_disk)[:20]:
        add_issue("done_match_dir_missing", mid)

    required_fixed = [
        "MatchDaten.json", "FormDaten.json", "TableDaten.json",
        "PlayerDaten.json", "ResultTarget.json", "Metadata.json",
    ]

    for mid in sorted(done_set):
        d = match_dir / str(mid)
        if not d.is_dir():
            continue
        sid_expected = target_seasons.get(mid)
        expected_paths = {suffix: d / f"{mid}_{suffix}" for suffix in required_fixed}
        league_files = list(d.glob(f"*_{mid}_LeagueDaten.json"))
        if len(league_files) != 1:
            add_issue("league_file_count_not_one", {"match_id": mid, "count": len(league_files)})
            league_path = league_files[0] if league_files else None
        else:
            league_path = league_files[0]

        missing = [s for s, p in expected_paths.items() if not p.exists()]
        if missing:
            add_issue("bundle_missing_files", {"match_id": mid, "missing": missing})
            continue

        try:
            meta = read_json(expected_paths["Metadata.json"])
        except Exception as exc:
            add_issue("metadata_parse_error", {"match_id": mid, "error": str(exc)})
            continue

        if int(meta.get("match_id", -1)) != mid:
            add_issue("metadata_match_id_mismatch", mid)
        if sid_expected is not None and int(meta.get("season_id", -1)) != sid_expected:
            add_issue("metadata_season_id_mismatch", {"match_id": mid, "actual": meta.get("season_id"), "expected": sid_expected})

        kick = meta.get("kickoff_unix")
        mt = meta.get("requested_max_time")
        if kick is None or mt is None or int(mt) != int(kick) - 1:
            add_issue("max_time_not_kickoff_minus_1", {"match_id": mid, "kickoff": kick, "max_time": mt})

        is_strict = meta.get("strict_prematch") is True
        if is_strict:
            strict += 1
            if meta.get("reason_if_false") not in (None, [], ""):
                add_issue("strict_has_reason_if_false", mid)
        else:
            nonstrict += 1
            reasons = meta.get("reason_if_false") or []
            if not isinstance(reasons, list):
                reasons = [str(reasons)]
            if not reasons:
                add_issue("nonstrict_without_reason", mid)
            for reason in reasons:
                s = str(reason)
                q_reason[s] += 1
                q_class[reason_class(s)] += 1
            q_season[str(meta.get("season_id"))] += 1

        files_sha = meta.get("files_sha256") or {}
        for name, digest in files_sha.items():
            p = d / name
            if not p.exists():
                add_issue("metadata_hashed_file_missing", {"match_id": mid, "file": name})
                continue
            actual = sha256_file(p)
            verified_payload_hashes += 1
            if actual != digest:
                add_issue("payload_sha256_mismatch", {"match_id": mid, "file": name})

        try:
            form = read_json(expected_paths["FormDaten.json"])
            for side in ("home", "away"):
                block = form.get(side) or {}
                for row in block.get("source_matches") or []:
                    if int(row.get("match_id", -1)) == mid:
                        add_issue("form_contains_target", {"match_id": mid, "side": side})
                    ts = row.get("date_unix")
                    if kick is not None and ts is not None and int(ts) >= int(kick):
                        add_issue("form_timestamp_not_before_kickoff", {"match_id": mid, "side": side, "ts": ts, "kick": kick})
        except Exception as exc:
            add_issue("form_parse_or_audit_error", {"match_id": mid, "error": str(exc)})

        if league_path is not None:
            try:
                league = read_json(league_path)
                derived = league.get("league_aggregates_derived") or {}
                ids = {int(x) for x in (derived.get("league_source_match_ids") or []) if x is not None}
                if mid in ids:
                    add_issue("league_contains_target", mid)
                lmax = derived.get("league_source_max_timestamp")
                if kick is not None and lmax is not None and int(lmax) >= int(kick):
                    add_issue("league_timestamp_not_before_kickoff", {"match_id": mid, "ts": lmax, "kick": kick})
            except Exception as exc:
                add_issue("league_parse_or_audit_error", {"match_id": mid, "error": str(exc)})

        try:
            player = read_json(expected_paths["PlayerDaten.json"])
            pag = player.get("pagination") or {}
            if pag.get("pagination_complete") is not True:
                add_issue("player_pagination_incomplete", mid)
            total = pag.get("total_results")
            rows = pag.get("loaded_rows")
            max_page = pag.get("max_page")
            loaded_pages = pag.get("loaded_pages")
            if total not in (None, 0) and rows != total:
                add_issue("player_row_count_mismatch", {"match_id": mid, "rows": rows, "total": total})
            if max_page not in (None, 0) and loaded_pages != max_page:
                add_issue("player_page_count_mismatch", {"match_id": mid, "loaded": loaded_pages, "max": max_page})
        except Exception as exc:
            add_issue("player_parse_or_audit_error", {"match_id": mid, "error": str(exc)})

        feature_paths = [
            expected_paths["MatchDaten.json"], expected_paths["FormDaten.json"],
            expected_paths["TableDaten.json"], expected_paths["PlayerDaten.json"],
        ] + ([league_path] if league_path is not None else [])

        # Target post-match fields are forbidden in MatchDaten. Historical
        # source rows in Form/League legitimately contain prior-match results,
        # so they are not leakage merely because they contain goal keys.
        try:
            match_obj = read_json(expected_paths["MatchDaten.json"])
            for path_key, key, _ in walk_keys(match_obj):
                if key in POSTMATCH_FORBIDDEN:
                    feature_key_leaks[path_key] += 1
        except Exception:
            pass

        # Outcome-label / hit fields are forbidden anywhere in feature files.
        label_keys = {"actual_1x2", "actual_btts", "actual_over25", "hit_ou", "hit_btts"}
        for fp in feature_paths:
            try:
                obj = read_json(fp)
            except Exception:
                continue
            for path_key, key, _ in walk_keys(obj):
                if key in label_keys:
                    feature_key_leaks[path_key] += 1
                if "odd" in key.lower():
                    odds_like_keys[path_key] += 1

        for rec in meta.get("request_provenance") or []:
            ep = rec.get("endpoint")
            rmt = rec.get("requested_max_time")
            if ep in {"league-matches", "league-season", "league-teams", "league-tables", "league-players"}:
                if rmt is None:
                    provenance_missing_max_time += 1
                elif mt is not None and int(rmt) != int(mt):
                    provenance_max_time_violations += 1

    quarantine_dirs = {int(p.name) for p in quar_dir.iterdir() if p.is_dir() and p.name.isdigit()} if quar_dir.exists() else set()

    # reason.json is authoritative even when an API exception happened before
    # a complete match Metadata.json could be written.
    q_reason.clear()
    q_class.clear()
    q_season.clear()
    for mid in sorted(quarantine_dirs):
        reason_p = quar_dir / str(mid) / "reason.json"
        if not reason_p.exists():
            add_issue("quarantine_without_reason", mid)
            continue
        try:
            qobj = read_json(reason_p)
        except Exception as exc:
            add_issue("quarantine_reason_parse_error", {"match_id": mid, "error": str(exc)})
            continue
        reasons = qobj.get("reason_if_false") or []
        if not isinstance(reasons, list):
            reasons = [str(reasons)]
        if not reasons:
            add_issue("quarantine_without_reason_text", mid)
        for reason in reasons:
            rs = str(reason)
            q_reason[rs] += 1
            q_class[reason_class(rs)] += 1
        q_season[str(qobj.get("season_id"))] += 1

    metadata_nonstrict_ids = set()
    metadata_strict_ids = set()
    for mid in done_set:
        mp = match_dir / str(mid) / f"{mid}_Metadata.json"
        if not mp.exists():
            continue
        try:
            if read_json(mp).get("strict_prematch") is True:
                metadata_strict_ids.add(mid)
            else:
                metadata_nonstrict_ids.add(mid)
        except Exception:
            pass

    for mid in sorted(metadata_nonstrict_ids - quarantine_dirs)[:20]:
        add_issue("nonstrict_missing_quarantine_dir", mid)
    for mid in sorted(metadata_strict_ids & quarantine_dirs)[:20]:
        add_issue("strict_has_active_quarantine_dir", mid)

    # Final classification is active quarantine vs non-quarantine done IDs.
    nonstrict = len(quarantine_dirs)
    strict = len(done_set - quarantine_dirs)

    raw = {
        "checked": False,
        "index_records": 0,
        "unique_digests_in_index": 0,
        "gzip_files": 0,
        "hash_verified": 0,
        "hash_failures": 0,
        "missing_digest_files": 0,
    }
    if raw_dir.exists():
        raw["gzip_files"] = sum(1 for _ in raw_dir.glob("*.json.gz"))
    if raw_index.exists():
        digests = set()
        with raw_index.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    add_issue("raw_index_json_parse_error")
                    continue
                raw["index_records"] += 1
                dg = rec.get("raw_response_sha256")
                if dg:
                    digests.add(str(dg))
        raw["unique_digests_in_index"] = len(digests)
        for dg in digests:
            p = raw_dir / f"{dg}.json.gz"
            if not p.exists():
                raw["missing_digest_files"] += 1
                add_issue("raw_digest_file_missing", dg)
        if verify_raw:
            raw["checked"] = True
            for dg in sorted(digests):
                p = raw_dir / f"{dg}.json.gz"
                if not p.exists():
                    continue
                try:
                    h = hashlib.sha256()
                    with gzip.open(p, "rb") as fh:
                        for block in iter(lambda: fh.read(1024 * 1024), b""):
                            h.update(block)
                    if h.hexdigest() != dg:
                        raw["hash_failures"] += 1
                        add_issue("raw_sha256_mismatch", dg)
                    else:
                        raw["hash_verified"] += 1
                except Exception as exc:
                    raw["hash_failures"] += 1
                    add_issue("raw_gzip_read_error", {"digest": dg, "error": str(exc)})

    if strict + nonstrict != len(done_set):
        add_issue("classification_total_mismatch", {"strict": strict, "nonstrict": nonstrict, "done": len(done_set)})

    report = {
        "audit_version": "FULL7_COLLECTION_FINAL_AUDIT_1.0",
        "root": str(root),
        "manifest": str(csv_path),
        "expected_total": expected_total,
        "manifest_unique": len(target_set),
        "done_unique": len(done_set),
        "match_dirs": len(match_ids_on_disk),
        "strict_pass": strict,
        "quarantined_active": nonstrict,
        "quarantine_dirs": len(quarantine_dirs),
        "verified_payload_hashes": verified_payload_hashes,
        "quarantine_reason_classes": dict(q_class.most_common()),
        "quarantine_reasons": dict(q_reason.most_common()),
        "quarantine_seasons": dict(q_season.most_common()),
        "feature_forbidden_key_hits": dict(feature_key_leaks.most_common()),
        "odds_like_key_hits": dict(odds_like_keys.most_common()),
        "provenance_missing_max_time": provenance_missing_max_time,
        "provenance_max_time_violations": provenance_max_time_violations,
        "raw_cache": raw,
        "state": state,
        "issues": dict(issues.most_common()),
        "issue_examples": dict(examples),
        "pass_for_master_dataset": not any(n for _, n in issues.items() if n),
    }
    return report


def render_text(report: dict) -> str:
    lines = [
        "FULL-7 COLLECTION FINAL AUDIT",
        f"audit_version={report['audit_version']}",
        f"expected_total={report['expected_total']}",
        f"manifest_unique={report['manifest_unique']}",
        f"done_unique={report['done_unique']}",
        f"match_dirs={report['match_dirs']}",
        f"strict_pass={report['strict_pass']}",
        f"quarantined_active={report['quarantined_active']}",
        f"quarantine_dirs={report['quarantine_dirs']}",
        f"verified_payload_hashes={report['verified_payload_hashes']}",
        f"provenance_missing_max_time={report['provenance_missing_max_time']}",
        f"provenance_max_time_violations={report['provenance_max_time_violations']}",
        f"raw_cache={json.dumps(report['raw_cache'], sort_keys=True)}",
        f"quarantine_reason_classes={json.dumps(report['quarantine_reason_classes'], sort_keys=True)}",
        f"quarantine_seasons={json.dumps(report['quarantine_seasons'], sort_keys=True)}",
        f"feature_forbidden_key_hits={json.dumps(report['feature_forbidden_key_hits'], sort_keys=True)}",
        f"odds_like_key_hits={json.dumps(report['odds_like_key_hits'], sort_keys=True)}",
        f"issues={json.dumps(report['issues'], sort_keys=True)}",
        f"pass_for_master_dataset={report['pass_for_master_dataset']}",
    ]
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.environ.get("FULL7_ROOT", "/var/data/full7/output"))
    ap.add_argument("--csv", default=os.environ.get("FULL7_CSV", "/var/data/full7/input/full7_targets_17685_min.csv"))
    ap.add_argument("--expected-total", type=int, default=int(os.environ.get("FULL7_EXPECTED_TOTAL", EXPECTED_TOTAL_DEFAULT)))
    ap.add_argument("--verify-raw", action="store_true", help="Decompress and SHA-256 verify every raw cache object.")
    args = ap.parse_args()

    root = Path(args.root)
    out = root / "final_audit"
    out.mkdir(parents=True, exist_ok=True)
    report = audit(root, Path(args.csv), args.expected_total, args.verify_raw)
    (out / "collection_final_audit.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    (out / "collection_final_audit.txt").write_text(render_text(report), encoding="utf-8")
    print(render_text(report), end="")


if __name__ == "__main__":
    main()
