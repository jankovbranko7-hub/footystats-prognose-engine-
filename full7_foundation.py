"""FULL-7 Bronze/Silver/Gold input foundation (development only)."""
from __future__ import annotations

import copy, hashlib, json, math
from dataclasses import asdict
from full7_feature_registry import build_registry, classify as registry_classify
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Tuple

FOUNDATION_VERSION = "0.2.0"
INPUT_CONTRACT_VERSION = "FULL7_INPUT_CONTRACT_0.2"

KINDS = ("match", "league", "form", "table", "player", "referee", "manager")
SPECS = {
    "match": ("matchdaten", {"/match"}, False),
    "league": ("leaguedaten", {"/league-season", "/league-teams"}, True),
    "form": ("formdaten", {"/lastx"}, False),
    "table": ("tabledaten", {"/league-tables"}, True),
    "player": ("playerdaten", {"/league-players"}, True),
    "referee": ("refereedaten", {"/league-referees"}, True),
    "manager": ("managerdaten", {"/manager"}, False),
}
SIGNAL_FAMILIES = (
    "expected_goals_xga", "goals_defence", "venue", "form", "league_context",
    "table_strength", "shots_chance_creation", "first_second_half",
    "btts_ou_profile", "player_depth", "player_quality", "player_concentration",
    "h2h", "referee", "manager", "data_quality",
)
TARGETS = {"winningTeam", "homeGoalCount", "awayGoalCount", "totalGoalCount", "HTGoalCount", "GoalCount_2hg", "overallGoalCount"}
ACTUAL_MATCH = {
    "team_a_xg", "team_b_xg", "total_xg", "team_a_possession", "team_b_possession",
    "team_a_shots", "team_b_shots", "team_a_shotsOnTarget", "team_b_shotsOnTarget",
    "team_a_shotsOffTarget", "team_b_shotsOffTarget", "team_a_corners", "team_b_corners",
    "totalCornerCount", "team_a_fouls", "team_b_fouls", "team_a_offsides", "team_b_offsides",
    "team_a_yellow_cards", "team_b_yellow_cards", "team_a_red_cards", "team_b_red_cards",
    "team_a_attacks", "team_b_attacks", "team_a_dangerous_attacks", "team_b_dangerous_attacks",
}
IDENTITY = {"id", "homeID", "awayID", "competition_id", "date_unix", "season", "home_name", "away_name", "roundID", "game_week"}


def _num(v: Any) -> Optional[float]:
    if v is None or isinstance(v, bool): return None
    try: x = float(v)
    except (TypeError, ValueError): return None
    return x if math.isfinite(x) else None


def _int(v: Any) -> Optional[int]:
    x = _num(v); return int(x) if x is not None else None


def _positive_int(v: Any) -> Optional[int]:
    x = _int(v)
    return x if x is not None and x > 0 else None


def _hash(v: Any) -> str:
    raw = json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(raw).hexdigest()


def _meta(raw: Any) -> Dict[str, Any]:
    return copy.deepcopy(raw.get("_footystats_meta") or {}) if isinstance(raw, dict) else {}


def _endpoint(raw: Any) -> Optional[str]:
    v = _meta(raw).get("endpoint"); return str(v).strip().lower() if v not in (None, "") else None


def _kind(name: str, raw: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
    n = (name or "").lower().replace(" ", "")
    f = [k for k, (marker, _, _) in SPECS.items() if marker in n]
    e = _endpoint(raw)
    ep = [k for k, (_, endpoints, _) in SPECS.items() if e in endpoints] if e else []
    fk = f[0] if len(f) == 1 else None; ek = ep[0] if len(ep) == 1 else None
    if fk and ek and fk != ek: return None, "SOURCE_FILENAME_ENDPOINT_MISMATCH"
    k = fk or ek
    return (k, None) if k else (None, "UNKNOWN_SOURCE")


def _issue(code: str, source: Optional[str] = None, critical: bool = True, **extra: Any) -> Dict[str, Any]:
    return {"code": code, "source": source, "critical": critical, **extra}


def build_bronze(files: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    issues, artifacts, seen = [], {}, {}
    if len(files) != 7: issues.append(_issue("FILE_COUNT_MISMATCH", received=len(files)))
    for item in files:
        name, raw = str(item.get("name") or ""), item.get("data")
        if not isinstance(raw, dict):
            issues.append(_issue("INVALID_JSON_ROOT", name=name)); continue
        raw = copy.deepcopy(raw)
        kind, error = _kind(name, raw)
        if error: issues.append(_issue(error, name=name)); continue
        seen[kind] = seen.get(kind, 0) + 1
        if seen[kind] > 1:
            issues.append(_issue("DUPLICATE_SOURCE", kind)); continue
        artifacts[kind] = {"name": name, "raw": raw, "meta": _meta(raw), "sha256": _hash(raw)}
    for k in KINDS:
        if k not in artifacts: issues.append(_issue("MISSING_SOURCE", k))
    return {"artifacts": artifacts, "issues": issues}


def _payload(a: Dict[str, Any]) -> Any:
    raw = a["raw"]; return raw.get("payload") if "payload" in raw else raw


def _data(v: Any) -> Any:
    return v.get("data") if isinstance(v, dict) and "data" in v else v


def _identity(a: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    m = _data(_payload(a)); m = m if isinstance(m, dict) else {}
    out = {
        "match_id": _int(m.get("id")), "home_id": _int(m.get("homeID")),
        "away_id": _int(m.get("awayID")), "season_id": _int(m.get("competition_id")),
        "kickoff_unix": _int(m.get("date_unix")), "referee_id": _positive_int(m.get("refereeID")),
    }
    return None if any(out[k] is None for k in ("match_id", "home_id", "away_id", "season_id", "kickoff_unix")) else out


def _dicts(v: Any) -> Iterable[Dict[str, Any]]:
    if isinstance(v, dict):
        yield v
        for x in v.values(): yield from _dicts(x)
    elif isinstance(v, list):
        for x in v: yield from _dicts(x)


def _has_id(v: Any, wanted: int) -> bool:
    for row in _dicts(v):
        for key in ("id", "team_id", "teamID", "club_team_id", "club_team_2_id"):
            if _int(row.get(key)) == wanted: return True
    return False


def _player_count(v: Any, wanted: int) -> int:
    """Count only the primary club assignment for deterministic team mapping.

    FootyStats documents club_team_2_id as a secondary loan/transfer club.
    It is retained for diagnostics but never used as a silent primary join.
    """
    n = 0
    for row in _dicts(v):
        if _int(row.get("club_team_id")) == wanted:
            if "id" in row and ("minutes_played_overall" in row or "position" in row): n += 1
    return n


def _matches_played(payload: Any, team_id: int) -> Optional[int]:
    if payload is None:
        return None
    found = None
    for row in _dicts(payload):
        if _int(row.get("id")) != team_id:
            continue
        for key in ("matchesPlayed", "seasonMatchesPlayed_overall", "matches_played", "played"):
            if key in row:
                found = _int(row.get(key))
                if found is not None:
                    return found
    return found


def _player_pages_ok(a: Dict[str, Any]) -> bool:
    explicit = a["meta"].get("pagination_complete")
    if explicit is True or (isinstance(explicit, str) and explicit.lower() == "true"): return True
    p = _payload(a); pages = p.get("pages") if isinstance(p, dict) else None
    if not isinstance(pages, list) or not pages: return False
    current, maxima = set(), []
    for page in pages:
        pager = page.get("pager") if isinstance(page, dict) else None
        if isinstance(pager, dict):
            cp, mp = _int(pager.get("current_page")), _int(pager.get("max_page"))
            if cp is not None: current.add(cp)
            if mp is not None: maxima.append(mp)
    return bool(maxima) and current >= set(range(1, max(maxima) + 1))


def build_silver(bronze: Dict[str, Any]) -> Dict[str, Any]:
    artifacts, issues = bronze["artifacts"], list(bronze["issues"])
    ident = _identity(artifacts["match"]) if "match" in artifacts else None
    if "match" in artifacts and ident is None: issues.append(_issue("MATCH_IDENTITY_MISSING", "match"))
    if ident:
        ko = ident["kickoff_unix"]
        for k, a in artifacts.items():
            meta = a["meta"]
            if not meta:
                issues.append(_issue("MISSING_METADATA", k)); continue
            cap = _int(meta.get("captured_at_unix"))
            if cap is None: issues.append(_issue("MISSING_CAPTURE_TIME", k))
            elif cap >= ko: issues.append(_issue("CAPTURE_NOT_PREMATCH", k, captured_at_unix=cap, kickoff_unix=ko))
            max_time = _int(meta.get("max_time")); require_max = SPECS[k][2]
            if require_max and max_time is None: issues.append(_issue("MISSING_REQUIRED_MAX_TIME", k))
            if max_time is not None and max_time >= ko: issues.append(_issue("MAX_TIME_NOT_PREMATCH", k, max_time=max_time, kickoff_unix=ko))
            if k != "match":
                sid = _int(meta.get("season_id"))
                if sid is None: issues.append(_issue("SEASON_ID_NOT_DECLARED", k, False))
                elif sid != ident["season_id"]: issues.append(_issue("SEASON_ID_MISMATCH", k, season_id=sid, expected=ident["season_id"]))
        mm = _int(artifacts["match"]["meta"].get("match_id"))
        if mm is not None and mm != ident["match_id"]: issues.append(_issue("MATCH_META_ID_MISMATCH", "match"))
        for k in ("league", "form", "table"):
            if k in artifacts:
                p = _payload(artifacts[k])
                if not _has_id(p, ident["home_id"]): issues.append(_issue(f"{k.upper()}_HOME_TEAM_MISSING", k))
                if not _has_id(p, ident["away_id"]): issues.append(_issue(f"{k.upper()}_AWAY_TEAM_MISSING", k))
        if "player" in artifacts:
            p = _payload(artifacts["player"])
            table_payload = _payload(artifacts["table"]) if "table" in artifacts else None
            for side, team_id, code in (
                ("home", ident["home_id"], "PLAYER_HOME_TEAM_MISSING"),
                ("away", ident["away_id"], "PLAYER_AWAY_TEAM_MISSING"),
            ):
                if _player_count(p, team_id) <= 0:
                    played = _matches_played(table_payload, team_id)
                    early_entry = played == 0
                    issues.append(_issue(code, "player", critical=not early_entry, side=side, matches_played=played))
            if not _player_pages_ok(artifacts["player"]): issues.append(_issue("PLAYER_PAGINATION_INCOMPLETE", "player"))
        if "referee" in artifacts:
            ref = artifacts["referee"]
            if ident["referee_id"] is not None and not _has_id(_payload(ref), ident["referee_id"]):
                issues.append(_issue("REFEREE_ID_NOT_FOUND", "referee", False))
        if "manager" in artifacts:
            meta = artifacts["manager"]["meta"]
            payload = _payload(artifacts["manager"])
            for side in ("home", "away"):
                manager_id = _positive_int(meta.get(f"{side}_manager_id"))
                side_payload = payload.get(side) if isinstance(payload, dict) else None
                explicitly_unavailable = (
                    isinstance(side_payload, dict)
                    and side_payload.get("available") in (False, "false", "False", 0, "0")
                )
                if manager_id is None and not explicitly_unavailable:
                    issues.append(_issue("MANAGER_UNAVAILABLE_NOT_EXPLICIT", "manager", False, side=side))
    critical = [x for x in issues if x["critical"]]
    return {
        "valid": ident is not None and not critical, "identity": ident,
        "normalized": {k: copy.deepcopy(_payload(a)) for k, a in artifacts.items()},
        "issues": issues,
        "audit": {
            "architecture": "FULL7_BRONZE_SILVER_GOLD",
            "foundation_version": FOUNDATION_VERSION,
            "input_contract_version": INPUT_CONTRACT_VERSION,
            "expected_file_count": 7,
            "received_file_count": len(artifacts), "identity": ident,
            "critical_issue_count": len(critical), "warning_count": len(issues)-len(critical),
            "strict_pre_match": ident is not None and not any(x["critical"] and x["code"] in {
                "MISSING_METADATA", "MISSING_CAPTURE_TIME", "CAPTURE_NOT_PREMATCH", "MISSING_REQUIRED_MAX_TIME", "MAX_TIME_NOT_PREMATCH"} for x in issues),
            "sentinel_policy": "NO_GLOBAL_CONVERSION; field-specific semantics only",
            "post_match_leakage_policy": "BLOCK_BY_FEATURE_REGISTRY; no generic flatten-to-model",
        },
    }


def build_gold(bronze: Dict[str, Any], silver: Dict[str, Any]) -> Dict[str, Any]:
    if not silver["valid"]: raise ValueError("Gold requires valid Silver")
    return {
        "identity": copy.deepcopy(silver["identity"]),
        "namespaces": {k: copy.deepcopy(silver["normalized"][k]) for k in KINDS},
        "quality": {"status": "VALID", "signal_families": list(SIGNAL_FAMILIES), "no_imputation": True, "no_global_sentinel_conversion": True},
        "lineage": {k: {"filename": bronze["artifacts"][k]["name"], "sha256": bronze["artifacts"][k]["sha256"], "endpoint": _endpoint(bronze["artifacts"][k]["raw"]), "captured_at_unix": _int(bronze["artifacts"][k]["meta"].get("captured_at_unix")), "max_time": _int(bronze["artifacts"][k]["meta"].get("max_time"))} for k in KINDS},
    }


def process_full7(files: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    bronze = build_bronze(files); silver = build_silver(bronze)
    out = {"ok": silver["valid"], "stage": "VALIDATION_FAILED", "audit": silver["audit"], "issues": silver["issues"], "gold": None}
    if silver["valid"]:
        out["stage"] = "GOLD_READY"; out["gold"] = build_gold(bronze, silver)
    return out


def classify_path(source: str, path: str, value: Any) -> Dict[str, Any]:
    """Compatibility wrapper around the single semantic registry."""
    return asdict(registry_classify(source, path, value))


def inventory_gold(gold: Dict[str, Any]) -> Dict[str, Any]:
    """Inventory Gold using the single authoritative FULL-7 feature registry."""
    return build_registry(gold["namespaces"])
