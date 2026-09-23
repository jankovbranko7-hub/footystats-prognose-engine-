#!/usr/bin/env python3
"""Read-only recovery probe for the FULL-7 raw backup.

This module never calls FootyStats, never mutates collection data, and never
rebuilds CP1-CP7. It verifies the frozen 2026-09-21 source snapshot and searches
the Render persistent disk for the original encrypted backup parts / part lists.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

DATA_ROOT = Path("/var/data/full7")
SEARCH_ROOT = Path("/var/data")
SOURCE_MANIFEST = DATA_ROOT / "FULL7_BACKUP_SHA256_MANIFEST.tsv"
SOURCE_INVENTORY = DATA_ROOT / "FULL7_BACKUP_INVENTORY.json"

EXPECTED_MANIFEST_SHA256 = "86c05accd2f1cb56e5afed13057b5dbb2e857e847b5dd75d927863e7879999d6"
EXPECTED_INVENTORY_SHA256 = "ebe438fbacf2d35315bd2ed7d80dac2ed44468e0e3ada9d1d98ead066b91a304"
EXPECTED_MANIFEST_ENTRIES = 217258
EXPECTED_MANIFEST_ENTRY_BYTES = 10993329748
EXPECTED_SOURCE_FILE_COUNT = 217260
EXPECTED_SOURCE_TOTAL_BYTES = 11023029301

EXPECTED_PARTS = {
    "part-0000.tar.enc": (815360032, "c41210c9ddaa0038a2297b92b84b49c3cfe44b9c07ee77aa9acd3ff3cf2deb54"),
    "part-0001.tar.enc": (817561632, "dd27636ce8cbafc43af0232539ef1d836a8cc4befcd951d2ef08943835cf3b44"),
    "part-0002.tar.enc": (817387552, "dda7b0e5494d407e94b255617a414d13311523b0d76e2e89755efa553235f7e1"),
    "part-0003.tar.enc": (817612832, "72c9967e4885829b25a93c3017342d55a9bfd0ab098e058f0fe43676fabe9191"),
    "part-0004.tar.enc": (817356832, "9138ab65c2a49e371c0445f75fd4748667065de2b61b5cb5dd74bec6c7072c56"),
    "part-0005.tar.enc": (817704992, "c0a67bf05e9e49031b0cfb452ebc3c67c72d0e05a9e2e5ffb3095ce60c8a3a71"),
    "part-0006.tar.enc": (817684512, "5bac8b875c680e53f50143db8b6969cb9e97620ab73d9f8527a85349d8af05d7"),
    "part-0007.tar.enc": (818851872, "a12000b7f446761b7a9541ff4404ab1ddfd1f553067d2d9f043c6b8c9cb44e61"),
    "part-0008.tar.enc": (817489952, "3bdd172e7d76bd123c4fa2f7175e9fef1a9b6b4191ee587c720bdd5fc16d89ff"),
    "part-0009.tar.enc": (817448992, "2c6e08b3a214e266074e1b7db8ee7b647328adab7d9f76c4073a833674e36376"),
    "part-0010.tar.enc": (817664032, "89f5aed7285ce01658028cfa0092bdce15c7d849c0b78afd66d7cb98966d07f3"),
    "part-0011.tar.enc": (817766432, "eff0bb754d69fbdac5abaad2c9a1695c651481c1cab40e50c5e5a4a4e9b75b54"),
    "part-0012.tar.enc": (817582112, "ec5708d58736e93fdaf950d67df08c9a0148f3a9125bc6cadef217a7eb7477a2"),
    "part-0013.tar.enc": (563517472, "0539966b903f1753894184bc9c621890571729b839f22b13e4da69d055608b8e"),
}


class RecoveryProbeError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(4 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _require_authorized_runtime() -> None:
    if os.environ.get("RENDER_SERVICE_ID") != "srv-damiu0p42hec739a0rig":
        raise RecoveryProbeError("wrong_render_service")
    if os.environ.get("RENDER_GIT_BRANCH") != "audit/full7-cp2-20260922":
        raise RecoveryProbeError("wrong_git_branch")
    if os.environ.get("RUN_FULL7_BACKUP_RECOVERY_ONESHOT", "false").strip().lower() != "true":
        raise RecoveryProbeError("recovery_flag_not_enabled")


def _verify_frozen_source() -> dict[str, Any]:
    if not DATA_ROOT.is_dir():
        raise RecoveryProbeError("missing_data_root:/var/data/full7")
    if not SOURCE_MANIFEST.is_file():
        raise RecoveryProbeError("missing_source_manifest")
    if not SOURCE_INVENTORY.is_file():
        raise RecoveryProbeError("missing_source_inventory")

    manifest_sha = _sha256(SOURCE_MANIFEST)
    inventory_sha = _sha256(SOURCE_INVENTORY)
    if manifest_sha != EXPECTED_MANIFEST_SHA256:
        raise RecoveryProbeError(f"source_manifest_sha_mismatch:{manifest_sha}")
    if inventory_sha != EXPECTED_INVENTORY_SHA256:
        raise RecoveryProbeError(f"source_inventory_sha_mismatch:{inventory_sha}")

    count = 0
    total_bytes = 0
    missing: list[str] = []
    size_bad: list[str] = []
    sha_bad: list[str] = []

    with SOURCE_MANIFEST.open("r", encoding="utf-8") as fh:
        header = fh.readline().rstrip("\n")
        if header != "sha256\tsize_bytes\trelative_path":
            raise RecoveryProbeError("unexpected_manifest_header")
        for line in fh:
            line = line.rstrip("\n")
            if not line:
                continue
            expected_sha, size_text, rel = line.split("\t", 2)
            expected_size = int(size_text)
            path = DATA_ROOT / rel
            count += 1
            total_bytes += expected_size
            if not path.is_file():
                if len(missing) < 20:
                    missing.append(rel)
                continue
            actual_size = path.stat().st_size
            if actual_size != expected_size:
                if len(size_bad) < 20:
                    size_bad.append(rel)
                continue
            actual_sha = _sha256(path)
            if actual_sha != expected_sha and len(sha_bad) < 20:
                sha_bad.append(rel)
            if count % 10000 == 0:
                print(
                    "FULL7_RECOVERY_SOURCE_PROGRESS="
                    + json.dumps({"checked": count, "manifest_entries": EXPECTED_MANIFEST_ENTRIES}),
                    flush=True,
                )

    if count != EXPECTED_MANIFEST_ENTRIES:
        raise RecoveryProbeError(f"manifest_entry_count_mismatch:{count}")
    if total_bytes != EXPECTED_MANIFEST_ENTRY_BYTES:
        raise RecoveryProbeError(f"manifest_entry_bytes_mismatch:{total_bytes}")
    if missing or size_bad or sha_bad:
        raise RecoveryProbeError(
            "frozen_source_integrity_failed:"
            + json.dumps(
                {"missing": missing, "size_bad": size_bad, "sha_bad": sha_bad},
                sort_keys=True,
            )
        )

    all_snapshot_bytes = (
        EXPECTED_MANIFEST_ENTRY_BYTES
        + SOURCE_MANIFEST.stat().st_size
        + SOURCE_INVENTORY.stat().st_size
    )
    if all_snapshot_bytes != EXPECTED_SOURCE_TOTAL_BYTES:
        raise RecoveryProbeError(f"source_total_bytes_mismatch:{all_snapshot_bytes}")

    return {
        "status": "PASS",
        "manifest_entries": count,
        "manifest_entry_bytes": total_bytes,
        "source_file_count": EXPECTED_SOURCE_FILE_COUNT,
        "source_total_bytes": all_snapshot_bytes,
        "manifest_sha256": manifest_sha,
        "inventory_sha256": inventory_sha,
        "missing": 0,
        "size_bad": 0,
        "sha_bad": 0,
    }


def _search_artifacts() -> dict[str, Any]:
    target_parts = set(EXPECTED_PARTS)
    target_lists = {name.replace(".tar.enc", ".lst") for name in target_parts}
    part_candidates: dict[str, list[str]] = {name: [] for name in sorted(target_parts)}
    list_candidates: dict[str, list[str]] = {name: [] for name in sorted(target_lists)}
    recovery_metadata: list[str] = []

    prune_exact = {
        str(DATA_ROOT / "output" / "matches"),
        str(DATA_ROOT / "output" / "raw_cache"),
        str(DATA_ROOT / "output" / "quarantine"),
        str(DATA_ROOT / "derived"),
    }

    for root, dirs, files in os.walk(SEARCH_ROOT):
        root_path = Path(root)
        root_text = str(root_path)
        if root_text in prune_exact:
            dirs[:] = []
            continue
        for filename in files:
            full = root_path / filename
            if filename in target_parts:
                part_candidates[filename].append(str(full))
            elif filename in target_lists:
                list_candidates[filename].append(str(full))
            elif filename in {
                "FULL7_EXPORT_INDEX.json",
                "FULL7_ENCRYPTED_PARTS_SHA256.json",
                "FULL7_ENCRYPTED_PARTS_CHECKSUMS.json",
                "FULL7_RECOVERY_KEY.txt",
            }:
                recovery_metadata.append(str(full))

    exact_parts: dict[str, str] = {}
    rejected_candidates: dict[str, list[dict[str, Any]]] = {}
    for name, candidates in part_candidates.items():
        expected_size, expected_sha = EXPECTED_PARTS[name]
        for raw in candidates:
            path = Path(raw)
            size = path.stat().st_size
            if size != expected_size:
                rejected_candidates.setdefault(name, []).append(
                    {"path": raw, "bytes": size, "reason": "size"}
                )
                continue
            digest = _sha256(path)
            if digest == expected_sha:
                exact_parts[name] = raw
                break
            rejected_candidates.setdefault(name, []).append(
                {"path": raw, "bytes": size, "sha256": digest, "reason": "sha256"}
            )

    return {
        "exact_original_parts": exact_parts,
        "exact_original_part_count": len(exact_parts),
        "missing_original_parts": sorted(set(target_parts) - set(exact_parts)),
        "part_candidates": {k: v for k, v in part_candidates.items() if v},
        "rejected_candidates": rejected_candidates,
        "part_lists_found": {k: v for k, v in list_candidates.items() if v},
        "part_list_count": sum(bool(v) for v in list_candidates.values()),
        "recovery_metadata_found": sorted(recovery_metadata),
    }


EXPECTED_PART_PLAN = [
    ("part-0000.tar.enc", 13009, 805133453),
    ("part-0001.tar.enc", 15834, 805203710),
    ("part-0002.tar.enc", 15778, 805152728),
    ("part-0003.tar.enc", 15817, 805255444),
    ("part-0004.tar.enc", 15736, 805300103),
    ("part-0005.tar.enc", 15879, 805252045),
    ("part-0006.tar.enc", 16006, 805239493),
    ("part-0007.tar.enc", 18034, 805104188),
    ("part-0008.tar.enc", 15918, 805255219),
    ("part-0009.tar.enc", 15839, 805289919),
    ("part-0010.tar.enc", 16057, 805286239),
    ("part-0011.tar.enc", 16406, 805173012),
    ("part-0012.tar.enc", 15992, 805296642),
    ("part-0013.tar.enc", 10955, 555087106),
]


def _partition_plan_diagnostic() -> dict[str, Any]:
    records: list[tuple[str, int]] = []
    with SOURCE_MANIFEST.open("r", encoding="utf-8") as fh:
        header = fh.readline()
        for line in fh:
            line = line.rstrip("\n")
            if not line:
                continue
            _sha, size_text, rel = line.split("\t", 2)
            records.append((rel, int(size_text)))

    meta = [
        ("FULL7_BACKUP_INVENTORY.json", SOURCE_INVENTORY.stat().st_size),
        ("FULL7_BACKUP_SHA256_MANIFEST.tsv", SOURCE_MANIFEST.stat().st_size),
    ]
    candidates = {
        "SORT_ALL_RELATIVE_PATHS": sorted(records + meta, key=lambda item: item[0]),
        "MANIFEST_ORDER_THEN_META_SORTED": records + sorted(meta),
        "META_SORTED_THEN_MANIFEST_ORDER": sorted(meta) + records,
        "MANIFEST_THEN_INVENTORY_THEN_SHA_MANIFEST": records + meta,
        "SHA_MANIFEST_THEN_INVENTORY_THEN_MANIFEST": [meta[1], meta[0]] + records,
    }

    results: dict[str, Any] = {}
    exact: list[str] = []
    expected_total_count = sum(item[1] for item in EXPECTED_PART_PLAN)
    expected_total_bytes = sum(item[2] for item in EXPECTED_PART_PLAN)
    for name, ordered in candidates.items():
        cursor = 0
        parts = []
        all_match = True
        for part_name, expected_count, expected_bytes in EXPECTED_PART_PLAN:
            group = ordered[cursor : cursor + expected_count]
            actual_count = len(group)
            actual_bytes = sum(size for _rel, size in group)
            match = actual_count == expected_count and actual_bytes == expected_bytes
            all_match = all_match and match
            parts.append(
                {
                    "name": part_name,
                    "expected_count": expected_count,
                    "actual_count": actual_count,
                    "expected_raw_bytes": expected_bytes,
                    "actual_raw_bytes": actual_bytes,
                    "match": match,
                    "first": group[0][0] if group else None,
                    "last": group[-1][0] if group else None,
                }
            )
            cursor += expected_count
        result = {
            "record_count": len(ordered),
            "record_bytes": sum(size for _rel, size in ordered),
            "expected_total_count": expected_total_count,
            "expected_total_bytes": expected_total_bytes,
            "all_parts_match": all_match and cursor == len(ordered),
            "parts": parts,
        }
        results[name] = result
        if result["all_parts_match"]:
            exact.append(name)
    threshold = 805306368  # 768 MiB
    greedy_results: dict[str, Any] = {}
    greedy_exact: list[str] = []
    for name, ordered in candidates.items():
        parts: list[list[tuple[str, int]]] = []
        current: list[tuple[str, int]] = []
        current_bytes = 0
        for item in ordered:
            item_size = item[1]
            if current and current_bytes + item_size > threshold:
                parts.append(current)
                current = []
                current_bytes = 0
            current.append(item)
            current_bytes += item_size
        if current:
            parts.append(current)
        observed = []
        all_match = len(parts) == len(EXPECTED_PART_PLAN)
        for idx, group in enumerate(parts):
            count = len(group)
            raw_bytes = sum(size for _rel, size in group)
            expected_name = EXPECTED_PART_PLAN[idx][0] if idx < len(EXPECTED_PART_PLAN) else None
            expected_count = EXPECTED_PART_PLAN[idx][1] if idx < len(EXPECTED_PART_PLAN) else None
            expected_bytes = EXPECTED_PART_PLAN[idx][2] if idx < len(EXPECTED_PART_PLAN) else None
            match = count == expected_count and raw_bytes == expected_bytes
            if not match:
                all_match = False
            observed.append(
                {
                    "name": expected_name,
                    "count": count,
                    "raw_bytes": raw_bytes,
                    "expected_count": expected_count,
                    "expected_raw_bytes": expected_bytes,
                    "match": match,
                    "first": group[0][0] if group else None,
                    "last": group[-1][0] if group else None,
                }
            )
        greedy_results[name] = {
            "threshold_bytes": threshold,
            "part_count": len(parts),
            "all_parts_match": all_match,
            "parts": observed,
        }
        if all_match:
            greedy_exact.append(name)

    return {
        "exact_order_candidates": exact,
        "candidates": results,
        "greedy_threshold_bytes": threshold,
        "greedy_exact_order_candidates": greedy_exact,
        "greedy_candidates": greedy_results,
    }


def run_backup_recovery_probe() -> dict[str, Any]:
    _require_authorized_runtime()
    print("FULL7_BACKUP_RECOVERY_MODE=READ_ONLY_PROBE", flush=True)
    source = _verify_frozen_source()
    print("FULL7_BACKUP_RECOVERY_SOURCE=" + json.dumps(source, sort_keys=True), flush=True)
    artifacts = _search_artifacts()
    print("FULL7_BACKUP_RECOVERY_ARTIFACTS=" + json.dumps(artifacts, sort_keys=True), flush=True)
    partition_plan = _partition_plan_diagnostic()
    print("FULL7_BACKUP_RECOVERY_PARTITION_PLAN=" + json.dumps(partition_plan, sort_keys=True), flush=True)
    status = (
        "ORIGINAL_PARTS_FOUND_ALL"
        if artifacts["exact_original_part_count"] == 14
        else "SOURCE_VERIFIED_ORIGINAL_PARTS_NOT_ALL_FOUND"
    )
    receipt = {
        "status": status,
        "source": source,
        "artifacts": artifacts,
        "partition_plan": partition_plan,
        "collection_performed": False,
        "api_calls_performed": False,
        "cp1_cp7_reexecuted": False,
        "main_changed": False,
        "production_changed": False,
    }
    print("FULL7_BACKUP_RECOVERY_RECEIPT=" + json.dumps(receipt, sort_keys=True), flush=True)
    return receipt


def main() -> None:
    run_backup_recovery_probe()


if __name__ == "__main__":
    main()
