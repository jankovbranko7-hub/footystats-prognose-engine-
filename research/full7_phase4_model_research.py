#!/usr/bin/env python3
"""FULL-7 Phase 4 — chronological model research on frozen CP2/CP3 only.

No collection, no API, no CP1/CP2 rebuild, no production wiring.
The runner validates frozen inputs, materializes a bounded research matrix,
compares V3.1-contract and new model variants on chronological splits, performs
group ablations/incremental tests, and freezes Phase-5 calibration inputs.
"""
from __future__ import annotations

import gc
import gzip
import hashlib
import json
import math
import os
import socket
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from unittest.mock import patch

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.linear_model import SGDClassifier

PHASE4_VERSION = "FULL7_PHASE4_MODEL_RESEARCH_1.0"
EXPECTED_ROWS = 16137
EXPECTED_CP3_AUDIT = "FULL7_FEATURE_AUDIT_2.0_BOUNDED"
MIN_TRAIN_COVERAGE = 0.20
MIN_TRAIN_NON_NULL = 100
OOS_FOLDS = 3
RANDOM_STATE = 42

PRIORITY_GROUPS = (
    "A1_FH_BTTS_VENUE",
    "A2_PLAYER_DEPTH",
    "B1_CS_FTS_ZERO_GOAL",
    "B2_PLAYER_CONCENTRATION",
    "B3_PLAYER_CHANCE_QUALITY",
    "B4_RELATIVE_TABLE_STRENGTH",
    "H2H",
    "PROVIDER_POTENTIALS",
)
RESEARCH_ONLY_GROUPS = {"H2H", "PROVIDER_POTENTIALS"}

DIRECT_VARIANTS = {
    "HGB_SHALLOW_CORE": {
        "feature_set": "CORE",
        "params": {
            "max_iter": 140,
            "learning_rate": 0.05,
            "max_leaf_nodes": 15,
            "min_samples_leaf": 45,
            "l2_regularization": 2.0,
        },
    },
    "HGB_REGULARIZED_CORE": {
        "feature_set": "CORE",
        "params": {
            "max_iter": 220,
            "learning_rate": 0.035,
            "max_leaf_nodes": 31,
            "min_samples_leaf": 60,
            "l2_regularization": 6.0,
        },
    },
    "HGB_REGULARIZED_FULL_RESEARCH": {
        "feature_set": "FULL_RESEARCH",
        "params": {
            "max_iter": 220,
            "learning_rate": 0.035,
            "max_leaf_nodes": 31,
            "min_samples_leaf": 60,
            "l2_regularization": 6.0,
        },
    },
}
ABLATION_PARAMS = {
    "max_iter": 110,
    "learning_rate": 0.045,
    "max_leaf_nodes": 15,
    "min_samples_leaf": 60,
    "l2_regularization": 6.0,
}
POISSON_PARAMS = {
    "max_iter": 180,
    "learning_rate": 0.04,
    "max_leaf_nodes": 15,
    "min_samples_leaf": 60,
    "l2_regularization": 5.0,
}


class Phase4Error(RuntimeError):
    pass


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _json_atomic(path: Path, value: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def _finite(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _safe_key(key: str) -> bool:
    low = key.lower()
    exact = {
        "id", "match_id", "homeid", "awayid", "home_id", "away_id", "team_id",
        "competition_id", "season_id", "club_team_id", "club_team_2_id",
        "refereeid", "coach_a_id", "coach_b_id", "roundid",
    }
    if low in exact or low.endswith("_id"):
        return False
    if "timestamp" in low or low.endswith("date_unix") or "source_max_timestamp" in low:
        return False
    if "odd" in low:
        return False
    return True


def _walk_dict_numbers(value: Any, prefix: str = ""):
    if isinstance(value, dict):
        for key, child in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            if isinstance(child, dict):
                yield from _walk_dict_numbers(child, path)
            elif isinstance(child, list):
                continue
            else:
                x = _finite(child)
                if x is not None:
                    yield path, str(key), x


def _find_numeric_key(value: Any, wanted: str) -> float | None:
    if isinstance(value, dict):
        if wanted in value:
            x = _finite(value.get(wanted))
            if x is not None:
                return x
        for child in value.values():
            found = _find_numeric_key(child, wanted)
            if found is not None:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _find_numeric_key(child, wanted)
            if found is not None:
                return found
    return None


def _player_number(row: Mapping[str, Any], keys: Sequence[str]) -> tuple[float | None, str | None]:
    for key in keys:
        x = _finite(row.get(key))
        if x is not None:
            return x, key
    return None, None


def _assign_group(name: str, source_context: str, side: str | None = None) -> str:
    low = name.lower()
    if source_context == "provider":
        return "PROVIDER_POTENTIALS"
    if source_context == "h2h":
        return "H2H"
    if source_context == "table":
        return "B4_RELATIVE_TABLE_STRENGTH"
    if "seasonbttspercentageht" in low:
        if side == "home" and low.endswith("_home"):
            return "A1_FH_BTTS_VENUE"
        if side == "away" and low.endswith("_away"):
            return "A1_FH_BTTS_VENUE"
        return "HALF_OTHER"
    if any(token in low for token in ("cspercentage", "ftspercentage", "cs_rate", "fts_rate", "clean_sheet", "failed_to_score", "zerogoal")):
        return "B1_CS_FTS_ZERO_GOAL"
    if any(token in low for token in ("seasonppg", "table_position", "position", "ppg_overall", "points", "goaldifference", "goal_difference")):
        return "B4_RELATIVE_TABLE_STRENGTH"
    if source_context == "form":
        if any(token in low for token in ("xg", "xga")):
            return "FORM_XG"
        return "FORM"
    if source_context == "league_team":
        if any(token in low for token in ("shots", "possession", "corners")):
            return "LEAGUE_TEAM_AUXILIARY"
        if any(token in low for token in ("xg", "scored", "conceded", "btts", "over25", "under25")):
            return "LEAGUE_TEAM_GOAL_PROFILE"
        return "LEAGUE_TEAM_PROFILE"
    if source_context == "league_context":
        return "LEAGUE_CONTEXT"
    if source_context == "match":
        return "MATCH_XG_PPG"
    return "OTHER"


def _add_feature(
    out: dict[str, float],
    groups: dict[str, str],
    name: str,
    value: Any,
    group: str,
) -> None:
    x = _finite(value)
    if x is None:
        return
    previous = groups.get(name)
    if previous is not None and previous != group:
        raise Phase4Error(f"feature_group_conflict:{name}:{previous}!={group}")
    out[name] = x
    groups[name] = group


def _target_team_rows(league: Mapping[str, Any], home_id: int, away_id: int):
    home = away = None
    for row in league.get("teams_full_home_away") or []:
        if not isinstance(row, dict):
            continue
        tid = row.get("id", row.get("team_id"))
        try:
            tid = int(float(tid))
        except (TypeError, ValueError):
            continue
        if tid == home_id:
            home = row
        elif tid == away_id:
            away = row
    return home or {}, away or {}


def _extract_features(row: Mapping[str, Any]) -> tuple[dict[str, float], dict[str, str]]:
    sources = json.loads(row["feature_sources_json"])
    match = sources.get("match") or {}
    league = sources.get("league") or {}
    form = sources.get("form") or {}
    table = sources.get("table") or {}
    player = sources.get("player") or {}
    home_id, away_id = int(row["home_id"]), int(row["away_id"])

    out: dict[str, float] = {}
    groups: dict[str, str] = {}

    prematch = match.get("prematch_optional") or {}
    for key, value in prematch.items():
        if not _safe_key(str(key)):
            continue
        group = "PROVIDER_POTENTIALS" if "potential" in str(key).lower() else "MATCH_XG_PPG"
        _add_feature(out, groups, f"match.{key}", value, group)

    identity = match.get("identity") or {}
    if isinstance(identity, dict):
        for path, key, value in _walk_dict_numbers(identity):
            if _safe_key(key) and key.lower() in {"game_week", "revised_game_week", "matches_completed_minimum", "no_home_away"}:
                _add_feature(out, groups, f"match_identity.{path}", value, "MATCH_CONTEXT")

    season_safe = league.get("season_safe_identity") or {}
    for path, key, value in _walk_dict_numbers(season_safe):
        if _safe_key(key):
            group = "SAMPLE_SECURITY" if any(t in key.lower() for t in ("matchescompleted", "totalmatches", "progress", "round")) else "LEAGUE_CONTEXT"
            _add_feature(out, groups, f"league_context.{path}", value, group)

    derived = league.get("league_aggregates_derived") or {}
    for path, key, value in _walk_dict_numbers(derived):
        if not _safe_key(key):
            continue
        if key == "league_source_count" or key.endswith("_recorded_n"):
            group = "SAMPLE_SECURITY"
        else:
            group = "LEAGUE_CONTEXT"
        _add_feature(out, groups, f"league_derived.{path}", value, group)

    home_team, away_team = _target_team_rows(league, home_id, away_id)
    for side, team in (("home", home_team), ("away", away_team)):
        for path, key, value in _walk_dict_numbers(team):
            if not _safe_key(key):
                continue
            group = _assign_group(key, "league_team", side)
            if "seasonmatchesplayed" in key.lower():
                group = "SAMPLE_SECURITY"
            _add_feature(out, groups, f"league_team.{side}.{path}", value, group)

    # Explicit A1 venue pair + deterministic interactions.
    a1_home = _find_numeric_key(home_team, "seasonBTTSPercentageHT_home")
    a1_away = _find_numeric_key(away_team, "seasonBTTSPercentageHT_away")
    _add_feature(out, groups, "A1.fh_btts_venue_home", a1_home, "A1_FH_BTTS_VENUE")
    _add_feature(out, groups, "A1.fh_btts_venue_away", a1_away, "A1_FH_BTTS_VENUE")
    if a1_home is not None and a1_away is not None:
        _add_feature(out, groups, "A1.fh_btts_venue_diff", a1_home - a1_away, "A1_FH_BTTS_VENUE")
        _add_feature(out, groups, "A1.fh_btts_venue_mean", (a1_home + a1_away) / 2.0, "A1_FH_BTTS_VENUE")

    for side in ("home", "away"):
        side_obj = form.get(side) or {}
        for block in ("last5", "last6", "last10", "home_split", "away_split"):
            payload = side_obj.get(block) or {}
            if not isinstance(payload, dict):
                continue
            for path, key, value in _walk_dict_numbers(payload):
                if not _safe_key(key):
                    continue
                group = _assign_group(key, "form", side)
                if key == "n":
                    group = "SAMPLE_SECURITY"
                _add_feature(out, groups, f"form.{side}.{block}.{path}", value, group)

    for side, table_row in (("home", table.get("home_row") or {}), ("away", table.get("away_row") or {})):
        if isinstance(table_row, dict):
            for path, key, value in _walk_dict_numbers(table_row):
                if _safe_key(key):
                    group = "SAMPLE_SECURITY" if "matchesplayed" in key.lower() or key.lower() == "played" else "B4_RELATIVE_TABLE_STRENGTH"
                    _add_feature(out, groups, f"table.{side}.{path}", value, group)

    # B4 deterministic relative features when both target rows expose the same scalar.
    if isinstance(table.get("home_row"), dict) and isinstance(table.get("away_row"), dict):
        hflat = {p: v for p, k, v in _walk_dict_numbers(table["home_row"]) if _safe_key(k)}
        aflat = {p: v for p, k, v in _walk_dict_numbers(table["away_row"]) if _safe_key(k)}
        for key in sorted(set(hflat) & set(aflat)):
            low = key.lower()
            if any(token in low for token in ("ppg", "point", "position", "goaldifference", "goal_difference")):
                _add_feature(out, groups, f"B4.diff.{key}", hflat[key] - aflat[key], "B4_RELATIVE_TABLE_STRENGTH")

    players = [p for p in (player.get("players") or []) if isinstance(p, dict)]
    by_team = {
        home_id: [p for p in players if int(float(p.get("club_team_id", p.get("team_id", -1)) or -1)) == home_id],
        away_id: [p for p in players if int(float(p.get("club_team_id", p.get("team_id", -1)) or -1)) == away_id],
    }
    depths = {}
    side_metrics: dict[str, dict[str, float | None]] = {}
    for side, tid in (("home", home_id), ("away", away_id)):
        ps = by_team[tid]
        depth = len(ps)
        depths[side] = depth
        _add_feature(out, groups, f"A2.players_found_{side}", depth, "A2_PLAYER_DEPTH")
        goals, assists, involvement = [], [], []
        goals90, assists90, involvement90 = [], [], []
        for p in ps:
            g, _ = _player_number(p, ("goals_overall", "goals", "total_goals"))
            a, _ = _player_number(p, ("assists_overall", "assists", "total_assists"))
            minutes, _ = _player_number(p, ("minutes_played_overall", "minutes_played", "minutes"))
            if g is not None:
                goals.append(g)
            if a is not None:
                assists.append(a)
            if g is not None and a is not None:
                involvement.append(g + a)
            if minutes is not None and minutes > 0:
                if g is not None:
                    goals90.append(g * 90.0 / minutes)
                if a is not None:
                    assists90.append(a * 90.0 / minutes)
                if g is not None and a is not None:
                    involvement90.append((g + a) * 90.0 / minutes)
        for metric, values in (("goals", goals), ("assists", assists), ("involvement", involvement)):
            ordered = sorted(values, reverse=True)
            total = sum(ordered)
            for n in (1, 2, 3):
                if len(ordered) >= n:
                    s = sum(ordered[:n])
                    _add_feature(out, groups, f"B2.{metric}_top{n}_{side}", s, "B2_PLAYER_CONCENTRATION")
                    if total > 0:
                        _add_feature(out, groups, f"B2.{metric}_share_top{n}_{side}", s / total, "B2_PLAYER_CONCENTRATION")
        for metric, values in (("goals_per90", goals90), ("assists_per90", assists90), ("involvement_per90", involvement90)):
            if values:
                mean = sum(values) / len(values)
                _add_feature(out, groups, f"B3.{metric}_mean_{side}", mean, "B3_PLAYER_CHANCE_QUALITY")
                side_metrics.setdefault(side, {})[metric] = mean

    _add_feature(out, groups, "A2.player_depth_min", min(depths.values()), "A2_PLAYER_DEPTH")
    _add_feature(out, groups, "A2.player_depth_mean", sum(depths.values()) / 2.0, "A2_PLAYER_DEPTH")
    _add_feature(out, groups, "A2.player_depth_diff", depths["home"] - depths["away"], "A2_PLAYER_DEPTH")
    for metric in ("goals_per90", "assists_per90", "involvement_per90"):
        hv = (side_metrics.get("home") or {}).get(metric)
        av = (side_metrics.get("away") or {}).get(metric)
        if hv is not None and av is not None:
            _add_feature(out, groups, f"B3.{metric}_home_minus_away", hv - av, "B3_PLAYER_CHANCE_QUALITY")

    # H2H is expected to be unavailable in the frozen collector, but handle it fail-safely if present.
    h2h = match.get("h2h")
    if isinstance(h2h, dict):
        for path, key, value in _walk_dict_numbers(h2h):
            if _safe_key(key):
                _add_feature(out, groups, f"h2h.{path}", value, "H2H")

    return out, groups


def _v3_base_record(row: Mapping[str, Any]) -> tuple[dict[str, float] | None, str | None]:
    sources = json.loads(row["feature_sources_json"])
    match = sources.get("match") or {}
    league = sources.get("league") or {}
    prematch = match.get("prematch_optional") or {}
    season = league.get("season_safe_identity") or {}
    mapping = {
        "liga_avg_heim_vor_spiel": season.get("seasonAVG_home"),
        "liga_avg_aus_vor_spiel": season.get("seasonAVG_away"),
        "liga_spiele_bisher": season.get("matchesCompleted"),
        "fs_xg_prematch_heim": prematch.get("team_a_xg_prematch"),
        "fs_xg_prematch_aus": prematch.get("team_b_xg_prematch"),
        "fs_o25_potential": prematch.get("o25_potential"),
        "fs_btts_potential": prematch.get("btts_potential"),
        "fs_avg_potential": prematch.get("avg_potential"),
        "fs_pre_ppg_heim": prematch.get("pre_match_home_ppg"),
        "fs_pre_ppg_aus": prematch.get("pre_match_away_ppg"),
    }
    base: dict[str, float] = {}
    for name, value in mapping.items():
        x = _finite(value)
        if x is None:
            return None, None
        base[name] = x
    country = str(season.get("country") or "").strip()
    name = str(season.get("name") or season.get("division") or row.get("competition") or "").strip()
    league_name = f"{country} {name}".strip() if country else name
    if not league_name:
        return None, None
    lh, la = base["liga_avg_heim_vor_spiel"], base["liga_avg_aus_vor_spiel"]
    xh, xa = base["fs_xg_prematch_heim"], base["fs_xg_prematch_aus"]
    ph, pa = base["fs_pre_ppg_heim"], base["fs_pre_ppg_aus"]
    o, b, a = base["fs_o25_potential"] / 100.0, base["fs_btts_potential"] / 100.0, base["fs_avg_potential"]
    engineered = {
        "league_goal_total": lh + la,
        "league_goal_diff": lh - la,
        "league_goal_absdiff": abs(lh - la),
        "fs_xg_total": xh + xa,
        "fs_xg_diff": xh - xa,
        "fs_xg_absdiff": abs(xh - xa),
        "fs_xg_min": min(xh, xa),
        "fs_xg_product": xh * xa,
        "ppg_diff": ph - pa,
        "ppg_absdiff": abs(ph - pa),
        "ppg_total": ph + pa,
        "o25_potential_frac": o,
        "btts_potential_frac": b,
        "avg_potential_copy": a,
        "potential_diff": o - b,
        "potential_absdiff": abs(o - b),
        "avg_minus_fsxg": a - (xh + xa),
        "fsxg_minus_league": (xh + xa) - (lh + la),
        "potential_product": o * b,
        "ppg_product": ph * pa,
    }
    return {**base, **engineered}, league_name


V3_NUMERIC = (
    "liga_avg_heim_vor_spiel", "liga_avg_aus_vor_spiel", "liga_spiele_bisher",
    "fs_xg_prematch_heim", "fs_xg_prematch_aus", "fs_o25_potential",
    "fs_btts_potential", "fs_avg_potential", "fs_pre_ppg_heim", "fs_pre_ppg_aus",
    "league_goal_total", "league_goal_diff", "league_goal_absdiff",
    "fs_xg_total", "fs_xg_diff", "fs_xg_absdiff", "fs_xg_min", "fs_xg_product",
    "ppg_diff", "ppg_absdiff", "ppg_total", "o25_potential_frac",
    "btts_potential_frac", "avg_potential_copy", "potential_diff",
    "potential_absdiff", "avg_minus_fsxg", "fsxg_minus_league",
    "potential_product", "ppg_product",
)


def _decision_for_cp3_path(profile: Mapping[str, Any], redundant_paths: set[str]) -> dict[str, Any]:
    path = str(profile.get("path") or "")
    eligibility = str(profile.get("research_eligibility") or "")
    types = profile.get("data_types") or {}
    coverage = float(profile.get("coverage_rate") or 0.0)
    reasons = []
    status = "AVAILABLE_FOR_PHASE4_TRANSFORMATION"
    if eligibility.startswith("BLOCKED_") or eligibility.startswith("NOT_ELIGIBLE"):
        status = "EXCLUDED"
        reasons.append(eligibility or "CP3_NOT_ELIGIBLE")
    elif "season_candidate_unvalidated" in path:
        status = "EXCLUDED"
        reasons.append("UNVALIDATED_PROVIDER_SEASON_FIELD")
    elif not any(k in types for k in ("int", "float")):
        status = "EXCLUDED"
        reasons.append("NON_NUMERIC")
    elif ".source_matches[]" in path:
        status = "EXCLUDED_DIRECT"
        reasons.append("VARIABLE_LENGTH_RAW_HISTORY_REPRESENTED_BY_STRICT_FORM_AGGREGATES")
    elif path.startswith("player.players[]"):
        status = "DERIVED_ONLY"
        reasons.append("VARIABLE_LENGTH_PLAYER_ROWS_REPRESENTED_BY_A2_B2_B3_DERIVATIONS")
    elif any(token in path.lower() for token in ("date_unix", "timestamp", ".id", "_id")):
        status = "CONTEXT_ONLY"
        reasons.append("IDENTITY_OR_TIMESTAMP_NOT_MODEL_SIGNAL")
    if path in redundant_paths:
        reasons.append("CP3_HIGH_REDUNDANCY_REVIEW")
    if coverage < 0.20:
        reasons.append("LOW_GLOBAL_COVERAGE_LT_20PCT")
    return {
        "path": path,
        "status": status,
        "coverage_rate": coverage,
        "research_eligibility": eligibility,
        "reasons": reasons,
    }


def _validate_inputs(cp2_dir: Path, cp3_dir: Path) -> dict[str, Any]:
    cp2_checkpoint = json.loads((cp2_dir / "CP2_MASTER_DATASET.json").read_text(encoding="utf-8"))
    cp3_checkpoint = json.loads((cp3_dir / "CP3_FEATURE_AUDIT.json").read_text(encoding="utf-8"))
    if cp2_checkpoint.get("gate") != "PASS" or int(cp2_checkpoint.get("match_count_valid", -1)) != EXPECTED_ROWS:
        raise Phase4Error("frozen_cp2_not_pass_16137")
    if (
        cp3_checkpoint.get("gate") != "PASS"
        or cp3_checkpoint.get("status") != "COMPLETE"
        or int(cp3_checkpoint.get("match_count_valid", -1)) != EXPECTED_ROWS
        or cp3_checkpoint.get("audit_version") != EXPECTED_CP3_AUDIT
    ):
        raise Phase4Error("frozen_cp3_not_complete_pass_16137")

    cp2_manifest = json.loads((cp2_dir / "FULL7_MASTER_BUILD_MANIFEST.json").read_text(encoding="utf-8"))
    master = cp2_dir / "FULL7_MASTER_STRICT.jsonl"
    expected_master_hash = ((cp2_manifest.get("artifacts") or {}).get(master.name) or {}).get("sha256")
    if not expected_master_hash or _sha256(master) != expected_master_hash:
        raise Phase4Error("frozen_cp2_master_hash_mismatch")

    cp3_manifest_path = cp3_dir / "FULL7_FEATURE_AUDIT_MANIFEST.json"
    cp3_manifest = json.loads(cp3_manifest_path.read_text(encoding="utf-8"))
    for name, info in (cp3_manifest.get("artifacts") or {}).items():
        path = cp3_dir / name
        if not path.is_file() or path.stat().st_size != int(info["bytes"]) or _sha256(path) != info["sha256"]:
            raise Phase4Error(f"frozen_cp3_artifact_hash_mismatch:{name}")

    catalog = cp3_dir / "FULL7_FEATURE_CATALOG.jsonl"
    field_profiles = [json.loads(line) for line in catalog.read_text(encoding="utf-8").splitlines() if line.strip()]
    derived_profiles = json.loads((cp3_dir / "FULL7_DERIVED_FEATURE_CATALOG.json").read_text(encoding="utf-8"))
    redundancy = json.loads((cp3_dir / "FULL7_REDUNDANCY_AUDIT.json").read_text(encoding="utf-8"))
    if len(field_profiles) != 2541 or len(derived_profiles) != 27:
        raise Phase4Error(f"cp3_catalog_counts_changed:{len(field_profiles)}:{len(derived_profiles)}")
    redundant_paths = {str(r.get("path_b")) for r in redundancy if r.get("path_b")}
    decisions = [_decision_for_cp3_path(p, redundant_paths) for p in field_profiles]
    return {
        "cp2_checkpoint": cp2_checkpoint,
        "cp3_checkpoint": cp3_checkpoint,
        "cp2_master_sha256": expected_master_hash,
        "cp3_manifest_sha256": _sha256(cp3_manifest_path),
        "field_profiles": field_profiles,
        "derived_profiles": derived_profiles,
        "redundancy": redundancy,
        "feature_decisions": decisions,
    }


def _date_from_row(row: Mapping[str, Any]) -> str:
    value = str(row.get("kickoff_utc") or "")
    if len(value) < 10:
        raise Phase4Error(f"kickoff_utc_missing:{row.get('match_id')}")
    return value[:10]


def _make_splits(dates: Sequence[str], match_ids: Sequence[int]) -> dict[str, Any]:
    n = len(dates)
    date_counts: dict[str, int] = {}
    for d in dates:
        date_counts[d] = date_counts.get(d, 0) + 1
    ordered_dates = sorted(date_counts)

    def boundary(target_fraction: float) -> str:
        target = n * target_fraction
        c = 0
        for d in ordered_dates:
            c += date_counts[d]
            if c >= target:
                return d
        return ordered_dates[-1]

    train_end = boundary(0.50)
    dev_end = boundary(0.65)
    train = [i for i, d in enumerate(dates) if d <= train_end]
    dev = [i for i, d in enumerate(dates) if train_end < d <= dev_end]
    oos_dates = [d for d in ordered_dates if d > dev_end]
    if len(train) < 3000 or len(dev) < 500 or not oos_dates:
        raise Phase4Error("insufficient_chronological_split")

    total_oos = sum(date_counts[d] for d in oos_dates)
    target_per_fold = total_oos / OOS_FOLDS
    folds: list[list[str]] = [[] for _ in range(OOS_FOLDS)]
    fold_idx = 0
    acc = 0
    for d in oos_dates:
        if fold_idx < OOS_FOLDS - 1 and acc >= target_per_fold:
            fold_idx += 1
            acc = 0
        folds[fold_idx].append(d)
        acc += date_counts[d]
    fold_rows = []
    for number, fold_dates in enumerate(folds, 1):
        test = [i for i, d in enumerate(dates) if d in set(fold_dates)]
        if not test:
            raise Phase4Error(f"empty_oos_fold:{number}")
        start = min(test)
        train_idx = list(range(start))
        fold_rows.append({
            "fold": number,
            "train_indices": train_idx,
            "test_indices": test,
            "train_rows": len(train_idx),
            "test_rows": len(test),
            "test_start_date": min(fold_dates),
            "test_end_date": max(fold_dates),
        })

    def id_hash(indices: Sequence[int]) -> str:
        raw = "\n".join(str(match_ids[i]) for i in indices) + "\n"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    return {
        "split_version": "FULL7_PHASE4_CHRONO_1.0",
        "policy": "date-preserving chronological train/development/expanding walk-forward OOS",
        "shuffle": False,
        "train_end_date": train_end,
        "development_end_date": dev_end,
        "train_indices": train,
        "development_indices": dev,
        "train_rows": len(train),
        "development_rows": len(dev),
        "oos_rows": sum(f["test_rows"] for f in fold_rows),
        "train_match_id_sha256": id_hash(train),
        "development_match_id_sha256": id_hash(dev),
        "oos_folds": [
            {k: v for k, v in f.items() if k not in {"train_indices", "test_indices"}}
            | {
                "train_match_id_sha256": id_hash(f["train_indices"]),
                "test_match_id_sha256": id_hash(f["test_indices"]),
            }
            for f in fold_rows
        ],
        "_fold_indices": fold_rows,
    }


def _matrix_pass(master_path: Path, stage: Path) -> dict[str, Any]:
    matrix_meta_path = stage / "PHASE4_MATRIX_METADATA.json"
    if matrix_meta_path.is_file():
        meta = json.loads(matrix_meta_path.read_text(encoding="utf-8"))
        required = [
            stage / "PHASE4_MATRIX.npy",
            stage / "PHASE4_V3_MATRIX.npy",
            stage / "PHASE4_LABELS.npz",
        ]
        if all(p.is_file() for p in required):
            return meta
        raise Phase4Error("phase4_matrix_metadata_without_files")

    feature_names: set[str] = set()
    group_map: dict[str, str] = {}
    match_ids, kickoffs, dates, leagues = [], [], [], []
    y1, yb, yo, yh, ya = [], [], [], [], []
    v3_support = 0
    processed = 0

    with master_path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            features, groups = _extract_features(row)
            feature_names.update(features)
            for name, group in groups.items():
                old = group_map.get(name)
                if old is not None and old != group:
                    raise Phase4Error(f"feature_group_changed:{name}:{old}!={group}")
                group_map[name] = group
            base, league_name = _v3_base_record(row)
            v3_support += int(base is not None)
            match_ids.append(int(row["match_id"]))
            kickoffs.append(int(row["kickoff_unix"]))
            dates.append(_date_from_row(row))
            leagues.append(league_name or "")
            y1.append({"H": 0, "D": 1, "A": 2}[row["label_actual_1x2"]])
            yb.append(int(row["label_actual_btts"]))
            yo.append(int(row["label_actual_over25"]))
            yh.append(int(row["label_home_goals"]))
            ya.append(int(row["label_away_goals"]))
            processed += 1
            if processed % 500 == 0:
                print(f"PHASE4_MATRIX_DISCOVERY_ROWS={processed}", flush=True)

    if processed != EXPECTED_ROWS or len(set(match_ids)) != EXPECTED_ROWS:
        raise Phase4Error(f"phase4_master_population_mismatch:{processed}")
    # CP2 physical row order is frozen but is not required to be chronological.
    # Phase 4 must be chronological, so derive a stable permutation without
    # mutating/rebuilding CP2 and write every research row into that order.
    order = np.asarray(
        sorted(range(processed), key=lambda i: (kickoffs[i], match_ids[i])),
        dtype=np.int64,
    )
    inverse_order = np.empty(processed, dtype=np.int64)
    inverse_order[order] = np.arange(processed, dtype=np.int64)

    names = sorted(feature_names)
    index = {name: j for j, name in enumerate(names)}
    X = np.lib.format.open_memmap(
        stage / "PHASE4_MATRIX.npy", mode="w+", dtype=np.float32, shape=(processed, len(names))
    )
    X[:] = np.nan
    V3 = np.lib.format.open_memmap(
        stage / "PHASE4_V3_MATRIX.npy", mode="w+", dtype=np.float32, shape=(processed, len(V3_NUMERIC))
    )
    V3[:] = np.nan

    row_index = 0
    with master_path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            features, _groups = _extract_features(row)
            target_index = int(inverse_order[row_index])
            for name, value in features.items():
                X[target_index, index[name]] = value
            base, _league_name = _v3_base_record(row)
            if base is not None:
                for j, name in enumerate(V3_NUMERIC):
                    V3[target_index, j] = base[name]
            row_index += 1
            if row_index % 500 == 0:
                X.flush()
                V3.flush()
                print(f"PHASE4_MATRIX_FILL_ROWS={row_index}", flush=True)
    X.flush()
    V3.flush()
    del X, V3
    gc.collect()

    np.savez_compressed(
        stage / "PHASE4_LABELS.npz",
        match_ids=np.asarray(match_ids, dtype=np.int64)[order],
        kickoffs=np.asarray(kickoffs, dtype=np.int64)[order],
        dates=np.asarray(dates, dtype="U10")[order],
        leagues=np.asarray(leagues, dtype="U128")[order],
        y1=np.asarray(y1, dtype=np.int8)[order],
        yb=np.asarray(yb, dtype=np.int8)[order],
        yo=np.asarray(yo, dtype=np.int8)[order],
        yh=np.asarray(yh, dtype=np.int16)[order],
        ya=np.asarray(ya, dtype=np.int16)[order],
    )
    meta = {
        "matrix_version": "FULL7_PHASE4_MATRIX_1.0",
        "row_count": processed,
        "feature_count_discovered": len(names),
        "feature_names": names,
        "feature_groups": {name: group_map[name] for name in names},
        "v3_numeric_features": list(V3_NUMERIC),
        "v3_supported_rows": v3_support,
        "research_row_order": "chronological_by_kickoff_unix_then_match_id",
        "cp2_physical_order_mutated": False,
        "created_at_utc": _utcnow(),
    }
    _json_atomic(matrix_meta_path, meta)
    return meta


def _feature_selection(stage: Path, matrix_meta: Mapping[str, Any], splits: Mapping[str, Any]) -> dict[str, Any]:
    path = stage / "PHASE4_FEATURE_SELECTION.json"
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    X = np.load(stage / "PHASE4_MATRIX.npy", mmap_mode="r")
    train = np.asarray(splits["train_indices"], dtype=np.int64)
    names = list(matrix_meta["feature_names"])
    groups = dict(matrix_meta["feature_groups"])
    count = np.zeros(len(names), dtype=np.int64)
    total = np.zeros(len(names), dtype=np.float64)
    total2 = np.zeros(len(names), dtype=np.float64)
    for start in range(0, len(train), 512):
        block = np.asarray(X[train[start:start+512]], dtype=np.float64)
        finite = np.isfinite(block)
        count += finite.sum(axis=0)
        safe = np.where(finite, block, 0.0)
        total += safe.sum(axis=0)
        total2 += (safe * safe).sum(axis=0)
    variance = np.zeros(len(names), dtype=np.float64)
    mask = count > 1
    variance[mask] = np.maximum(0.0, (total2[mask] - total[mask] * total[mask] / count[mask]) / (count[mask] - 1))

    selected, excluded = [], []
    for j, name in enumerate(names):
        coverage = count[j] / len(train)
        reasons = []
        if count[j] < MIN_TRAIN_NON_NULL:
            reasons.append("TRAIN_NON_NULL_LT_100")
        if coverage < MIN_TRAIN_COVERAGE:
            reasons.append("TRAIN_COVERAGE_LT_20PCT")
        if variance[j] <= 1e-12:
            reasons.append("CONSTANT_OR_NEAR_CONSTANT_IN_TRAIN")
        low = name.lower()
        if "under25" in low:
            counterpart = name.replace("Under25", "Over25").replace("under25", "over25")
            if counterpart in names:
                reasons.append("REDUNDANT_COMPLEMENT_OF_OVER25")
        if reasons:
            excluded.append({
                "feature": name,
                "group": groups[name],
                "train_coverage": round(float(coverage), 12),
                "train_non_null": int(count[j]),
                "variance": float(variance[j]),
                "reasons": reasons,
            })
        else:
            selected.append(name)

    group_counts: dict[str, int] = {}
    for name in selected:
        group_counts[groups[name]] = group_counts.get(groups[name], 0) + 1
    core = [name for name in selected if groups[name] not in RESEARCH_ONLY_GROUPS]
    full = list(selected)
    stable_base = [name for name in core if groups[name] not in set(PRIORITY_GROUPS)]
    result = {
        "selection_version": "FULL7_PHASE4_FEATURE_SELECTION_1.0",
        "train_only_filtering": True,
        "train_rows": len(train),
        "min_train_coverage": MIN_TRAIN_COVERAGE,
        "min_train_non_null": MIN_TRAIN_NON_NULL,
        "selected_feature_count": len(selected),
        "core_feature_count": len(core),
        "full_research_feature_count": len(full),
        "stable_base_feature_count": len(stable_base),
        "selected_features": selected,
        "core_features": core,
        "full_research_features": full,
        "stable_base_features": stable_base,
        "group_counts": dict(sorted(group_counts.items())),
        "excluded_features": excluded,
    }
    _json_atomic(path, result)
    return result


def _clip_prob(p: np.ndarray) -> np.ndarray:
    return np.clip(p.astype(float), 1e-7, 1.0 - 1e-7)


def _reliability_binary(y: np.ndarray, p: np.ndarray, bins: int = 10) -> tuple[list[dict[str, Any]], float, float]:
    p = _clip_prob(p)
    rows = []
    ece = 0.0
    mce = 0.0
    for b in range(bins):
        lo, hi = b / bins, (b + 1) / bins
        mask = (p >= lo) & (p < hi if b < bins - 1 else p <= hi)
        n = int(mask.sum())
        if not n:
            continue
        pred = float(p[mask].mean())
        actual = float(y[mask].mean())
        gap = abs(pred - actual)
        ece += gap * n / len(y)
        mce = max(mce, gap)
        rows.append({"bin": b, "n": n, "mean_probability": pred, "empirical_rate": actual, "absolute_gap": gap})
    return rows, float(ece), float(mce)


def _metrics_binary(y: np.ndarray, p: np.ndarray) -> dict[str, Any]:
    p = _clip_prob(p)
    ll = -float(np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))
    brier = float(np.mean((p - y) ** 2))
    acc = float(np.mean((p >= 0.5) == y))
    rel, ece, mce = _reliability_binary(y, p)
    return {"n": len(y), "logloss": ll, "brier": brier, "accuracy": acc, "ece_10": ece, "mce_10": mce, "reliability_10": rel}


def _metrics_multiclass(y: np.ndarray, p: np.ndarray) -> dict[str, Any]:
    p = np.clip(p.astype(float), 1e-7, 1.0)
    p = p / p.sum(axis=1, keepdims=True)
    ll = -float(np.mean(np.log(p[np.arange(len(y)), y])))
    onehot = np.eye(3)[y]
    brier = float(np.mean(np.sum((p - onehot) ** 2, axis=1)))
    pred = p.argmax(axis=1)
    acc = float(np.mean(pred == y))
    conf = p.max(axis=1)
    correct = (pred == y).astype(int)
    rel, ece, mce = _reliability_binary(correct, conf)
    class_metrics = {}
    for cls, name in enumerate(("home", "draw", "away")):
        class_metrics[name] = _metrics_binary((y == cls).astype(int), p[:, cls])
    return {
        "n": len(y), "logloss": ll, "brier": brier, "accuracy": acc,
        "toplabel_ece_10": ece, "toplabel_mce_10": mce, "toplabel_reliability_10": rel,
        "one_vs_rest": class_metrics,
    }


def _target_arrays(labels: Mapping[str, np.ndarray], target: str):
    if target == "1X2":
        return labels["y1"]
    if target == "BTTS":
        return labels["yb"]
    if target == "O25":
        return labels["yo"]
    raise Phase4Error(f"unknown_target:{target}")


def _target_metrics(target: str, y: np.ndarray, p: np.ndarray):
    return _metrics_multiclass(y, p) if target == "1X2" else _metrics_binary(y, p)


def _hgb_classifier(params: Mapping[str, Any]) -> HistGradientBoostingClassifier:
    return HistGradientBoostingClassifier(
        loss="log_loss",
        random_state=RANDOM_STATE,
        early_stopping=False,
        max_bins=63,
        **params,
    )


def _fit_direct(
    X: np.ndarray,
    y: np.ndarray,
    train_idx: Sequence[int],
    test_idx: Sequence[int],
    cols: Sequence[int],
    target: str,
    params: Mapping[str, Any],
) -> np.ndarray:
    xtr = np.asarray(X[np.ix_(np.asarray(train_idx), np.asarray(cols))], dtype=np.float32)
    xte = np.asarray(X[np.ix_(np.asarray(test_idx), np.asarray(cols))], dtype=np.float32)
    model = _hgb_classifier(params)
    model.fit(xtr, y[np.asarray(train_idx)])
    raw = model.predict_proba(xte)
    if target == "1X2":
        out = np.zeros((len(test_idx), 3), dtype=np.float64)
        for col, cls in enumerate(model.classes_):
            out[:, int(cls)] = raw[:, col]
    else:
        cls_to_col = {int(cls): i for i, cls in enumerate(model.classes_)}
        out = raw[:, cls_to_col[1]]
    del model, xtr, xte
    gc.collect()
    return out


def _poisson_market_probs(lh: np.ndarray, la: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    lh = np.clip(np.asarray(lh, dtype=float), 0.03, 8.0)
    la = np.clip(np.asarray(la, dtype=float), 0.03, 8.0)
    n = len(lh)
    p1 = np.zeros((n, 3), dtype=float)
    pb = np.zeros(n, dtype=float)
    po = np.zeros(n, dtype=float)
    factorial = [math.factorial(k) for k in range(13)]
    for r in range(n):
        ph = np.array([math.exp(-lh[r]) * lh[r] ** k / factorial[k] for k in range(13)])
        pa = np.array([math.exp(-la[r]) * la[r] ** k / factorial[k] for k in range(13)])
        matrix = np.outer(ph, pa)
        matrix /= matrix.sum() or 1.0
        p1[r, 0] = np.tril(matrix, -1).sum()
        p1[r, 1] = np.trace(matrix)
        p1[r, 2] = np.triu(matrix, 1).sum()
        pb[r] = matrix[1:, 1:].sum()
        po[r] = sum(matrix[i, j] for i in range(13) for j in range(13) if i + j >= 3)
    return p1, pb, po


def _fit_poisson(
    X: np.ndarray,
    labels: Mapping[str, np.ndarray],
    train_idx: Sequence[int],
    test_idx: Sequence[int],
    cols: Sequence[int],
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    xtr = np.asarray(X[np.ix_(np.asarray(train_idx), np.asarray(cols))], dtype=np.float32)
    xte = np.asarray(X[np.ix_(np.asarray(test_idx), np.asarray(cols))], dtype=np.float32)
    yh, ya = labels["yh"], labels["ya"]
    mh = HistGradientBoostingRegressor(
        loss="poisson", random_state=RANDOM_STATE, early_stopping=False, max_bins=63, **POISSON_PARAMS
    )
    ma = HistGradientBoostingRegressor(
        loss="poisson", random_state=RANDOM_STATE + 1, early_stopping=False, max_bins=63, **POISSON_PARAMS
    )
    mh.fit(xtr, yh[np.asarray(train_idx)])
    ph = mh.predict(xte)
    del mh
    gc.collect()
    ma.fit(xtr, ya[np.asarray(train_idx)])
    pa = ma.predict(xte)
    del ma, xtr, xte
    gc.collect()
    return _poisson_market_probs(ph, pa)


def _prepare_feature_indices(matrix_meta: Mapping[str, Any], selection: Mapping[str, Any]):
    index = {name: i for i, name in enumerate(matrix_meta["feature_names"])}
    sets = {
        "CORE": [index[n] for n in selection["core_features"]],
        "FULL_RESEARCH": [index[n] for n in selection["full_research_features"]],
        "STABLE_BASE": [index[n] for n in selection["stable_base_features"]],
    }
    return index, sets


def _experiment_paths(stage: Path, name: str, target: str, split: str):
    safe = f"{name}__{target}__{split}".replace("/", "_")
    directory = stage / "experiments"
    directory.mkdir(exist_ok=True)
    return directory / f"{safe}.json", directory / f"{safe}.npz"


def _eval_direct_experiment(
    stage: Path,
    name: str,
    target: str,
    feature_names: Sequence[str],
    matrix_meta: Mapping[str, Any],
    split_indices: Sequence[tuple[Sequence[int], Sequence[int], str]],
    params: Mapping[str, Any],
    labels: Mapping[str, np.ndarray],
    X: np.ndarray,
    evaluation_mask: np.ndarray | None = None,
) -> dict[str, Any]:
    result_path, pred_path = _experiment_paths(stage, name, target, "WALKFORWARD")
    if result_path.is_file() and pred_path.is_file():
        return json.loads(result_path.read_text(encoding="utf-8"))
    idx_map = {n: i for i, n in enumerate(matrix_meta["feature_names"])}
    cols = [idx_map[n] for n in feature_names]
    if not cols:
        raise Phase4Error(f"empty_feature_set:{name}")
    y = _target_arrays(labels, target)
    pred = np.full((len(y), 3), np.nan, dtype=np.float32) if target == "1X2" else np.full(len(y), np.nan, dtype=np.float32)
    folds = []
    for train_idx, test_idx, label in split_indices:
        p = _fit_direct(X, y, train_idx, test_idx, cols, target, params)
        pred[np.asarray(test_idx)] = p
        folds.append({"fold": label, **_target_metrics(target, y[np.asarray(test_idx)], p)})
        print(f"PHASE4_EXPERIMENT_FOLD={name}:{target}:{label}", flush=True)
    test_all = np.concatenate([np.asarray(x[1], dtype=int) for x in split_indices])
    metrics = _target_metrics(target, y[test_all], pred[test_all])
    common = None
    if evaluation_mask is not None:
        ci = test_all[evaluation_mask[test_all]]
        if len(ci):
            common = _target_metrics(target, y[ci], pred[ci])
    np.savez_compressed(pred_path, pred=pred)
    result = {
        "experiment": name,
        "target": target,
        "feature_count": len(feature_names),
        "params": dict(params),
        "metrics_all": metrics,
        "metrics_v3_common": common,
        "folds": folds,
        "prediction_file": pred_path.name,
        "prediction_sha256": _sha256(pred_path),
    }
    _json_atomic(result_path, result)
    return result


def _eval_direct_development(
    stage: Path,
    name: str,
    target: str,
    feature_names: Sequence[str],
    matrix_meta: Mapping[str, Any],
    train_idx: Sequence[int],
    dev_idx: Sequence[int],
    params: Mapping[str, Any],
    labels: Mapping[str, np.ndarray],
    X: np.ndarray,
    evaluation_mask: np.ndarray | None = None,
) -> dict[str, Any]:
    result_path, pred_path = _experiment_paths(stage, name, target, "DEVELOPMENT")
    if result_path.is_file() and pred_path.is_file():
        return json.loads(result_path.read_text(encoding="utf-8"))
    idx_map = {n: i for i, n in enumerate(matrix_meta["feature_names"])}
    cols = [idx_map[n] for n in feature_names]
    y = _target_arrays(labels, target)
    p = _fit_direct(X, y, train_idx, dev_idx, cols, target, params)
    pred = np.full((len(y), 3), np.nan, dtype=np.float32) if target == "1X2" else np.full(len(y), np.nan, dtype=np.float32)
    pred[np.asarray(dev_idx)] = p
    metrics = _target_metrics(target, y[np.asarray(dev_idx)], p)
    common = None
    if evaluation_mask is not None:
        ci = np.asarray(dev_idx)[evaluation_mask[np.asarray(dev_idx)]]
        if len(ci):
            common = _target_metrics(target, y[ci], pred[ci])
    np.savez_compressed(pred_path, pred=pred)
    result = {
        "experiment": name, "target": target, "feature_count": len(feature_names),
        "params": dict(params), "metrics_all": metrics, "metrics_v3_common": common,
        "prediction_file": pred_path.name, "prediction_sha256": _sha256(pred_path),
    }
    _json_atomic(result_path, result)
    return result


def _v3_design(v3: np.ndarray, leagues: np.ndarray, train_idx: np.ndarray, test_idx: np.ndarray):
    xtr = np.asarray(v3[train_idx], dtype=float)
    xte = np.asarray(v3[test_idx], dtype=float)
    mean = xtr.mean(axis=0)
    scale = xtr.std(axis=0)
    scale[scale < 1e-12] = 1.0
    ztr, zte = (xtr - mean) / scale, (xte - mean) / scale
    cats = sorted(set(str(leagues[i]) for i in train_idx))
    cmap = {c: j for j, c in enumerate(cats)}
    ohtr = np.zeros((len(train_idx), len(cats)), dtype=np.float32)
    ohte = np.zeros((len(test_idx), len(cats)), dtype=np.float32)
    for r, i in enumerate(train_idx):
        j = cmap.get(str(leagues[i]))
        if j is not None:
            ohtr[r, j] = 1.0
    for r, i in enumerate(test_idx):
        j = cmap.get(str(leagues[i]))
        if j is not None:
            ohte[r, j] = 1.0
    return np.hstack([ztr, ohtr]), np.hstack([zte, ohte])


def _fit_v3_target(v3: np.ndarray, leagues: np.ndarray, y: np.ndarray, train_idx: np.ndarray, test_idx: np.ndarray, target: str):
    xtr, xte = _v3_design(v3, leagues, train_idx, test_idx)
    model = SGDClassifier(
        loss="log_loss", penalty="l2", alpha=0.0001, max_iter=3000, tol=1e-5,
        random_state=RANDOM_STATE, shuffle=True,
    )
    model.fit(xtr, y[train_idx])
    raw = model.predict_proba(xte)
    if target == "1X2":
        out = np.zeros((len(test_idx), 3), dtype=float)
        for col, cls in enumerate(model.classes_):
            out[:, int(cls)] = raw[:, col]
    else:
        cls_to_col = {int(cls): i for i, cls in enumerate(model.classes_)}
        out = raw[:, cls_to_col[1]]
    del model, xtr, xte
    gc.collect()
    return out


def _eval_v3_baseline(
    stage: Path,
    labels: Mapping[str, np.ndarray],
    v3: np.ndarray,
    leagues: np.ndarray,
    train_idx: Sequence[int],
    dev_idx: Sequence[int],
    folds: Sequence[tuple[Sequence[int], Sequence[int], str]],
) -> dict[str, Any]:
    path = stage / "PHASE4_V3_BASELINE.json"
    pred_file = stage / "PHASE4_V3_BASELINE_PREDICTIONS.npz"
    if path.is_file() and pred_file.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    supported = np.all(np.isfinite(v3), axis=1) & (leagues != "")
    train_arr = np.asarray(train_idx, dtype=int)
    dev_arr = np.asarray(dev_idx, dtype=int)
    fold_support = []
    for _ftr, _fte, _label in folds:
        _fte_arr = np.asarray(_fte, dtype=int)
        fold_support.append({
            "fold": _label,
            "rows": int(len(_fte_arr)),
            "supported_rows": int(supported[_fte_arr].sum()),
        })
    per_feature = {}
    for j, name in enumerate(V3_NUMERIC):
        per_feature[name] = {
            "all_non_null": int(np.isfinite(v3[:, j]).sum()),
            "train_non_null": int(np.isfinite(v3[train_arr, j]).sum()),
            "development_non_null": int(np.isfinite(v3[dev_arr, j]).sum()),
        }
    support_diag = {
        "all_rows": int(len(supported)),
        "all_supported_rows": int(supported.sum()),
        "train_rows": int(len(train_arr)),
        "train_supported_rows": int(supported[train_arr].sum()),
        "development_rows": int(len(dev_arr)),
        "development_supported_rows": int(supported[dev_arr].sum()),
        "oos_folds": fold_support,
        "per_feature_non_null": per_feature,
    }
    _json_atomic(stage / "PHASE4_V3_SUPPORT_DIAGNOSTIC.json", support_diag)
    print("PHASE4_V3_SUPPORT=" + json.dumps(support_diag, sort_keys=True), flush=True)
    outputs: dict[str, Any] = {
        "baseline": "V3_1_CONTRACT_RETRAINED_REFERENCE",
        "architecture": "30 numeric V3.1 features + train-only league one-hot + standardized SGDClassifier(log_loss)",
        "exact_live_feature_contract": True,
        "estimator_hyperparameter_caveat": "Original V3.1 SGD hyperparameters were not persisted; architecture and feature contract are exact, this is the fair retrained chronological reference.",
        "supported_rows": int(supported.sum()),
        "targets": {},
    }
    saved = {}
    for target in ("1X2", "BTTS", "O25"):
        y = _target_arrays(labels, target)
        shape = (len(y), 3) if target == "1X2" else (len(y),)
        dev_pred = np.full(shape, np.nan, dtype=np.float32)
        oos_pred = np.full(shape, np.nan, dtype=np.float32)
        tr = np.asarray([i for i in train_idx if supported[i]], dtype=int)
        dv = np.asarray([i for i in dev_idx if supported[i]], dtype=int)
        if len(tr) < 1000 or len(dv) < 100:
            raise Phase4Error(
                f"v3_development_support_too_low:train={len(tr)}:development={len(dv)}"
            )
        pdev = _fit_v3_target(v3, leagues, y, tr, dv, target)
        dev_pred[dv] = pdev
        fold_metrics = []
        for fold_train, fold_test, label in folds:
            ftr = np.asarray([i for i in fold_train if supported[i]], dtype=int)
            fte = np.asarray([i for i in fold_test if supported[i]], dtype=int)
            if len(ftr) < 1000 or len(fte) < 50:
                raise Phase4Error(f"v3_fold_support_too_low:{label}")
            p = _fit_v3_target(v3, leagues, y, ftr, fte, target)
            oos_pred[fte] = p
            fold_metrics.append({"fold": label, **_target_metrics(target, y[fte], p)})
        oos_idx = np.concatenate([
            np.asarray([i for i in ft if supported[i]], dtype=int)
            for _tr, ft, _label in folds
        ])
        outputs["targets"][target] = {
            "development": _target_metrics(target, y[dv], dev_pred[dv]),
            "walkforward_oos": _target_metrics(target, y[oos_idx], oos_pred[oos_idx]),
            "folds": fold_metrics,
        }
        saved[f"{target}_dev"] = dev_pred
        saved[f"{target}_oos"] = oos_pred
    saved["supported"] = supported
    np.savez_compressed(pred_file, **saved)
    outputs["prediction_file"] = pred_file.name
    outputs["prediction_sha256"] = _sha256(pred_file)
    _json_atomic(path, outputs)
    return outputs


def _eval_poisson(
    stage: Path,
    name: str,
    feature_names: Sequence[str],
    matrix_meta: Mapping[str, Any],
    labels: Mapping[str, np.ndarray],
    X: np.ndarray,
    train_idx: Sequence[int],
    dev_idx: Sequence[int],
    folds: Sequence[tuple[Sequence[int], Sequence[int], str]],
    v3_supported: np.ndarray,
) -> dict[str, Any]:
    path = stage / f"{name}.json"
    pred_file = stage / f"{name}_PREDICTIONS.npz"
    if path.is_file() and pred_file.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    idx = {n: i for i, n in enumerate(matrix_meta["feature_names"])}
    cols = [idx[n] for n in feature_names]
    predictions = {}
    result = {"experiment": name, "feature_count": len(feature_names), "targets": {}, "params": dict(POISSON_PARAMS)}
    # Development
    d1, db, do = _fit_poisson(X, labels, train_idx, dev_idx, cols)
    dev_map = {"1X2": d1, "BTTS": db, "O25": do}
    # Walk-forward
    oos_map = {
        "1X2": np.full((len(labels["y1"]), 3), np.nan, dtype=np.float32),
        "BTTS": np.full(len(labels["yb"]), np.nan, dtype=np.float32),
        "O25": np.full(len(labels["yo"]), np.nan, dtype=np.float32),
    }
    fold_metrics = {t: [] for t in ("1X2", "BTTS", "O25")}
    for ftr, fte, label in folds:
        p1, pb, po = _fit_poisson(X, labels, ftr, fte, cols)
        for target, p in (("1X2", p1), ("BTTS", pb), ("O25", po)):
            oos_map[target][np.asarray(fte)] = p
            y = _target_arrays(labels, target)
            fold_metrics[target].append({"fold": label, **_target_metrics(target, y[np.asarray(fte)], p)})
        print(f"PHASE4_POISSON_FOLD={label}", flush=True)
    oos_idx = np.concatenate([np.asarray(f[1], dtype=int) for f in folds])
    for target in ("1X2", "BTTS", "O25"):
        y = _target_arrays(labels, target)
        dev_arr = np.full_like(oos_map[target], np.nan)
        dev_arr[np.asarray(dev_idx)] = dev_map[target]
        common_dev = np.asarray(dev_idx)[v3_supported[np.asarray(dev_idx)]]
        common_oos = oos_idx[v3_supported[oos_idx]]
        result["targets"][target] = {
            "development": _target_metrics(target, y[np.asarray(dev_idx)], dev_map[target]),
            "development_v3_common": _target_metrics(target, y[common_dev], dev_arr[common_dev]) if len(common_dev) else None,
            "walkforward_oos": _target_metrics(target, y[oos_idx], oos_map[target][oos_idx]),
            "walkforward_oos_v3_common": _target_metrics(target, y[common_oos], oos_map[target][common_oos]) if len(common_oos) else None,
            "folds": fold_metrics[target],
        }
        predictions[f"{target}_dev"] = dev_arr
        predictions[f"{target}_oos"] = oos_map[target]
    np.savez_compressed(pred_file, **predictions)
    result["prediction_file"] = pred_file.name
    result["prediction_sha256"] = _sha256(pred_file)
    _json_atomic(path, result)
    return result


def _ensemble_metrics(
    stage: Path,
    hgb_dev_files: Mapping[str, str],
    hgb_oos_files: Mapping[str, str],
    poisson_file: Path,
    labels: Mapping[str, np.ndarray],
    dev_idx: Sequence[int],
    oos_idx: np.ndarray,
    v3_supported: np.ndarray,
) -> dict[str, Any]:
    path = stage / "ENSEMBLE_HGB_POISSON_CORE.json"
    pred_path = stage / "ENSEMBLE_HGB_POISSON_CORE_PREDICTIONS.npz"
    if path.is_file() and pred_path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    pp = np.load(poisson_file)
    saved, result_targets = {}, {}
    for target in ("1X2", "BTTS", "O25"):
        hd = np.load(stage / "experiments" / hgb_dev_files[target])["pred"]
        ho = np.load(stage / "experiments" / hgb_oos_files[target])["pred"]
        pd = pp[f"{target}_dev"]
        po = pp[f"{target}_oos"]
        ed = (hd + pd) / 2.0
        eo = (ho + po) / 2.0
        y = _target_arrays(labels, target)
        dvi = np.asarray(dev_idx)
        common_dev = dvi[v3_supported[dvi]]
        common_oos = oos_idx[v3_supported[oos_idx]]
        result_targets[target] = {
            "development": _target_metrics(target, y[dvi], ed[dvi]),
            "development_v3_common": _target_metrics(target, y[common_dev], ed[common_dev]) if len(common_dev) else None,
            "walkforward_oos": _target_metrics(target, y[oos_idx], eo[oos_idx]),
            "walkforward_oos_v3_common": _target_metrics(target, y[common_oos], eo[common_oos]) if len(common_oos) else None,
        }
        saved[f"{target}_dev"] = ed
        saved[f"{target}_oos"] = eo
    np.savez_compressed(pred_path, **saved)
    result = {
        "experiment": "ENSEMBLE_HGB_POISSON_CORE",
        "blend": "fixed arithmetic mean 0.5/0.5; no weight tuning",
        "targets": result_targets,
        "prediction_file": pred_path.name,
        "prediction_sha256": _sha256(pred_path),
    }
    _json_atomic(path, result)
    return result


def _ablation_experiment(
    stage: Path,
    set_name: str,
    feature_names: Sequence[str],
    target: str,
    matrix_meta: Mapping[str, Any],
    labels: Mapping[str, np.ndarray],
    X: np.ndarray,
    folds: Sequence[tuple[Sequence[int], Sequence[int], str]],
) -> dict[str, Any]:
    return _eval_direct_experiment(
        stage, f"ABLATION_{set_name}", target, feature_names, matrix_meta, folds,
        ABLATION_PARAMS, labels, X, evaluation_mask=None,
    )


def _delta(reference: Mapping[str, Any], comparison: Mapping[str, Any]) -> dict[str, float]:
    r, c = reference["metrics_all"], comparison["metrics_all"]
    return {
        "logloss_improvement": float(r["logloss"] - c["logloss"]),
        "brier_improvement": float(r["brier"] - c["brier"]),
        "accuracy_change": float(c["accuracy"] - r["accuracy"]),
    }


def _group_research(
    stage: Path,
    selection: Mapping[str, Any],
    matrix_meta: Mapping[str, Any],
    labels: Mapping[str, np.ndarray],
    X: np.ndarray,
    folds: Sequence[tuple[Sequence[int], Sequence[int], str]],
) -> dict[str, Any]:
    path = stage / "PHASE4_GROUP_ABLATIONS.json"
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    groups = dict(matrix_meta["feature_groups"])
    core = list(selection["core_features"])
    full = list(selection["full_research_features"])
    base = list(selection["stable_base_features"])
    group_names = sorted({groups[n] for n in full})
    output = {"ablation_model": "HistGradientBoosting fixed ablation parameters", "groups": {}}
    for target in ("1X2", "BTTS", "O25"):
        ref_core = _ablation_experiment(stage, "REF_CORE", core, target, matrix_meta, labels, X, folds)
        ref_full = _ablation_experiment(stage, "REF_FULL_RESEARCH", full, target, matrix_meta, labels, X, folds)
        ref_base = _ablation_experiment(stage, "REF_STABLE_BASE", base, target, matrix_meta, labels, X, folds)
        for group in group_names:
            members = [n for n in full if groups[n] == group]
            if not members:
                continue
            entry = output["groups"].setdefault(group, {"feature_count": len(members), "targets": {}})
            reference_names = full if group in RESEARCH_ONLY_GROUPS else core
            reference = ref_full if group in RESEARCH_ONLY_GROUPS else ref_core
            if group not in RESEARCH_ONLY_GROUPS and not any(groups[n] == group for n in core):
                continue
            loo_names = [n for n in reference_names if groups[n] != group]
            if not loo_names:
                continue
            removed = _ablation_experiment(stage, f"WITHOUT_{group}", loo_names, target, matrix_meta, labels, X, folds)
            loo_delta = {
                "logloss_deterioration_when_removed": float(removed["metrics_all"]["logloss"] - reference["metrics_all"]["logloss"]),
                "brier_deterioration_when_removed": float(removed["metrics_all"]["brier"] - reference["metrics_all"]["brier"]),
            }
            target_result: dict[str, Any] = {
                "leave_one_group_out": loo_delta,
                "reference_logloss": reference["metrics_all"]["logloss"],
                "removed_logloss": removed["metrics_all"]["logloss"],
            }
            if group in PRIORITY_GROUPS:
                add_names = sorted(set(base + members))
                added = _ablation_experiment(stage, f"BASE_PLUS_{group}", add_names, target, matrix_meta, labels, X, folds)
                inc = {
                    "logloss_improvement_vs_stable_base": float(ref_base["metrics_all"]["logloss"] - added["metrics_all"]["logloss"]),
                    "brier_improvement_vs_stable_base": float(ref_base["metrics_all"]["brier"] - added["metrics_all"]["brier"]),
                }
                target_result["incremental"] = inc
                robust = (
                    loo_delta["logloss_deterioration_when_removed"] > 0
                    and loo_delta["brier_deterioration_when_removed"] >= 0
                    and inc["logloss_improvement_vs_stable_base"] > 0
                    and inc["brier_improvement_vs_stable_base"] >= 0
                )
                target_result["oos_support"] = "SUPPORTED" if robust else "MIXED_OR_NOT_SUPPORTED"
            entry["targets"][target] = target_result
        print(f"PHASE4_ABLATION_TARGET_COMPLETE={target}", flush=True)
    _json_atomic(path, output)
    return output


def _load_pred(stage: Path, filename: str, target: str, split: str) -> np.ndarray:
    arr = np.load(stage / filename)
    key = f"{target}_{'dev' if split == 'development' else 'oos'}"
    if key in arr.files:
        return arr[key]
    if "pred" in arr.files:
        return arr["pred"]
    raise Phase4Error(f"prediction_key_missing:{filename}:{key}")


def _write_calibration_input(
    stage: Path,
    candidates: Mapping[str, Any],
    labels: Mapping[str, np.ndarray],
    dev_idx: Sequence[int],
    oos_idx: np.ndarray,
    match_ids: np.ndarray,
    dates: np.ndarray,
    experiment_lookup: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    path = stage / "PHASE4_CALIBRATION_INPUT.jsonl.gz"
    if path.is_file():
        return {"file": path.name, "sha256": _sha256(path), "bytes": path.stat().st_size}
    candidate_predictions: dict[tuple[str, str], np.ndarray] = {}
    for family, cand in candidates.items():
        if not cand.get("phase5_ready"):
            continue
        variant = cand["variant"]
        info = experiment_lookup[variant]
        for split in ("development", "walkforward_oos"):
            candidate_predictions[(family, split)] = _load_pred(
                stage, info["prediction_file"], family, split
            )
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        for split, indices in (("development", np.asarray(dev_idx)), ("walkforward_oos", oos_idx)):
            for i in indices:
                row = {
                    "match_id": int(match_ids[i]),
                    "date": str(dates[i]),
                    "split": split,
                    "actual_1x2": int(labels["y1"][i]),
                    "actual_btts": int(labels["yb"][i]),
                    "actual_o25": int(labels["yo"][i]),
                    "candidate_probabilities": {},
                }
                for family, cand in candidates.items():
                    if not cand.get("phase5_ready"):
                        continue
                    p = candidate_predictions[(family, split)][i]
                    row["candidate_probabilities"][family] = (
                        [float(x) for x in p] if family == "1X2" else float(p)
                    )
                handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    return {"file": path.name, "sha256": _sha256(path), "bytes": path.stat().st_size}


def _manifest(stage: Path) -> dict[str, Any]:
    artifacts = {}
    for path in sorted(stage.rglob("*")):
        if not path.is_file() or path.name == "PHASE4_MANIFEST.json":
            continue
        rel = path.relative_to(stage).as_posix()
        artifacts[rel] = {"bytes": path.stat().st_size, "sha256": _sha256(path)}
    manifest = {"created_at_utc": _utcnow(), "phase4_version": PHASE4_VERSION, "artifacts": artifacts}
    _json_atomic(stage / "PHASE4_MANIFEST.json", manifest)
    return manifest


def run_phase4(cp2_dir: Path, cp3_dir: Path, output_dir: Path) -> dict[str, Any]:
    cp2_dir, cp3_dir, output_dir = Path(cp2_dir), Path(cp3_dir), Path(output_dir)
    final_checkpoint = output_dir / "PHASE4_MODEL_RESEARCH.json"
    if final_checkpoint.is_file():
        result = json.loads(final_checkpoint.read_text(encoding="utf-8"))
        if result.get("PHASE4_MODEL_RESEARCH") == "PASS":
            print("PHASE4_REUSE_PASS", flush=True)
            return result
        raise Phase4Error("existing_phase4_checkpoint_not_pass")
    if output_dir.exists():
        raise Phase4Error("phase4_output_exists_without_pass")

    stage = output_dir.parent / ".phase4.stage"
    stage.mkdir(parents=True, exist_ok=True)
    input_info = _validate_inputs(cp2_dir, cp3_dir)
    _json_atomic(stage / "PHASE4_CP3_FEATURE_DECISIONS.json", input_info["feature_decisions"])
    _json_atomic(stage / "PHASE4_INPUT_FREEZE.json", {
        "phase4_version": PHASE4_VERSION,
        "cp2_master_sha256": input_info["cp2_master_sha256"],
        "cp3_manifest_sha256": input_info["cp3_manifest_sha256"],
        "cp2_match_count": input_info["cp2_checkpoint"]["match_count_valid"],
        "cp3_match_count": input_info["cp3_checkpoint"]["match_count_valid"],
        "cp3_field_count": input_info["cp3_checkpoint"]["validations_completed"]["field_count"],
        "cp3_derived_feature_count": input_info["cp3_checkpoint"]["validations_completed"]["derived_feature_count"],
        "cp3_audit_version": input_info["cp3_checkpoint"]["audit_version"],
        "odds_used": False,
        "postmatch_features_used": False,
        "collection_performed": False,
        "api_calls_performed": False,
        "cp2_rebuilt": False,
    })
    print("PHASE4_INPUT_VALIDATED", flush=True)

    master_path = cp2_dir / "FULL7_MASTER_STRICT.jsonl"
    matrix_meta = _matrix_pass(master_path, stage)
    labels_npz = np.load(stage / "PHASE4_LABELS.npz")
    labels = {k: labels_npz[k] for k in ("y1", "yb", "yo", "yh", "ya")}
    match_ids = labels_npz["match_ids"]
    dates = labels_npz["dates"]
    leagues = labels_npz["leagues"]
    splits_raw = _make_splits(list(dates), list(match_ids))
    fold_indices = splits_raw.pop("_fold_indices")
    _json_atomic(stage / "PHASE4_SPLITS.json", splits_raw)
    # recreate internal folds from dates to keep persisted split free of giant index arrays
    fold_tuples = []
    for meta in splits_raw["oos_folds"]:
        test = [i for i, d in enumerate(dates) if meta["test_start_date"] <= d <= meta["test_end_date"]]
        fold_tuples.append((list(range(min(test))), test, f"OOS{meta['fold']}"))
    train_idx = [i for i, d in enumerate(dates) if d <= splits_raw["train_end_date"]]
    dev_idx = [i for i, d in enumerate(dates) if splits_raw["train_end_date"] < d <= splits_raw["development_end_date"]]
    selection = _feature_selection(stage, matrix_meta, {"train_indices": train_idx})
    _json_atomic(stage / "PHASE4_MODEL_FEATURE_GROUPS.json", {
        "group_counts": selection["group_counts"],
        "priority_groups": list(PRIORITY_GROUPS),
        "research_only_groups": sorted(RESEARCH_ONLY_GROUPS),
    })
    print(f"PHASE4_FEATURES_SELECTED={selection['selected_feature_count']}", flush=True)

    X = np.load(stage / "PHASE4_MATRIX.npy", mmap_mode="r")
    V3 = np.load(stage / "PHASE4_V3_MATRIX.npy", mmap_mode="r")
    v3_supported = np.all(np.isfinite(V3), axis=1) & (leagues != "")
    oos_idx = np.concatenate([np.asarray(t[1], dtype=int) for t in fold_tuples])

    v3 = _eval_v3_baseline(stage, labels, V3, leagues, train_idx, dev_idx, fold_tuples)
    print("PHASE4_V3_BASELINE_COMPLETE", flush=True)

    model_results: dict[str, Any] = {}
    experiment_lookup: dict[str, dict[str, Any]] = {}
    for variant, spec in DIRECT_VARIANTS.items():
        feature_names = selection["core_features"] if spec["feature_set"] == "CORE" else selection["full_research_features"]
        target_results = {}
        pred_files = {}
        for target in ("1X2", "BTTS", "O25"):
            dev = _eval_direct_development(
                stage, variant, target, feature_names, matrix_meta, train_idx, dev_idx,
                spec["params"], labels, X, evaluation_mask=v3_supported,
            )
            oos = _eval_direct_experiment(
                stage, variant, target, feature_names, matrix_meta, fold_tuples,
                spec["params"], labels, X, evaluation_mask=v3_supported,
            )
            target_results[target] = {"development": dev, "walkforward_oos": oos}
            pred_files[target] = {"development": dev["prediction_file"], "walkforward_oos": oos["prediction_file"]}
        model_results[variant] = {
            "feature_set": spec["feature_set"],
            "feature_count": len(feature_names),
            "params": spec["params"],
            "targets": target_results,
        }
        # A single target-specific experiment file is used by calibration lookup below.
        experiment_lookup[variant] = {}
        print(f"PHASE4_MODEL_VARIANT_COMPLETE={variant}", flush=True)

    poisson = _eval_poisson(
        stage, "GOAL_POISSON_CORE", selection["core_features"], matrix_meta, labels, X,
        train_idx, dev_idx, fold_tuples, v3_supported,
    )
    model_results["GOAL_POISSON_CORE"] = poisson
    print("PHASE4_MODEL_VARIANT_COMPLETE=GOAL_POISSON_CORE", flush=True)

    # Fixed ensemble uses HGB_REGULARIZED_CORE target-specific prediction files.
    hgb_dev_files = {}
    hgb_oos_files = {}
    for target in ("1X2", "BTTS", "O25"):
        hgb_dev_files[target] = model_results["HGB_REGULARIZED_CORE"]["targets"][target]["development"]["prediction_file"]
        hgb_oos_files[target] = model_results["HGB_REGULARIZED_CORE"]["targets"][target]["walkforward_oos"]["prediction_file"]
    ensemble = _ensemble_metrics(
        stage, hgb_dev_files, hgb_oos_files,
        stage / poisson["prediction_file"], labels, dev_idx, oos_idx, v3_supported,
    )
    model_results["ENSEMBLE_HGB_POISSON_CORE"] = ensemble
    print("PHASE4_MODEL_VARIANT_COMPLETE=ENSEMBLE_HGB_POISSON_CORE", flush=True)

    ablations = _group_research(stage, selection, matrix_meta, labels, X, fold_tuples)

    # Normalize model comparison table.
    comparisons: dict[str, Any] = {}
    for target in ("1X2", "BTTS", "O25"):
        comparisons[target] = {}
        comparisons[target]["V3_1_CONTRACT_RETRAINED_REFERENCE"] = {
            "development": v3["targets"][target]["development"],
            "walkforward_oos": v3["targets"][target]["walkforward_oos"],
            "v3_common_only": True,
        }
        for variant in DIRECT_VARIANTS:
            dev = model_results[variant]["targets"][target]["development"]
            oos = model_results[variant]["targets"][target]["walkforward_oos"]
            comparisons[target][variant] = {
                "development": dev["metrics_all"],
                "development_v3_common": dev["metrics_v3_common"],
                "walkforward_oos": oos["metrics_all"],
                "walkforward_oos_v3_common": oos["metrics_v3_common"],
            }
        comparisons[target]["GOAL_POISSON_CORE"] = {
            "development": poisson["targets"][target]["development"],
            "development_v3_common": poisson["targets"][target]["development_v3_common"],
            "walkforward_oos": poisson["targets"][target]["walkforward_oos"],
            "walkforward_oos_v3_common": poisson["targets"][target]["walkforward_oos_v3_common"],
        }
        comparisons[target]["ENSEMBLE_HGB_POISSON_CORE"] = ensemble["targets"][target]

    # Candidate selection: OOS logloss, tie-break Brier; Phase5 requires dev + OOS improvements vs V3 on common support.
    candidates: dict[str, Any] = {}
    new_variants = list(DIRECT_VARIANTS) + ["GOAL_POISSON_CORE", "ENSEMBLE_HGB_POISSON_CORE"]
    for target in ("1X2", "BTTS", "O25"):
        ranked = sorted(
            new_variants,
            key=lambda v: (
                comparisons[target][v]["walkforward_oos"]["logloss"],
                comparisons[target][v]["walkforward_oos"]["brier"],
            ),
        )
        best = ranked[0]
        best_common_oos = comparisons[target][best].get("walkforward_oos_v3_common")
        best_common_dev = comparisons[target][best].get("development_v3_common")
        v3_dev = comparisons[target]["V3_1_CONTRACT_RETRAINED_REFERENCE"]["development"]
        v3_oos = comparisons[target]["V3_1_CONTRACT_RETRAINED_REFERENCE"]["walkforward_oos"]
        improves_dev = bool(best_common_dev and best_common_dev["logloss"] < v3_dev["logloss"] and best_common_dev["brier"] <= v3_dev["brier"])
        improves_oos = bool(best_common_oos and best_common_oos["logloss"] < v3_oos["logloss"] and best_common_oos["brier"] <= v3_oos["brier"])
        candidates[target] = {
            "variant": best,
            "research_rank_by_oos": ranked,
            "phase5_ready": bool(improves_dev and improves_oos),
            "development_improves_v3_common": improves_dev,
            "oos_improves_v3_common": improves_oos,
            "oos_logloss": comparisons[target][best]["walkforward_oos"]["logloss"],
            "oos_brier": comparisons[target][best]["walkforward_oos"]["brier"],
            "v3_common_oos_logloss": v3_oos["logloss"],
            "v3_common_oos_brier": v3_oos["brier"],
        }

    # Build prediction lookup for calibration-input writer.
    calibration_lookup: dict[str, dict[str, Any]] = {}
    for variant in DIRECT_VARIANTS:
        # Files differ by target, so create a target-specific lookup marker below.
        calibration_lookup[variant] = {"prediction_file": None}
    calibration_lookup["GOAL_POISSON_CORE"] = {"prediction_file": poisson["prediction_file"]}
    calibration_lookup["ENSEMBLE_HGB_POISSON_CORE"] = {"prediction_file": ensemble["prediction_file"]}

    # Calibration input is written explicitly to support target-specific direct-model files.
    cal_path = stage / "PHASE4_CALIBRATION_INPUT.jsonl.gz"
    if not cal_path.is_file():
        loaded_cache: dict[tuple[str, str, str], np.ndarray] = {}
        with gzip.open(cal_path, "wt", encoding="utf-8") as handle:
            for split_name, indices in (("development", np.asarray(dev_idx)), ("walkforward_oos", oos_idx)):
                for i in indices:
                    rec = {
                        "match_id": int(match_ids[i]), "date": str(dates[i]), "split": split_name,
                        "actual_1x2": int(labels["y1"][i]), "actual_btts": int(labels["yb"][i]),
                        "actual_o25": int(labels["yo"][i]), "candidate_probabilities": {},
                    }
                    for target, cand in candidates.items():
                        if not cand["phase5_ready"]:
                            continue
                        variant = cand["variant"]
                        key = (variant, target, split_name)
                        if key not in loaded_cache:
                            if variant in DIRECT_VARIANTS:
                                exp = model_results[variant]["targets"][target][
                                    "development" if split_name == "development" else "walkforward_oos"
                                ]
                                loaded_cache[key] = np.load(stage / "experiments" / exp["prediction_file"])["pred"]
                            elif variant == "GOAL_POISSON_CORE":
                                loaded_cache[key] = np.load(stage / poisson["prediction_file"])[
                                    f"{target}_{'dev' if split_name == 'development' else 'oos'}"
                                ]
                            else:
                                loaded_cache[key] = np.load(stage / ensemble["prediction_file"])[
                                    f"{target}_{'dev' if split_name == 'development' else 'oos'}"
                                ]
                        value = loaded_cache[key][i]
                        rec["candidate_probabilities"][target] = [float(x) for x in value] if target == "1X2" else float(value)
                    handle.write(json.dumps(rec, ensure_ascii=False, sort_keys=True) + "\n")
        del loaded_cache

    published_v3 = {
        "source": "research/FULL7_V3_LIVE_COMPAT_AUDIT.json",
        "oos_rows": 12379,
        "metrics": {
            "1X2": {"logloss": 1.0396850943631781, "brier": 0.6225651144475047, "accuracy": 0.4819452298247031},
            "O25": {"logloss": 0.685542350878984, "brier": 0.24609469841197407, "accuracy": 0.5576379352128605},
            "BTTS": {"logloss": 0.6884483008570162, "brier": 0.24759332465487544, "accuracy": 0.5489942644801681},
        },
        "comparison_note": "Historical reference only; the retrained V3.1-contract baseline above is the exact-population chronological comparator for CP2 16,137.",
    }

    phase5_freeze = {
        "freeze_version": "FULL7_PHASE5_INPUT_FREEZE_1.0",
        "created_at_utc": _utcnow(),
        "cp2_master_sha256": input_info["cp2_master_sha256"],
        "cp3_manifest_sha256": input_info["cp3_manifest_sha256"],
        "split_sha256": _sha256(stage / "PHASE4_SPLITS.json"),
        "feature_selection_sha256": _sha256(stage / "PHASE4_FEATURE_SELECTION.json"),
        "calibration_input_file": cal_path.name,
        "calibration_input_sha256": _sha256(cal_path),
        "candidates": candidates,
        "no_production_release": True,
    }
    _json_atomic(stage / "PHASE4_PHASE5_FREEZE.json", phase5_freeze)

    result = {
        "PHASE4_MODEL_RESEARCH": "PASS",
        "status": "COMPLETE",
        "phase4_version": PHASE4_VERSION,
        "completed_at_utc": _utcnow(),
        "match_count_input": EXPECTED_ROWS,
        "cp2_gate": "PASS_FROZEN_REUSED",
        "cp3_gate": "PASS_FROZEN_REUSED",
        "cp2_rebuilt": False,
        "collection_performed": False,
        "api_calls_performed": False,
        "odds_used": False,
        "postmatch_features_used": False,
        "cp3_field_count_reviewed": len(input_info["field_profiles"]),
        "cp3_derived_feature_count_reviewed": len(input_info["derived_profiles"]),
        "matrix_feature_count_discovered": matrix_meta["feature_count_discovered"],
        "selected_feature_count": selection["selected_feature_count"],
        "core_feature_count": selection["core_feature_count"],
        "split_summary": {k: v for k, v in splits_raw.items() if k not in {"oos_folds"}},
        "oos_folds": splits_raw["oos_folds"],
        "model_comparisons": comparisons,
        "candidates": candidates,
        "feature_group_ablation_file": "PHASE4_GROUP_ABLATIONS.json",
        "published_v3_historical_reference": published_v3,
        "phase5_freeze_file": "PHASE4_PHASE5_FREEZE.json",
        "known_limitations": [
            "Original V3.1 SGD hyperparameters were not persisted; the exact V3.1 live feature contract and linear-logit architecture are reproduced with a documented deterministic SGD configuration.",
            "H2H can only be tested if present in frozen CP2; no API backfill is permitted.",
            "Rank percentile cannot be invented if the frozen TableDaten does not contain enough league-table cardinality context.",
        ],
        "next_phase": "PHASE 5 — CALIBRATION, only for candidates marked phase5_ready",
        "production_release_allowed": False,
    }
    _json_atomic(stage / "PHASE4_MODEL_RESEARCH.json", result)
    _manifest(stage)
    manifest_sha256 = _sha256(stage / "PHASE4_MANIFEST.json")

    if output_dir.exists():
        raise Phase4Error("phase4_output_appeared_during_publish")
    stage.rename(output_dir)
    print("PHASE4_MODEL_RESEARCH=PASS", flush=True)
    print("PHASE4_CANDIDATES=" + json.dumps(candidates, ensure_ascii=False, sort_keys=True), flush=True)
    print("PHASE4_MANIFEST_SHA256=" + manifest_sha256, flush=True)
    return result


def _network_disabled(*_args, **_kwargs):
    raise Phase4Error("network_disabled_during_phase4")


@contextmanager
def block_network():
    with patch("socket.create_connection", _network_disabled), patch.object(socket.socket, "connect", _network_disabled), patch.object(socket.socket, "connect_ex", _network_disabled):
        yield


def run_phase4_offline(cp2_dir: Path, cp3_dir: Path, output_dir: Path) -> dict[str, Any]:
    with block_network():
        return run_phase4(cp2_dir, cp3_dir, output_dir)
