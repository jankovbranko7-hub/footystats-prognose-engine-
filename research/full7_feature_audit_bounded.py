#!/usr/bin/env python3
"""Bounded-memory, crash-safe FULL-7 Phase-3 feature audit.

This implementation preserves the full Phase-3 audit scope while moving
cross-match state, deterministic samples, season statistics, correlation
progress, and top redundancy results to SQLite on the persistent disk.
"""
from __future__ import annotations

import hashlib
import heapq
import json
import math
import os
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from research.full7_feature_audit import (
    FeatureAuditError,
    _derived_features,
    _mandatory_groups,
    _sha256,
    _walk_leaves,
    classify_path,
)

STATE_SCHEMA_VERSION = "FULL7_CP3_BOUNDED_STATE_1.0"
AUDIT_VERSION = "FULL7_FEATURE_AUDIT_2.0_BOUNDED"
PROFILE_CHUNK_ROWS = 8
NUMERIC_SAMPLE_CAPACITY = 512
SCALAR_SAMPLE_CAPACITY = 1024
CORRELATION_BLOCK_PATHS = 24


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_atomic(path: Path, payload: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    temporary.replace(path)


def _score(token: str) -> int:
    return int.from_bytes(hashlib.sha256(token.encode("utf-8")).digest()[:8], "big")


def _push_lowest(heap: list[tuple], capacity: int, score: int, *payload: Any) -> None:
    entry = (-score, *payload)
    if len(heap) < capacity:
        heapq.heappush(heap, entry)
    elif score < -heap[0][0]:
        heapq.heapreplace(heap, entry)


@dataclass
class NumericAgg:
    count: int = 0
    total: float = 0.0
    total_sq: float = 0.0
    minimum: float | None = None
    maximum: float | None = None
    zero_count: int = 0

    def add(self, value: float) -> None:
        self.count += 1
        self.total += value
        self.total_sq += value * value
        self.minimum = value if self.minimum is None else min(self.minimum, value)
        self.maximum = value if self.maximum is None else max(self.maximum, value)
        self.zero_count += int(value == 0)


@dataclass
class SeasonChunk:
    matches_non_null: int = 0
    numeric: NumericAgg = field(default_factory=NumericAgg)


@dataclass
class PathChunk:
    path: str
    derived_name: str | None = None
    value_count: int = 0
    null_value_count: int = 0
    matches_present: int = 0
    matches_non_null: int = 0
    types: Counter = field(default_factory=Counter)
    numeric: NumericAgg = field(default_factory=NumericAgg)
    seasons: dict[int, SeasonChunk] = field(default_factory=lambda: defaultdict(SeasonChunk))
    numeric_samples: list[tuple] = field(default_factory=list)
    scalar_samples: list[tuple] = field(default_factory=list)
    source_fields: Counter = field(default_factory=Counter)

    def add_match(
        self,
        match_id: int,
        season_id: int,
        values: list[Any],
        *,
        source_field: str | None = None,
    ) -> None:
        self.matches_present += 1
        non_null = False
        numeric_values: list[float] = []
        season = self.seasons[season_id]
        for ordinal, value in enumerate(values):
            self.value_count += 1
            if value is None:
                self.null_value_count += 1
                self.types["null"] += 1
                continue
            non_null = True
            type_name = "bool" if isinstance(value, bool) else type(value).__name__
            self.types[type_name] += 1
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                number = float(value)
                if math.isfinite(number):
                    numeric_values.append(number)
                    self.numeric.add(number)
                    season.numeric.add(number)
                    sample_score = _score(f"{self.path}|{match_id}|{ordinal}|{number}")
                    _push_lowest(
                        self.numeric_samples,
                        NUMERIC_SAMPLE_CAPACITY,
                        sample_score,
                        match_id,
                        ordinal,
                        number,
                    )
        if non_null:
            self.matches_non_null += 1
            season.matches_non_null += 1
        if "[]" not in self.path and len(numeric_values) == 1:
            scalar_score = _score(str(match_id))
            _push_lowest(
                self.scalar_samples,
                SCALAR_SAMPLE_CAPACITY,
                scalar_score,
                match_id,
                numeric_values[0],
            )
        if source_field:
            self.source_fields[source_field] += 1


def _connect(state_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(state_path)
    conn.execute("PRAGMA journal_mode=DELETE")
    conn.execute("PRAGMA synchronous=FULL")
    conn.execute("PRAGMA temp_store=FILE")
    conn.execute("PRAGMA cache_size=-32768")
    conn.execute("PRAGMA mmap_size=0")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS processed_matches (
            match_id INTEGER PRIMARY KEY,
            season_id INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS season_totals (
            season_id INTEGER PRIMARY KEY,
            rows INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS path_stats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            path TEXT NOT NULL UNIQUE,
            source TEXT NOT NULL,
            derived_name TEXT,
            value_count INTEGER NOT NULL DEFAULT 0,
            null_value_count INTEGER NOT NULL DEFAULT 0,
            matches_present INTEGER NOT NULL DEFAULT 0,
            matches_non_null INTEGER NOT NULL DEFAULT 0,
            numeric_count INTEGER NOT NULL DEFAULT 0,
            numeric_sum REAL NOT NULL DEFAULT 0.0,
            numeric_sumsq REAL NOT NULL DEFAULT 0.0,
            numeric_min REAL,
            numeric_max REAL,
            zero_count INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS path_types (
            path_id INTEGER NOT NULL REFERENCES path_stats(id) ON DELETE CASCADE,
            type_name TEXT NOT NULL,
            count INTEGER NOT NULL,
            PRIMARY KEY(path_id, type_name)
        );
        CREATE TABLE IF NOT EXISTS path_seasons (
            path_id INTEGER NOT NULL REFERENCES path_stats(id) ON DELETE CASCADE,
            season_id INTEGER NOT NULL,
            matches_non_null INTEGER NOT NULL DEFAULT 0,
            numeric_count INTEGER NOT NULL DEFAULT 0,
            numeric_sum REAL NOT NULL DEFAULT 0.0,
            numeric_sumsq REAL NOT NULL DEFAULT 0.0,
            numeric_min REAL,
            numeric_max REAL,
            zero_count INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY(path_id, season_id)
        );
        CREATE TABLE IF NOT EXISTS source_fields (
            path_id INTEGER NOT NULL REFERENCES path_stats(id) ON DELETE CASCADE,
            source_field TEXT NOT NULL,
            count INTEGER NOT NULL,
            PRIMARY KEY(path_id, source_field)
        );
        CREATE TABLE IF NOT EXISTS numeric_sample (
            path_id INTEGER NOT NULL REFERENCES path_stats(id) ON DELETE CASCADE,
            score TEXT NOT NULL,
            match_id INTEGER NOT NULL,
            ordinal INTEGER NOT NULL,
            value REAL NOT NULL,
            PRIMARY KEY(path_id, score, match_id, ordinal)
        );
        CREATE INDEX IF NOT EXISTS numeric_sample_path_score
            ON numeric_sample(path_id, score, match_id, ordinal);
        CREATE TABLE IF NOT EXISTS scalar_sample (
            path_id INTEGER NOT NULL REFERENCES path_stats(id) ON DELETE CASCADE,
            score TEXT NOT NULL,
            match_id INTEGER NOT NULL,
            value REAL NOT NULL,
            PRIMARY KEY(path_id, match_id)
        );
        CREATE INDEX IF NOT EXISTS scalar_sample_path_score
            ON scalar_sample(path_id, score, match_id);
        CREATE TABLE IF NOT EXISTS redundancy_top (
            path_a TEXT NOT NULL,
            path_b TEXT NOT NULL,
            overlap INTEGER NOT NULL,
            pearson_r REAL NOT NULL,
            abs_r REAL NOT NULL,
            PRIMARY KEY(path_a, path_b)
        );
        """
    )
    conn.commit()


def _get_meta(conn: sqlite3.Connection, key: str, default: str | None = None) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row[0] if row else default


def _set_meta(conn: sqlite3.Connection, key: str, value: Any) -> None:
    conn.execute(
        "INSERT INTO meta(key,value) VALUES(?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, str(value)),
    )


def _initialize_or_validate_state(
    conn: sqlite3.Connection,
    *,
    master_sha256: str,
    expected_rows: int,
) -> None:
    _schema(conn)
    version = _get_meta(conn, "schema_version")
    if version is None:
        with conn:
            _set_meta(conn, "schema_version", STATE_SCHEMA_VERSION)
            _set_meta(conn, "master_sha256", master_sha256)
            _set_meta(conn, "expected_rows", expected_rows)
            _set_meta(conn, "profile_processed_rows", 0)
            _set_meta(conn, "profile_byte_offset", 0)
            _set_meta(conn, "profile_complete", 0)
            _set_meta(conn, "catalog_complete", 0)
            _set_meta(conn, "correlation_complete", 0)
            _set_meta(conn, "corr_block_i", 0)
            _set_meta(conn, "corr_block_j", 0)
            _set_meta(conn, "corr_pairs_evaluated", 0)
            _set_meta(conn, "corr_pairs_meeting_overlap", 0)
            _set_meta(conn, "corr_pairs_high", 0)
        return
    if version != STATE_SCHEMA_VERSION:
        raise FeatureAuditError(f"cp3_state_schema_mismatch:{version}")
    if _get_meta(conn, "master_sha256") != master_sha256:
        raise FeatureAuditError("cp3_state_master_hash_mismatch")
    if int(_get_meta(conn, "expected_rows", "-1")) != expected_rows:
        raise FeatureAuditError("cp3_state_expected_rows_mismatch")
    check = conn.execute("PRAGMA quick_check").fetchone()
    if not check or check[0] != "ok":
        raise FeatureAuditError(f"cp3_state_sqlite_integrity_failed:{check}")


def _classify_stage_entries(entries: list[dict[str, Any]]) -> str:
    names = {entry["path"] for entry in entries}
    if "FULL7_FEATURE_AUDIT_MANIFEST.json" in names:
        return "LEGACY_CP3_MANIFEST_PRESENT"
    if "CP3_FEATURE_AUDIT.json" in names:
        return "LEGACY_CP3_CHECKPOINT_PRESENT"
    if "FULL7_FEATURE_AUDIT.txt" in names:
        return "LEGACY_CP3_SUMMARY_PRESENT"
    if "FULL7_REDUNDANCY_AUDIT.json" in names:
        return "LEGACY_REDUNDANCY_OUTPUT_PRESENT"
    if "FULL7_DERIVED_FEATURE_CATALOG.json" in names:
        return "LEGACY_DERIVED_CATALOG_PRESENT"
    if "FULL7_FEATURE_CATALOG.jsonl" in names:
        return "LEGACY_FEATURE_CATALOG_PRESENT"
    if "FULL7_FEATURE_AUDIT.json" in names:
        return "LEGACY_PROFILE_MASTER_COMPLETE"
    return "CP2_GATE_AND_MASTER_HASH_VALIDATION_COMPLETE__PROFILE_MASTER_INCOMPLETE"


def inspect_stage_once(stage: Path) -> dict[str, Any]:
    inspection_path = stage / "CP3_STAGE_INSPECTION.json"
    if inspection_path.is_file():
        return json.loads(inspection_path.read_text(encoding="utf-8"))

    entries: list[dict[str, Any]] = []
    for path in sorted(stage.rglob("*")):
        if path == inspection_path:
            continue
        relative = path.relative_to(stage).as_posix()
        if path.is_dir():
            entries.append({"path": relative, "kind": "directory"})
            continue
        item: dict[str, Any] = {
            "path": relative,
            "kind": "file",
            "bytes": path.stat().st_size,
            "sha256": _sha256(path),
        }
        if path.suffix in {".json", ".jsonl"} and path.name != "FULL7_FEATURE_CATALOG.jsonl":
            if path.suffix == ".json":
                try:
                    json.loads(path.read_text(encoding="utf-8"))
                    item["json_valid"] = True
                except Exception as exc:
                    item["json_valid"] = False
                    item["json_error"] = f"{type(exc).__name__}:{exc}"
        entries.append(item)

    legacy_names = {
        "FULL7_FEATURE_AUDIT.json",
        "FULL7_FEATURE_CATALOG.jsonl",
        "FULL7_DERIVED_FEATURE_CATALOG.json",
        "FULL7_REDUNDANCY_AUDIT.json",
        "FULL7_FEATURE_AUDIT.txt",
        "CP3_FEATURE_AUDIT.json",
        "CP3_FEATURE_AUDIT.txt",
        "FULL7_FEATURE_AUDIT_MANIFEST.json",
    }
    inspection = {
        "inspection": "FULL7_CP3_STAGE_INSPECTION_1.0",
        "inspected_at_utc": _utcnow(),
        "stage": str(stage),
        "entry_count_before_inspection": len(entries),
        "entries_before_inspection": entries,
        "last_fully_completed_substep": _classify_stage_entries(entries),
        "legacy_phase3_artifacts": sorted(
            entry["path"] for entry in entries if entry["path"] in legacy_names
        ),
        "mutation_of_existing_entries": False,
    }
    _json_atomic(inspection_path, inspection)
    return inspection


def _upsert_path(conn: sqlite3.Connection, item: PathChunk) -> int:
    source = item.path.split(".", 1)[0]
    n = item.numeric
    conn.execute(
        """
        INSERT INTO path_stats(
            path, source, derived_name, value_count, null_value_count,
            matches_present, matches_non_null, numeric_count, numeric_sum,
            numeric_sumsq, numeric_min, numeric_max, zero_count
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(path) DO UPDATE SET
            value_count=path_stats.value_count+excluded.value_count,
            null_value_count=path_stats.null_value_count+excluded.null_value_count,
            matches_present=path_stats.matches_present+excluded.matches_present,
            matches_non_null=path_stats.matches_non_null+excluded.matches_non_null,
            numeric_count=path_stats.numeric_count+excluded.numeric_count,
            numeric_sum=path_stats.numeric_sum+excluded.numeric_sum,
            numeric_sumsq=path_stats.numeric_sumsq+excluded.numeric_sumsq,
            numeric_min=CASE
                WHEN excluded.numeric_min IS NULL THEN path_stats.numeric_min
                WHEN path_stats.numeric_min IS NULL THEN excluded.numeric_min
                ELSE MIN(path_stats.numeric_min, excluded.numeric_min)
            END,
            numeric_max=CASE
                WHEN excluded.numeric_max IS NULL THEN path_stats.numeric_max
                WHEN path_stats.numeric_max IS NULL THEN excluded.numeric_max
                ELSE MAX(path_stats.numeric_max, excluded.numeric_max)
            END,
            zero_count=path_stats.zero_count+excluded.zero_count
        """,
        (
            item.path,
            source,
            item.derived_name,
            item.value_count,
            item.null_value_count,
            item.matches_present,
            item.matches_non_null,
            n.count,
            n.total,
            n.total_sq,
            n.minimum,
            n.maximum,
            n.zero_count,
        ),
    )
    row = conn.execute("SELECT id FROM path_stats WHERE path=?", (item.path,)).fetchone()
    if not row:
        raise FeatureAuditError(f"cp3_path_id_missing:{item.path}")
    return int(row[0])


def _merge_chunk(
    conn: sqlite3.Connection,
    chunk: dict[str, PathChunk],
    season_rows: Counter,
    processed_matches: list[tuple[int, int]],
    *,
    processed_total: int,
    byte_offset: int,
) -> None:
    with conn:
        conn.executemany(
            "INSERT INTO processed_matches(match_id,season_id) VALUES(?,?)",
            processed_matches,
        )
        for season_id, count in season_rows.items():
            conn.execute(
                "INSERT INTO season_totals(season_id,rows) VALUES(?,?) "
                "ON CONFLICT(season_id) DO UPDATE SET rows=season_totals.rows+excluded.rows",
                (season_id, count),
            )

        for item in chunk.values():
            path_id = _upsert_path(conn, item)
            for type_name, count in item.types.items():
                conn.execute(
                    "INSERT INTO path_types(path_id,type_name,count) VALUES(?,?,?) "
                    "ON CONFLICT(path_id,type_name) DO UPDATE SET count=path_types.count+excluded.count",
                    (path_id, type_name, count),
                )
            for season_id, season in item.seasons.items():
                n = season.numeric
                conn.execute(
                    """
                    INSERT INTO path_seasons(
                        path_id,season_id,matches_non_null,numeric_count,numeric_sum,
                        numeric_sumsq,numeric_min,numeric_max,zero_count
                    ) VALUES(?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(path_id,season_id) DO UPDATE SET
                        matches_non_null=path_seasons.matches_non_null+excluded.matches_non_null,
                        numeric_count=path_seasons.numeric_count+excluded.numeric_count,
                        numeric_sum=path_seasons.numeric_sum+excluded.numeric_sum,
                        numeric_sumsq=path_seasons.numeric_sumsq+excluded.numeric_sumsq,
                        numeric_min=CASE
                            WHEN excluded.numeric_min IS NULL THEN path_seasons.numeric_min
                            WHEN path_seasons.numeric_min IS NULL THEN excluded.numeric_min
                            ELSE MIN(path_seasons.numeric_min, excluded.numeric_min)
                        END,
                        numeric_max=CASE
                            WHEN excluded.numeric_max IS NULL THEN path_seasons.numeric_max
                            WHEN path_seasons.numeric_max IS NULL THEN excluded.numeric_max
                            ELSE MAX(path_seasons.numeric_max, excluded.numeric_max)
                        END,
                        zero_count=path_seasons.zero_count+excluded.zero_count
                    """,
                    (
                        path_id,
                        season_id,
                        season.matches_non_null,
                        n.count,
                        n.total,
                        n.total_sq,
                        n.minimum,
                        n.maximum,
                        n.zero_count,
                    ),
                )
            for source_field, count in item.source_fields.items():
                conn.execute(
                    "INSERT INTO source_fields(path_id,source_field,count) VALUES(?,?,?) "
                    "ON CONFLICT(path_id,source_field) DO UPDATE SET count=source_fields.count+excluded.count",
                    (path_id, source_field, count),
                )

            if item.numeric_samples:
                conn.executemany(
                    "INSERT OR IGNORE INTO numeric_sample(path_id,score,match_id,ordinal,value) "
                    "VALUES(?,?,?,?,?)",
                    [
                        (
                            path_id,
                            f"{-entry[0]:016x}",
                            int(entry[1]),
                            int(entry[2]),
                            float(entry[3]),
                        )
                        for entry in item.numeric_samples
                    ],
                )
                conn.execute(
                    """
                    DELETE FROM numeric_sample
                    WHERE rowid IN (
                        SELECT rowid FROM numeric_sample
                        WHERE path_id=?
                        ORDER BY score ASC, match_id ASC, ordinal ASC
                        LIMIT -1 OFFSET ?
                    )
                    """,
                    (path_id, NUMERIC_SAMPLE_CAPACITY),
                )

            if item.scalar_samples:
                conn.executemany(
                    "INSERT INTO scalar_sample(path_id,score,match_id,value) VALUES(?,?,?,?) "
                    "ON CONFLICT(path_id,match_id) DO UPDATE SET "
                    "score=excluded.score,value=excluded.value",
                    [
                        (
                            path_id,
                            f"{-entry[0]:016x}",
                            int(entry[1]),
                            float(entry[2]),
                        )
                        for entry in item.scalar_samples
                    ],
                )
                conn.execute(
                    """
                    DELETE FROM scalar_sample
                    WHERE rowid IN (
                        SELECT rowid FROM scalar_sample
                        WHERE path_id=?
                        ORDER BY score ASC, match_id ASC
                        LIMIT -1 OFFSET ?
                    )
                    """,
                    (path_id, SCALAR_SAMPLE_CAPACITY),
                )

        _set_meta(conn, "profile_processed_rows", processed_total)
        _set_meta(conn, "profile_byte_offset", byte_offset)


def _profile_stream(
    conn: sqlite3.Connection,
    master_path: Path,
    stage: Path,
    *,
    expected_rows: int,
) -> None:
    if _get_meta(conn, "profile_complete", "0") == "1":
        return

    processed = int(_get_meta(conn, "profile_processed_rows", "0"))
    offset = int(_get_meta(conn, "profile_byte_offset", "0"))
    if conn.execute("SELECT COUNT(*) FROM processed_matches").fetchone()[0] != processed:
        raise FeatureAuditError("cp3_profile_checkpoint_count_mismatch")

    with master_path.open("rb") as handle:
        handle.seek(offset)
        while True:
            chunk: dict[str, PathChunk] = {}
            chunk_seasons: Counter = Counter()
            chunk_matches: list[tuple[int, int]] = []
            read_any = False

            for _ in range(PROFILE_CHUNK_ROWS):
                line = handle.readline()
                if not line:
                    break
                if not line.strip():
                    continue
                read_any = True
                row = json.loads(line)
                match_id = int(row["match_id"])
                season_id = int(row["season_id"])
                chunk_matches.append((match_id, season_id))
                chunk_seasons[season_id] += 1

                sources = json.loads(row["feature_sources_json"])
                per_path: dict[str, list[Any]] = defaultdict(list)
                for source_name, payload in sources.items():
                    for path, value in _walk_leaves(payload, source_name):
                        classification = classify_path(path)
                        if classification["research_eligibility"].startswith("BLOCKED_"):
                            raise FeatureAuditError(f"blocked_feature_path:{match_id}:{path}")
                        per_path[path].append(value)

                for path, values in per_path.items():
                    item = chunk.get(path)
                    if item is None:
                        item = PathChunk(path=path)
                        chunk[path] = item
                    item.add_match(match_id, season_id, values)

                for name, (value, source_field) in _derived_features(row, sources).items():
                    path = f"derived.{name}"
                    item = chunk.get(path)
                    if item is None:
                        item = PathChunk(path=path, derived_name=name)
                        chunk[path] = item
                    item.add_match(
                        match_id,
                        season_id,
                        [value],
                        source_field=source_field,
                    )

            if not read_any:
                break

            processed += len(chunk_matches)
            byte_offset = handle.tell()
            _merge_chunk(
                conn,
                chunk,
                chunk_seasons,
                chunk_matches,
                processed_total=processed,
                byte_offset=byte_offset,
            )
            _json_atomic(
                stage / "CP3_PROGRESS.json",
                {
                    "checkpoint": "CP3_PROFILE_STREAM",
                    "status": "RUNNING",
                    "processed_rows": processed,
                    "expected_rows": expected_rows,
                    "byte_offset": byte_offset,
                    "profile_chunk_rows": PROFILE_CHUNK_ROWS,
                    "state_database": "PHASE3_STATE.sqlite3",
                    "updated_at_utc": _utcnow(),
                },
            )

    if processed != expected_rows:
        raise FeatureAuditError(f"cp3_master_row_count_mismatch:{processed}!={expected_rows}")
    unique_matches = conn.execute("SELECT COUNT(*) FROM processed_matches").fetchone()[0]
    if unique_matches != expected_rows:
        raise FeatureAuditError(
            f"cp3_unique_match_count_mismatch:{unique_matches}!={expected_rows}"
        )
    season_total = conn.execute("SELECT COALESCE(SUM(rows),0) FROM season_totals").fetchone()[0]
    if season_total != expected_rows:
        raise FeatureAuditError(
            f"cp3_season_total_mismatch:{season_total}!={expected_rows}"
        )

    with conn:
        _set_meta(conn, "profile_complete", 1)

    profile_checkpoint = {
        "checkpoint": "CP3_PROFILE_STREAM",
        "status": "COMPLETE",
        "gate": "PASS",
        "rows_profiled": expected_rows,
        "unique_match_ids": unique_matches,
        "path_count": conn.execute("SELECT COUNT(*) FROM path_stats").fetchone()[0],
        "derived_feature_count": conn.execute(
            "SELECT COUNT(*) FROM path_stats WHERE derived_name IS NOT NULL"
        ).fetchone()[0],
        "state_database": "PHASE3_STATE.sqlite3",
        "sqlite_quick_check": conn.execute("PRAGMA quick_check").fetchone()[0],
        "completed_at_utc": _utcnow(),
    }
    _json_atomic(stage / "CP3_PROFILE_PASS.json", profile_checkpoint)


def _variance(count: int, total: float, total_sq: float) -> float:
    if count <= 1:
        return 0.0
    value = (total_sq - (total * total) / count) / (count - 1)
    return max(0.0, value)


def _quantile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    position = (len(values) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return values[lower]
    return values[lower] + (values[upper] - values[lower]) * (position - lower)


def _finalize_path(
    conn: sqlite3.Connection,
    row: sqlite3.Row,
    *,
    total_rows: int,
    season_totals: list[tuple[int, int]],
) -> dict[str, Any]:
    path_id = int(row["id"])
    path = str(row["path"])
    numeric_count = int(row["numeric_count"])
    total = float(row["numeric_sum"])
    total_sq = float(row["numeric_sumsq"])
    sample = [
        float(value)
        for (value,) in conn.execute(
            "SELECT value FROM numeric_sample WHERE path_id=? ORDER BY value ASC",
            (path_id,),
        )
    ]
    q1 = _quantile(sample, 0.25)
    median = _quantile(sample, 0.5)
    q3 = _quantile(sample, 0.75)
    if q1 is not None and q3 is not None:
        iqr = q3 - q1
        low = q1 - 1.5 * iqr
        high = q3 + 1.5 * iqr
        outliers = sum(value < low or value > high for value in sample)
    else:
        iqr = low = high = None
        outliers = 0

    season_map = {
        int(season_id): (
            int(non_null),
            int(n_count),
            float(n_sum),
            float(n_sumsq),
        )
        for season_id, non_null, n_count, n_sum, n_sumsq in conn.execute(
            "SELECT season_id,matches_non_null,numeric_count,numeric_sum,numeric_sumsq "
            "FROM path_seasons WHERE path_id=?",
            (path_id,),
        )
    }
    season_rows = []
    for season_id, rows in season_totals:
        non_null, n_count, n_sum, _n_sumsq = season_map.get(
            season_id, (0, 0, 0.0, 0.0)
        )
        season_rows.append(
            {
                "season_id": season_id,
                "rows": rows,
                "matches_non_null": non_null,
                "coverage_rate": round(non_null / rows, 12),
                "numeric_mean": round(n_sum / n_count, 12) if n_count else None,
            }
        )
    coverages = [item["coverage_rate"] for item in season_rows]
    types = {
        str(name): int(count)
        for name, count in conn.execute(
            "SELECT type_name,count FROM path_types WHERE path_id=? ORDER BY type_name",
            (path_id,),
        )
    }
    source_fields = {
        str(name): int(count)
        for name, count in conn.execute(
            "SELECT source_field,count FROM source_fields WHERE path_id=? ORDER BY source_field",
            (path_id,),
        )
    }
    classification = classify_path(path)
    matches_non_null = int(row["matches_non_null"])
    numeric = {
        "count": numeric_count,
        "min": row["numeric_min"],
        "max": row["numeric_max"],
        "mean": round(total / numeric_count, 12) if numeric_count else None,
        "stddev": round(
            math.sqrt(_variance(numeric_count, total, total_sq)), 12
        )
        if numeric_count
        else None,
        "zero_rate": round(int(row["zero_count"]) / numeric_count, 12)
        if numeric_count
        else None,
        "sample_size": len(sample),
        "q1": q1,
        "median": median,
        "q3": q3,
        "iqr": iqr,
        "outlier_lower_fence": low,
        "outlier_upper_fence": high,
        "sample_outlier_count": outliers,
        "outlier_method": "IQR_ON_DETERMINISTIC_SAMPLE",
    }
    result = {
        "path": path,
        "source": path.split(".", 1)[0],
        "data_types": types,
        "value_count": int(row["value_count"]),
        "null_value_count": int(row["null_value_count"]),
        "matches_present": int(row["matches_present"]),
        "matches_non_null": matches_non_null,
        "coverage_rate": round(matches_non_null / total_rows, 12),
        "missingness_rate": round(1 - matches_non_null / total_rows, 12),
        "numeric": numeric,
        "season_stability": {
            "season_count": len(season_rows),
            "coverage_min": min(coverages) if coverages else None,
            "coverage_max": max(coverages) if coverages else None,
            "by_season": season_rows,
        },
        "source_fields": source_fields,
        **classification,
    }
    if row["derived_name"] is not None:
        result["feature"] = str(row["derived_name"])
        result["definition"] = (
            "Explicit deterministic derivation; source fields listed in source_fields"
        )
    return result


def _write_catalogs(
    conn: sqlite3.Connection,
    stage: Path,
    *,
    expected_rows: int,
) -> dict[str, int]:
    if _get_meta(conn, "catalog_complete", "0") == "1":
        checkpoint = json.loads(
            (stage / "CP3_CATALOG_PASS.json").read_text(encoding="utf-8")
        )
        for name, expected_hash in checkpoint["sha256"].items():
            path = stage / name
            if not path.is_file() or _sha256(path) != expected_hash:
                raise FeatureAuditError(f"cp3_catalog_hash_mismatch:{name}")
        return {
            "field_count": int(checkpoint["field_count"]),
            "derived_feature_count": int(checkpoint["derived_feature_count"]),
        }

    conn.row_factory = sqlite3.Row
    season_totals = [
        (int(season_id), int(rows))
        for season_id, rows in conn.execute(
            "SELECT season_id,rows FROM season_totals ORDER BY season_id"
        )
    ]
    field_tmp = stage / "FULL7_FEATURE_CATALOG.jsonl.tmp"
    derived_tmp = stage / "FULL7_DERIVED_FEATURE_CATALOG.json.tmp"

    field_count = 0
    with field_tmp.open("w", encoding="utf-8") as handle:
        cursor = conn.execute(
            "SELECT * FROM path_stats WHERE derived_name IS NULL ORDER BY path"
        )
        for row in cursor:
            profile = _finalize_path(
                conn, row, total_rows=expected_rows, season_totals=season_totals
            )
            handle.write(
                json.dumps(profile, ensure_ascii=False, sort_keys=True) + "\n"
            )
            field_count += 1

    derived_count = 0
    with derived_tmp.open("w", encoding="utf-8") as handle:
        handle.write("[\n")
        first = True
        cursor = conn.execute(
            "SELECT * FROM path_stats WHERE derived_name IS NOT NULL ORDER BY derived_name"
        )
        for row in cursor:
            profile = _finalize_path(
                conn, row, total_rows=expected_rows, season_totals=season_totals
            )
            if not first:
                handle.write(",\n")
            handle.write(json.dumps(profile, ensure_ascii=False, sort_keys=True))
            first = False
            derived_count += 1
        handle.write("\n]\n")

    field_path = stage / "FULL7_FEATURE_CATALOG.jsonl"
    derived_path = stage / "FULL7_DERIVED_FEATURE_CATALOG.json"
    field_tmp.replace(field_path)
    derived_tmp.replace(derived_path)
    hashes = {
        field_path.name: _sha256(field_path),
        derived_path.name: _sha256(derived_path),
    }
    checkpoint = {
        "checkpoint": "CP3_CATALOGS",
        "status": "COMPLETE",
        "gate": "PASS",
        "field_count": field_count,
        "derived_feature_count": derived_count,
        "sha256": hashes,
        "completed_at_utc": _utcnow(),
    }
    _json_atomic(stage / "CP3_CATALOG_PASS.json", checkpoint)
    with conn:
        _set_meta(conn, "catalog_complete", 1)
    return {
        "field_count": field_count,
        "derived_feature_count": derived_count,
    }


def _pearson(left: dict[int, float], right: dict[int, float]) -> tuple[int, float | None]:
    common = set(left).intersection(right)
    n = len(common)
    if n < 2:
        return n, None
    sx = sy = sxx = syy = sxy = 0.0
    for key in common:
        x = left[key]
        y = right[key]
        sx += x
        sy += y
        sxx += x * x
        syy += y * y
        sxy += x * y
    numerator = sxy - (sx * sy) / n
    dx = sxx - (sx * sx) / n
    dy = syy - (sy * sy) / n
    if dx <= 0 or dy <= 0:
        return n, None
    return n, numerator / math.sqrt(dx * dy)


def _load_scalar_block(
    conn: sqlite3.Connection,
    block: list[tuple[int, str]],
) -> dict[int, dict[int, float]]:
    result: dict[int, dict[int, float]] = {}
    for path_id, _path in block:
        result[path_id] = {
            int(match_id): float(value)
            for match_id, value in conn.execute(
                "SELECT match_id,value FROM scalar_sample WHERE path_id=?",
                (path_id,),
            )
        }
    return result


def _trim_redundancy_top(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        DELETE FROM redundancy_top
        WHERE rowid IN (
            SELECT rowid FROM redundancy_top
            ORDER BY abs_r DESC, path_a ASC, path_b ASC
            LIMIT -1 OFFSET 1000
        )
        """
    )


def _run_correlations(
    conn: sqlite3.Connection,
    stage: Path,
    *,
    min_overlap: int,
) -> dict[str, int]:
    if _get_meta(conn, "correlation_complete", "0") == "1":
        checkpoint = json.loads(
            (stage / "CP3_CORRELATION_PASS.json").read_text(encoding="utf-8")
        )
        path = stage / "FULL7_REDUNDANCY_AUDIT.json"
        if not path.is_file() or _sha256(path) != checkpoint["sha256"]:
            raise FeatureAuditError("cp3_redundancy_hash_mismatch")
        return {
            "scalar_path_count": int(checkpoint["scalar_path_count"]),
            "pairs_evaluated": int(checkpoint["pairs_evaluated"]),
            "pairs_meeting_overlap": int(checkpoint["pairs_meeting_overlap"]),
            "pairs_high_correlation": int(checkpoint["pairs_high_correlation"]),
            "reported_top_pairs": int(checkpoint["reported_top_pairs"]),
        }

    scalar_paths = [
        (int(path_id), str(path))
        for path_id, path in conn.execute(
            """
            SELECT p.id,p.path
            FROM path_stats p
            WHERE EXISTS(
                SELECT 1 FROM scalar_sample s WHERE s.path_id=p.id
            )
            ORDER BY p.path
            """
        )
    ]
    blocks = [
        scalar_paths[index : index + CORRELATION_BLOCK_PATHS]
        for index in range(0, len(scalar_paths), CORRELATION_BLOCK_PATHS)
    ]
    n_blocks = len(blocks)
    start_i = int(_get_meta(conn, "corr_block_i", "0"))
    start_j = int(_get_meta(conn, "corr_block_j", "0"))
    pairs_evaluated = int(_get_meta(conn, "corr_pairs_evaluated", "0"))
    pairs_overlap = int(_get_meta(conn, "corr_pairs_meeting_overlap", "0"))
    pairs_high = int(_get_meta(conn, "corr_pairs_high", "0"))

    for block_i in range(start_i, n_blocks):
        first_j = max(block_i, start_j if block_i == start_i else block_i)
        left_block = blocks[block_i]
        left_values = _load_scalar_block(conn, left_block)
        for block_j in range(first_j, n_blocks):
            right_block = blocks[block_j]
            right_values = (
                left_values if block_j == block_i else _load_scalar_block(conn, right_block)
            )
            qualifying: list[tuple[str, str, int, float, float]] = []
            evaluated_here = overlap_here = high_here = 0

            for left_index, (left_id, left_path) in enumerate(left_block):
                for right_index, (right_id, right_path) in enumerate(right_block):
                    if block_i == block_j and right_index <= left_index:
                        continue
                    evaluated_here += 1
                    overlap, correlation = _pearson(
                        left_values[left_id], right_values[right_id]
                    )
                    if overlap >= min_overlap:
                        overlap_here += 1
                    if (
                        overlap >= min_overlap
                        and correlation is not None
                        and abs(correlation) >= 0.9
                    ):
                        high_here += 1
                        qualifying.append(
                            (
                                left_path,
                                right_path,
                                overlap,
                                round(correlation, 12),
                                abs(correlation),
                            )
                        )

            next_i = block_i
            next_j = block_j + 1
            if next_j >= n_blocks:
                next_i = block_i + 1
                next_j = next_i

            with conn:
                if qualifying:
                    conn.executemany(
                        "INSERT OR REPLACE INTO redundancy_top("
                        "path_a,path_b,overlap,pearson_r,abs_r"
                        ") VALUES(?,?,?,?,?)",
                        qualifying,
                    )
                    _trim_redundancy_top(conn)
                pairs_evaluated += evaluated_here
                pairs_overlap += overlap_here
                pairs_high += high_here
                _set_meta(conn, "corr_pairs_evaluated", pairs_evaluated)
                _set_meta(conn, "corr_pairs_meeting_overlap", pairs_overlap)
                _set_meta(conn, "corr_pairs_high", pairs_high)
                _set_meta(conn, "corr_block_i", next_i)
                _set_meta(conn, "corr_block_j", next_j)

            _json_atomic(
                stage / "CP3_PROGRESS.json",
                {
                    "checkpoint": "CP3_CORRELATION_BLOCKS",
                    "status": "RUNNING",
                    "scalar_path_count": len(scalar_paths),
                    "block_i_next": next_i,
                    "block_j_next": next_j,
                    "block_count": n_blocks,
                    "pairs_evaluated": pairs_evaluated,
                    "pairs_meeting_overlap": pairs_overlap,
                    "pairs_high_correlation": pairs_high,
                    "correlation_min_overlap": min_overlap,
                    "updated_at_utc": _utcnow(),
                },
            )

    rows = [
        {
            "path_a": path_a,
            "path_b": path_b,
            "overlap": int(overlap),
            "pearson_r": float(pearson_r),
            "action": "REDUNDANCY_REVIEW_REQUIRED",
        }
        for path_a, path_b, overlap, pearson_r in conn.execute(
            "SELECT path_a,path_b,overlap,pearson_r FROM redundancy_top "
            "ORDER BY abs_r DESC, path_a ASC, path_b ASC"
        )
    ]
    redundancy_path = stage / "FULL7_REDUNDANCY_AUDIT.json"
    _json_atomic(redundancy_path, rows)
    with conn:
        _set_meta(conn, "correlation_complete", 1)

    checkpoint = {
        "checkpoint": "CP3_CORRELATION_BLOCKS",
        "status": "COMPLETE",
        "gate": "PASS",
        "scalar_path_count": len(scalar_paths),
        "pairs_evaluated": pairs_evaluated,
        "pairs_meeting_overlap": pairs_overlap,
        "pairs_high_correlation": pairs_high,
        "reported_top_pairs": len(rows),
        "correlation_min_overlap": min_overlap,
        "block_paths": CORRELATION_BLOCK_PATHS,
        "sha256": _sha256(redundancy_path),
        "completed_at_utc": _utcnow(),
    }
    _json_atomic(stage / "CP3_CORRELATION_PASS.json", checkpoint)
    return {
        "scalar_path_count": len(scalar_paths),
        "pairs_evaluated": pairs_evaluated,
        "pairs_meeting_overlap": pairs_overlap,
        "pairs_high_correlation": pairs_high,
        "reported_top_pairs": len(rows),
    }


def _copy_json_array_from_jsonl(out, path: Path) -> None:
    out.write("[\n")
    first = True
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            if not first:
                out.write(",\n")
            out.write(line.strip())
            first = False
    out.write("\n]")


def _write_final_outputs(
    conn: sqlite3.Connection,
    stage: Path,
    checkpoint: dict[str, Any],
    *,
    catalog_counts: dict[str, int],
    correlation_counts: dict[str, int],
    expected_master_hash: str,
) -> dict[str, Any]:
    raw_paths = [
        str(path)
        for (path,) in conn.execute(
            "SELECT path FROM path_stats WHERE derived_name IS NULL ORDER BY path"
        )
    ]
    derived_names = [
        str(name)
        for (name,) in conn.execute(
            "SELECT derived_name FROM path_stats "
            "WHERE derived_name IS NOT NULL ORDER BY derived_name"
        )
    ]
    mandatory = _mandatory_groups(raw_paths, derived_names)
    season_counts = {
        str(season_id): int(rows)
        for season_id, rows in conn.execute(
            "SELECT season_id,rows FROM season_totals ORDER BY season_id"
        )
    }

    report_tmp = stage / "FULL7_FEATURE_AUDIT.json.tmp"
    field_catalog = stage / "FULL7_FEATURE_CATALOG.jsonl"
    derived_catalog = stage / "FULL7_DERIVED_FEATURE_CATALOG.json"
    redundancy_path = stage / "FULL7_REDUNDANCY_AUDIT.json"
    with report_tmp.open("w", encoding="utf-8") as out:
        prefix = {
            "audit_version": AUDIT_VERSION,
            "rows_profiled": int(checkpoint["match_count_valid"]),
            "unique_match_ids": int(checkpoint["match_count_valid"]),
            "season_counts": season_counts,
            "field_count": catalog_counts["field_count"],
            "derived_feature_count": catalog_counts["derived_feature_count"],
        }
        out.write("{\n")
        items = list(prefix.items())
        for key, value in items:
            out.write(
                json.dumps(key)
                + ": "
                + json.dumps(value, ensure_ascii=False, sort_keys=True)
                + ",\n"
            )
        out.write('"field_profiles": ')
        _copy_json_array_from_jsonl(out, field_catalog)
        out.write(',\n"derived_feature_profiles": ')
        with derived_catalog.open(encoding="utf-8") as src:
            for block in iter(lambda: src.read(1024 * 1024), ""):
                if not block:
                    break
                out.write(block)
        out.write(',\n"high_redundancy_pairs": ')
        with redundancy_path.open(encoding="utf-8") as src:
            for block in iter(lambda: src.read(1024 * 1024), ""):
                if not block:
                    break
                out.write(block)
        tail = {
            "mandatory_groups": mandatory,
            "leakage_hits": 0,
            "odds_hits": 0,
            "labels_used_for_feature_engineering": False,
            "model_training_performed": False,
            "bounded_memory": {
                "profile_state": "SQLITE_DISK_BACKED",
                "profile_chunk_rows": PROFILE_CHUNK_ROWS,
                "numeric_sample_capacity_per_path": NUMERIC_SAMPLE_CAPACITY,
                "scalar_sample_capacity_per_path": SCALAR_SAMPLE_CAPACITY,
                "correlation_mode": "DISK_BACKED_BLOCKWISE",
                "correlation_block_paths": CORRELATION_BLOCK_PATHS,
                "correlation_pairs_evaluated": correlation_counts["pairs_evaluated"],
            },
        }
        for key, value in tail.items():
            out.write(
                ",\n"
                + json.dumps(key)
                + ": "
                + json.dumps(value, ensure_ascii=False, sort_keys=True)
            )
        out.write("\n}\n")
    report_path = stage / "FULL7_FEATURE_AUDIT.json"
    report_tmp.replace(report_path)

    summary_path = stage / "FULL7_FEATURE_AUDIT.txt"
    summary_path.write_text(
        "\n".join(
            [
                "FULL7 FULL FEATURE AUDIT",
                f"rows_profiled={checkpoint['match_count_valid']}",
                f"field_count={catalog_counts['field_count']}",
                f"derived_feature_count={catalog_counts['derived_feature_count']}",
                f"seasons={len(season_counts)}",
                f"redundancy_pairs_reported={correlation_counts['reported_top_pairs']}",
                f"correlation_pairs_evaluated={correlation_counts['pairs_evaluated']}",
                "profile_state=SQLITE_DISK_BACKED",
                f"profile_chunk_rows={PROFILE_CHUNK_ROWS}",
                f"correlation_block_paths={CORRELATION_BLOCK_PATHS}",
                "leakage_hits=0",
                "odds_hits=0",
                "labels_used_for_feature_engineering=false",
                "mandatory_groups=" + ",".join(sorted(mandatory)),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    cp3 = {
        "checkpoint": "CP3_FEATURE_AUDIT",
        "status": "COMPLETE",
        "gate": "PASS",
        "model_used": "GPT-5.6 Sol",
        "audit_version": AUDIT_VERSION,
        "dataset_version": checkpoint["dataset_version"],
        "match_count_input": checkpoint["match_count_valid"],
        "match_count_valid": checkpoint["match_count_valid"],
        "match_count_quarantined": checkpoint["match_count_quarantined"],
        "new_cp1_holds_excluded": checkpoint["new_cp1_holds_excluded"],
        "validations_completed": {
            "field_count": catalog_counts["field_count"],
            "derived_feature_count": catalog_counts["derived_feature_count"],
            "mandatory_groups_audited": sorted(mandatory),
            "leakage_hits": 0,
            "odds_hits": 0,
            "labels_used_for_feature_engineering": False,
            "model_training_performed": False,
            "correlation_pairs_evaluated": correlation_counts["pairs_evaluated"],
            "correlation_pairs_meeting_overlap": correlation_counts[
                "pairs_meeting_overlap"
            ],
            "correlation_pairs_high": correlation_counts[
                "pairs_high_correlation"
            ],
            "bounded_memory": True,
            "crash_safe_resume": True,
        },
        "known_problems": [],
        "open_questions": [
            "Feature eligibility and incremental utility require chronological research in the next authorized phase."
        ],
        "next_phase": "PHASE 4 — NEW MODELLING / temporal research gates",
        "resume_instruction": (
            "Use frozen CP2 master rows and this completed CP3 catalog; "
            "do not use Forward-OOS for selection."
        ),
    }
    _json_atomic(stage / "CP3_FEATURE_AUDIT.json", cp3)
    (stage / "CP3_FEATURE_AUDIT.txt").write_text(
        "\n".join(
            f"{key}: {json.dumps(value, ensure_ascii=False, sort_keys=True)}"
            for key, value in cp3.items()
        )
        + "\n",
        encoding="utf-8",
    )

    _json_atomic(
        stage / "CP3_PROGRESS.json",
        {
            "checkpoint": "CP3_FEATURE_AUDIT",
            "status": "COMPLETE",
            "gate": "PASS",
            "rows_profiled": checkpoint["match_count_valid"],
            "completed_at_utc": _utcnow(),
        },
    )

    return cp3


def _write_manifest(
    stage: Path,
    *,
    expected_master_hash: str,
) -> dict[str, Any]:
    artifacts: dict[str, Any] = {}
    for path in sorted(stage.iterdir()):
        if not path.is_file() or path.name == "FULL7_FEATURE_AUDIT_MANIFEST.json":
            continue
        artifacts[path.name] = {
            "bytes": path.stat().st_size,
            "sha256": _sha256(path),
        }
    manifest = {
        "created_at_utc": _utcnow(),
        "audit_version": AUDIT_VERSION,
        "cp2_master_sha256": expected_master_hash,
        "artifacts": artifacts,
    }
    _json_atomic(stage / "FULL7_FEATURE_AUDIT_MANIFEST.json", manifest)
    return manifest


def run_bounded_feature_audit(
    cp2_dir: Path,
    output_dir: Path,
    *,
    existing_stage: Path | None = None,
    correlation_min_overlap: int = 100,
) -> dict[str, Any]:
    """Run/resume Phase 3 only, using frozen passing CP2 artifacts."""
    cp2_dir, output_dir = Path(cp2_dir), Path(output_dir)
    checkpoint_path = cp2_dir / "CP2_MASTER_DATASET.json"
    manifest_path = cp2_dir / "FULL7_MASTER_BUILD_MANIFEST.json"
    if not checkpoint_path.is_file() or not manifest_path.is_file():
        raise FeatureAuditError("cp2_checkpoint_or_manifest_missing")
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    if checkpoint.get("checkpoint") != "CP2_MASTER_DATASET" or checkpoint.get("gate") != "PASS":
        raise FeatureAuditError("cp2_gate_not_pass")
    if int(checkpoint.get("match_count_valid", -1)) != 16137:
        raise FeatureAuditError("cp2_frozen_match_count_not_16137")

    master_path = cp2_dir / "FULL7_MASTER_STRICT.jsonl"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected_master_hash = (
        ((manifest.get("artifacts") or {}).get(master_path.name) or {}).get("sha256")
    )
    if not expected_master_hash:
        raise FeatureAuditError("cp2_master_hash_missing")
    if _sha256(master_path) != expected_master_hash:
        raise FeatureAuditError("cp2_artifact_hash_mismatch:FULL7_MASTER_STRICT.jsonl")

    if output_dir.is_dir():
        cp3_path = output_dir / "CP3_FEATURE_AUDIT.json"
        if not cp3_path.is_file():
            raise FeatureAuditError("cp3_output_exists_without_checkpoint")
        cp3 = json.loads(cp3_path.read_text(encoding="utf-8"))
        if cp3.get("gate") != "PASS":
            raise FeatureAuditError("cp3_existing_checkpoint_not_pass")
        return cp3

    stage = (
        Path(existing_stage)
        if existing_stage is not None
        else output_dir.parent / ".cp3.stage-bounded"
    )
    if not stage.is_dir():
        stage.mkdir(parents=True)

    inspection = inspect_stage_once(stage)
    legacy = inspection.get("legacy_phase3_artifacts") or []
    if legacy and not (stage / "PHASE3_STATE.sqlite3").is_file():
        raise FeatureAuditError(
            "legacy_partial_cp3_artifacts_preserved_require_manual_reconciliation:"
            + ",".join(legacy)
        )

    state_path = stage / "PHASE3_STATE.sqlite3"
    conn = _connect(state_path)
    try:
        _initialize_or_validate_state(
            conn,
            master_sha256=expected_master_hash,
            expected_rows=int(checkpoint["match_count_valid"]),
        )
        _profile_stream(
            conn,
            master_path,
            stage,
            expected_rows=int(checkpoint["match_count_valid"]),
        )
        catalog_counts = _write_catalogs(
            conn,
            stage,
            expected_rows=int(checkpoint["match_count_valid"]),
        )
        correlation_counts = _run_correlations(
            conn,
            stage,
            min_overlap=correlation_min_overlap,
        )
        cp3 = _write_final_outputs(
            conn,
            stage,
            checkpoint,
            catalog_counts=catalog_counts,
            correlation_counts=correlation_counts,
            expected_master_hash=expected_master_hash,
        )
        conn.execute("PRAGMA optimize")
        conn.commit()
    finally:
        conn.close()

    _write_manifest(stage, expected_master_hash=expected_master_hash)
    if output_dir.exists():
        raise FeatureAuditError("cp3_output_appeared_during_publish")
    stage.rename(output_dir)
    return cp3
