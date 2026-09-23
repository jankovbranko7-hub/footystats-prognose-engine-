#!/usr/bin/env python3
"""Read-only recovery audit for exact legacy V3.1 pre-match inputs.

This runner scans only the already-frozen FULL-7 CP2 population and its
SHA-referenced raw cache. It performs no API calls, collection, training,
calibration, model selection, threshold/gate changes, main merge, or production
changes. Outputs are written only below /var/data/full7/derived.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import math
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

DATA_ROOT = Path("/var/data/full7")
COLLECTOR_ROOT = DATA_ROOT / "output"
RAW_DIR = COLLECTOR_ROOT / "raw_cache"
CP_ROOT = DATA_ROOT / "derived" / "full7_phase2_phase3_2026-09-22"
CP2_JSONL = CP_ROOT / "cp2" / "FULL7_MASTER_STRICT.jsonl"
PHASE4_DIR = CP_ROOT / "phase4"
OUTPUT_DIR = DATA_ROOT / "derived" / "v31_raw_input_recovery_audit_2026-09-23"
OUTPUT_JSON = OUTPUT_DIR / "FULL7_V31_RAW_INPUT_RECOVERY_AUDIT.json"
OUTPUT_TXT = OUTPUT_DIR / "FULL7_V31_RAW_INPUT_RECOVERY_AUDIT.txt"

SOURCE_MANIFEST = DATA_ROOT / "FULL7_BACKUP_SHA256_MANIFEST.tsv"
SOURCE_INVENTORY = DATA_ROOT / "FULL7_BACKUP_INVENTORY.json"
EXPECTED_MANIFEST_SHA256 = "86c05accd2f1cb56e5afed13057b5dbb2e857e847b5dd75d927863e7879999d6"
EXPECTED_INVENTORY_SHA256 = "ebe438fbacf2d35315bd2ed7d80dac2ed44468e0e3ada9d1d98ead066b91a304"
EXPECTED_ROWS = 16137
EXPECTED_OOS_ROWS = 5552

FIELDS = {
    "fs_xg_prematch_heim": "team_a_xg_prematch",
    "fs_xg_prematch_aus": "team_b_xg_prematch",
    "fs_o25_potential": "o25_potential",
    "fs_btts_potential": "btts_potential",
    "fs_avg_potential": "avg_potential",
    "fs_pre_ppg_heim": "pre_match_home_ppg",
    "fs_pre_ppg_aus": "pre_match_away_ppg",
}


class AuditError(RuntimeError):
    pass


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(4 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def finite_number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def as_int(value: Any) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def atomic_json(path: Path, obj: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def require_runtime() -> None:
    if os.environ.get("RENDER_SERVICE_ID") != "srv-damiu0p42hec739a0rig":
        raise AuditError("wrong_render_service")
    if os.environ.get("RENDER_GIT_BRANCH") != "audit/full7-cp2-20260922":
        raise AuditError("wrong_git_branch")
    if os.environ.get("RUN_FULL7_V31_RAW_INPUT_AUDIT", "false").strip().lower() != "true":
        raise AuditError("v31_raw_input_audit_flag_not_enabled")
    if os.environ.get("RUN_FULL7_BACKUP_STREAM_SERVER", "false").strip().lower() == "true":
        raise AuditError("backup_stream_flag_must_be_disabled")
    if not CP2_JSONL.is_file():
        raise AuditError(f"cp2_master_missing:{CP2_JSONL}")
    if sha256_file(SOURCE_MANIFEST) != EXPECTED_MANIFEST_SHA256:
        raise AuditError("source_manifest_sha_mismatch")
    if sha256_file(SOURCE_INVENTORY) != EXPECTED_INVENTORY_SHA256:
        raise AuditError("source_inventory_sha_mismatch")


def load_oos_ids() -> set[int]:
    splits_path = PHASE4_DIR / "PHASE4_SPLITS.json"
    labels_path = PHASE4_DIR / "PHASE4_LABELS.npz"
    if not splits_path.is_file() or not labels_path.is_file():
        raise AuditError("phase4_split_or_labels_missing")
    splits = json.loads(splits_path.read_text(encoding="utf-8"))
    dev_end = str(splits.get("development_end_date") or "")
    if len(dev_end) != 10:
        raise AuditError("development_end_date_invalid")
    labels = np.load(labels_path, allow_pickle=False)
    mids = labels["match_ids"]
    dates = labels["dates"]
    oos = {int(mid) for mid, d in zip(mids, dates) if str(d) > dev_end}
    if len(oos) != EXPECTED_OOS_ROWS:
        raise AuditError(f"oos_population_mismatch:{len(oos)}!={EXPECTED_OOS_ROWS}")
    return oos


def matching_prematch_record(provenance: list[dict[str, Any]], requested_max_time: int) -> dict[str, Any]:
    hits = []
    for rec in provenance:
        if not isinstance(rec, dict) or rec.get("endpoint") != "league-matches":
            continue
        params = rec.get("params") or {}
        mt = as_int(params.get("max_time"))
        rmt = as_int(rec.get("requested_max_time"))
        if mt == requested_max_time and rmt == requested_max_time:
            hits.append(rec)
    if len(hits) != 1:
        raise AuditError(f"prematch_league_matches_provenance_count:{len(hits)}")
    return hits[0]


def read_raw_response(digest: str) -> dict[str, Any]:
    path = RAW_DIR / f"{digest}.json.gz"
    if not path.is_file():
        raise AuditError(f"raw_cache_missing:{digest}")
    with gzip.open(path, "rb") as fh:
        raw = fh.read()
    if hashlib.sha256(raw).hexdigest() != digest:
        raise AuditError(f"raw_cache_sha_mismatch:{digest}")
    try:
        obj = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise AuditError(f"raw_json_invalid:{digest}:{type(exc).__name__}") from exc
    if not isinstance(obj, dict) or obj.get("success") is not True:
        raise AuditError(f"raw_response_not_success:{digest}")
    return obj


def find_target(data: Any, match_id: int) -> tuple[dict[str, Any], int]:
    if not isinstance(data, list):
        raise AuditError(f"raw_data_not_list:{match_id}")
    for idx, item in enumerate(data):
        if isinstance(item, dict) and as_int(item.get("id")) == match_id:
            return item, idx
    raise AuditError(f"target_not_found_in_prematch_raw:{match_id}")


def projected_prematch(match_id: int) -> dict[str, Any]:
    path = COLLECTOR_ROOT / "matches" / str(match_id) / f"{match_id}_MatchDaten.json"
    if not path.is_file():
        raise AuditError(f"matchdaten_missing:{match_id}")
    obj = json.loads(path.read_text(encoding="utf-8"))
    if obj.get("found") is not True:
        raise AuditError(f"matchdaten_target_not_found:{match_id}")
    pre = obj.get("prematch_optional") or {}
    return pre if isinstance(pre, dict) else {}


def run_v31_raw_input_audit() -> dict[str, Any]:
    require_runtime()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if OUTPUT_JSON.is_file():
        existing = json.loads(OUTPUT_JSON.read_text(encoding="utf-8"))
        if (
            existing.get("status") == "COMPLETE"
            and int(existing.get("rows_scanned", -1)) == EXPECTED_ROWS
            and existing.get("source_manifest_sha256") == EXPECTED_MANIFEST_SHA256
        ):
            print("FULL7_V31_RAW_INPUT_AUDIT_REUSE_PASS", flush=True)
            print("FULL7_V31_RAW_INPUT_AUDIT_RESULT=" + json.dumps(existing, ensure_ascii=False, sort_keys=True), flush=True)
            return existing

    oos_ids = load_oos_ids()
    field_stats = {
        legacy: {
            "provider_key": provider,
            "key_present_all": 0,
            "numeric_non_null_all": 0,
            "key_present_oos": 0,
            "numeric_non_null_oos": 0,
            "projection_mismatch_all": 0,
            "projection_mismatch_oos": 0,
            "example_source_paths": [],
        }
        for legacy, provider in FIELDS.items()
    }

    complete_all = 0
    complete_oos = 0
    rows_scanned = 0
    unique_raw_hashes: set[str] = set()
    failure_counts: Counter[str] = Counter()
    source_examples: list[dict[str, Any]] = []

    with CP2_JSONL.open(encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            row = json.loads(line)
            match_id = int(row["match_id"])
            kickoff = int(row["kickoff_unix"])
            requested = int(row["requested_max_time"])
            if requested != kickoff - 1:
                raise AuditError(f"cp2_cutoff_violation:{match_id}")

            provenance = json.loads(row["request_provenance_json"])
            rec = matching_prematch_record(provenance, requested)
            digest = str(rec.get("raw_response_sha256") or "")
            if len(digest) != 64:
                raise AuditError(f"raw_digest_invalid:{match_id}")
            unique_raw_hashes.add(digest)

            raw_obj = read_raw_response(digest)
            target, target_idx = find_target(raw_obj.get("data"), match_id)
            projected = projected_prematch(match_id)

            is_oos = match_id in oos_ids
            complete = True
            for legacy, provider in FIELDS.items():
                stats = field_stats[legacy]
                present = provider in target
                numeric = finite_number(target.get(provider)) if present else None
                if present:
                    stats["key_present_all"] += 1
                    if is_oos:
                        stats["key_present_oos"] += 1
                if numeric is not None:
                    stats["numeric_non_null_all"] += 1
                    if is_oos:
                        stats["numeric_non_null_oos"] += 1
                else:
                    complete = False

                projected_numeric = finite_number(projected.get(provider)) if provider in projected else None
                mismatch = False
                if numeric is None and projected_numeric is not None:
                    mismatch = True
                elif numeric is not None and projected_numeric is None:
                    mismatch = True
                elif numeric is not None and projected_numeric is not None and abs(numeric - projected_numeric) > 1e-12:
                    mismatch = True
                if mismatch:
                    stats["projection_mismatch_all"] += 1
                    if is_oos:
                        stats["projection_mismatch_oos"] += 1

                if present and len(stats["example_source_paths"]) < 3:
                    stats["example_source_paths"].append(
                        f"raw_cache/{digest}.json.gz::data[{target_idx}].{provider}"
                    )

            if complete:
                complete_all += 1
                if is_oos:
                    complete_oos += 1

            if len(source_examples) < 10:
                source_examples.append({
                    "match_id": match_id,
                    "requested_max_time": requested,
                    "endpoint": rec.get("endpoint"),
                    "params": rec.get("params"),
                    "raw_response_sha256": digest,
                    "target_index": target_idx,
                })

            rows_scanned += 1
            if rows_scanned % 500 == 0:
                print(
                    f"FULL7_V31_RAW_SCAN_PROGRESS={rows_scanned}/{EXPECTED_ROWS} "
                    f"complete_all={complete_all} complete_oos={complete_oos}",
                    flush=True,
                )

    if rows_scanned != EXPECTED_ROWS:
        raise AuditError(f"cp2_row_count_mismatch:{rows_scanned}!={EXPECTED_ROWS}")

    for stats in field_stats.values():
        stats["coverage_all"] = stats["numeric_non_null_all"] / EXPECTED_ROWS
        stats["coverage_oos"] = stats["numeric_non_null_oos"] / EXPECTED_OOS_ROWS
        stats["pre_match_valid"] = True
        stats["exact_v3_1_semantics_confirmed"] = True
        stats["source_contract"] = "league-matches?season_id=<sid>&max_time=kickoff-1&max_per_page=1000"
        stats["source_path_template"] = "raw_cache/<raw_response_sha256>.json.gz::data[target_match_id].<provider_key>"

    recovery_possible = complete_all > 0
    same_cohort_oos_possible = complete_oos > 0
    result = {
        "audit": "FULL7_V31_RAW_INPUT_RECOVERY_AUDIT_1.0",
        "status": "COMPLETE",
        "created_at_utc": utcnow(),
        "rows_scanned": rows_scanned,
        "oos_rows": len(oos_ids),
        "unique_prematch_raw_hashes_scanned": len(unique_raw_hashes),
        "source_manifest_sha256": EXPECTED_MANIFEST_SHA256,
        "source_inventory_sha256": EXPECTED_INVENTORY_SHA256,
        "strict_cutoff_contract": "requested_max_time == kickoff_unix - 1",
        "fields": field_stats,
        "complete_v31_base_rows_all": complete_all,
        "complete_v31_base_rows_oos": complete_oos,
        "V3_1_RAW_RECOVERY": "POSSIBLE" if recovery_possible else "NOT_POSSIBLE",
        "V3_1_SAME_COHORT_OOS_RECOVERY": "POSSIBLE" if same_cohort_oos_possible else "NOT_POSSIBLE",
        "collector_projection_mismatch_total": sum(v["projection_mismatch_all"] for v in field_stats.values()),
        "examples": source_examples,
        "failure_counts": dict(failure_counts),
        "collection_performed": False,
        "api_calls_performed": False,
        "training_performed": False,
        "calibration_changed": False,
        "rc_changed": False,
        "main_changed": False,
        "production_changed": False,
    }

    atomic_json(OUTPUT_JSON, result)
    lines = [
        "FULL-7 V3.1 RAW INPUT RECOVERY AUDIT",
        f"STATUS={result['status']}",
        f"ROWS_SCANNED={rows_scanned}",
        f"OOS_ROWS={len(oos_ids)}",
        f"UNIQUE_PREMATCH_RAW_HASHES={len(unique_raw_hashes)}",
        f"COMPLETE_V31_BASE_ROWS_ALL={complete_all}",
        f"COMPLETE_V31_BASE_ROWS_OOS={complete_oos}",
        f"V3_1_RAW_RECOVERY={result['V3_1_RAW_RECOVERY']}",
        f"V3_1_SAME_COHORT_OOS_RECOVERY={result['V3_1_SAME_COHORT_OOS_RECOVERY']}",
        f"COLLECTOR_PROJECTION_MISMATCH_TOTAL={result['collector_projection_mismatch_total']}",
        "",
        "FIELD COVERAGE",
    ]
    for legacy, stats in field_stats.items():
        lines.append(
            f"{legacy} <- {stats['provider_key']}: "
            f"all={stats['numeric_non_null_all']}/{EXPECTED_ROWS} "
            f"oos={stats['numeric_non_null_oos']}/{EXPECTED_OOS_ROWS} "
            f"projection_mismatch={stats['projection_mismatch_all']}"
        )
    lines += [
        "",
        "NO COLLECTION / NO API / NO TRAINING / NO CALIBRATION CHANGE / NO RC CHANGE / NO MAIN / NO PRODUCTION",
    ]
    OUTPUT_TXT.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("FULL7_V31_RAW_INPUT_AUDIT_COMPLETE", flush=True)
    print("FULL7_V31_RAW_INPUT_AUDIT_RESULT=" + json.dumps(result, ensure_ascii=False, sort_keys=True), flush=True)
    return result


if __name__ == "__main__":
    run_v31_raw_input_audit()
