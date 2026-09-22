import json
import socket
from pathlib import Path

import pytest

from research.run_full7_phase2_phase3 import (
    OfflineExecutionError,
    _read_hold_ids,
    block_network,
    compare_manifest_files,
    execute_phase2_phase3,
    write_protected_manifest,
)
from research.test_full7_master_dataset import make_population


def test_network_blocker_rejects_outbound_connection():
    with block_network():
        with pytest.raises(OfflineExecutionError, match="network_disabled"):
            socket.create_connection(("example.com", 80), timeout=0.01)


def test_hold_id_reader_ignores_documentation_comments(tmp_path):
    hold_path = tmp_path / "holds.txt"
    hold_path.write_text(
        "# FULL7 CP1 held IDs\n# Reason: documented provenance\n102\n103 # inline note\n",
        encoding="utf-8",
    )

    assert _read_hold_ids(hold_path) == {102, 103}


def test_protected_manifest_detects_no_change_and_then_mutation(tmp_path):
    root, _cp1 = make_population(tmp_path)
    before = tmp_path / "before.tsv"
    after = tmp_path / "after.tsv"
    write_protected_manifest(root, before)
    write_protected_manifest(root, after)
    equal = compare_manifest_files(before, after)
    assert equal["equal"] is True
    assert equal["differences"] == 0

    state = root / "done_ids.txt"
    state.write_text(state.read_text(encoding="utf-8") + "999\n", encoding="utf-8")
    write_protected_manifest(root, after)
    changed = compare_manifest_files(before, after)
    assert changed["equal"] is False
    assert changed["differences"] == 1


def test_cp3_never_starts_when_cp2_gate_is_not_pass(tmp_path, monkeypatch):
    root, cp1 = make_population(tmp_path)
    hold_path = tmp_path / "holds.txt"
    hold_path.write_text("102\n", encoding="utf-8")
    cp3_called = False

    def fake_build(*_args, **_kwargs):
        return {"checkpoint": "CP2_MASTER_DATASET", "gate": "FAIL"}

    def fake_cp3(*_args, **_kwargs):
        nonlocal cp3_called
        cp3_called = True

    monkeypatch.setattr("research.run_full7_phase2_phase3.build_master_dataset", fake_build)
    monkeypatch.setattr("research.run_full7_phase2_phase3.run_feature_audit", fake_cp3)
    with pytest.raises(OfflineExecutionError, match="cp2_gate_not_pass"):
        execute_phase2_phase3(
            root=root,
            cp1_path=cp1,
            hold_ids_path=hold_path,
            output_root=tmp_path / "derived",
            expected_target_total=3,
            expected_collector_strict=2,
            expected_quarantine_total=1,
            expected_hold_total=1,
            expected_eligible_total=1,
        )
    assert cp3_called is False


def test_offline_runner_completes_cp2_then_cp3_without_mutating_sources(tmp_path):
    root, cp1 = make_population(tmp_path)
    hold_path = tmp_path / "holds.txt"
    hold_path.write_text("102\n", encoding="utf-8")
    output_root = tmp_path / "derived"
    result = execute_phase2_phase3(
        root=root,
        cp1_path=cp1,
        hold_ids_path=hold_path,
        output_root=output_root,
        expected_target_total=3,
        expected_collector_strict=2,
        expected_quarantine_total=1,
        expected_hold_total=1,
        expected_eligible_total=1,
        correlation_min_overlap=2,
    )
    assert result["status"] == "COMPLETE"
    assert result["cp2_gate"] == "PASS"
    assert result["cp3_gate"] == "PASS"
    assert result["protected_collection_integrity"]["equal"] is True
    assert (output_root / "cp2" / "CP2_MASTER_DATASET.json").is_file()
    assert (output_root / "cp3" / "CP3_FEATURE_AUDIT.json").is_file()
    ledger = json.loads((output_root / "FULL7_PHASE2_PHASE3_EXECUTION.json").read_text(encoding="utf-8"))
    assert ledger["api_calls_performed"] is False
    assert ledger["collection_performed"] is False
    assert ledger["source_mutation_detected"] is False
