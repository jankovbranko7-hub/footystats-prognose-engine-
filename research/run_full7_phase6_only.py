#!/usr/bin/env python3
"""Fail-closed one-shot dispatcher for the authorized FULL-7 Phase-6 audit run."""
from __future__ import annotations

import json
import os
from pathlib import Path

from research.full7_phase6_decision_research import (
    EXPECTED_PHASE4_MANIFEST_SHA256,
    EXPECTED_PHASE5_DECISION_LOCK_SHA256,
    EXPECTED_PHASE5_MANIFEST_SHA256,
    Phase6Error,
    _sha256,
    run_phase6,
)
from research.full7_phase4_continue import block_network

REQUIRED_FALSE_FLAGS = (
    "COLLECTION_ALLOWED",
    "API_COLLECTION_ALLOWED",
    "CP1_ALLOWED",
    "CP2_ALLOWED",
    "CP3_ALLOWED",
    "PHASE4_REBUILD_ALLOWED",
    "PHASE5_REBUILD_ALLOWED",
    "O25_PHASE6_ALLOWED",
)

REQUIRED_FILES = (
    "phase5/PHASE5_PREOOS_1X2.npz",
    "phase5/PHASE5_PREOOS_BTTS.npz",
    "phase5/PHASE5_MANIFEST.json",
    "phase5/PHASE5_CALIBRATION_DECISION_LOCK.json",
    "phase4/PHASE4_MANIFEST.json",
    "phase4/PHASE4_LOCKED_OOS_PREDICTIONS.npz",
)


def _require_false_env() -> dict[str, str]:
    if os.environ.get("FULL7_PHASE6_ONLY") != "true":
        raise Phase6Error("FULL7_PHASE6_ONLY_must_equal_true")
    values = {}
    for key in REQUIRED_FALSE_FLAGS:
        value = os.environ.get(key)
        if value != "false":
            raise Phase6Error(f"phase6_guard_env_not_false:{key}:{value}")
        values[key] = value
    return values


def _validate_frozen_inputs(root: Path) -> dict[str, object]:
    root = Path(root)
    if not root.is_dir():
        raise Phase6Error(f"phase6_root_missing:{root}")

    for rel in REQUIRED_FILES:
        if not (root / rel).is_file():
            raise Phase6Error(f"phase6_required_input_missing:{rel}")

    p4_sha = _sha256(root / "phase4/PHASE4_MANIFEST.json")
    p5_sha = _sha256(root / "phase5/PHASE5_MANIFEST.json")
    p5_lock_sha = _sha256(root / "phase5/PHASE5_CALIBRATION_DECISION_LOCK.json")
    if p4_sha != EXPECTED_PHASE4_MANIFEST_SHA256:
        raise Phase6Error(f"phase4_manifest_sha_mismatch:{p4_sha}")
    if p5_sha != EXPECTED_PHASE5_MANIFEST_SHA256:
        raise Phase6Error(f"phase5_manifest_sha_mismatch:{p5_sha}")
    if p5_lock_sha != EXPECTED_PHASE5_DECISION_LOCK_SHA256:
        raise Phase6Error(f"phase5_decision_lock_sha_mismatch:{p5_lock_sha}")

    p5_manifest = json.loads((root / "phase5/PHASE5_MANIFEST.json").read_text(encoding="utf-8"))
    artifacts = p5_manifest.get("artifacts") or {}
    for name in ("PHASE5_PREOOS_1X2.npz", "PHASE5_PREOOS_BTTS.npz"):
        expected = (artifacts.get(name) or {}).get("sha256")
        if not expected:
            raise Phase6Error(f"phase5_manifest_missing_preoos_hash:{name}")
        actual = _sha256(root / "phase5" / name)
        if actual != expected:
            raise Phase6Error(f"phase5_preoos_hash_mismatch:{name}:{actual}")

    return {
        "root": str(root),
        "phase4_manifest_sha256": p4_sha,
        "phase5_manifest_sha256": p5_sha,
        "phase5_calibration_decision_lock_sha256": p5_lock_sha,
        "phase5_preoos_1x2_sha256": _sha256(root / "phase5/PHASE5_PREOOS_1X2.npz"),
        "phase5_preoos_btts_sha256": _sha256(root / "phase5/PHASE5_PREOOS_BTTS.npz"),
        "frozen_inputs_read_only": True,
    }


def run_phase6_only(root: Path) -> dict[str, object]:
    env = _require_false_env()
    integrity = _validate_frozen_inputs(root)
    if (Path(root) / "phase6").exists() or (Path(root) / ".phase6.stage").exists():
        raise Phase6Error("phase6_output_or_stage_already_exists_fail_closed")

    receipt = {
        "PHASE6_ONLY_GUARDS": "PASS",
        "COLLECTION_ALLOWED": False,
        "API_COLLECTION_ALLOWED": False,
        "CP1_ALLOWED": False,
        "CP2_ALLOWED": False,
        "CP3_ALLOWED": False,
        "PHASE4_REBUILD_ALLOWED": False,
        "PHASE5_REBUILD_ALLOWED": False,
        "O25_PHASE6_ALLOWED": False,
        "guard_env": env,
        "input_integrity": integrity,
    }
    print("PHASE6_ONLY_GUARDS=" + json.dumps(receipt, sort_keys=True), flush=True)
    with block_network():
        result = run_phase6(Path(root))
    return {"guards": receipt, "result": result}
