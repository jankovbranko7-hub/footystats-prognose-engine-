#!/usr/bin/env python3
"""Offline-only orchestrator for FULL-7 Phase 2 and Phase 3.

The runner blocks network sockets, fingerprints protected collection inputs
before and after execution, and starts Phase 3 only after a persisted CP2 PASS.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
from contextlib import contextmanager
from datetime import datetime, timezone
from itertools import zip_longest
from pathlib import Path
from unittest.mock import patch

from research.full7_feature_audit import run_feature_audit
from research.full7_master_dataset import build_master_dataset, derive_population


class OfflineExecutionError(RuntimeError):
    """Raised when the offline phase gate or mutation guard fails."""


PROTECTED_DIRECTORIES = ("raw_cache", "matches", "quarantine")
PROTECTED_FILES = (
    "done_ids.txt",
    "state.json",
    "progress.jsonl",
    "raw_cache_index.jsonl",
    "raw_cache_index.jsonl.sqlite3",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _network_disabled(*_args, **_kwargs):
    raise OfflineExecutionError("network_disabled_for_full7_phase2_phase3")


@contextmanager
def block_network():
    """Prevent accidental API, HTTP, or arbitrary socket connections."""
    with patch("socket.create_connection", _network_disabled), patch.object(
        socket.socket, "connect", _network_disabled
    ), patch.object(socket.socket, "connect_ex", _network_disabled):
        yield


def _protected_paths(root: Path):
    root = Path(root)
    for name in PROTECTED_FILES:
        path = root / name
        if path.is_file():
            yield path
    for name in PROTECTED_DIRECTORIES:
        directory = root / name
        if directory.is_dir():
            for path in sorted(candidate for candidate in directory.rglob("*") if candidate.is_file()):
                yield path


def write_protected_manifest(root: Path, output_path: Path) -> dict[str, object]:
    """Write a content-hash manifest for every protected collection object."""
    root, output_path = Path(root), Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + ".tmp")
    count = 0
    total_bytes = 0
    manifest_digest = hashlib.sha256()
    with temporary.open("w", encoding="utf-8") as handle:
        for path in _protected_paths(root):
            relative = path.relative_to(root).as_posix()
            size = path.stat().st_size
            digest = _sha256(path)
            line = f"{relative}\t{size}\t{digest}\n"
            handle.write(line)
            manifest_digest.update(line.encode("utf-8"))
            count += 1
            total_bytes += size
    temporary.replace(output_path)
    return {
        "file_count": count,
        "total_bytes": total_bytes,
        "manifest_sha256": manifest_digest.hexdigest(),
        "manifest_file": output_path.name,
    }


def compare_manifest_files(before: Path, after: Path) -> dict[str, object]:
    """Stream-compare two sorted manifests without loading them into memory."""
    differences = 0
    examples = []
    with Path(before).open(encoding="utf-8") as left, Path(after).open(encoding="utf-8") as right:
        for line_number, (left_line, right_line) in enumerate(zip_longest(left, right), 1):
            if left_line != right_line:
                differences += 1
                if len(examples) < 20:
                    examples.append(
                        {
                            "line": line_number,
                            "before": left_line.rstrip("\n") if left_line else None,
                            "after": right_line.rstrip("\n") if right_line else None,
                        }
                    )
    return {"equal": differences == 0, "differences": differences, "examples": examples}


def _read_hold_ids(path: Path) -> set[int]:
    values = []
    for token in Path(path).read_text(encoding="utf-8").split():
        try:
            values.append(int(token))
        except ValueError as exc:
            raise OfflineExecutionError(f"invalid_hold_id:{token}") from exc
    if len(values) != len(set(values)):
        raise OfflineExecutionError("duplicate_hold_id")
    return set(values)


def _write_json_atomic(path: Path, value: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def execute_phase2_phase3(
    *,
    root: Path,
    cp1_path: Path,
    hold_ids_path: Path,
    output_root: Path,
    expected_target_total: int = 17_685,
    expected_collector_strict: int = 16_267,
    expected_quarantine_total: int = 1_418,
    expected_hold_total: int = 130,
    expected_eligible_total: int = 16_137,
    correlation_min_overlap: int = 100,
) -> dict[str, object]:
    """Execute the two phases with an integrity barrier around collection data."""
    root, cp1_path = Path(root), Path(cp1_path)
    hold_ids_path, output_root = Path(hold_ids_path), Path(output_root)
    if output_root.exists():
        raise OfflineExecutionError(f"output_root_already_exists:{output_root}")
    output_root.mkdir(parents=True)
    lock_path = output_root / ".phase2_phase3.lock"
    try:
        descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise OfflineExecutionError("execution_lock_exists") from exc
    os.write(descriptor, str(os.getpid()).encode("ascii"))
    os.close(descriptor)

    pre_manifest = output_root / "PROTECTED_COLLECTION_BEFORE.tsv"
    post_manifest = output_root / "PROTECTED_COLLECTION_AFTER.tsv"
    result: dict[str, object] = {
        "execution": "FULL7_PHASE2_PHASE3_OFFLINE_1.0",
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "RUNNING",
        "api_calls_performed": False,
        "collection_performed": False,
        "source_mutation_detected": None,
        "cp2_gate": None,
        "cp3_gate": None,
    }
    pending_error: Exception | None = None
    try:
        result["protected_before"] = write_protected_manifest(root, pre_manifest)
        with block_network():
            population = derive_population(
                root,
                _read_hold_ids(hold_ids_path),
                cp1_path,
                expected_target_total=expected_target_total,
                expected_collector_strict=expected_collector_strict,
                expected_quarantine_total=expected_quarantine_total,
                expected_hold_total=expected_hold_total,
                expected_eligible_total=expected_eligible_total,
            )
            cp2 = build_master_dataset(root, output_root / "cp2", population)
            result["cp2_gate"] = cp2.get("gate")
            result["cp2_checkpoint"] = cp2
            if cp2.get("gate") != "PASS":
                raise OfflineExecutionError("cp2_gate_not_pass")
            cp3 = run_feature_audit(
                output_root / "cp2",
                output_root / "cp3",
                correlation_min_overlap=correlation_min_overlap,
            )
            result["cp3_gate"] = cp3.get("gate")
            result["cp3_checkpoint"] = cp3
            if cp3.get("gate") != "PASS":
                raise OfflineExecutionError("cp3_gate_not_pass")
        result["status"] = "COMPLETE"
    except Exception as exc:
        pending_error = exc
        result["status"] = "BLOCKED"
        result["error"] = {"type": type(exc).__name__, "message": str(exc)}
    finally:
        result["protected_after"] = write_protected_manifest(root, post_manifest)
        integrity = compare_manifest_files(pre_manifest, post_manifest)
        result["protected_collection_integrity"] = integrity
        result["source_mutation_detected"] = not integrity["equal"]
        if not integrity["equal"]:
            result["status"] = "BLOCKED"
            mutation_error = OfflineExecutionError("protected_collection_mutation_detected")
            result["error"] = {
                "type": type(mutation_error).__name__,
                "message": str(mutation_error),
            }
            if pending_error is None:
                pending_error = mutation_error
        result["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
        _write_json_atomic(output_root / "FULL7_PHASE2_PHASE3_EXECUTION.json", result)
        if lock_path.is_file() and lock_path.parent == output_root:
            lock_path.unlink()
    if pending_error is not None:
        raise pending_error
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/var/data/full7/output")
    parser.add_argument(
        "--cp1",
        default="artifacts/full7_cp1_2026-09-22/CP1_STRICT_DATASET.json",
    )
    parser.add_argument(
        "--hold-ids",
        default="artifacts/full7_cp1_2026-09-22/LEAGUE_TARGET_GAP_MATCH_IDS.txt",
    )
    parser.add_argument(
        "--output-root",
        default="/var/data/full7/derived/full7_phase2_phase3_2026-09-22",
    )
    args = parser.parse_args()
    result = execute_phase2_phase3(
        root=Path(args.root),
        cp1_path=Path(args.cp1),
        hold_ids_path=Path(args.hold_ids),
        output_root=Path(args.output_root),
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
