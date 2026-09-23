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
from research.full7_feature_audit_bounded import run_bounded_feature_audit
from research.full7_master_dataset import (
    build_master_dataset,
    derive_population,
    resume_master_dataset_from_stage,
)


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
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        uncommented = line.split("#", 1)[0]
        for token in uncommented.split():
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


def _next_available_path(path: Path) -> Path:
    path = Path(path)
    if not path.exists():
        return path
    for index in range(1, 1000):
        candidate = path.with_name(f"{path.name}.{index}")
        if not candidate.exists():
            return candidate
    raise OfflineExecutionError(f"no_available_preservation_path:{path}")



def inspect_existing_output(output_root: Path) -> dict[str, object]:
    """Read-only inventory of an interrupted/finished offline output root."""
    output_root = Path(output_root)
    if not output_root.is_dir():
        raise OfflineExecutionError(f"existing_output_not_directory:{output_root}")

    entries: list[dict[str, object]] = []
    checkpoint_payloads: dict[str, object] = {}
    for path in sorted(output_root.rglob("*")):
        relative = path.relative_to(output_root).as_posix()
        stat = path.stat()
        if path.is_dir():
            entries.append(
                {
                    "path": relative,
                    "kind": "directory",
                    "mtime_ns": stat.st_mtime_ns,
                }
            )
            continue
        item = {
            "path": relative,
            "kind": "file",
            "bytes": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
            "sha256": _sha256(path),
        }
        entries.append(item)
        if path.name in {
            "CP2_MASTER_DATASET.json",
            "CP2_MASTER_DATASET_AUDIT.json",
            "FULL7_MASTER_BUILD_MANIFEST.json",
            "CP3_FEATURE_AUDIT.json",
            "FULL7_FEATURE_AUDIT_MANIFEST.json",
            "FULL7_PHASE2_PHASE3_EXECUTION.json",
        }:
            try:
                checkpoint_payloads[relative] = json.loads(path.read_text(encoding="utf-8"))
            except Exception as exc:
                checkpoint_payloads[relative] = {
                    "parse_error": f"{type(exc).__name__}:{exc}"
                }

    names = {entry["path"] for entry in entries}
    stage_dirs = sorted(
        entry["path"]
        for entry in entries
        if entry["kind"] == "directory"
        and any(part.startswith(".cp2.stage-") or part.startswith(".cp3.stage-") for part in str(entry["path"]).split("/"))
    )
    cp2_published = "cp2" in names and "cp2/CP2_MASTER_DATASET.json" in names
    cp3_published = "cp3" in names and "cp3/CP3_FEATURE_AUDIT.json" in names

    return {
        "inspection": "FULL7_EXISTING_OUTPUT_READ_ONLY_1.0",
        "inspected_at_utc": datetime.now(timezone.utc).isoformat(),
        "output_root": str(output_root),
        "entry_count": len(entries),
        "cp2_published_checkpoint_present": cp2_published,
        "cp3_published_checkpoint_present": cp3_published,
        "stage_directories": stage_dirs,
        "checkpoint_payloads": checkpoint_payloads,
        "entries": entries,
        "mutation_performed": False,
        "api_calls_performed": False,
        "collection_performed": False,
    }


def resume_existing_phase2_phase3(
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
    """Phase-3-only resume from the frozen passing CP2 checkpoint.

    CP2 is never rebuilt here. The raw collection population is not re-derived.
    """
    root, output_root = Path(root), Path(output_root)
    if not output_root.is_dir():
        raise OfflineExecutionError(f"resume_output_root_missing:{output_root}")

    resume_lock = output_root / ".phase3_only.resume.lock"
    if resume_lock.exists():
        preserved_lock = _next_available_path(
            output_root / ".phase3_only.resume.lock.interrupted"
        )
        resume_lock.rename(preserved_lock)
    descriptor = os.open(resume_lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.write(descriptor, str(os.getpid()).encode("ascii"))
    os.close(descriptor)

    original_before = output_root / "PROTECTED_COLLECTION_BEFORE.tsv"
    resume_after = _next_available_path(
        output_root / "PROTECTED_COLLECTION_PHASE3_AFTER.tsv"
    )
    if not original_before.is_file():
        raise OfflineExecutionError("phase3_original_protected_manifest_missing")

    result: dict[str, object] = {
        "execution": "FULL7_PHASE3_ONLY_OFFLINE_RESUME_1.0",
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "RUNNING",
        "api_calls_performed": False,
        "collection_performed": False,
        "cp2_rebuilt": False,
        "source_mutation_detected": None,
        "cp2_gate": None,
        "cp3_gate": None,
    }
    pending_error: Exception | None = None
    try:
        with block_network():
            cp2_dir = output_root / "cp2"
            cp2_checkpoint_path = cp2_dir / "CP2_MASTER_DATASET.json"
            if not cp2_checkpoint_path.is_file():
                raise OfflineExecutionError("frozen_cp2_checkpoint_missing")
            cp2 = json.loads(cp2_checkpoint_path.read_text(encoding="utf-8"))
            if (
                cp2.get("checkpoint") != "CP2_MASTER_DATASET"
                or cp2.get("gate") != "PASS"
                or int(cp2.get("match_count_valid", -1)) != expected_eligible_total
            ):
                raise OfflineExecutionError("frozen_cp2_checkpoint_not_pass")
            print("RESUME_CP2_REUSE_PASS", flush=True)
            result["cp2_gate"] = "PASS"
            result["cp2_checkpoint"] = {
                "checkpoint": cp2.get("checkpoint"),
                "gate": cp2.get("gate"),
                "dataset_version": cp2.get("dataset_version"),
                "match_count_valid": cp2.get("match_count_valid"),
                "eligible_id_sha256": cp2.get("eligible_id_sha256"),
                "reused_frozen": True,
                "rebuilt": False,
            }

            cp3_dir = output_root / "cp3"
            cp3_checkpoint_path = cp3_dir / "CP3_FEATURE_AUDIT.json"
            if cp3_checkpoint_path.is_file():
                cp3 = json.loads(cp3_checkpoint_path.read_text(encoding="utf-8"))
                if cp3.get("gate") != "PASS" or int(
                    cp3.get("match_count_valid", -1)
                ) != expected_eligible_total:
                    raise OfflineExecutionError("existing_cp3_checkpoint_not_pass")
                print("RESUME_CP3_REUSE_PASS", flush=True)
            else:
                cp3_stages = sorted(output_root.glob(".cp3.stage-*"))
                if len(cp3_stages) > 1:
                    raise OfflineExecutionError(
                        "phase3_stage_count_gt_one:"
                        + ",".join(path.name for path in cp3_stages)
                    )
                existing_stage = cp3_stages[0] if cp3_stages else None
                if existing_stage is not None:
                    print(f"RESUME_CP3_STAGE={existing_stage.name}", flush=True)
                else:
                    print("RESUME_CP3_NEW_BOUNDED_STAGE", flush=True)
                print("RESUME_CP3_BOUNDED_START", flush=True)
                cp3 = run_bounded_feature_audit(
                    cp2_dir,
                    cp3_dir,
                    existing_stage=existing_stage,
                    correlation_min_overlap=correlation_min_overlap,
                )
                print("RESUME_CP3_PASS", flush=True)

            result["cp3_gate"] = cp3.get("gate")
            result["cp3_checkpoint"] = cp3
            if cp3.get("gate") != "PASS":
                raise OfflineExecutionError("phase3_gate_not_pass")
            result["status"] = "COMPLETE"
    except Exception as exc:
        pending_error = exc
        result["status"] = "BLOCKED"
        result["error"] = {"type": type(exc).__name__, "message": str(exc)}
    finally:
        result["protected_after"] = write_protected_manifest(root, resume_after)
        integrity = compare_manifest_files(original_before, resume_after)
        result["protected_collection_integrity"] = integrity
        result["source_mutation_detected"] = not integrity["equal"]
        if not integrity["equal"]:
            result["status"] = "BLOCKED"
            mutation_error = OfflineExecutionError(
                "protected_collection_mutation_detected_on_phase3_resume"
            )
            result["error"] = {
                "type": type(mutation_error).__name__,
                "message": str(mutation_error),
            }
            if pending_error is None:
                pending_error = mutation_error
        result["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
        execution_path = _next_available_path(
            output_root / "FULL7_PHASE3_EXECUTION_RESUME.json"
        )
        _write_json_atomic(execution_path, result)
        if resume_lock.is_file() and resume_lock.parent == output_root:
            resume_lock.unlink()
    if pending_error is not None:
        raise pending_error
    return result


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


def _phase7_worker_authorized(*, service_id: str | None, branch: str | None, enabled: str) -> bool:
    return (
        service_id == "srv-damiu0p42hec739a0rig"
        and branch
        in {"audit/full7-cp2-20260922", "release/full7-final-rc-1.0.0"}
        and enabled.strip().lower() == "true"
    )


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
    output_root = Path(args.output_root)

    # Authorized read-only V3.1 raw-input recovery audit. This dispatcher runs
    # before backup/research paths and is hard-bound to the existing audit worker.
    v31_raw_audit_authorized = (
        os.environ.get("RENDER_SERVICE_ID") == "srv-damiu0p42hec739a0rig"
        and os.environ.get("RENDER_GIT_BRANCH") == "audit/full7-cp2-20260922"
        and os.environ.get("RUN_FULL7_V31_RAW_INPUT_AUDIT", "false").strip().lower() == "true"
    )
    if v31_raw_audit_authorized:
        from research.run_full7_v31_raw_input_audit import run_v31_raw_input_audit
        receipt = run_v31_raw_input_audit()
        print("FULL7_V31_RAW_INPUT_AUDIT_EXIT=0", flush=True)
        print(json.dumps(receipt, ensure_ascii=False, sort_keys=True), flush=True)
        return

    # Authorized streaming recovery export. Read-only on the frozen FULL-7 source;
    # it serves independently encrypted tar parts without entering collection or CP1-CP7.
    backup_stream_authorized = (
        os.environ.get("RENDER_SERVICE_ID") == "srv-damiu0p42hec739a0rig"
        and os.environ.get("RENDER_GIT_BRANCH") == "audit/full7-cp2-20260922"
        and os.environ.get("RUN_FULL7_BACKUP_STREAM_SERVER", "false").strip().lower() == "true"
    )
    if backup_stream_authorized:
        from research.run_full7_backup_stream_server import run_stream_server
        run_stream_server()
        return

    # Authorized one-shot FULL-7 raw-backup recovery probe. This path is read-only,
    # hard-bound to the existing audit worker/branch, and runs before every legacy
    # CP/model path so no collection or research phase can be entered accidentally.
    backup_recovery_authorized = (
        os.environ.get("RENDER_SERVICE_ID") == "srv-damiu0p42hec739a0rig"
        and os.environ.get("RENDER_GIT_BRANCH") == "audit/full7-cp2-20260922"
        and os.environ.get("RUN_FULL7_BACKUP_RECOVERY_ONESHOT", "false").strip().lower() == "true"
    )
    if backup_recovery_authorized:
        from research.run_full7_backup_recovery import run_backup_recovery_probe
        recovery_receipt = run_backup_recovery_probe()
        print("FULL7_BACKUP_RECOVERY_EXIT=0", flush=True)
        print(json.dumps(recovery_receipt, ensure_ascii=False, sort_keys=True), flush=True)
        return

    # Authorized one-shot Phase-6 audit dispatcher. It is hard-bound to the
    # existing audit worker + audit branch and executes BEFORE every legacy path.
    phase6_worker = (
        os.environ.get("RENDER_SERVICE_ID") == "srv-damiu0p42hec739a0rig"
        and os.environ.get("RENDER_GIT_BRANCH") == "audit/full7-cp2-20260922"
    )
    phase7_authorized = _phase7_worker_authorized(
        service_id=os.environ.get("RENDER_SERVICE_ID"),
        branch=os.environ.get("RENDER_GIT_BRANCH"),
        enabled=os.environ.get("RUN_FULL7_PHASE7_ONESHOT", "false"),
    )
    if phase7_authorized:
        from research.run_full7_phase7_only import run_phase7_only
        phase7_receipt = run_phase7_only(output_root)
        print("FULL7_PHASE7_ONLY_EXIT=0", flush=True)
        print(json.dumps(phase7_receipt, ensure_ascii=False, sort_keys=True), flush=True)
        return
    if phase6_worker:
        from research.run_full7_phase6_only import run_phase6_only
        phase6_receipt = run_phase6_only(output_root)
        print("FULL7_PHASE6_ONLY_EXIT=0", flush=True)
        print(json.dumps(phase6_receipt, ensure_ascii=False, sort_keys=True), flush=True)
        return

    # Post-CP3 rule: once the frozen CP3 checkpoint is COMPLETE/PASS for 16,137
    # rows, never re-enter CP1/CP2/CP3. Go directly to Phase 4 research.
    cp3_checkpoint_path = output_root / "cp3" / "CP3_FEATURE_AUDIT.json"
    if cp3_checkpoint_path.is_file():
        cp3 = json.loads(cp3_checkpoint_path.read_text(encoding="utf-8"))
        if (
            cp3.get("checkpoint") == "CP3_FEATURE_AUDIT"
            and cp3.get("gate") == "PASS"
            and cp3.get("status") == "COMPLETE"
            and int(cp3.get("match_count_valid", -1)) == 16137
        ):
            print("CP3_FROZEN_REUSE_PASS", flush=True)
            from research.full7_phase4_continue import run_phase4_continue_offline
            phase4 = run_phase4_continue_offline(
                output_root / "cp2",
                output_root / "cp3",
                output_root / "phase4",
            )
            phase4_dir = output_root / "phase4"
            manifest_path = phase4_dir / "PHASE4_MANIFEST.json"
            print(
                json.dumps(
                    {
                        "PHASE4_MODEL_RESEARCH": phase4.get("PHASE4_MODEL_RESEARCH"),
                        "status": phase4.get("status"),
                        "manifest_sha256": _sha256(manifest_path) if manifest_path.is_file() else None,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                flush=True,
            )

            # Readout-only receipt for the already frozen Phase-4 artifacts.
            # This performs no fitting, mutation, collection or CP2/CP3 work.
            if phase4.get("PHASE4_MODEL_RESEARCH") == "PASS":
                from collections import Counter
                ablation = json.loads((phase4_dir / "PHASE4_GROUP_ABLATIONS_DEVELOPMENT.json").read_text(encoding="utf-8"))
                dev_models = json.loads((phase4_dir / "PHASE4_DEVELOPMENT_MODEL_COMPARISON.json").read_text(encoding="utf-8"))
                selection = json.loads((phase4_dir / "PHASE4_FEATURE_SELECTION.json").read_text(encoding="utf-8"))
                freeze = json.loads((phase4_dir / "PHASE4_PHASE5_FREEZE.json").read_text(encoding="utf-8"))
                coverage = json.loads((phase4_dir / "PHASE4_V3_COVERAGE_DIAGNOSTIC_V2.json").read_text(encoding="utf-8"))
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

                group_summary = {}
                for target, target_obj in ablation.get("targets", {}).items():
                    group_summary[target] = {
                        "locked_feature_count": target_obj.get("locked_feature_count"),
                        "supported_groups": target_obj.get("supported_groups"),
                        "groups": {
                            group: {
                                "development_support": info.get("development_support"),
                                "feature_count": info.get("feature_count"),
                                "aggregate_logloss_deterioration_when_removed": info.get("aggregate_logloss_deterioration_when_removed"),
                                "aggregate_brier_deterioration_when_removed": info.get("aggregate_brier_deterioration_when_removed"),
                                "positive_logloss_segments": info.get("positive_logloss_segments"),
                            }
                            for group, info in target_obj.get("groups", {}).items()
                        },
                    }
                print("PHASE4_GROUP_SUMMARY=" + json.dumps(group_summary, ensure_ascii=False, sort_keys=True), flush=True)

                model_summary = {}
                for target, target_obj in dev_models.get("targets", {}).items():
                    model_summary[target] = {
                        "selected_for_oos": target_obj.get("selected_for_oos"),
                        "development_rank": target_obj.get("development_rank"),
                        "locked_feature_count": target_obj.get("locked_feature_count"),
                        "variants": {
                            name: {
                                "metrics": info.get("metrics"),
                                "folds": info.get("folds"),
                            }
                            for name, info in target_obj.get("variants", {}).items()
                        },
                    }
                print("PHASE4_DEV_MODEL_SUMMARY=" + json.dumps(model_summary, ensure_ascii=False, sort_keys=True), flush=True)

                excluded_reason_counts = Counter()
                excluded_group_counts = Counter()
                for row in selection.get("excluded_features", []):
                    excluded_group_counts[str(row.get("group"))] += 1
                    for reason in row.get("reasons", []):
                        excluded_reason_counts[str(reason)] += 1
                print(
                    "PHASE4_EXCLUSION_SUMMARY=" + json.dumps(
                        {
                            "selected_feature_count": selection.get("selected_feature_count"),
                            "core_feature_count": selection.get("core_feature_count"),
                            "full_research_feature_count": selection.get("full_research_feature_count"),
                            "stable_base_feature_count": selection.get("stable_base_feature_count"),
                            "group_counts": selection.get("group_counts"),
                            "excluded_feature_count": len(selection.get("excluded_features", [])),
                            "excluded_reason_counts": dict(sorted(excluded_reason_counts.items())),
                            "excluded_group_counts": dict(sorted(excluded_group_counts.items())),
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    flush=True,
                )
                print("PHASE4_PHASE5_FREEZE=" + json.dumps(freeze, ensure_ascii=False, sort_keys=True), flush=True)

                oos_result = json.loads((phase4_dir / "PHASE4_LOCKED_OOS_RESULTS.json").read_text(encoding="utf-8"))
                oos_compact = {}
                for target, target_obj in oos_result.get("targets", {}).items():
                    metrics = target_obj.get("oos_metrics") or {}
                    prior = target_obj.get("rolling_prior_metrics") or {}
                    oos_compact[target] = {
                        "variant": target_obj.get("variant"),
                        "feature_count": target_obj.get("feature_count"),
                        "n": metrics.get("n"),
                        "logloss": metrics.get("logloss"),
                        "brier": metrics.get("brier"),
                        "accuracy": metrics.get("accuracy"),
                        "ece_10": metrics.get("ece_10"),
                        "mce_10": metrics.get("mce_10"),
                        "toplabel_ece_10": metrics.get("toplabel_ece_10"),
                        "toplabel_mce_10": metrics.get("toplabel_mce_10"),
                        "rolling_prior_logloss": prior.get("logloss"),
                        "rolling_prior_brier": prior.get("brier"),
                    }
                print("PHASE4_OOS_METRICS=" + json.dumps(oos_compact, ensure_ascii=False, sort_keys=True), flush=True)

                print(
                    "PHASE4_KEY_HASHES=" + json.dumps(
                        {
                            name: info
                            for name, info in manifest.get("artifacts", {}).items()
                            if name in {
                                "PHASE4_MODEL_RESEARCH.json",
                                "PHASE4_PHASE5_FREEZE.json",
                                "PHASE4_CALIBRATION_INPUT.jsonl.gz",
                                "PHASE4_OOS_LOCK.json",
                                "PHASE4_LOCKED_OOS_RESULTS.json",
                                "PHASE4_LOCKED_OOS_PREDICTIONS.npz",
                                "PHASE4_GROUP_ABLATIONS_DEVELOPMENT.json",
                                "PHASE4_DEVELOPMENT_MODEL_COMPARISON.json",
                                "PHASE4_V3_COVERAGE_DIAGNOSTIC_V2.json",
                                "PHASE4_FEATURE_SELECTION.json",
                                "PHASE4_SPLITS.json",
                            }
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    flush=True,
                )

                # Phase 5 only: reuse immutable Phase-4 artifacts. No Phase-4 rebuild.
                from research.full7_phase5_calibration import run_phase5_offline
                phase5 = run_phase5_offline(
                    phase4_dir,
                    output_root / "phase5",
                )
                phase5_dir = output_root / "phase5"
                print(
                    "PHASE5_RECEIPT=" + json.dumps(
                        {
                            "PHASE5_CALIBRATION": phase5.get("PHASE5_CALIBRATION"),
                            "status": phase5.get("status"),
                            "decision_lock_sha256": phase5.get("PHASE5_CALIBRATION_DECISION_LOCK_SHA256"),
                            "targets": {
                                target: {
                                    "selected_calibrator": obj.get("SELECTED_CALIBRATOR"),
                                    "calibration_accepted": obj.get("CALIBRATION_ACCEPTED"),
                                    "phase6_ready": obj.get("PHASE6_READY"),
                                }
                                for target, obj in phase5.get("targets", {}).items()
                            },
                            "manifest_sha256": _sha256(phase5_dir / "PHASE5_MANIFEST.json")
                            if (phase5_dir / "PHASE5_MANIFEST.json").is_file()
                            else None,
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    flush=True,
                )

                # Read-only Phase-5 final receipt. No fit, selection, prediction,
                # thresholding or artifact mutation occurs here.
                dev_cal = json.loads(
                    (phase5_dir / "PHASE5_CALIBRATOR_DEVELOPMENT_COMPARISON.json").read_text(encoding="utf-8")
                )
                for target in ("1X2", "BTTS", "O25"):
                    obj = phase5["targets"][target]
                    candidate_receipt = {}
                    for name, cand in dev_cal["targets"][target]["candidates"].items():
                        if cand.get("status") != "COMPLETE":
                            candidate_receipt[name] = {
                                "status": cand.get("status"),
                                "error": cand.get("error"),
                                "eligible": False,
                            }
                            continue
                        metrics = cand["aggregate_metrics"]
                        candidate_receipt[name] = {
                            "status": "COMPLETE",
                            "n": metrics.get("n"),
                            "logloss": metrics.get("logloss"),
                            "brier": metrics.get("brier"),
                            "accuracy": metrics.get("accuracy"),
                            "ece_10": metrics.get("ece_10"),
                            "mce_10": metrics.get("mce_10"),
                            "toplabel_ece_10": metrics.get("toplabel_ece_10"),
                            "toplabel_mce_10": metrics.get("toplabel_mce_10"),
                            "selection_diagnostic": cand.get("selection_diagnostic"),
                        }
                    print(
                        f"PHASE5_CANDIDATES_{target}="
                        + json.dumps(candidate_receipt, ensure_ascii=False, sort_keys=True),
                        flush=True,
                    )

                    def compact_metrics(metrics):
                        return {
                            "n": metrics.get("n"),
                            "logloss": metrics.get("logloss"),
                            "brier": metrics.get("brier"),
                            "accuracy": metrics.get("accuracy"),
                            "ece_10": metrics.get("ece_10"),
                            "mce_10": metrics.get("mce_10"),
                            "toplabel_ece_10": metrics.get("toplabel_ece_10"),
                            "toplabel_mce_10": metrics.get("toplabel_mce_10"),
                            "calibration_slope_intercept": metrics.get("calibration_slope_intercept"),
                            "sum_to_one_coherence": metrics.get("sum_to_one_coherence"),
                            "class_calibration": {
                                k: {
                                    "ece_10": v.get("ece_10"),
                                    "mce_10": v.get("mce_10"),
                                    "calibration_slope_intercept": v.get("calibration_slope_intercept"),
                                }
                                for k, v in (metrics.get("class_calibration") or {}).items()
                            } or None,
                            "probability_distribution": metrics.get("probability_distribution"),
                        }

                    split_receipt = {}
                    for split_name in ("OOS1_METRICS", "OOS2_METRICS", "OOS3_METRICS"):
                        split_obj = obj[split_name]
                        split_receipt[split_name] = {
                            "pre": compact_metrics(split_obj["PRE_CALIBRATION_METRICS"]),
                            "post": compact_metrics(split_obj["POST_CALIBRATION_METRICS"]),
                            "prior": compact_metrics(split_obj["ROLLING_PRIOR_METRICS"]),
                            "paired": split_obj["ROLLING_PRIOR_PAIRED_COMPARISON"],
                        }
                    agg = obj["AGGREGATE_OOS_METRICS"]
                    split_receipt["AGGREGATE"] = {
                        "pre": compact_metrics(agg["PRE_CALIBRATION_METRICS"]),
                        "post": compact_metrics(agg["POST_CALIBRATION_METRICS"]),
                        "prior": compact_metrics(agg["ROLLING_PRIOR_METRICS"]),
                        "paired": agg["ROLLING_PRIOR_PAIRED_COMPARISON"],
                    }
                    print(
                        f"PHASE5_METRICS_{target}="
                        + json.dumps(split_receipt, ensure_ascii=False, sort_keys=True),
                        flush=True,
                    )
                    print(
                        f"PHASE5_UNCERTAINTY_{target}="
                        + json.dumps(
                            {
                                "fold_stability": obj["OOS_FOLD_STABILITY"],
                                "uncertainty": obj["UNCERTAINTY_RESULT"],
                                "coherence": obj["1X2_COHERENCE_CHECK"],
                                "selected_calibrator": obj["SELECTED_CALIBRATOR"],
                                "calibration_accepted": obj["CALIBRATION_ACCEPTED"],
                                "phase6_ready": obj["PHASE6_READY"],
                            },
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                        flush=True,
                    )
                    for split_name, split_obj in [
                        ("OOS1", obj["OOS1_METRICS"]),
                        ("OOS2", obj["OOS2_METRICS"]),
                        ("OOS3", obj["OOS3_METRICS"]),
                        ("AGGREGATE", obj["AGGREGATE_OOS_METRICS"]),
                    ]:
                        print(
                            f"PHASE5_BINS_{target}_{split_name}="
                            + json.dumps(
                                {
                                    "pre": {
                                        "reliability_bins": split_obj["PRE_CALIBRATION_METRICS"].get("reliability_bins"),
                                        "toplabel_reliability_bins": split_obj["PRE_CALIBRATION_METRICS"].get("toplabel_reliability_bins"),
                                        "class_calibration": split_obj["PRE_CALIBRATION_METRICS"].get("class_calibration"),
                                    },
                                    "post": {
                                        "reliability_bins": split_obj["POST_CALIBRATION_METRICS"].get("reliability_bins"),
                                        "toplabel_reliability_bins": split_obj["POST_CALIBRATION_METRICS"].get("toplabel_reliability_bins"),
                                        "class_calibration": split_obj["POST_CALIBRATION_METRICS"].get("class_calibration"),
                                    },
                                },
                                ensure_ascii=False,
                                sort_keys=True,
                            ),
                            flush=True,
                        )
            return

    if output_root.exists():
        result = resume_existing_phase2_phase3(
            root=Path(args.root),
            cp1_path=Path(args.cp1),
            hold_ids_path=Path(args.hold_ids),
            output_root=output_root,
        )
    else:
        result = execute_phase2_phase3(
            root=Path(args.root),
            cp1_path=Path(args.cp1),
            hold_ids_path=Path(args.hold_ids),
            output_root=output_root,
        )
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
