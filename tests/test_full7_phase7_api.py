import json
import ast
import hashlib
import hmac
from pathlib import Path

import numpy as np
import pytest

from full7_phase7_api import (
    FULL7_RELEASE_CANDIDATE_VERSION,
    RuntimeArtifactError,
    _read_pinned_manifest,
    _validated_input_integrity,
    phase7_engine_health,
    predict_phase7_rc,
)
from full7_phase7_runtime import Full7Phase7Runtime
from tests.test_full7_phase7_features import sample_row
from research.full7_master_dataset import load_validated_bundle
from research.test_full7_master_dataset import make_bundle


class ConstantRegressor:
    def __init__(self, value):
        self.value = value

    def predict(self, matrix):
        return np.full(len(matrix), self.value, dtype=float)


INPUT_KEY = b"phase7-test-collector-key-32bytes!"


def make_strict_sources(sources):
    kickoff = 1_700_003_600
    sources["match"].update({"found": True, "stored_postmatch": False})
    sources["match"]["identity"].update(
        {"match_id": 123, "date_unix": kickoff}
    )
    sources["form"].update(
        {
            "home_id": 10,
            "away_id": 20,
            "kickoff_unix": kickoff,
            "rule": "date_unix < kickoff AND id != target",
        }
    )
    for side in ("home", "away"):
        sources["form"][side]["source_matches"] = [
            {"match_id": 100 if side == "home" else 101, "date_unix": 1_700_000_000}
        ]
    sources["league"]["league_aggregates_derived"].update(
        {
            "league_source_match_ids": [100, 101],
            "league_source_max_timestamp": 1_700_000_000,
        }
    )
    player_count = len(sources["player"]["players"])
    sources["player"]["pagination"] = {
        "pagination_complete": True,
        "total_results": player_count,
        "loaded_rows": player_count,
        "max_page": 1,
        "loaded_pages": 1,
    }
    return sources


def strict_integrity(
    sources,
    *,
    match_id=123,
    home_id=10,
    away_id=20,
    source_max_timestamp=1_700_000_000,
    kickoff_timestamp=1_700_003_600,
):
    payload_hash = hashlib.sha256(
        json.dumps(sources, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    proof = {
        "source_contract": "FULL7_CP2_STRICT_PREMATCH_NORMALIZED_1.0",
        "strict_pre_match": True,
        "match_id": match_id,
        "home_id": home_id,
        "away_id": away_id,
        "source_max_timestamp": source_max_timestamp,
        "kickoff_timestamp": kickoff_timestamp,
        "sources_sha256": payload_hash,
    }
    message = json.dumps(
        proof, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    proof["collector_hmac_sha256"] = hmac.new(
        INPUT_KEY, message, hashlib.sha256
    ).hexdigest()
    return proof


def test_phase7_health_exposes_new_decision_dependency_only():
    health = phase7_engine_health()
    assert health["code_status"] == "PASS_RELEASE_CANDIDATE"
    assert health["runtime_ready"] is False
    assert health["engine_version"] == FULL7_RELEASE_CANDIDATE_VERSION
    assert health["final_decision_source"].startswith("PHASE6_DECISION_LOCK_SHA256:")
    assert health["manual_performance_gates"] is False
    assert health["legacy_v3_1_override_active"] is False
    assert health["o25_status"] == "HOLD"
    assert health["production_mounted"] is False
    assert health["main_changed"] is False
    assert health["input_integrity_mode"] == "HMAC_TRUSTED_STRICT_PREMATCH_CP2"


def test_phase7_health_does_not_advertise_legacy_thresholds_or_totals_play():
    health = phase7_engine_health()
    assert health["active_play_thresholds"] == {
        "HOME": 0.50,
        "AWAY": 0.50,
        "BTTS_YES": 0.55,
    }
    assert "TOTALS" not in health["spielen_allowed_families"]
    assert health["o25_decision_rules_active"] is False


def test_normalized_prediction_path_extracts_features_and_runs_rc_runtime():
    row = sample_row()
    sources = make_strict_sources(json.loads(row["feature_sources_json"]))
    from full7_phase7_features import extract_phase4_features

    features, _ = extract_phase4_features(sources, home_id=10, away_id=20)
    names = list(features)
    runtime = Full7Phase7Runtime(
        models={
            "1X2_HOME": ConstantRegressor(1.6),
            "1X2_AWAY": ConstantRegressor(0.9),
            "BTTS_HOME": ConstantRegressor(1.5),
            "BTTS_AWAY": ConstantRegressor(1.2),
        },
        feature_names={"1X2": names, "BTTS": names},
        calibrator_1x2={
            "name": "MULTINOMIAL_LOGIT",
            "classes": [0, 1, 2],
            "coef": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
            "intercept": [0, 0, 0],
        },
        expected_feature_counts={"1X2": len(names), "BTTS": len(names)},
        frozen_gate_attestations_verified=True,
        model_artifact_integrity_verified=True,
    )
    result = predict_phase7_rc(
        sources=sources,
        home_id=10,
        away_id=20,
        input_integrity=strict_integrity(sources),
        input_hmac_key=INPUT_KEY,
        decision_timestamp=1_700_001_000,
        runtime=runtime,
    )
    assert result["input_contract"] == "PHASE4_NORMALIZED_FEATURE_SOURCES"
    assert result["o25_status"] == "HOLD"
    assert all(result["coherence"].values())


def test_normalized_prediction_path_fails_closed_on_malformed_source():
    result = predict_phase7_rc(
        sources=[], home_id=10, away_id=20, input_integrity=None, runtime=None
    )
    assert result["directions"]["HOME"]["decision"] == "AUSLASSEN"
    assert "INPUT_NORMALIZATION_FAIL" in result["fail_closed_reasons"]


def test_normalized_prediction_rejects_non_prematch_or_wrong_fixture_provenance():
    row = sample_row()
    sources = make_strict_sources(json.loads(row["feature_sources_json"]))
    bad = strict_integrity(sources)
    bad["source_max_timestamp"] = bad["kickoff_timestamp"]
    result = predict_phase7_rc(
        sources=sources,
        home_id=10,
        away_id=20,
        input_integrity=bad,
        input_hmac_key=INPUT_KEY,
        decision_timestamp=1_700_001_000,
        runtime=None,
    )
    assert result["directions"]["BTTS_YES"]["decision"] == "AUSLASSEN"
    assert "INPUT_INTEGRITY_FAIL" in result["fail_closed_reasons"]


def test_normalized_prediction_rejects_proof_bound_to_different_payload():
    row = sample_row()
    sources = make_strict_sources(json.loads(row["feature_sources_json"]))
    proof = strict_integrity(sources)
    sources["match"]["prematch_optional"]["team_a_xg_prematch"] = 9.9
    result = predict_phase7_rc(
        sources=sources,
        home_id=10,
        away_id=20,
        input_integrity=proof,
        input_hmac_key=INPUT_KEY,
        decision_timestamp=1_700_001_000,
        runtime=None,
    )
    assert "INPUT_INTEGRITY_FAIL" in result["fail_closed_reasons"]


def test_normalized_prediction_rejects_unsigned_self_attestation():
    row = sample_row()
    sources = make_strict_sources(json.loads(row["feature_sources_json"]))
    proof = strict_integrity(sources)
    proof["collector_hmac_sha256"] = "0" * 64
    result = predict_phase7_rc(
        sources=sources,
        home_id=10,
        away_id=20,
        input_integrity=proof,
        input_hmac_key=INPUT_KEY,
        decision_timestamp=1_700_001_000,
        runtime=None,
    )
    assert "INPUT_INTEGRITY_FAIL" in result["fail_closed_reasons"]


def test_manifest_must_match_external_pin_before_bundle_hash_is_read(tmp_path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text('{"artifacts": {}}\n', encoding="utf-8")
    expected = hashlib.sha256(manifest.read_bytes()).hexdigest()
    assert _read_pinned_manifest(manifest, expected_sha256=expected)["artifacts"] == {}
    with pytest.raises(RuntimeArtifactError, match="manifest_hash_mismatch"):
        _read_pinned_manifest(manifest, expected_sha256="0" * 64)


def test_integrity_validator_accepts_real_frozen_cp2_bundle_shape(tmp_path):
    root = tmp_path / "collector"
    make_bundle(root, 101, 7, strict=True)
    bundle = load_validated_bundle(root, 101, 7)
    proof = strict_integrity(
        bundle.feature_sources,
        match_id=bundle.match_id,
        home_id=bundle.home_id,
        away_id=bundle.away_id,
        source_max_timestamp=bundle.kickoff_unix - 100,
        kickoff_timestamp=bundle.kickoff_unix,
    )
    assert _validated_input_integrity(
        sources=bundle.feature_sources,
        home_id=bundle.home_id,
        away_id=bundle.away_id,
        proof=proof,
        hmac_key=INPUT_KEY,
        decision_timestamp=bundle.kickoff_unix - 50,
    )


def test_signed_payload_replayed_after_kickoff_fails_closed():
    row = sample_row()
    sources = make_strict_sources(json.loads(row["feature_sources_json"]))
    proof = strict_integrity(sources)
    result = predict_phase7_rc(
        sources=sources,
        home_id=10,
        away_id=20,
        input_integrity=proof,
        input_hmac_key=INPUT_KEY,
        decision_timestamp=1_700_003_601,
        runtime=None,
    )
    assert "INPUT_INTEGRITY_FAIL" in result["fail_closed_reasons"]


def test_rc_runtime_dependency_graph_has_no_legacy_v3_import():
    for name in (
        "app_phase7_rc.py",
        "full7_phase7_api.py",
        "full7_phase7_runtime.py",
        "full7_phase7_decision.py",
    ):
        tree = ast.parse(Path(name).read_text(encoding="utf-8"), filename=name)
        imported = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module)
        assert not any("full7_v3" in module for module in imported)
