import hashlib
import json
from pathlib import Path

import pytest

from research.full7_feature_audit import (
    REQUIRED_GROUPS,
    FeatureAuditError,
    classify_path,
    profile_master,
    run_feature_audit,
)
from research.test_full7_master_dataset import build_fixture_master


def test_full_feature_audit_profiles_fields_and_all_required_groups(tmp_path):
    _root, _population, cp2_dir, _checkpoint = build_fixture_master(tmp_path)
    cp3_dir = tmp_path / "cp3"
    checkpoint = run_feature_audit(cp2_dir, cp3_dir, correlation_min_overlap=2)
    assert checkpoint["checkpoint"] == "CP3_FEATURE_AUDIT"
    assert checkpoint["status"] == "COMPLETE"
    assert checkpoint["gate"] == "PASS"

    report = json.loads((cp3_dir / "FULL7_FEATURE_AUDIT.json").read_text(encoding="utf-8"))
    profiles = {row["path"]: row for row in report["field_profiles"]}
    identity = profiles["match.identity.match_id"]
    assert identity["matches_non_null"] == 1
    assert identity["coverage_rate"] == 1.0
    assert identity["missingness_rate"] == 0.0
    assert identity["numeric"]["min"] == 101.0
    assert identity["numeric"]["max"] == 101.0

    ppg = profiles["league.teams_full_home_away[].seasonPPG_home"]
    assert ppg["provider_dependency"] == "FOOTYSTATS_PROVIDER_FIELD"
    assert ppg["leakage_risk"] == "STRICT_PREMATCH_CANDIDATE"
    assert ppg["numeric"]["outlier_method"] == "IQR_ON_DETERMINISTIC_SAMPLE"

    assert REQUIRED_GROUPS.issubset(report["mandatory_groups"])
    assert report["mandatory_groups"]["A2_PLAYER_DEPTH"]["audit_status"] == "AUDITED"
    derived = {row["feature"]: row for row in report["derived_feature_profiles"]}
    assert derived["player_depth_home"]["matches_non_null"] == 1
    assert derived["player_depth_away"]["matches_non_null"] == 1
    assert derived["player_depth_diff"]["numeric"]["mean"] == 0.0


def test_path_classification_distinguishes_historical_results_and_blocked_fields():
    historical = classify_path("form.home.source_matches[].home_goals")
    assert historical["leakage_risk"] == "HISTORICAL_RESULT_ALLOWED_BEFORE_KICKOFF"
    unvalidated = classify_path("league.season_candidate_unvalidated.recorded_home_avg")
    assert unvalidated["research_eligibility"] == "NOT_ELIGIBLE_PENDING_PROVENANCE"
    blocked = classify_path("match.identity.actual_1x2")
    assert blocked["research_eligibility"] == "BLOCKED_LABEL_LEAKAGE"
    odds = classify_path("player.players[].market_odds")
    assert odds["research_eligibility"] == "BLOCKED_ODDS"


def test_profile_master_reports_season_stability_and_redundancy(tmp_path):
    path = tmp_path / "master.jsonl"
    rows = []
    for match_id, season_id, value in ((1, 10, 1.0), (2, 10, 2.0), (3, 11, 3.0)):
        rows.append(
            {
                "match_id": match_id,
                "season_id": season_id,
                "home_id": 100 + match_id,
                "away_id": 200 + match_id,
                "feature_sources_json": json.dumps(
                    {
                        "match": {"signal_a": value, "signal_b": value * 2},
                        "league": {},
                        "form": {},
                        "table": {},
                        "player": {"players": []},
                    }
                ),
            }
        )
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    report = profile_master(path, expected_rows=3, correlation_min_overlap=3)
    profiles = {row["path"]: row for row in report["field_profiles"]}
    signal = profiles["match.signal_a"]
    assert signal["season_stability"]["season_count"] == 2
    assert signal["season_stability"]["coverage_min"] == 1.0
    assert signal["season_stability"]["coverage_max"] == 1.0
    assert signal["numeric"]["mean"] == 2.0
    pair = next(
        row
        for row in report["high_redundancy_pairs"]
        if {row["path_a"], row["path_b"]} == {"match.signal_a", "match.signal_b"}
    )
    assert pair["overlap"] == 3
    assert pair["pearson_r"] == 1.0


def test_phase3_refuses_nonpassing_cp2(tmp_path):
    _root, _population, cp2_dir, _checkpoint = build_fixture_master(tmp_path)
    checkpoint_path = cp2_dir / "CP2_MASTER_DATASET.json"
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    checkpoint["gate"] = "FAIL"
    checkpoint_path.write_text(json.dumps(checkpoint), encoding="utf-8")
    with pytest.raises(FeatureAuditError, match="cp2_gate_not_pass"):
        run_feature_audit(cp2_dir, tmp_path / "cp3")


def test_phase3_refuses_odds_or_label_path_even_if_cp2_file_is_tampered(tmp_path):
    _root, _population, cp2_dir, _checkpoint = build_fixture_master(tmp_path)
    master_path = cp2_dir / "FULL7_MASTER_STRICT.jsonl"
    row = json.loads(master_path.read_text(encoding="utf-8"))
    sources = json.loads(row["feature_sources_json"])
    sources["player"]["players"][0]["closing_odds"] = 1.5
    row["feature_sources_json"] = json.dumps(sources)
    master_path.write_text(json.dumps(row) + "\n", encoding="utf-8")
    manifest_path = cp2_dir / "FULL7_MASTER_BUILD_MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["artifacts"][master_path.name]["sha256"] = hashlib.sha256(
        master_path.read_bytes()
    ).hexdigest()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(FeatureAuditError, match="blocked_feature_path"):
        run_feature_audit(cp2_dir, tmp_path / "cp3")
    assert not (tmp_path / "cp3").exists()
