import hashlib
import json
from pathlib import Path

import pytest

from research.full7_master_dataset import (
    DatasetValidationError,
    audit_master_outputs,
    build_master_dataset,
    canonical_json,
    canonical_sha256,
    derive_population,
    load_validated_bundle,
)


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, separators=(",", ":")), encoding="utf-8")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_bundle(root: Path, match_id: int, season_id: int, *, strict: bool = True) -> Path:
    match_dir = root / "matches" / str(match_id)
    match_dir.mkdir(parents=True)
    kickoff = 1_700_000_000 + match_id
    home_id = match_id * 10 + 1
    away_id = match_id * 10 + 2

    payloads = {
        f"{match_id}_MatchDaten.json": {
            "found": True,
            "identity": {
                "match_id": match_id,
                "season": season_id,
                "homeID": home_id,
                "awayID": away_id,
                "home_name": f"H{match_id}",
                "away_name": f"A{match_id}",
                "date_unix": kickoff,
            },
            "prematch_optional": {"team_a_xg_prematch": None},
            "stored_postmatch": False,
        },
        f"{season_id}_{match_id}_LeagueDaten.json": {
            "season_safe_identity": {"id": season_id, "name": f"S{season_id}"},
            "season_candidate_unvalidated": {},
            "season_excluded_recorded_keys": [],
            "teams_core_home_away": [
                {"id": home_id, "name": f"H{match_id}"},
                {"id": away_id, "name": f"A{match_id}"},
            ],
            "teams_full_home_away": [
                {"id": home_id, "name": f"H{match_id}", "seasonPPG_home": 1.25},
                {"id": away_id, "name": f"A{match_id}", "seasonPPG_away": 1.10},
            ],
            "league_aggregates_derived": {
                "league_source_count": 3,
                "league_source_match_ids": [match_id - 3, match_id - 2, match_id - 1],
                "league_source_max_timestamp": kickoff - 100,
            },
            "feature_policy": {},
        },
        f"{match_id}_FormDaten.json": {
            "home_id": home_id,
            "away_id": away_id,
            "kickoff_unix": kickoff,
            "rule": "date_unix < kickoff AND id != target",
            "home": {"source_matches": [], "last5": {"n": 0, "xg_avg": None}},
            "away": {"source_matches": [], "last5": {"n": 0, "xg_avg": None}},
        },
        f"{match_id}_TableDaten.json": {
            "home_row": {"id": home_id, "position": 1},
            "away_row": {"id": away_id, "position": 2},
        },
        f"{match_id}_PlayerDaten.json": {
            "pagination": {
                "max_page": 1,
                "loaded_pages": 1,
                "loaded_rows": 2,
                "total_results": 2,
                "pagination_complete": True,
            },
            "n_kept_home_away": 2,
            "available_fields": ["club_team_id", "id", "goals_overall"],
            "players": [
                {"id": home_id + 1000, "club_team_id": home_id, "goals_overall": 2},
                {"id": away_id + 1000, "club_team_id": away_id, "goals_overall": 1},
            ],
        },
        f"{match_id}_ResultTarget.json": {
            "match_id": match_id,
            "home_goals": 2,
            "away_goals": 1,
            "actual_1x2": "H",
            "actual_btts": 1,
            "actual_over25": 1,
            "note": "LABEL ONLY",
        },
    }
    for name, value in payloads.items():
        write_json(match_dir / name, value)

    metadata = {
        "match_id": match_id,
        "season_id": season_id,
        "liga": f"S{season_id}",
        "home": f"H{match_id}",
        "away": f"A{match_id}",
        "home_id": home_id,
        "away_id": away_id,
        "kickoff_utc": "2023-11-14T00:00:00+00:00",
        "kickoff_unix": kickoff,
        "requested_max_time": kickoff - 1,
        "strict_prematch": strict,
        "reason_if_false": None if strict else ["fixture_quarantine"],
        "request_provenance": [
            {
                "endpoint": "league-teams",
                "params": {"season_id": season_id, "max_time": kickoff - 1},
                "requested_max_time": kickoff - 1,
                "raw_response_sha256": "a" * 64,
                "page": 1,
                "max_page": 1,
                "raw_row_count": 2,
            }
        ],
        "files_sha256": {name: sha256(match_dir / name) for name in payloads},
    }
    write_json(match_dir / f"{match_id}_Metadata.json", metadata)
    return match_dir


def make_population(tmp_path: Path):
    root = tmp_path / "output"
    make_bundle(root, 101, 7, strict=True)
    make_bundle(root, 102, 7, strict=True)
    make_bundle(root, 103, 8, strict=False)
    (root / "done_ids.txt").write_text("101\n102\n103\n", encoding="utf-8")
    write_json(
        root / "quarantine" / "103" / "reason.json",
        {"match_id": 103, "season_id": 8, "reason_if_false": ["fixture_quarantine"]},
    )
    cp1 = tmp_path / "CP1_STRICT_DATASET.json"
    write_json(
        cp1,
        {
            "checkpoint": "CP1_STRICT_DATASET",
            "status": "BLOCKED_REPAIR_REQUIRED",
            "collector_strict_label": 2,
            "cp1_eligible_strict": 1,
            "existing_quarantine": 1,
            "new_cp1_audit_holds": 1,
        },
    )
    return root, cp1


def test_population_is_strict_minus_holds_and_quarantine(tmp_path):
    root, cp1 = make_population(tmp_path)
    audit = derive_population(
        root,
        hold_ids={102},
        cp1_path=cp1,
        expected_target_total=3,
        expected_collector_strict=2,
        expected_quarantine_total=1,
        expected_hold_total=1,
        expected_eligible_total=1,
    )
    assert audit.target_ids == (101, 102, 103)
    assert audit.strict_ids == (101, 102)
    assert audit.quarantine_ids == (103,)
    assert audit.hold_ids == (102,)
    assert audit.eligible_ids == (101,)


def test_population_rejects_duplicate_done_id(tmp_path):
    root, cp1 = make_population(tmp_path)
    (root / "done_ids.txt").write_text("101\n102\n102\n103\n", encoding="utf-8")
    with pytest.raises(DatasetValidationError, match="duplicate_done_id"):
        derive_population(
            root,
            hold_ids={102},
            cp1_path=cp1,
            expected_target_total=3,
            expected_collector_strict=2,
            expected_quarantine_total=1,
            expected_hold_total=1,
            expected_eligible_total=1,
        )


def test_validated_bundle_separates_label_and_records_null_paths(tmp_path):
    root, _ = make_population(tmp_path)
    bundle = load_validated_bundle(root, 101, 7)
    assert bundle.match_id == 101
    assert bundle.label == {
        "home_goals": 2,
        "away_goals": 1,
        "actual_1x2": "H",
        "actual_btts": 1,
        "actual_over25": 1,
    }
    assert "result_target" not in bundle.feature_sources
    assert "match.prematch_optional.team_a_xg_prematch" in bundle.null_paths
    assert bundle.source_file_sha256["101_MatchDaten.json"] == sha256(
        root / "matches" / "101" / "101_MatchDaten.json"
    )


def test_validated_bundle_rejects_payload_hash_mismatch(tmp_path):
    root, _ = make_population(tmp_path)
    path = root / "matches" / "101" / "101_FormDaten.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    value["home"]["last5"]["n"] = 1
    write_json(path, value)
    with pytest.raises(DatasetValidationError, match="payload_sha256_mismatch"):
        load_validated_bundle(root, 101, 7)


def test_validated_bundle_rejects_team_join_mismatch(tmp_path):
    root, _ = make_population(tmp_path)
    match_dir = root / "matches" / "101"
    path = match_dir / "101_TableDaten.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    value["away_row"]["id"] = 999999
    write_json(path, value)
    metadata_path = match_dir / "101_Metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["files_sha256"][path.name] = sha256(path)
    write_json(metadata_path, metadata)
    with pytest.raises(DatasetValidationError, match="table_away_team_id_mismatch"):
        load_validated_bundle(root, 101, 7)


def test_validated_bundle_rejects_odds_like_feature(tmp_path):
    root, _ = make_population(tmp_path)
    match_dir = root / "matches" / "101"
    path = match_dir / "101_PlayerDaten.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    value["players"][0]["opening_odds"] = 1.8
    write_json(path, value)
    metadata_path = match_dir / "101_Metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["files_sha256"][path.name] = sha256(path)
    write_json(metadata_path, metadata)
    with pytest.raises(DatasetValidationError, match="odds_like_feature_path"):
        load_validated_bundle(root, 101, 7)


def fake_parquet_writer(jsonl_path: Path, parquet_path: Path) -> None:
    pairs = []
    for line in jsonl_path.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        pairs.append([row["match_id"], row["row_sha256"]])
    parquet_path.write_text(json.dumps(pairs), encoding="utf-8")


def fake_parquet_reader(parquet_path: Path):
    return [tuple(pair) for pair in json.loads(parquet_path.read_text(encoding="utf-8"))]


def build_fixture_master(tmp_path: Path):
    root, cp1 = make_population(tmp_path)
    population = derive_population(
        root,
        hold_ids={102},
        cp1_path=cp1,
        expected_target_total=3,
        expected_collector_strict=2,
        expected_quarantine_total=1,
        expected_hold_total=1,
        expected_eligible_total=1,
    )
    output_dir = tmp_path / "cp2"
    checkpoint = build_master_dataset(
        root,
        output_dir,
        population,
        parquet_writer=fake_parquet_writer,
        parquet_reader=fake_parquet_reader,
    )
    return root, population, output_dir, checkpoint


def test_build_master_emits_one_row_exact_labels_and_cp2_pass(tmp_path):
    _root, population, output_dir, checkpoint = build_fixture_master(tmp_path)
    assert checkpoint["checkpoint"] == "CP2_MASTER_DATASET"
    assert checkpoint["status"] == "COMPLETE"
    assert checkpoint["gate"] == "PASS"
    assert checkpoint["match_count_valid"] == 1
    assert checkpoint["match_count_excluded"] == 2

    lines = (output_dir / "FULL7_MASTER_STRICT.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row["match_id"] == 101
    assert row["label_actual_1x2"] == "H"
    assert row["label_actual_btts"] == 1
    assert row["label_actual_over25"] == 1
    assert "result" not in json.loads(row["feature_sources_json"])
    assert row["row_sha256"] == canonical_sha256(
        {key: value for key, value in row.items() if key != "row_sha256"}
    )
    assert sorted(json.loads(row["null_paths_json"])) == [
        "form.away.last5.xg_avg",
        "form.home.last5.xg_avg",
        "match.prematch_optional.team_a_xg_prematch",
    ]

    exclusions = (output_dir / "FULL7_QUARANTINE_FINAL.csv").read_text(encoding="utf-8")
    assert "102,7,CP1_HOLD,LEAGUE_TARGET_TEAM_ROWS_MISSING" in exclusions
    assert "103,8,EXISTING_QUARANTINE,fixture_quarantine" in exclusions
    assert set(checkpoint["eligible_id_sha256"]) <= set("0123456789abcdef")
    assert population.eligible_ids == (101,)


def test_build_master_is_atomic_when_parquet_write_fails(tmp_path):
    root, cp1 = make_population(tmp_path)
    population = derive_population(
        root,
        hold_ids={102},
        cp1_path=cp1,
        expected_target_total=3,
        expected_collector_strict=2,
        expected_quarantine_total=1,
        expected_hold_total=1,
        expected_eligible_total=1,
    )
    output_dir = tmp_path / "cp2"

    def explode(_jsonl: Path, _parquet: Path) -> None:
        raise RuntimeError("parquet exploded")

    with pytest.raises(RuntimeError, match="parquet exploded"):
        build_master_dataset(
            root,
            output_dir,
            population,
            parquet_writer=explode,
            parquet_reader=fake_parquet_reader,
        )
    assert not output_dir.exists()
    assert not list(tmp_path.glob(".cp2.stage-*"))


def test_build_master_fails_closed_without_pyarrow(tmp_path, monkeypatch):
    root, cp1 = make_population(tmp_path)
    population = derive_population(
        root,
        hold_ids={102},
        cp1_path=cp1,
        expected_target_total=3,
        expected_collector_strict=2,
        expected_quarantine_total=1,
        expected_hold_total=1,
        expected_eligible_total=1,
    )
    real_import = __import__

    def blocked_import(name, *args, **kwargs):
        if name.startswith("pyarrow"):
            raise ImportError("simulated missing pyarrow")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", blocked_import)
    with pytest.raises(DatasetValidationError, match="pyarrow_required_for_parquet"):
        build_master_dataset(root, tmp_path / "cp2", population)


def test_default_pyarrow_backend_roundtrips_match_ids_and_hashes(tmp_path):
    root, cp1 = make_population(tmp_path)
    population = derive_population(
        root,
        hold_ids={102},
        cp1_path=cp1,
        expected_target_total=3,
        expected_collector_strict=2,
        expected_quarantine_total=1,
        expected_hold_total=1,
        expected_eligible_total=1,
    )
    checkpoint = build_master_dataset(root, tmp_path / "cp2", population)
    assert checkpoint["gate"] == "PASS"
    assert (tmp_path / "cp2" / "FULL7_MASTER_STRICT.parquet").stat().st_size > 0


def test_cp2_audit_detects_feature_leak_even_with_matching_row_hash(tmp_path):
    _root, population, output_dir, _checkpoint = build_fixture_master(tmp_path)
    jsonl_path = output_dir / "FULL7_MASTER_STRICT.jsonl"
    row = json.loads(jsonl_path.read_text(encoding="utf-8"))
    sources = json.loads(row["feature_sources_json"])
    sources["match"]["identity"]["actual_1x2"] = "H"
    row["feature_sources_json"] = canonical_json(sources)
    row["row_sha256"] = canonical_sha256(
        {key: value for key, value in row.items() if key != "row_sha256"}
    )
    jsonl_path.write_text(canonical_json(row) + "\n", encoding="utf-8")
    with pytest.raises(DatasetValidationError, match="cp2_label_key_in_feature"):
        audit_master_outputs(
            output_dir,
            population,
            parquet_reader=fake_parquet_reader,
        )
