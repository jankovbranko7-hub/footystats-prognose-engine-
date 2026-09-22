#!/usr/bin/env python3
"""Build a fail-closed FULL-7 master dataset from immutable bundles.

This module has no network client and performs no collection.  Its public
functions validate population membership and one complete bundle at a time.
"""
from __future__ import annotations

import hashlib
import csv
import gzip
import json
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


EXPECTED_TARGET_TOTAL = 17_685
EXPECTED_COLLECTOR_STRICT = 16_267
EXPECTED_QUARANTINE_TOTAL = 1_418
EXPECTED_HOLD_TOTAL = 130
EXPECTED_ELIGIBLE_TOTAL = 16_137

LABEL_KEYS = {
    "actual_1x2",
    "actual_btts",
    "actual_over25",
    "hit_ou",
    "hit_btts",
}
MATCH_POSTMATCH_FORBIDDEN = {
    "homeGoalCount",
    "awayGoalCount",
    "overallGoalCount",
    "totalGoalCount",
    "homeGoals",
    "awayGoals",
    "homeGoals_timings",
    "awayGoals_timings",
    "HTGoalCount",
    "ht_goals_team_a",
    "ht_goals_team_b",
    "winningTeam",
    "attendance",
    "team_a_shots",
    "team_b_shots",
    "team_a_possession",
    "team_b_possession",
    "totalCornerCount",
} | LABEL_KEYS


class DatasetValidationError(RuntimeError):
    """Raised whenever a fail-closed dataset contract is violated."""


@dataclass(frozen=True)
class PopulationAudit:
    target_ids: tuple[int, ...]
    strict_ids: tuple[int, ...]
    quarantine_ids: tuple[int, ...]
    hold_ids: tuple[int, ...]
    eligible_ids: tuple[int, ...]
    season_by_match: dict[int, int]


@dataclass(frozen=True)
class BundleRecord:
    match_id: int
    season_id: int
    home_id: int
    away_id: int
    kickoff_unix: int
    requested_max_time: int
    metadata: dict[str, Any]
    feature_sources: dict[str, Any]
    label: dict[str, Any]
    null_paths: tuple[str, ...]
    source_file_sha256: dict[str, str]


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover - message path is exercised
        raise DatasetValidationError(f"json_read_error:{path}:{exc}") from exc


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _as_int(value: Any, code: str) -> int:
    if isinstance(value, bool):
        raise DatasetValidationError(code)
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise DatasetValidationError(code) from exc


def _unique_int_tokens(path: Path) -> tuple[int, ...]:
    if not path.is_file():
        raise DatasetValidationError(f"missing_file:{path}")
    values: list[int] = []
    seen: set[int] = set()
    for token in path.read_text(encoding="utf-8").split():
        value = _as_int(token, f"invalid_id_token:{path}:{token}")
        if value in seen:
            raise DatasetValidationError(f"duplicate_done_id:{value}")
        seen.add(value)
        values.append(value)
    return tuple(sorted(values))


def _numeric_dirs(path: Path) -> tuple[int, ...]:
    if not path.is_dir():
        raise DatasetValidationError(f"missing_directory:{path}")
    return tuple(sorted(int(child.name) for child in path.iterdir() if child.is_dir() and child.name.isdigit()))


def derive_population(
    root: Path,
    hold_ids: Iterable[int],
    cp1_path: Path,
    *,
    expected_target_total: int = EXPECTED_TARGET_TOTAL,
    expected_collector_strict: int = EXPECTED_COLLECTOR_STRICT,
    expected_quarantine_total: int = EXPECTED_QUARANTINE_TOTAL,
    expected_hold_total: int = EXPECTED_HOLD_TOTAL,
    expected_eligible_total: int = EXPECTED_ELIGIBLE_TOTAL,
) -> PopulationAudit:
    """Derive the sole permitted Phase-2 population from immutable CP1 state."""
    root = Path(root)
    target_ids = _unique_int_tokens(root / "done_ids.txt")
    if len(target_ids) != expected_target_total:
        raise DatasetValidationError(
            f"target_total_mismatch:{len(target_ids)}!={expected_target_total}"
        )

    match_ids = _numeric_dirs(root / "matches")
    if match_ids != target_ids:
        missing = sorted(set(target_ids) - set(match_ids))[:20]
        extra = sorted(set(match_ids) - set(target_ids))[:20]
        raise DatasetValidationError(f"match_directory_id_mismatch:missing={missing}:extra={extra}")

    quarantine_ids = _numeric_dirs(root / "quarantine")
    if len(quarantine_ids) != expected_quarantine_total:
        raise DatasetValidationError(
            f"quarantine_total_mismatch:{len(quarantine_ids)}!={expected_quarantine_total}"
        )
    target_set = set(target_ids)
    quarantine_set = set(quarantine_ids)
    if not quarantine_set.issubset(target_set):
        raise DatasetValidationError("quarantine_not_subset_of_targets")

    strict_ids: list[int] = []
    season_by_match: dict[int, int] = {}
    for match_id in target_ids:
        metadata_path = root / "matches" / str(match_id) / f"{match_id}_Metadata.json"
        if metadata_path.is_file():
            metadata = _read_json(metadata_path)
            if _as_int(metadata.get("match_id"), "metadata_match_id_missing") != match_id:
                raise DatasetValidationError(f"metadata_match_id_mismatch:{match_id}")
            season_by_match[match_id] = _as_int(
                metadata.get("season_id"), f"metadata_season_id_missing:{match_id}"
            )
            if metadata.get("strict_prematch") is True:
                strict_ids.append(match_id)
        elif match_id not in quarantine_set:
            raise DatasetValidationError(f"strict_metadata_missing:{match_id}")

    strict_tuple = tuple(sorted(strict_ids))
    if len(strict_tuple) != expected_collector_strict:
        raise DatasetValidationError(
            f"collector_strict_total_mismatch:{len(strict_tuple)}!={expected_collector_strict}"
        )
    if set(strict_tuple) & quarantine_set:
        raise DatasetValidationError("strict_quarantine_overlap")
    if set(strict_tuple) | quarantine_set != target_set:
        raise DatasetValidationError("strict_quarantine_reconciliation_mismatch")

    hold_tuple = tuple(sorted(_as_int(value, "invalid_hold_id") for value in hold_ids))
    if len(hold_tuple) != len(set(hold_tuple)):
        raise DatasetValidationError("duplicate_hold_id")
    if len(hold_tuple) != expected_hold_total:
        raise DatasetValidationError(f"hold_total_mismatch:{len(hold_tuple)}!={expected_hold_total}")
    hold_set = set(hold_tuple)
    if not hold_set.issubset(set(strict_tuple)):
        raise DatasetValidationError("hold_not_subset_of_collector_strict")
    if hold_set & quarantine_set:
        raise DatasetValidationError("hold_quarantine_overlap")

    eligible_ids = tuple(sorted(set(strict_tuple) - hold_set))
    if len(eligible_ids) != expected_eligible_total:
        raise DatasetValidationError(
            f"eligible_total_mismatch:{len(eligible_ids)}!={expected_eligible_total}"
        )

    cp1 = _read_json(Path(cp1_path))
    expected_cp1 = {
        "checkpoint": "CP1_STRICT_DATASET",
        "status": "BLOCKED_REPAIR_REQUIRED",
        "collector_strict_label": expected_collector_strict,
        "cp1_eligible_strict": expected_eligible_total,
        "existing_quarantine": expected_quarantine_total,
        "new_cp1_audit_holds": expected_hold_total,
    }
    for key, expected in expected_cp1.items():
        if cp1.get(key) != expected:
            raise DatasetValidationError(f"cp1_contract_mismatch:{key}:{cp1.get(key)!r}!={expected!r}")

    return PopulationAudit(
        target_ids=target_ids,
        strict_ids=strict_tuple,
        quarantine_ids=quarantine_ids,
        hold_ids=hold_tuple,
        eligible_ids=eligible_ids,
        season_by_match={match_id: season_by_match[match_id] for match_id in eligible_ids},
    )


def _walk(value: Any, prefix: str):
    if isinstance(value, dict):
        for key, child in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            yield path, str(key), child
            yield from _walk(child, path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk(child, f"{prefix}[{index}]")


def _row_team_id(row: Any) -> int | None:
    if not isinstance(row, dict):
        return None
    for key in ("id", "team_id", "teamID"):
        if row.get(key) is not None:
            try:
                return int(row[key])
            except (TypeError, ValueError):
                return None
    return None


def load_validated_bundle(root: Path, match_id: int, season_id: int) -> BundleRecord:
    """Load one CP1-eligible bundle and validate every join before returning it."""
    root = Path(root)
    match_id = _as_int(match_id, "invalid_match_id")
    season_id = _as_int(season_id, "invalid_season_id")
    match_dir = root / "matches" / str(match_id)
    if not match_dir.is_dir():
        raise DatasetValidationError(f"match_directory_missing:{match_id}")

    fixed_paths = {
        "match": match_dir / f"{match_id}_MatchDaten.json",
        "form": match_dir / f"{match_id}_FormDaten.json",
        "table": match_dir / f"{match_id}_TableDaten.json",
        "player": match_dir / f"{match_id}_PlayerDaten.json",
        "result": match_dir / f"{match_id}_ResultTarget.json",
        "metadata": match_dir / f"{match_id}_Metadata.json",
    }
    league_paths = list(match_dir.glob(f"*_{match_id}_LeagueDaten.json"))
    if len(league_paths) != 1:
        raise DatasetValidationError(f"league_file_count_not_one:{match_id}:{len(league_paths)}")
    fixed_paths["league"] = league_paths[0]
    for key, path in fixed_paths.items():
        if not path.is_file():
            raise DatasetValidationError(f"bundle_file_missing:{key}:{path.name}")

    metadata = _read_json(fixed_paths["metadata"])
    if metadata.get("strict_prematch") is not True:
        raise DatasetValidationError(f"bundle_not_strict:{match_id}")
    if _as_int(metadata.get("match_id"), "metadata_match_id_missing") != match_id:
        raise DatasetValidationError(f"metadata_match_id_mismatch:{match_id}")
    if _as_int(metadata.get("season_id"), "metadata_season_id_missing") != season_id:
        raise DatasetValidationError(f"metadata_season_id_mismatch:{match_id}")
    home_id = _as_int(metadata.get("home_id"), f"metadata_home_id_missing:{match_id}")
    away_id = _as_int(metadata.get("away_id"), f"metadata_away_id_missing:{match_id}")
    kickoff = _as_int(metadata.get("kickoff_unix"), f"metadata_kickoff_missing:{match_id}")
    max_time = _as_int(
        metadata.get("requested_max_time"), f"metadata_requested_max_time_missing:{match_id}"
    )
    if max_time != kickoff - 1:
        raise DatasetValidationError(f"requested_max_time_not_kickoff_minus_1:{match_id}")

    expected_hashes = metadata.get("files_sha256")
    if not isinstance(expected_hashes, dict):
        raise DatasetValidationError(f"files_sha256_missing:{match_id}")
    source_hashes: dict[str, str] = {}
    for key, path in fixed_paths.items():
        if key == "metadata":
            continue
        expected = expected_hashes.get(path.name)
        if not isinstance(expected, str):
            raise DatasetValidationError(f"payload_sha256_missing:{match_id}:{path.name}")
        actual = _sha256(path)
        if actual != expected:
            raise DatasetValidationError(f"payload_sha256_mismatch:{match_id}:{path.name}")
        source_hashes[path.name] = actual

    match = _read_json(fixed_paths["match"])
    league = _read_json(fixed_paths["league"])
    form = _read_json(fixed_paths["form"])
    table = _read_json(fixed_paths["table"])
    player = _read_json(fixed_paths["player"])
    result = _read_json(fixed_paths["result"])
    feature_sources = {
        "match": match,
        "league": league,
        "form": form,
        "table": table,
        "player": player,
    }

    identity = match.get("identity") if isinstance(match, dict) else None
    if not isinstance(identity, dict) or match.get("found") is not True:
        raise DatasetValidationError(f"match_identity_missing:{match_id}")
    if _as_int(identity.get("match_id"), "identity_match_id_missing") != match_id:
        raise DatasetValidationError(f"identity_match_id_mismatch:{match_id}")
    if identity.get("season") is not None and _as_int(
        identity.get("season"), "identity_season_invalid"
    ) != season_id:
        raise DatasetValidationError(f"identity_season_id_mismatch:{match_id}")
    if _as_int(identity.get("homeID"), "identity_home_id_missing") != home_id:
        raise DatasetValidationError(f"identity_home_id_mismatch:{match_id}")
    if _as_int(identity.get("awayID"), "identity_away_id_missing") != away_id:
        raise DatasetValidationError(f"identity_away_id_mismatch:{match_id}")
    if match.get("stored_postmatch") is not False:
        raise DatasetValidationError(f"match_stored_postmatch_not_false:{match_id}")

    season_identity = league.get("season_safe_identity") or {}
    if season_identity.get("id") is not None and _as_int(
        season_identity.get("id"), "league_season_id_invalid"
    ) != season_id:
        raise DatasetValidationError(f"league_season_id_mismatch:{match_id}")
    league_team_ids = {
        value
        for value in (_row_team_id(row) for row in (league.get("teams_full_home_away") or []))
        if value is not None
    }
    if not {home_id, away_id}.issubset(league_team_ids):
        raise DatasetValidationError(f"league_target_team_rows_missing:{match_id}")

    if _as_int(form.get("home_id"), "form_home_id_missing") != home_id:
        raise DatasetValidationError(f"form_home_id_mismatch:{match_id}")
    if _as_int(form.get("away_id"), "form_away_id_missing") != away_id:
        raise DatasetValidationError(f"form_away_id_mismatch:{match_id}")
    if _as_int(form.get("kickoff_unix"), "form_kickoff_missing") != kickoff:
        raise DatasetValidationError(f"form_kickoff_mismatch:{match_id}")
    for side in ("home", "away"):
        for source in ((form.get(side) or {}).get("source_matches") or []):
            if _as_int(source.get("match_id"), "form_source_match_id_invalid") == match_id:
                raise DatasetValidationError(f"form_contains_target:{match_id}:{side}")
            if _as_int(source.get("date_unix"), "form_source_timestamp_invalid") >= kickoff:
                raise DatasetValidationError(f"form_source_not_before_kickoff:{match_id}:{side}")

    league_derived = league.get("league_aggregates_derived") or {}
    source_ids = {
        _as_int(value, "league_source_match_id_invalid")
        for value in (league_derived.get("league_source_match_ids") or [])
    }
    if match_id in source_ids:
        raise DatasetValidationError(f"league_contains_target:{match_id}")
    source_max = league_derived.get("league_source_max_timestamp")
    if source_max is not None and _as_int(source_max, "league_source_timestamp_invalid") >= kickoff:
        raise DatasetValidationError(f"league_source_not_before_kickoff:{match_id}")

    if _row_team_id(table.get("home_row")) != home_id:
        raise DatasetValidationError(f"table_home_team_id_mismatch:{match_id}")
    if _row_team_id(table.get("away_row")) != away_id:
        raise DatasetValidationError(f"table_away_team_id_mismatch:{match_id}")

    pagination = player.get("pagination") or {}
    if pagination.get("pagination_complete") is not True:
        raise DatasetValidationError(f"player_pagination_incomplete:{match_id}")
    total_results = _as_int(pagination.get("total_results"), "player_total_results_missing")
    loaded_rows = _as_int(pagination.get("loaded_rows"), "player_loaded_rows_missing")
    max_page = _as_int(pagination.get("max_page"), "player_max_page_missing")
    loaded_pages = _as_int(pagination.get("loaded_pages"), "player_loaded_pages_missing")
    if total_results and loaded_rows != total_results:
        raise DatasetValidationError(f"player_row_count_mismatch:{match_id}")
    if max_page and loaded_pages != max_page:
        raise DatasetValidationError(f"player_page_count_mismatch:{match_id}")
    for row in player.get("players") or []:
        club_id = row.get("club_team_id", row.get("team_id"))
        if _as_int(club_id, "player_club_team_id_missing") not in {home_id, away_id}:
            raise DatasetValidationError(f"player_team_id_mismatch:{match_id}")

    if _as_int(result.get("match_id"), "result_match_id_missing") != match_id:
        raise DatasetValidationError(f"result_match_id_mismatch:{match_id}")
    label = {
        "home_goals": _as_int(result.get("home_goals"), "label_home_goals_missing"),
        "away_goals": _as_int(result.get("away_goals"), "label_away_goals_missing"),
        "actual_1x2": result.get("actual_1x2"),
        "actual_btts": _as_int(result.get("actual_btts"), "label_actual_btts_missing"),
        "actual_over25": _as_int(
            result.get("actual_over25"), "label_actual_over25_missing"
        ),
    }
    if label["home_goals"] < 0 or label["away_goals"] < 0:
        raise DatasetValidationError(f"negative_goal_label:{match_id}")
    if label["actual_1x2"] not in {"H", "D", "A"}:
        raise DatasetValidationError(f"invalid_actual_1x2:{match_id}")
    if label["actual_btts"] not in {0, 1} or label["actual_over25"] not in {0, 1}:
        raise DatasetValidationError(f"invalid_binary_label:{match_id}")

    for source_name, payload in feature_sources.items():
        for path, key, _value in _walk(payload, source_name):
            if key in LABEL_KEYS:
                raise DatasetValidationError(f"label_key_in_feature_path:{match_id}:{path}")
            if "odd" in key.lower():
                raise DatasetValidationError(f"odds_like_feature_path:{match_id}:{path}")
            if source_name == "match" and key in MATCH_POSTMATCH_FORBIDDEN:
                raise DatasetValidationError(f"target_postmatch_feature_path:{match_id}:{path}")

    provenance = metadata.get("request_provenance")
    if not isinstance(provenance, list) or not provenance:
        raise DatasetValidationError(f"request_provenance_missing:{match_id}")
    for record in provenance:
        if _as_int(
            record.get("requested_max_time"), "provenance_requested_max_time_missing"
        ) != max_time:
            raise DatasetValidationError(f"provenance_max_time_mismatch:{match_id}")
        raw_hash = record.get("raw_response_sha256")
        if not isinstance(raw_hash, str) or len(raw_hash) != 64:
            raise DatasetValidationError(f"provenance_raw_sha256_invalid:{match_id}")

    null_paths = tuple(
        sorted(
            path
            for source_name, payload in feature_sources.items()
            for path, _key, value in _walk(payload, source_name)
            if value is None
        )
    )
    source_hashes[fixed_paths["metadata"].name] = _sha256(fixed_paths["metadata"])

    return BundleRecord(
        match_id=match_id,
        season_id=season_id,
        home_id=home_id,
        away_id=away_id,
        kickoff_unix=kickoff,
        requested_max_time=max_time,
        metadata=metadata,
        feature_sources=feature_sources,
        label=label,
        null_paths=null_paths,
        source_file_sha256=dict(sorted(source_hashes.items())),
    )


MASTER_COLUMNS = (
    "match_id",
    "season_id",
    "competition",
    "kickoff_unix",
    "kickoff_utc",
    "requested_max_time",
    "home_id",
    "away_id",
    "home_name",
    "away_name",
    "strict_prematch",
    "dataset_status",
    "feature_sources_json",
    "null_paths_json",
    "source_file_sha256_json",
    "request_provenance_json",
    "label_home_goals",
    "label_away_goals",
    "label_actual_1x2",
    "label_actual_btts",
    "label_actual_over25",
    "row_sha256",
)


def _bundle_to_row(bundle: BundleRecord) -> dict[str, Any]:
    metadata = bundle.metadata
    row: dict[str, Any] = {
        "match_id": bundle.match_id,
        "season_id": bundle.season_id,
        "competition": metadata.get("liga"),
        "kickoff_unix": bundle.kickoff_unix,
        "kickoff_utc": metadata.get("kickoff_utc"),
        "requested_max_time": bundle.requested_max_time,
        "home_id": bundle.home_id,
        "away_id": bundle.away_id,
        "home_name": metadata.get("home"),
        "away_name": metadata.get("away"),
        "strict_prematch": True,
        "dataset_status": "CP1_ELIGIBLE_STRICT",
        "feature_sources_json": canonical_json(bundle.feature_sources),
        "null_paths_json": canonical_json(list(bundle.null_paths)),
        "source_file_sha256_json": canonical_json(bundle.source_file_sha256),
        "request_provenance_json": canonical_json(metadata.get("request_provenance")),
        "label_home_goals": bundle.label["home_goals"],
        "label_away_goals": bundle.label["away_goals"],
        "label_actual_1x2": bundle.label["actual_1x2"],
        "label_actual_btts": bundle.label["actual_btts"],
        "label_actual_over25": bundle.label["actual_over25"],
    }
    row["row_sha256"] = canonical_sha256(row)
    return row


def _write_parquet_pyarrow(jsonl_path: Path, parquet_path: Path) -> None:
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise DatasetValidationError("pyarrow_required_for_parquet") from exc

    writer = None
    batch: list[dict[str, Any]] = []
    try:
        with jsonl_path.open(encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                batch.append(json.loads(line))
                if len(batch) >= 256:
                    table = pa.Table.from_pylist(batch)
                    if writer is None:
                        writer = pq.ParquetWriter(parquet_path, table.schema, compression="zstd")
                    writer.write_table(table)
                    batch.clear()
        if batch:
            table = pa.Table.from_pylist(batch)
            if writer is None:
                writer = pq.ParquetWriter(parquet_path, table.schema, compression="zstd")
            writer.write_table(table)
        if writer is None:
            raise DatasetValidationError("cannot_write_empty_parquet")
    finally:
        if writer is not None:
            writer.close()


def _read_parquet_pairs_pyarrow(parquet_path: Path):
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise DatasetValidationError("pyarrow_required_for_parquet") from exc
    parquet = pq.ParquetFile(parquet_path)
    for batch in parquet.iter_batches(columns=["match_id", "row_sha256"], batch_size=1024):
        data = batch.to_pydict()
        yield from zip(data["match_id"], data["row_sha256"])


def _artifact_info(path: Path) -> dict[str, Any]:
    return {"bytes": path.stat().st_size, "sha256": _sha256(path)}


def _id_sha256(ids: Iterable[int]) -> str:
    return hashlib.sha256(("\n".join(str(value) for value in ids) + "\n").encode("utf-8")).hexdigest()


def _check_feature_tree(match_id: int, sources: Any) -> None:
    if not isinstance(sources, dict) or set(sources) != {"match", "league", "form", "table", "player"}:
        raise DatasetValidationError(f"cp2_feature_source_set_invalid:{match_id}")
    for source_name, payload in sources.items():
        for path, key, _value in _walk(payload, source_name):
            if key in LABEL_KEYS:
                raise DatasetValidationError(f"cp2_label_key_in_feature:{match_id}:{path}")
            if "odd" in key.lower():
                raise DatasetValidationError(f"cp2_odds_key_in_feature:{match_id}:{path}")
            if source_name == "match" and key in MATCH_POSTMATCH_FORBIDDEN:
                raise DatasetValidationError(f"cp2_target_postmatch_in_feature:{match_id}:{path}")


def audit_master_outputs(
    output_dir: Path,
    population: PopulationAudit,
    *,
    parquet_reader=None,
) -> dict[str, Any]:
    """Independently reread all master representations and enforce CP2."""
    output_dir = Path(output_dir)
    parquet_reader = parquet_reader or _read_parquet_pairs_pyarrow
    jsonl_path = output_dir / "FULL7_MASTER_STRICT.jsonl"
    csv_path = output_dir / "FULL7_MASTER_STRICT.csv.gz"
    parquet_path = output_dir / "FULL7_MASTER_STRICT.parquet"
    for path in (jsonl_path, csv_path, parquet_path):
        if not path.is_file() or path.stat().st_size <= 0:
            raise DatasetValidationError(f"cp2_artifact_missing_or_empty:{path.name}")

    rows_by_id: dict[int, str] = {}
    label_counts = {"H": 0, "D": 0, "A": 0}
    null_path_counts: dict[str, int] = {}
    with jsonl_path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except Exception as exc:
                raise DatasetValidationError(f"cp2_jsonl_parse_error:{line_number}") from exc
            if len(row) != len(MASTER_COLUMNS) or set(row) != set(MASTER_COLUMNS):
                raise DatasetValidationError(f"cp2_column_contract_mismatch:{line_number}")
            match_id = _as_int(row.get("match_id"), "cp2_match_id_missing")
            if match_id in rows_by_id:
                raise DatasetValidationError(f"cp2_duplicate_match_id:{match_id}")
            calculated = canonical_sha256({key: value for key, value in row.items() if key != "row_sha256"})
            if row.get("row_sha256") != calculated:
                raise DatasetValidationError(f"cp2_row_sha256_mismatch:{match_id}")
            if row.get("strict_prematch") is not True or row.get("dataset_status") != "CP1_ELIGIBLE_STRICT":
                raise DatasetValidationError(f"cp2_strict_status_invalid:{match_id}")
            if _as_int(row.get("requested_max_time"), "cp2_max_time_missing") != _as_int(
                row.get("kickoff_unix"), "cp2_kickoff_missing"
            ) - 1:
                raise DatasetValidationError(f"cp2_max_time_violation:{match_id}")
            sources = json.loads(row["feature_sources_json"])
            _check_feature_tree(match_id, sources)
            if row.get("label_actual_1x2") not in label_counts:
                raise DatasetValidationError(f"cp2_label_1x2_invalid:{match_id}")
            label_counts[row["label_actual_1x2"]] += 1
            if row.get("label_actual_btts") not in {0, 1} or row.get("label_actual_over25") not in {0, 1}:
                raise DatasetValidationError(f"cp2_binary_label_invalid:{match_id}")
            if _as_int(row.get("label_home_goals"), "cp2_home_goals_missing") < 0 or _as_int(
                row.get("label_away_goals"), "cp2_away_goals_missing"
            ) < 0:
                raise DatasetValidationError(f"cp2_goal_label_invalid:{match_id}")
            hashes = json.loads(row["source_file_sha256_json"])
            if len(hashes) != 7 or any(len(value) != 64 for value in hashes.values()):
                raise DatasetValidationError(f"cp2_source_hash_contract_invalid:{match_id}")
            provenance = json.loads(row["request_provenance_json"])
            if not isinstance(provenance, list) or not provenance:
                raise DatasetValidationError(f"cp2_provenance_missing:{match_id}")
            null_paths = json.loads(row["null_paths_json"])
            if not isinstance(null_paths, list):
                raise DatasetValidationError(f"cp2_null_paths_invalid:{match_id}")
            for path in null_paths:
                null_path_counts[str(path)] = null_path_counts.get(str(path), 0) + 1
            rows_by_id[match_id] = row["row_sha256"]

    expected_ids = set(population.eligible_ids)
    actual_ids = set(rows_by_id)
    if actual_ids != expected_ids:
        raise DatasetValidationError(
            f"cp2_eligible_id_mismatch:missing={sorted(expected_ids-actual_ids)[:20]}:extra={sorted(actual_ids-expected_ids)[:20]}"
        )
    if actual_ids & set(population.quarantine_ids):
        raise DatasetValidationError("cp2_quarantine_overlap")
    if actual_ids & set(population.hold_ids):
        raise DatasetValidationError("cp2_hold_overlap")

    csv_pairs: list[tuple[int, str]] = []
    with gzip.open(csv_path, "rt", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != MASTER_COLUMNS:
            raise DatasetValidationError("cp2_csv_column_contract_mismatch")
        for row in reader:
            csv_pairs.append((int(row["match_id"]), row["row_sha256"]))
    expected_pairs = sorted(rows_by_id.items())
    if sorted(csv_pairs) != expected_pairs:
        raise DatasetValidationError("cp2_csv_jsonl_pair_mismatch")

    parquet_pairs = sorted((int(match_id), str(row_hash)) for match_id, row_hash in parquet_reader(parquet_path))
    if parquet_pairs != expected_pairs:
        raise DatasetValidationError("cp2_parquet_jsonl_pair_mismatch")

    return {
        "gate": "PASS",
        "row_count": len(rows_by_id),
        "unique_match_ids": len(actual_ids),
        "eligible_id_sha256": _id_sha256(sorted(actual_ids)),
        "quarantine_overlap": 0,
        "hold_overlap": 0,
        "duplicate_match_ids": 0,
        "missing_labels": 0,
        "label_1x2_counts": label_counts,
        "null_path_counts": dict(sorted(null_path_counts.items())),
        "odds_like_feature_hits": 0,
        "target_postmatch_feature_hits": 0,
        "join_failures": 0,
        "source_hash_failures": 0,
        "representations_equal": True,
    }


def _write_exclusions(root: Path, path: Path, population: PopulationAudit) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["match_id", "season_id", "exclusion_type", "reason"])
        for match_id in population.hold_ids:
            metadata = _read_json(root / "matches" / str(match_id) / f"{match_id}_Metadata.json")
            writer.writerow(
                [match_id, metadata["season_id"], "CP1_HOLD", "LEAGUE_TARGET_TEAM_ROWS_MISSING"]
            )
        for match_id in population.quarantine_ids:
            reason_path = root / "quarantine" / str(match_id) / "reason.json"
            reason = _read_json(reason_path)
            reasons = reason.get("reason_if_false") or ["UNKNOWN"]
            if not isinstance(reasons, list):
                reasons = [str(reasons)]
            writer.writerow(
                [match_id, reason.get("season_id"), "EXISTING_QUARANTINE", " | ".join(map(str, reasons))]
            )


def _data_dictionary() -> list[dict[str, str]]:
    roles = {
        "feature_sources_json": "FEATURE_CONTAINER",
        "null_paths_json": "MISSINGNESS",
        "source_file_sha256_json": "PROVENANCE",
        "request_provenance_json": "PROVENANCE",
        "label_home_goals": "LABEL_ONLY",
        "label_away_goals": "LABEL_ONLY",
        "label_actual_1x2": "LABEL_ONLY",
        "label_actual_btts": "LABEL_ONLY",
        "label_actual_over25": "LABEL_ONLY",
        "row_sha256": "INTEGRITY",
    }
    return [
        {
            "column": column,
            "role": roles.get(column, "IDENTITY_OR_CUTOFF"),
            "missingness_policy": "preserve source null; never impute",
            "leakage_policy": "labels are isolated; features are strict pre-match only",
        }
        for column in MASTER_COLUMNS
    ]


def build_master_dataset(
    root: Path,
    output_dir: Path,
    population: PopulationAudit,
    *,
    parquet_writer=None,
    parquet_reader=None,
) -> dict[str, Any]:
    """Stream, independently audit, and atomically publish CP2 artifacts."""
    root = Path(root)
    output_dir = Path(output_dir)
    if output_dir.exists():
        raise DatasetValidationError(f"output_directory_already_exists:{output_dir}")
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    stage = output_dir.parent / f".{output_dir.name}.stage-{uuid.uuid4().hex}"
    if stage.exists():  # practically impossible, but avoids broad deletion
        raise DatasetValidationError(f"stage_path_collision:{stage}")
    stage.mkdir()
    parquet_writer = parquet_writer or _write_parquet_pyarrow
    parquet_reader = parquet_reader or _read_parquet_pairs_pyarrow

    jsonl_path = stage / "FULL7_MASTER_STRICT.jsonl"
    csv_path = stage / "FULL7_MASTER_STRICT.csv.gz"
    provenance_path = stage / "FULL7_MASTER_PROVENANCE.jsonl"
    try:
        with (
            jsonl_path.open("w", encoding="utf-8") as jsonl_handle,
            gzip.open(csv_path, "wt", encoding="utf-8", newline="") as csv_handle,
            provenance_path.open("w", encoding="utf-8") as provenance_handle,
        ):
            writer = csv.DictWriter(csv_handle, fieldnames=MASTER_COLUMNS)
            writer.writeheader()
            for match_id in population.eligible_ids:
                bundle = load_validated_bundle(
                    root, match_id, population.season_by_match[match_id]
                )
                row = _bundle_to_row(bundle)
                jsonl_handle.write(canonical_json(row) + "\n")
                writer.writerow(row)
                provenance_handle.write(
                    canonical_json(
                        {
                            "match_id": match_id,
                            "season_id": bundle.season_id,
                            "kickoff_unix": bundle.kickoff_unix,
                            "requested_max_time": bundle.requested_max_time,
                            "source_file_sha256": bundle.source_file_sha256,
                            "request_provenance": bundle.metadata["request_provenance"],
                            "row_sha256": row["row_sha256"],
                        }
                    )
                    + "\n"
                )

        parquet_path = stage / "FULL7_MASTER_STRICT.parquet"
        parquet_writer(jsonl_path, parquet_path)
        _write_exclusions(root, stage / "FULL7_QUARANTINE_FINAL.csv", population)
        dictionary = _data_dictionary()
        (stage / "FULL7_MASTER_DATA_DICTIONARY.json").write_text(
            json.dumps(dictionary, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        (stage / "FULL7_MASTER_DATA_DICTIONARY.txt").write_text(
            "\n".join(
                f"{item['column']}\t{item['role']}\t{item['missingness_policy']}\t{item['leakage_policy']}"
                for item in dictionary
            )
            + "\n",
            encoding="utf-8",
        )

        audit = audit_master_outputs(stage, population, parquet_reader=parquet_reader)
        (stage / "CP2_MASTER_DATASET_AUDIT.json").write_text(
            json.dumps(audit, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        (stage / "CP2_MASTER_DATASET_AUDIT.txt").write_text(
            "\n".join(f"{key}: {canonical_json(value)}" for key, value in audit.items()) + "\n",
            encoding="utf-8",
        )

        artifact_names = sorted(path.name for path in stage.iterdir() if path.is_file())
        manifest = {
            "dataset_version": "FULL7_MASTER_STRICT_CP2_2026-09-22",
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "match_count_input": len(population.target_ids),
            "match_count_valid": len(population.eligible_ids),
            "existing_quarantine": len(population.quarantine_ids),
            "cp1_holds": len(population.hold_ids),
            "match_count_excluded": len(population.quarantine_ids) + len(population.hold_ids),
            "eligible_id_sha256": _id_sha256(population.eligible_ids),
            "artifacts": {name: _artifact_info(stage / name) for name in artifact_names},
        }
        (stage / "FULL7_MASTER_BUILD_MANIFEST.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        files_created = sorted(path.name for path in stage.iterdir() if path.is_file())
        checkpoint = {
            "checkpoint": "CP2_MASTER_DATASET",
            "status": "COMPLETE",
            "gate": "PASS",
            "model_used": "GPT-5.6 Sol",
            "dataset_version": manifest["dataset_version"],
            "match_count_input": len(population.target_ids),
            "match_count_valid": len(population.eligible_ids),
            "match_count_quarantined": len(population.quarantine_ids),
            "new_cp1_holds_excluded": len(population.hold_ids),
            "match_count_excluded": len(population.quarantine_ids) + len(population.hold_ids),
            "eligible_id_sha256": audit["eligible_id_sha256"],
            "files_created_or_changed": files_created,
            "validations_completed": audit,
            "known_problems": [],
            "open_questions": [],
            "next_phase": "PHASE 3 — FULL FEATURE AUDIT",
            "resume_instruction": "Run Phase 3 only from this passing CP2 artifact set.",
        }
        (stage / "CP2_MASTER_DATASET.json").write_text(
            json.dumps(checkpoint, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        (stage / "CP2_MASTER_DATASET.txt").write_text(
            "\n".join(f"{key}: {canonical_json(value)}" for key, value in checkpoint.items()) + "\n",
            encoding="utf-8",
        )
        stage.rename(output_dir)
        return checkpoint
    except Exception:
        if stage.is_dir() and stage.parent == output_dir.parent and stage.name.startswith(
            f".{output_dir.name}.stage-"
        ):
            shutil.rmtree(stage)
        raise
