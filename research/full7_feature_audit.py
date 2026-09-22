#!/usr/bin/env python3
"""Streaming Phase-3 feature audit for the passing FULL-7 CP2 dataset."""
from __future__ import annotations

import hashlib
import heapq
import json
import math
import shutil
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from research.full7_master_dataset import LABEL_KEYS, MATCH_POSTMATCH_FORBIDDEN


REQUIRED_GROUPS = {
    "A1_LEAGUE_FIRST_HALF_BTTS_VENUE",
    "A2_PLAYER_DEPTH",
    "B1_CS_FTS_ZERO_GOAL_PROFILE",
    "B2_PLAYER_CONCENTRATION",
    "B3_PLAYER_CHANCE_QUALITY_CONTRIBUTION",
    "B4_RELATIVE_TABLE_STRENGTH",
    "C_WATCHLIST_PROVIDER_POTENTIALS",
    "C_H2H",
}


class FeatureAuditError(RuntimeError):
    """Fail-closed Phase-3 audit error."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _leaf_key(path: str) -> str:
    return path.rsplit(".", 1)[-1].replace("[]", "")


def classify_path(path: str) -> dict[str, str]:
    """Classify lineage, leakage risk, and eligibility from an exact path."""
    lower = path.lower()
    key = _leaf_key(path)
    source = path.split(".", 1)[0]
    if "odd" in lower:
        return {
            "leakage_risk": "ODDS_FORBIDDEN",
            "provider_dependency": "FORBIDDEN_INPUT",
            "transformation": "NONE",
            "research_eligibility": "BLOCKED_ODDS",
        }
    if key in LABEL_KEYS:
        return {
            "leakage_risk": "TARGET_LABEL_LEAKAGE",
            "provider_dependency": "LABEL_ONLY",
            "transformation": "NONE",
            "research_eligibility": "BLOCKED_LABEL_LEAKAGE",
        }
    if source == "match" and key in MATCH_POSTMATCH_FORBIDDEN:
        return {
            "leakage_risk": "TARGET_POSTMATCH_LEAKAGE",
            "provider_dependency": "POSTMATCH_TARGET",
            "transformation": "NONE",
            "research_eligibility": "BLOCKED_POSTMATCH",
        }
    if "season_candidate_unvalidated" in path:
        return {
            "leakage_risk": "UNVALIDATED_PROVIDER_SEASON_FIELD",
            "provider_dependency": "FOOTYSTATS_PROVIDER_FIELD",
            "transformation": "RAW_SNAPSHOT_FIELD",
            "research_eligibility": "NOT_ELIGIBLE_PENDING_PROVENANCE",
        }
    if ".source_matches[]" in path:
        result_tokens = {
            "home_goals",
            "away_goals",
            "gf",
            "ga",
            "xg",
            "xga",
            "venue",
        }
        return {
            "leakage_risk": (
                "HISTORICAL_RESULT_ALLOWED_BEFORE_KICKOFF"
                if key in result_tokens
                else "STRICT_PREMATCH_SOURCE_ROW"
            ),
            "provider_dependency": "FOOTYSTATS_HISTORICAL_MATCH",
            "transformation": "PRIOR_MATCH_SOURCE",
            "research_eligibility": "ELIGIBLE_STRICT_HISTORICAL",
        }
    if "league_aggregates_derived" in path or any(
        token in path for token in (".last5.", ".last6.", ".last10.", ".home_split.", ".away_split.")
    ):
        return {
            "leakage_risk": "STRICT_PREMATCH_DERIVED",
            "provider_dependency": "FOOTYSTATS_HISTORICAL_MATCH",
            "transformation": "STRICT_PRIOR_MATCH_AGGREGATE",
            "research_eligibility": "ELIGIBLE_STRICT_DERIVED",
        }
    if source in {"league", "table", "player"} or "prematch_optional" in path:
        return {
            "leakage_risk": "STRICT_PREMATCH_CANDIDATE",
            "provider_dependency": "FOOTYSTATS_PROVIDER_FIELD",
            "transformation": "RAW_SNAPSHOT_FIELD",
            "research_eligibility": "ELIGIBLE_AFTER_FEATURE_AUDIT",
        }
    return {
        "leakage_risk": "STRICT_PREMATCH_IDENTITY_OR_DERIVED",
        "provider_dependency": "COLLECTOR_VALIDATED",
        "transformation": "RAW_OR_IDENTITY",
        "research_eligibility": "ELIGIBLE_OR_CONTEXT_ONLY",
    }


def _walk_leaves(value: Any, prefix: str):
    if isinstance(value, dict):
        for key, child in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            yield from _walk_leaves(child, path)
    elif isinstance(value, list):
        path = f"{prefix}[]"
        if not value:
            return
        for child in value:
            yield from _walk_leaves(child, path)
    else:
        yield prefix, value


@dataclass
class RunningNumeric:
    count: int = 0
    mean: float = 0.0
    m2: float = 0.0
    minimum: float | None = None
    maximum: float | None = None
    zero_count: int = 0

    def add(self, value: float) -> None:
        self.count += 1
        delta = value - self.mean
        self.mean += delta / self.count
        self.m2 += delta * (value - self.mean)
        self.minimum = value if self.minimum is None else min(self.minimum, value)
        self.maximum = value if self.maximum is None else max(self.maximum, value)
        self.zero_count += int(value == 0)

    def summary(self) -> dict[str, Any]:
        variance = self.m2 / (self.count - 1) if self.count > 1 else 0.0
        return {
            "count": self.count,
            "min": self.minimum,
            "max": self.maximum,
            "mean": round(self.mean, 12) if self.count else None,
            "stddev": round(math.sqrt(max(0.0, variance)), 12) if self.count else None,
            "zero_rate": round(self.zero_count / self.count, 12) if self.count else None,
        }


@dataclass
class NumericSample:
    capacity: int = 512
    heap: list[tuple[int, float]] = field(default_factory=list)

    def add(self, token: str, value: float) -> None:
        score = int.from_bytes(hashlib.sha256(token.encode("utf-8")).digest()[:8], "big")
        entry = (-score, value)
        if len(self.heap) < self.capacity:
            heapq.heappush(self.heap, entry)
        elif score < -self.heap[0][0]:
            heapq.heapreplace(self.heap, entry)

    def values(self) -> list[float]:
        return sorted(value for _score, value in self.heap)


@dataclass
class ScalarSample:
    capacity: int = 1024
    heap: list[tuple[int, int]] = field(default_factory=list)
    values: dict[int, float] = field(default_factory=dict)

    def add(self, match_id: int, value: float) -> None:
        score = int.from_bytes(hashlib.sha256(str(match_id).encode("ascii")).digest()[:8], "big")
        if match_id in self.values:
            self.values[match_id] = value
            return
        if len(self.heap) < self.capacity:
            heapq.heappush(self.heap, (-score, match_id))
            self.values[match_id] = value
        elif score < -self.heap[0][0]:
            _old_score, old_match = heapq.heapreplace(self.heap, (-score, match_id))
            self.values.pop(old_match, None)
            self.values[match_id] = value


@dataclass
class PathStats:
    path: str
    value_count: int = 0
    null_value_count: int = 0
    matches_present: int = 0
    matches_non_null: int = 0
    types: Counter = field(default_factory=Counter)
    numeric: RunningNumeric = field(default_factory=RunningNumeric)
    sample: NumericSample = field(default_factory=NumericSample)
    season_non_null_matches: Counter = field(default_factory=Counter)
    season_numeric: dict[int, RunningNumeric] = field(default_factory=lambda: defaultdict(RunningNumeric))
    scalar_sample: ScalarSample = field(default_factory=ScalarSample)
    source_fields: Counter = field(default_factory=Counter)

    def add_match(self, match_id: int, season_id: int, values: list[Any]) -> None:
        self.matches_present += 1
        non_null = [value for value in values if value is not None]
        if non_null:
            self.matches_non_null += 1
            self.season_non_null_matches[season_id] += 1
        numeric_values: list[float] = []
        for ordinal, value in enumerate(values):
            self.value_count += 1
            if value is None:
                self.null_value_count += 1
                self.types["null"] += 1
                continue
            type_name = "bool" if isinstance(value, bool) else type(value).__name__
            self.types[type_name] += 1
            if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)):
                number = float(value)
                numeric_values.append(number)
                self.numeric.add(number)
                self.season_numeric[season_id].add(number)
                self.sample.add(f"{self.path}|{match_id}|{ordinal}|{number}", number)
        if "[]" not in self.path and len(numeric_values) == 1:
            self.scalar_sample.add(match_id, numeric_values[0])


def _quantile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    position = (len(values) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return values[lower]
    return values[lower] + (values[upper] - values[lower]) * (position - lower)


def _finalize_path(stats: PathStats, total_rows: int, season_totals: Counter) -> dict[str, Any]:
    classification = classify_path(stats.path)
    sample = stats.sample.values()
    q1 = _quantile(sample, 0.25)
    median = _quantile(sample, 0.5)
    q3 = _quantile(sample, 0.75)
    if q1 is not None and q3 is not None:
        iqr = q3 - q1
        low, high = q1 - 1.5 * iqr, q3 + 1.5 * iqr
        outliers = sum(value < low or value > high for value in sample)
    else:
        iqr = low = high = None
        outliers = 0
    numeric = stats.numeric.summary()
    numeric.update(
        {
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
    )
    season_rows = []
    for season_id, season_total in sorted(season_totals.items()):
        non_null = stats.season_non_null_matches.get(season_id, 0)
        season_rows.append(
            {
                "season_id": season_id,
                "rows": season_total,
                "matches_non_null": non_null,
                "coverage_rate": round(non_null / season_total, 12),
                "numeric_mean": stats.season_numeric[season_id].summary()["mean"]
                if season_id in stats.season_numeric
                else None,
            }
        )
    coverages = [row["coverage_rate"] for row in season_rows]
    return {
        "path": stats.path,
        "source": stats.path.split(".", 1)[0],
        "data_types": dict(sorted(stats.types.items())),
        "value_count": stats.value_count,
        "null_value_count": stats.null_value_count,
        "matches_present": stats.matches_present,
        "matches_non_null": stats.matches_non_null,
        "coverage_rate": round(stats.matches_non_null / total_rows, 12),
        "missingness_rate": round(1 - stats.matches_non_null / total_rows, 12),
        "numeric": numeric,
        "season_stability": {
            "season_count": len(season_rows),
            "coverage_min": min(coverages) if coverages else None,
            "coverage_max": max(coverages) if coverages else None,
            "by_season": season_rows,
        },
        "source_fields": dict(sorted(stats.source_fields.items())),
        **classification,
    }


def _pearson(left: dict[int, float], right: dict[int, float]) -> tuple[int, float | None]:
    common = sorted(set(left) & set(right))
    if len(common) < 2:
        return len(common), None
    xs = [left[key] for key in common]
    ys = [right[key] for key in common]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    numerator = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = sum((x - mx) ** 2 for x in xs)
    dy = sum((y - my) ** 2 for y in ys)
    if dx <= 0 or dy <= 0:
        return len(common), None
    return len(common), numerator / math.sqrt(dx * dy)


def _numeric_value(row: dict[str, Any], candidates: tuple[str, ...]):
    for candidate in candidates:
        value = row.get(candidate)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value), candidate
    return None, None


def _derived_features(row: dict[str, Any], sources: dict[str, Any]) -> dict[str, tuple[Any, str | None]]:
    derived: dict[str, tuple[Any, str | None]] = {}
    players = (sources.get("player") or {}).get("players") or []
    home_id, away_id = int(row["home_id"]), int(row["away_id"])
    by_team = {
        home_id: [player for player in players if int(player.get("club_team_id", player.get("team_id", -1))) == home_id],
        away_id: [player for player in players if int(player.get("club_team_id", player.get("team_id", -1))) == away_id],
    }
    home_depth, away_depth = len(by_team[home_id]), len(by_team[away_id])
    derived.update(
        {
            "player_depth_home": (home_depth, "player.players[].club_team_id"),
            "player_depth_away": (away_depth, "player.players[].club_team_id"),
            "player_depth_min": (min(home_depth, away_depth), "player.players[].club_team_id"),
            "player_depth_mean": ((home_depth + away_depth) / 2, "player.players[].club_team_id"),
            "player_depth_diff": (home_depth - away_depth, "player.players[].club_team_id"),
        }
    )
    goal_keys = ("goals_overall", "goals", "total_goals")
    assist_keys = ("assists_overall", "assists", "total_assists")
    minute_keys = ("minutes_played_overall", "minutes_played", "minutes")
    for side, team_id in (("home", home_id), ("away", away_id)):
        goals, assists, involvements, goals90, assists90 = [], [], [], [], []
        goal_sources, assist_sources, minute_sources = Counter(), Counter(), Counter()
        for player in by_team[team_id]:
            goal, goal_key = _numeric_value(player, goal_keys)
            assist, assist_key = _numeric_value(player, assist_keys)
            minutes, minute_key = _numeric_value(player, minute_keys)
            if goal is not None:
                goals.append(goal)
                goal_sources[goal_key] += 1
            if assist is not None:
                assists.append(assist)
                assist_sources[assist_key] += 1
            if goal is not None and assist is not None:
                involvements.append(goal + assist)
            if minutes is not None and minutes > 0:
                minute_sources[minute_key] += 1
                if goal is not None:
                    goals90.append(goal * 90 / minutes)
                if assist is not None:
                    assists90.append(assist * 90 / minutes)
        for metric, values, sources_used in (
            ("goals", goals, goal_sources),
            ("assists", assists, assist_sources),
            ("involvement", involvements, goal_sources + assist_sources),
        ):
            ordered = sorted(values, reverse=True)
            for top_n in (1, 2, 3):
                value = sum(ordered[:top_n]) if len(ordered) >= top_n else None
                source = "+".join(sorted(sources_used)) or None
                derived[f"player_{metric}_top{top_n}_{side}"] = (value, source)
        derived[f"player_goals_per90_mean_{side}"] = (
            sum(goals90) / len(goals90) if goals90 else None,
            "+".join(sorted(goal_sources + minute_sources)) or None,
        )
        derived[f"player_assists_per90_mean_{side}"] = (
            sum(assists90) / len(assists90) if assists90 else None,
            "+".join(sorted(assist_sources + minute_sources)) or None,
        )
    return derived


def _mandatory_groups(paths: list[str], derived_names: list[str]) -> dict[str, Any]:
    def matching(*tokens: str):
        return sorted(path for path in paths if any(token.lower() in path.lower() for token in tokens))

    groups = {
        "A1_LEAGUE_FIRST_HALF_BTTS_VENUE": {
            "required_fields": [
                "seasonBTTSPercentageHT_home",
                "seasonBTTSPercentageHT_away",
            ],
            "matched_paths": matching("seasonBTTSPercentageHT_home", "seasonBTTSPercentageHT_away"),
        },
        "A2_PLAYER_DEPTH": {
            "required_derived": [
                "player_depth_home",
                "player_depth_away",
                "player_depth_min",
                "player_depth_mean",
                "player_depth_diff",
            ],
            "matched_paths": matching("player.players[].club_team_id"),
        },
        "B1_CS_FTS_ZERO_GOAL_PROFILE": {
            "matched_paths": matching("cs_rate", "fts_rate", "clean", "failedtoscore", "zerogoal"),
        },
        "B2_PLAYER_CONCENTRATION": {
            "matched_paths": matching("goals", "assists"),
            "derived_features": sorted(name for name in derived_names if "_top" in name),
        },
        "B3_PLAYER_CHANCE_QUALITY_CONTRIBUTION": {
            "matched_paths": matching("goals_per_90", "assists_per_90", "minutes", "xg", "xa"),
            "derived_features": sorted(name for name in derived_names if "per90" in name),
        },
        "B4_RELATIVE_TABLE_STRENGTH": {
            "matched_paths": matching("ppg", "position", "rank", "points"),
        },
        "C_WATCHLIST_PROVIDER_POTENTIALS": {
            "matched_paths": matching("btts_potential", "o25_potential", "u25_potential"),
        },
        "C_H2H": {"matched_paths": matching("h2h", "head_to_head")},
    }
    for group in groups.values():
        group["audit_status"] = "AUDITED"
        group["availability"] = "AVAILABLE" if group.get("matched_paths") or group.get("derived_features") else "NOT_AVAILABLE"
        group["missingness_policy"] = "NOT_AVAILABLE is retained; no substitute or imputation"
    return groups


def profile_master(
    master_path: Path,
    *,
    expected_rows: int,
    correlation_min_overlap: int = 100,
) -> dict[str, Any]:
    stats: dict[str, PathStats] = {}
    derived_stats: dict[str, PathStats] = {}
    season_totals: Counter = Counter()
    processed = 0
    seen_ids: set[int] = set()
    with Path(master_path).open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            match_id = int(row["match_id"])
            season_id = int(row["season_id"])
            if match_id in seen_ids:
                raise FeatureAuditError(f"duplicate_match_id:{match_id}")
            seen_ids.add(match_id)
            season_totals[season_id] += 1
            processed += 1
            sources = json.loads(row["feature_sources_json"])
            per_path: dict[str, list[Any]] = defaultdict(list)
            for source_name, payload in sources.items():
                for path, value in _walk_leaves(payload, source_name):
                    classification = classify_path(path)
                    if classification["research_eligibility"].startswith("BLOCKED_"):
                        raise FeatureAuditError(f"blocked_feature_path:{match_id}:{path}")
                    per_path[path].append(value)
            for path, values in per_path.items():
                stats.setdefault(path, PathStats(path)).add_match(match_id, season_id, values)
            for name, (value, source_field) in _derived_features(row, sources).items():
                entry = derived_stats.setdefault(name, PathStats(f"derived.{name}"))
                entry.add_match(match_id, season_id, [value])
                if source_field:
                    entry.source_fields[source_field] += 1

    if processed != expected_rows:
        raise FeatureAuditError(f"master_row_count_mismatch:{processed}!={expected_rows}")

    field_profiles = [_finalize_path(stats[path], processed, season_totals) for path in sorted(stats)]
    derived_profiles = []
    for name in sorted(derived_stats):
        profile = _finalize_path(derived_stats[name], processed, season_totals)
        profile["feature"] = name
        profile["definition"] = "Explicit deterministic derivation; source fields listed in source_fields"
        derived_profiles.append(profile)

    scalar_paths = [path for path in sorted(stats) if stats[path].scalar_sample.values]
    redundancies = []
    for index, path_a in enumerate(scalar_paths):
        for path_b in scalar_paths[index + 1 :]:
            overlap, correlation = _pearson(
                stats[path_a].scalar_sample.values, stats[path_b].scalar_sample.values
            )
            if overlap >= correlation_min_overlap and correlation is not None and abs(correlation) >= 0.9:
                redundancies.append(
                    {
                        "path_a": path_a,
                        "path_b": path_b,
                        "overlap": overlap,
                        "pearson_r": round(correlation, 12),
                        "action": "REDUNDANCY_REVIEW_REQUIRED",
                    }
                )
    redundancies.sort(key=lambda row: (-abs(row["pearson_r"]), row["path_a"], row["path_b"]))
    mandatory = _mandatory_groups(sorted(stats), sorted(derived_stats))
    return {
        "audit_version": "FULL7_FEATURE_AUDIT_1.0",
        "rows_profiled": processed,
        "unique_match_ids": len(seen_ids),
        "season_counts": dict(sorted(season_totals.items())),
        "field_count": len(field_profiles),
        "derived_feature_count": len(derived_profiles),
        "field_profiles": field_profiles,
        "derived_feature_profiles": derived_profiles,
        "high_redundancy_pairs": redundancies[:1000],
        "mandatory_groups": mandatory,
        "leakage_hits": 0,
        "odds_hits": 0,
        "labels_used_for_feature_engineering": False,
        "model_training_performed": False,
    }


def run_feature_audit(
    cp2_dir: Path,
    output_dir: Path,
    *,
    correlation_min_overlap: int = 100,
) -> dict[str, Any]:
    """Gate on CP2, profile the actual master, and atomically publish CP3."""
    cp2_dir, output_dir = Path(cp2_dir), Path(output_dir)
    checkpoint_path = cp2_dir / "CP2_MASTER_DATASET.json"
    manifest_path = cp2_dir / "FULL7_MASTER_BUILD_MANIFEST.json"
    if not checkpoint_path.is_file() or not manifest_path.is_file():
        raise FeatureAuditError("cp2_checkpoint_or_manifest_missing")
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    if checkpoint.get("checkpoint") != "CP2_MASTER_DATASET" or checkpoint.get("gate") != "PASS":
        raise FeatureAuditError("cp2_gate_not_pass")
    master_path = cp2_dir / "FULL7_MASTER_STRICT.jsonl"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected_master_hash = ((manifest.get("artifacts") or {}).get(master_path.name) or {}).get("sha256")
    if not expected_master_hash or _sha256(master_path) != expected_master_hash:
        raise FeatureAuditError("cp2_artifact_hash_mismatch:FULL7_MASTER_STRICT.jsonl")
    if output_dir.exists():
        raise FeatureAuditError(f"output_directory_already_exists:{output_dir}")
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    stage = output_dir.parent / f".{output_dir.name}.stage-{uuid.uuid4().hex}"
    stage.mkdir()
    try:
        report = profile_master(
            master_path,
            expected_rows=int(checkpoint["match_count_valid"]),
            correlation_min_overlap=correlation_min_overlap,
        )
        (stage / "FULL7_FEATURE_AUDIT.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        with (stage / "FULL7_FEATURE_CATALOG.jsonl").open("w", encoding="utf-8") as handle:
            for row in report["field_profiles"]:
                handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        (stage / "FULL7_DERIVED_FEATURE_CATALOG.json").write_text(
            json.dumps(report["derived_feature_profiles"], indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        (stage / "FULL7_REDUNDANCY_AUDIT.json").write_text(
            json.dumps(report["high_redundancy_pairs"], indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        (stage / "FULL7_FEATURE_AUDIT.txt").write_text(
            "\n".join(
                [
                    "FULL7 FULL FEATURE AUDIT",
                    f"rows_profiled={report['rows_profiled']}",
                    f"field_count={report['field_count']}",
                    f"derived_feature_count={report['derived_feature_count']}",
                    f"seasons={len(report['season_counts'])}",
                    f"redundancy_pairs={len(report['high_redundancy_pairs'])}",
                    "leakage_hits=0",
                    "odds_hits=0",
                    "labels_used_for_feature_engineering=false",
                    "mandatory_groups=" + ",".join(sorted(report["mandatory_groups"])),
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        file_names = sorted(path.name for path in stage.iterdir())
        cp3 = {
            "checkpoint": "CP3_FEATURE_AUDIT",
            "status": "COMPLETE",
            "gate": "PASS",
            "model_used": "GPT-5.6 Sol",
            "dataset_version": checkpoint["dataset_version"],
            "match_count_input": checkpoint["match_count_valid"],
            "match_count_valid": report["rows_profiled"],
            "match_count_quarantined": checkpoint["match_count_quarantined"],
            "new_cp1_holds_excluded": checkpoint["new_cp1_holds_excluded"],
            "files_created_or_changed": file_names,
            "validations_completed": {
                "field_count": report["field_count"],
                "derived_feature_count": report["derived_feature_count"],
                "mandatory_groups_audited": sorted(report["mandatory_groups"]),
                "leakage_hits": report["leakage_hits"],
                "odds_hits": report["odds_hits"],
                "labels_used_for_feature_engineering": False,
                "model_training_performed": False,
            },
            "known_problems": [],
            "open_questions": [
                "Feature eligibility and incremental utility require chronological research in the next authorized phase."
            ],
            "next_phase": "PHASE 4 — NEW MODELLING / temporal research gates",
            "resume_instruction": "Use CP2 master rows and CP3 catalog; do not use Forward-OOS for selection.",
        }
        (stage / "CP3_FEATURE_AUDIT.json").write_text(
            json.dumps(cp3, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        (stage / "CP3_FEATURE_AUDIT.txt").write_text(
            "\n".join(f"{key}: {json.dumps(value, ensure_ascii=False, sort_keys=True)}" for key, value in cp3.items())
            + "\n",
            encoding="utf-8",
        )
        (stage / "FULL7_FEATURE_AUDIT_MANIFEST.json").write_text(
            json.dumps(
                {
                    "created_at_utc": datetime.now(timezone.utc).isoformat(),
                    "cp2_master_sha256": expected_master_hash,
                    "artifacts": {
                        path.name: {"bytes": path.stat().st_size, "sha256": _sha256(path)}
                        for path in sorted(stage.iterdir())
                        if path.is_file()
                    },
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        stage.rename(output_dir)
        return cp3
    except Exception:
        if stage.is_dir() and stage.parent == output_dir.parent and stage.name.startswith(
            f".{output_dir.name}.stage-"
        ):
            shutil.rmtree(stage)
        raise
