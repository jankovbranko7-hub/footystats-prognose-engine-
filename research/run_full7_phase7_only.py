#!/usr/bin/env python3
"""Fail-closed one-shot dispatcher for FULL-7 Phase 7 finalization only."""
from __future__ import annotations

import json
import os
from pathlib import Path

from research.full7_phase4_continue import block_network
from research.full7_phase7_finalize import (
    RELEASE_CANDIDATE_VERSION,
    Phase7Error,
    audit_frozen_tree,
    audit_manifest,
    build_release_candidate,
    emit_bundle_parts,
    sha256,
)


REQUIRED_FALSE_FLAGS = (
    "COLLECTION_ALLOWED",
    "API_COLLECTION_ALLOWED",
    "CP1_ALLOWED",
    "CP2_ALLOWED",
    "CP3_ALLOWED",
    "PHASE4_REBUILD_ALLOWED",
    "PHASE5_REBUILD_ALLOWED",
    "PHASE6_REBUILD_ALLOWED",
    "O25_PHASE6_ALLOWED",
    "O25_PHASE7_ALLOWED",
    "PRODUCTION_DEPLOY_ALLOWED",
    "MAIN_MERGE_ALLOWED",
)


def _require_false_env() -> dict[str, str]:
    values = {}
    for key in REQUIRED_FALSE_FLAGS:
        value = os.environ.get(key, "false").strip().lower()
        if value != "false":
            raise Phase7Error(f"phase7_guard_env_not_false:{key}:{value}")
        values[key] = "false"
    return values


def run_phase7_only(root: Path) -> dict[str, object]:
    root = Path(root)
    env = _require_false_env()
    output = root / "phase7_rc" / RELEASE_CANDIDATE_VERSION
    if output.exists():
        audit_frozen_tree(root)
        manifest = output / "FULL7_FINAL_RC_MANIFEST.json"
        expected_manifest = os.environ.get("FULL7_PHASE7_MANIFEST_SHA256", "").strip()
        if len(expected_manifest) != 64:
            raise Phase7Error("existing_phase7_manifest_external_pin_missing")
        receipt = audit_manifest(
            manifest, expected_manifest_sha256=expected_manifest
        )
        report = json.loads((output / "FULL7_FINAL_AUDIT.json").read_text(encoding="utf-8"))
        if report.get("FULL7_FINAL_ENGINE_STATUS") != "PASS_RELEASE_CANDIDATE":
            raise Phase7Error("existing_phase7_report_not_pass")
        reused = True
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        with block_network():
            report = build_release_candidate(root, output)
        expected_manifest = sha256(output / "FULL7_FINAL_RC_MANIFEST.json")
        receipt = audit_manifest(
            output / "FULL7_FINAL_RC_MANIFEST.json",
            expected_manifest_sha256=expected_manifest,
        )
        reused = False
    print("PHASE7_MANIFEST_SHA256=" + expected_manifest, flush=True)
    if os.environ.get("PHASE7_EMIT_BUNDLE", "false").strip().lower() == "true":
        emit_bundle_parts(output)
    result = {
        "PHASE7_ONLY_GUARDS": "PASS",
        "guard_env": env,
        "release_candidate_version": RELEASE_CANDIDATE_VERSION,
        "output": str(output),
        "output_reused": reused,
        "manifest_audit": receipt,
        "report": report,
    }
    print("PHASE7_ONLY_RESULT=" + json.dumps(result, sort_keys=True), flush=True)
    return result


if __name__ == "__main__":
    root = Path(os.environ.get("FULL7_DERIVED_ROOT", "/var/data/full7/derived/full7_phase2_phase3_2026-09-22"))
    run_phase7_only(root)
