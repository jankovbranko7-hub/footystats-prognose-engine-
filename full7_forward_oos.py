from __future__ import annotations

import copy
import hashlib
import json
from typing import Any, Dict, Mapping, Optional

from full7_dataset import derive_targets, validate_target_coherence

MARKETS = (
    "home_win", "draw", "away_win",
    "btts_yes", "btts_no", "over_2_5", "under_2_5",
)
FAMILY_MARKETS = {
    "1X2": ("home_win", "draw", "away_win"),
    "BTTS": ("btts_yes", "btts_no"),
    "TOTALS": ("over_2_5", "under_2_5"),
}
FROZEN_STATUS = "PREDICTION_FROZEN_BEFORE_RESULT_JOIN"
SPENT_STATUS = "SPENT_OOS"


def canonical_sha256(value: Any) -> str:
    raw = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _locked_prediction_view(frozen: Mapping[str, Any]) -> Dict[str, Any]:
    """Return the immutable outcome-blind portion of a frozen OOS prediction."""
    keys = (
        "oos_id",
        "status",
        "bundle_sha256",
        "file_sha256",
        "identity",
        "quality",
        "gold",
        "probabilities",
        "model_support",
        "families",
        "markets",
        "sample_security",
        "data_quality_support",
        "coherence",
        "contract_stage",
        "secondary_context",
    )
    return {key: copy.deepcopy(frozen.get(key)) for key in keys}


def verify_frozen_prediction(frozen: Mapping[str, Any]) -> str:
    """Validate that a record is a coherent, outcome-blind FULL-7 freeze.

    Returns a deterministic SHA-256 over the immutable prediction payload.
    The freeze itself remains result-free forever; result evaluation is written
    to a separate SPENT_OOS artifact.
    """
    if frozen.get("status") != FROZEN_STATUS:
        raise ValueError("OOS prediction is not in frozen pre-result state")

    audit = frozen.get("freeze_audit") or {}
    if audit.get("result_joined") is not False:
        raise ValueError("frozen prediction already claims a result join")
    if audit.get("frozen_before_result_join") is not True:
        raise ValueError("freeze audit does not prove pre-result locking")

    identity = frozen.get("identity") or {}
    if identity.get("match_id") is None:
        raise ValueError("frozen prediction missing match_id")

    probabilities = frozen.get("probabilities") or {}
    missing = [market for market in MARKETS if market not in probabilities]
    if missing:
        raise ValueError(f"frozen prediction missing markets: {missing}")

    for market in MARKETS:
        p = float(probabilities[market])
        if not 0.0 <= p <= 1.0:
            raise ValueError(f"invalid probability for {market}: {p}")

    if abs(sum(float(probabilities[m]) for m in FAMILY_MARKETS["1X2"]) - 1.0) > 1e-6:
        raise ValueError("1X2 probability coherence failed")
    if abs(sum(float(probabilities[m]) for m in FAMILY_MARKETS["BTTS"]) - 1.0) > 1e-6:
        raise ValueError("BTTS probability coherence failed")
    if abs(sum(float(probabilities[m]) for m in FAMILY_MARKETS["TOTALS"]) - 1.0) > 1e-6:
        raise ValueError("TOTALS probability coherence failed")

    market_rows = frozen.get("markets") or {}
    if any(market not in market_rows for market in MARKETS):
        raise ValueError("frozen prediction does not contain decisions for all seven markets")

    families = frozen.get("families") or {}
    for family, family_markets in FAMILY_MARKETS.items():
        row = families.get(family) or {}
        selected = row.get("selected_market")
        if selected not in family_markets:
            raise ValueError(f"invalid selected market for {family}: {selected}")

    return canonical_sha256(_locked_prediction_view(frozen))


def evaluate_frozen_prediction(
    frozen: Mapping[str, Any],
    *,
    home_goals: Any,
    away_goals: Any,
    result_source: str,
    verified_at: str,
    source_details: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Join a verified final result without mutating the frozen prediction."""
    frozen_hash = verify_frozen_prediction(frozen)
    targets = derive_targets(home_goals, away_goals)
    validate_target_coherence(targets)

    result = {
        "home_goals": int(targets["home_goals"]),
        "away_goals": int(targets["away_goals"]),
        "total_goals": int(targets["total_goals"]),
    }

    market_eval: Dict[str, Any] = {}
    market_rows = frozen["markets"]
    probabilities = frozen["probabilities"]
    for market in MARKETS:
        row = market_rows[market]
        market_eval[market] = {
            "probability": float(probabilities[market]),
            "decision": row.get("decision"),
            "decision_reason": row.get("decision_reason"),
            "selected_in_family": bool(row.get("selected_in_family")),
            "target": int(targets[market]),
            "hit": bool(targets[market]),
        }

    family_eval: Dict[str, Any] = {}
    for family, row in frozen["families"].items():
        selected = row["selected_market"]
        family_eval[family] = {
            "selected_market": selected,
            "decision": row.get("decision"),
            "base_probability": row.get("base_probability"),
            "reliability_score": row.get("reliability_score"),
            "hit": bool(targets[selected]),
        }

    out = {
        "oos_id": frozen.get("oos_id"),
        "status": SPENT_STATUS,
        "identity": copy.deepcopy(frozen.get("identity") or {}),
        "frozen_prediction_sha256": frozen_hash,
        "frozen_bundle_sha256": frozen.get("bundle_sha256"),
        "result": result,
        "targets": targets,
        "result_source": result_source,
        "result_verified_at": verified_at,
        "source_details": copy.deepcopy(source_details) if source_details else None,
        "markets": market_eval,
        "families": family_eval,
        "integrity": {
            "freeze_verified_before_join": True,
            "freeze_mutated": False,
            "all_seven_markets_evaluated": True,
            "architecture_change_allowed_from_single_oos": False,
        },
    }
    out["spent_oos_sha256"] = canonical_sha256(out)
    return out
