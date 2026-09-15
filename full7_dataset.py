from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


TARGET_KEYS = (
    "home_win", "draw", "away_win",
    "btts_yes", "btts_no",
    "over_2_5", "under_2_5",
)


def _num(v: Any) -> Optional[float]:
    if v is None or isinstance(v, bool):
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x


def _int(v: Any) -> Optional[int]:
    x = _num(v)
    return int(x) if x is not None else None


def derive_targets(home_goals: Any, away_goals: Any) -> Dict[str, Any]:
    hg, ag = _int(home_goals), _int(away_goals)
    if hg is None or ag is None or hg < 0 or ag < 0:
        raise ValueError("completed result requires non-negative home/away goals")

    total = hg + ag
    return {
        "home_goals": hg,
        "away_goals": ag,
        "total_goals": total,
        "home_win": 1 if hg > ag else 0,
        "draw": 1 if hg == ag else 0,
        "away_win": 1 if ag > hg else 0,
        "btts_yes": 1 if hg > 0 and ag > 0 else 0,
        "btts_no": 0 if hg > 0 and ag > 0 else 1,
        "over_2_5": 1 if total >= 3 else 0,
        "under_2_5": 1 if total <= 2 else 0,
    }


def validate_target_coherence(targets: Mapping[str, Any]) -> None:
    if sum(int(targets[k]) for k in ("home_win", "draw", "away_win")) != 1:
        raise ValueError("1X2 targets are incoherent")
    if int(targets["btts_yes"]) + int(targets["btts_no"]) != 1:
        raise ValueError("BTTS targets are incoherent")
    if int(targets["over_2_5"]) + int(targets["under_2_5"]) != 1:
        raise ValueError("O/U targets are incoherent")


def _stable_hash(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def snapshot_captured_at(gold: Mapping[str, Any]) -> Optional[int]:
    lineage = gold.get("lineage") or {}
    times = []
    for row in lineage.values():
        if not isinstance(row, Mapping):
            continue
        ts = _int(row.get("captured_at_unix"))
        if ts is not None:
            times.append(ts)
    if times:
        return max(times)

    # Historical archive reports predate per-source capture metadata. Their
    # archive.created_at timestamp is an observed report-level snapshot time,
    # not a fabricated source timestamp. It is allowed only when the adapter
    # explicitly marks LEGACY_ARCHIVE_STRICT provenance.
    quality = gold.get("quality") or {}
    if quality.get("provenance_mode") == "LEGACY_ARCHIVE_STRICT":
        return _int(quality.get("snapshot_captured_at_unix"))
    return None


def make_model_row(
    gold: Mapping[str, Any],
    gold_features: Mapping[str, Any],
    signal_groups: Mapping[str, Any],
    *,
    strict_pre_match: bool,
    result: Optional[Mapping[str, Any]] = None,
    result_source: Optional[str] = None,
) -> Dict[str, Any]:
    ident = gold.get("identity") or {}
    match_id = _int(ident.get("match_id"))
    kickoff = _int(ident.get("kickoff_unix"))
    if match_id is None or kickoff is None:
        raise ValueError("Gold identity requires match_id and kickoff_unix")

    captured = snapshot_captured_at(gold)
    if captured is None:
        raise ValueError("Gold lineage requires captured_at_unix")
    if captured >= kickoff:
        raise ValueError("snapshot is not pre-match")
    if not strict_pre_match:
        raise ValueError("model-ready dataset accepts only strict pre-match rows")

    features = dict(gold_features.get("features") or {})
    if any(k in features for k in (
        "home_goals", "away_goals", "total_goals",
        *TARGET_KEYS,
    )):
        raise ValueError("target/leakage field present inside features")
    if any("odds" in k.lower() for k in features):
        raise ValueError("odds field present inside model features")

    targets = None
    if result is not None:
        targets = derive_targets(result.get("home_goals"), result.get("away_goals"))
        validate_target_coherence(targets)

    row = {
        "match_id": match_id,
        "season_id": _int(ident.get("season_id")),
        "home_id": _int(ident.get("home_id")),
        "away_id": _int(ident.get("away_id")),
        "kickoff_unix": kickoff,
        "snapshot_captured_at_unix": captured,
        "strict_pre_match": True,
        "foundation_version": (gold.get("quality") or {}).get("foundation_version"),
        "feature_builder_version": gold_features.get("feature_builder_version"),
        "signal_group_version": signal_groups.get("signal_group_version"),
        "feature_count": len(features),
        "available_evidence_cluster_count": signal_groups.get("available_evidence_cluster_count"),
        "available_evidence_clusters": list(signal_groups.get("available_evidence_clusters") or []),
        "features": features,
        "feature_owners": dict(gold_features.get("feature_owners") or {}),
        "targets": targets,
        "result_source": result_source if targets is not None else None,
    }
    row["snapshot_hash"] = _stable_hash({
        "match_id": match_id,
        "kickoff_unix": kickoff,
        "captured_at_unix": captured,
        "features": features,
    })
    return row


def join_results(
    rows: Sequence[Mapping[str, Any]],
    results: Sequence[Mapping[str, Any]],
    *,
    source_name: str,
) -> List[Dict[str, Any]]:
    result_by_match: Dict[int, Mapping[str, Any]] = {}
    for result in results:
        match_id = _int(result.get("match_id"))
        if match_id is None:
            raise ValueError("result row missing match_id")
        if match_id in result_by_match:
            prev = result_by_match[match_id]
            if (_int(prev.get("home_goals")), _int(prev.get("away_goals"))) != (
                _int(result.get("home_goals")), _int(result.get("away_goals"))
            ):
                raise ValueError(f"conflicting results for match_id={match_id}")
        result_by_match[match_id] = result

    joined: List[Dict[str, Any]] = []
    for row in rows:
        out = dict(row)
        match_id = _int(row.get("match_id"))
        result = result_by_match.get(match_id)
        if result is not None:
            targets = derive_targets(result.get("home_goals"), result.get("away_goals"))
            validate_target_coherence(targets)
            out["targets"] = targets
            out["result_source"] = source_name
        joined.append(out)
    return joined


def dedupe_latest_strict(rows: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """Keep exactly one strict snapshot per match: latest capture before kickoff."""
    chosen: Dict[int, Dict[str, Any]] = {}

    for raw in rows:
        row = dict(raw)
        match_id = _int(row.get("match_id"))
        kickoff = _int(row.get("kickoff_unix"))
        captured = _int(row.get("snapshot_captured_at_unix"))
        strict = row.get("strict_pre_match") is True

        if match_id is None or kickoff is None or captured is None:
            raise ValueError("row missing match_id/kickoff/snapshot timestamp")
        if not strict or captured >= kickoff:
            continue

        prev = chosen.get(match_id)
        if prev is None:
            chosen[match_id] = row
            continue

        prev_captured = _int(prev.get("snapshot_captured_at_unix"))
        if captured > prev_captured:
            chosen[match_id] = row
        elif captured == prev_captured:
            # Same timestamp must be byte-equivalent at feature level; otherwise ambiguity is fatal.
            if row.get("snapshot_hash") != prev.get("snapshot_hash"):
                raise ValueError(f"ambiguous strict snapshots for match_id={match_id}")
            # deterministic tie: retain existing row

    return sorted(chosen.values(), key=lambda r: (int(r["kickoff_unix"]), int(r["match_id"])))


def feature_universe(rows: Sequence[Mapping[str, Any]]) -> List[str]:
    names = set()
    for row in rows:
        names.update((row.get("features") or {}).keys())
    return sorted(names)


def materialize_matrix(
    rows: Sequence[Mapping[str, Any]],
    *,
    feature_names: Optional[Sequence[str]] = None,
    require_targets: bool = False,
) -> Dict[str, Any]:
    ordered = dedupe_latest_strict(rows)
    if feature_names is None:
        feature_names = feature_universe(ordered)
    else:
        feature_names = list(feature_names)

    X: List[List[Optional[float]]] = []
    ids: List[int] = []
    kickoffs: List[int] = []
    targets: Dict[str, List[int]] = {k: [] for k in TARGET_KEYS}
    target_goals: Dict[str, List[int]] = {"home_goals": [], "away_goals": [], "total_goals": []}

    for row in ordered:
        features = row.get("features") or {}
        X.append([_num(features.get(name)) for name in feature_names])
        ids.append(int(row["match_id"]))
        kickoffs.append(int(row["kickoff_unix"]))

        row_targets = row.get("targets")
        if require_targets and not isinstance(row_targets, Mapping):
            raise ValueError(f"missing result target for match_id={row['match_id']}")
        if isinstance(row_targets, Mapping):
            validate_target_coherence(row_targets)
            for key in TARGET_KEYS:
                targets[key].append(int(row_targets[key]))
            for key in target_goals:
                target_goals[key].append(int(row_targets[key]))

    return {
        "dataset_version": "FULL7_MODEL_MATRIX_0.1",
        "row_count": len(ordered),
        "feature_count": len(feature_names),
        "match_ids": ids,
        "kickoff_unix": kickoffs,
        "feature_names": list(feature_names),
        "X": X,
        "targets": targets if (require_targets or any(row.get("targets") for row in ordered)) else None,
        "target_goals": target_goals if (require_targets or any(row.get("targets") for row in ordered)) else None,
        "missing_policy": "None/NaN preserved; no statistical imputation is performed here.",
        "dedupe_policy": "one match_id; latest strict snapshot before kickoff",
    }
