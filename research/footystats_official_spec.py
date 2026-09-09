"""FootyStats Official Analysis Spec v1.1 runtime.

This module is a provenance/interpretation layer. It does not modify the frozen
V0.4.3 FULL-5 probability core and it does not turn FootyStats tutorial examples
into model probabilities or mandatory betting gates.
"""
from __future__ import annotations

import copy
import json
import math
import time
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

SPEC_VERSION = "1.1"
SPEC_NAME = "FOOTYSTATS_OFFICIAL_ANALYSIS_SPEC"
REGISTRY_FILE = Path(__file__).resolve().parents[1] / "footystats_field_registry.json"
SHORTCUT_SCHEMA_FILE = Path(__file__).resolve().parents[1] / "footystats_shortcut_api_schema.json"

OFFICIAL_RULE_TYPE = "OFFICIAL_FOOTYSTATS_TUTORIAL_EXAMPLE"
DECISION_INFLUENCE = "EVIDENCE_FLAG_ONLY"

_TARGET_POSTMATCH_FIELDS = (
    "homeGoalCount",
    "awayGoalCount",
    "totalGoalCount",
    "winningTeam",
    "btts",
    "over05",
    "over15",
    "over25",
    "over35",
    "over45",
    "over55",
    "team_a_shots",
    "team_b_shots",
    "team_a_shotsOnTarget",
    "team_b_shotsOnTarget",
    "team_a_possession",
    "team_b_possession",
    "team_a_corners",
    "team_b_corners",
)


@lru_cache(maxsize=1)
def load_field_registry() -> Dict[str, Any]:
    with REGISTRY_FILE.open("r", encoding="utf-8") as handle:
        return json.load(handle)


@lru_cache(maxsize=1)
def load_shortcut_schema() -> Dict[str, Any]:
    with SHORTCUT_SCHEMA_FILE.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _num(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _find_meta(payload: Any) -> Dict[str, Any]:
    if isinstance(payload, dict):
        direct = payload.get("_footystats_meta")
        if isinstance(direct, dict):
            return direct
        for value in payload.values():
            found = _find_meta(value)
            if found:
                return found
    elif isinstance(payload, list):
        for value in payload:
            found = _find_meta(value)
            if found:
                return found
    return {}


def _raw_match_object(legacy: Any, match_data: Any) -> Dict[str, Any]:
    try:
        obj = legacy.match_obj(match_data)
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


def _first_number(legacy: Any, payload: Any, aliases: Iterable[str]) -> Optional[float]:
    try:
        value = legacy.firstnum(payload, list(aliases))
        return _num(value)
    except Exception:
        return None


def _first_value(legacy: Any, payload: Any, aliases: Iterable[str]) -> Any:
    try:
        return legacy.first(payload, list(aliases))
    except Exception:
        return None


def _rule_status(required: Iterable[Optional[float]], passed: bool) -> str:
    return "UNAVAILABLE" if any(value is None for value in required) else ("PASS" if passed else "FAIL")


def _official_tutorial_rules(legacy: Any, match_data: Any) -> Dict[str, Any]:
    match = {}
    try:
        match = legacy.mf(match_data) or {}
    except Exception:
        pass

    btts = _num(match.get("btts_potential"))
    avg = _first_number(legacy, match_data, ("avg_potential",))
    strict_home_ppg = _num(match.get("pre_match_home_ppg"))
    strict_away_ppg = _num(match.get("pre_match_away_ppg"))
    current_home_ppg = _first_number(legacy, match_data, ("home_ppg",))
    current_away_ppg = _first_number(legacy, match_data, ("away_ppg",))

    live_btts_pass = bool(
        btts is not None
        and current_away_ppg is not None
        and btts >= 65.0
        and current_away_ppg >= 1.50
    )
    strict_btts_pass = bool(
        btts is not None
        and strict_away_ppg is not None
        and btts >= 65.0
        and strict_away_ppg >= 1.50
    )
    live_low_pass = bool(
        avg is not None
        and current_home_ppg is not None
        and current_away_ppg is not None
        and avg <= 1.80
        and current_home_ppg <= 1.50
        and current_away_ppg <= 1.50
    )
    strict_low_pass = bool(
        avg is not None
        and strict_home_ppg is not None
        and strict_away_ppg is not None
        and avg <= 1.80
        and strict_home_ppg <= 1.50
        and strict_away_ppg <= 1.50
    )

    return {
        "rule_type": OFFICIAL_RULE_TYPE,
        "decision_influence": DECISION_INFLUENCE,
        "btts_yes_example": {
            "published_logic": "btts_potential >= 65 AND away_ppg >= 1.50",
            "live_status": _rule_status((btts, current_away_ppg), live_btts_pass),
            "strict_historical_status": _rule_status((btts, strict_away_ppg), strict_btts_pass),
            "values": {
                "btts_potential": btts,
                "away_ppg_current": current_away_ppg,
                "pre_match_away_ppg": strict_away_ppg,
            },
            "interpretation": "Tutorial example/evidence flag; not a calibrated BTTS probability and not a mandatory final-decision gate.",
        },
        "low_scoring_example": {
            "published_logic": "avg_potential <= 1.80 AND home_ppg <= 1.50 AND away_ppg <= 1.50",
            "live_status": _rule_status((avg, current_home_ppg, current_away_ppg), live_low_pass),
            "strict_historical_status": _rule_status((avg, strict_home_ppg, strict_away_ppg), strict_low_pass),
            "values": {
                "avg_potential": avg,
                "home_ppg_current": current_home_ppg,
                "away_ppg_current": current_away_ppg,
                "pre_match_home_ppg": strict_home_ppg,
                "pre_match_away_ppg": strict_away_ppg,
            },
            "interpretation": "Tutorial example/evidence flag; not a universal Under 2.5 decision formula.",
        },
    }


def _temporal_status(
    payload: Any,
    *,
    kickoff_unix: Optional[float],
    expected_endpoint: str,
    expects_max_time: bool,
    now_unix: Optional[float] = None,
) -> Dict[str, Any]:
    meta = _find_meta(payload)
    now_value = _num(now_unix) if now_unix is not None else float(time.time())
    kickoff = _num(kickoff_unix)
    capture = _num(meta.get("captured_at_unix"))
    max_time = _num(meta.get("max_time"))
    endpoint = str(meta.get("endpoint") or "")
    expected_max = int(kickoff) - 1 if kickoff is not None else None

    endpoint_ok = (not endpoint) or endpoint == expected_endpoint

    if kickoff is not None and now_value < kickoff and not meta:
        status = "LIVE_PREMATCH_AT_ANALYSIS"
        strict = True
        reason = "Bundle is being analyzed before kickoff; legacy package has no provenance metadata."
    elif expects_max_time and kickoff is not None and max_time is not None:
        strict = int(max_time) == expected_max and endpoint_ok
        status = "STRICT_MAX_TIME_VERIFIED" if strict else "MAX_TIME_MISMATCH"
        reason = (
            "Metadata proves max_time == kickoff - 1."
            if strict
            else "Metadata is present but max_time/endpoint does not match the strict contract."
        )
    elif not expects_max_time and kickoff is not None and capture is not None:
        strict = capture < kickoff and endpoint_ok
        status = "PREMATCH_CAPTURE_VERIFIED" if strict else "CAPTURE_NOT_PREMATCH"
        reason = (
            "Capture timestamp proves the no-max_time source existed before kickoff."
            if strict
            else "Capture timestamp does not prove a pre-match snapshot."
        )
    elif meta:
        strict = False
        status = "METADATA_INCOMPLETE"
        reason = "Provenance metadata exists but does not prove the strict temporal contract."
    else:
        strict = False
        status = "UNVERIFIED_LEGACY_PACKAGE"
        reason = "No embedded provenance metadata; historical strictness cannot be proven from payload values alone."

    return {
        "status": status,
        "strict_prematch_proven": strict,
        "reason": reason,
        "expected_endpoint": expected_endpoint,
        "metadata_endpoint": endpoint or None,
        "kickoff_unix": kickoff,
        "captured_at_unix": capture,
        "max_time": max_time,
        "expected_max_time": expected_max if expects_max_time else None,
    }


def _target_match_leakage_audit(legacy: Any, match_data: Any) -> Dict[str, Any]:
    match_obj = _raw_match_object(legacy, match_data)
    status = str(_first_value(legacy, match_obj, ("status",)) or "").strip().lower()
    present: List[str] = []

    # Only inspect the target match object, never historical H2H children.
    for key in _TARGET_POSTMATCH_FIELDS:
        if key not in match_obj:
            continue
        value = match_obj.get(key)
        if key in {"homeGoalCount", "awayGoalCount", "totalGoalCount"}:
            number = _num(value)
            if number is not None and number >= 0 and status == "complete":
                present.append(key)
        elif key == "winningTeam":
            if status == "complete":
                present.append(key)
        elif key.startswith("over") or key == "btts":
            if status == "complete" and value not in (None, -1, "-1", ""):
                present.append(key)
        elif status == "complete":
            number = _num(value)
            if number is not None and number >= 0:
                present.append(key)

    return {
        "target_status": status or None,
        "postmatch_target_fields_present": sorted(set(present)),
        "prediction_feature_use_allowed": False if present else True,
        "policy": "Target-match post-match fields are labels/audit only and are never whitelisted as prediction features.",
    }


def build_official_spec_report(
    legacy: Any,
    pair: Dict[str, Any],
    *,
    now_unix: Optional[float] = None,
) -> Dict[str, Any]:
    match_data = pair.get("match_data")
    league_data = pair.get("league_data")
    extras = pair.get("supplemental_data") or {}
    form_data = extras.get("form")
    table_data = extras.get("table")
    player_data = extras.get("player")

    kickoff = _first_number(legacy, match_data, ("date_unix",))
    temporal = {
        "MatchDaten": _temporal_status(match_data, kickoff_unix=kickoff, expected_endpoint="/match", expects_max_time=False, now_unix=now_unix),
        "LeagueDaten": _temporal_status(league_data, kickoff_unix=kickoff, expected_endpoint="/league-season", expects_max_time=True, now_unix=now_unix),
        "FormDaten": _temporal_status(form_data, kickoff_unix=kickoff, expected_endpoint="/lastx", expects_max_time=False, now_unix=now_unix),
        "TableDaten": _temporal_status(table_data, kickoff_unix=kickoff, expected_endpoint="/league-tables", expects_max_time=True, now_unix=now_unix),
        "PlayerDaten": _temporal_status(player_data, kickoff_unix=kickoff, expected_endpoint="/league-players", expects_max_time=True, now_unix=now_unix),
    }

    proven = [bool(item.get("strict_prematch_proven")) for item in temporal.values()]
    if all(proven):
        overall_temporal = "STRICT_PREMATCH_VERIFIED"
    elif any(proven):
        overall_temporal = "PARTIALLY_VERIFIED"
    else:
        overall_temporal = "UNVERIFIED"

    player_meta = _find_meta(player_data)
    pagination_flag = player_meta.get("pagination_complete")
    if pagination_flag is True:
        pagination_status = "COMPLETE"
    elif pagination_flag is False:
        pagination_status = "INCOMPLETE"
    else:
        pagination_status = "UNVERIFIED"

    match = {}
    try:
        match = legacy.mf(match_data) or {}
    except Exception:
        pass

    return {
        "name": SPEC_NAME,
        "version": SPEC_VERSION,
        "status": "ACTIVE_INTERPRETATION_AND_PROVENANCE_LAYER",
        "probability_core_modified": False,
        "probabilities_modified": False,
        "final_decision_modified": False,
        "official_rules_are_evidence_flags_only": True,
        "match_identity": {
            "match_id": match.get("match_id"),
            "home_id": match.get("home_id"),
            "away_id": match.get("away_id"),
            "competition_id": match.get("competition_id"),
            "kickoff_unix": kickoff,
        },
        "venue_contract": {
            "home_team_primary_split": "home",
            "away_team_primary_split": "away",
            "overall_split_role": "context/support",
        },
        "potential_interpretation": {
            "btts_potential": "FootyStats pre-match average historical/statistical BTTS value; not a calibrated probability.",
            "o25_potential": "FootyStats pre-match average Over 2.5 statistic; not a calibrated probability.",
            "u25_potential": "FootyStats pre-match average Under 2.5 statistic; not a calibrated probability.",
            "avg_potential": "FootyStats pre-match average total-goals statistic.",
        },
        "official_tutorial_examples": _official_tutorial_rules(legacy, match_data),
        "temporal_safety": {
            "overall": overall_temporal,
            "files": temporal,
            "historical_lastx_policy": "STRICT only when capture/source timestamp proves LastX existed before kickoff; endpoint has no documented max_time parameter.",
        },
        "player_pagination": {
            "status": pagination_status,
            "required": "Fetch all /league-players pages until current_page == max_page.",
        },
        "target_match_leakage": _target_match_leakage_audit(legacy, match_data),
        "registry": {"schema_version": load_field_registry().get("schema_version"), "source": REGISTRY_FILE.name},
        "shortcut_schema": {"schema_version": load_shortcut_schema().get("schema_version"), "source": SHORTCUT_SCHEMA_FILE.name},
    }
