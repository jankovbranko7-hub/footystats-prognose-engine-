from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Mapping

from full7_forward_oos import SPENT_STATUS, verify_frozen_prediction

ROOT = Path(__file__).resolve().parents[1]
FROZEN_001 = ROOT / "research" / "oos" / "FULL7_OOS_001_8558326_FROZEN.json"
SPENT_001 = ROOT / "research" / "oos" / "FULL7_OOS_001_8558326_SPENT.json"
FINAL_OOS_AUDIT = ROOT / "research" / "oos" / "FULL7_FORWARD_OOS_FINAL_AUDIT.json"
FINAL_CONTRACT_AUDIT = ROOT / "research" / "FULL7_CONTRACT_FINAL_AUDIT.json"
FINAL_DEPENDENCY_AUDIT = ROOT / "research" / "FULL7_DEPENDENCY_FINAL_AUDIT.json"


def _load(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(str(path.relative_to(ROOT)))
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must contain a JSON object")
    return value


def evaluate_final_oos_release_constraints(audit: Mapping[str, Any]) -> Dict[str, Any]:
    """Fail closed on explicit OOS release prohibitions and missing play exposure.

    A historical/forward audit may be internally valid while still explicitly
    forbidding promotion. Those authorization flags are release constraints and
    must not be ignored by the final gate.
    """
    blockers = []

    main_merge_allowed = audit.get("main_merge_allowed") is True
    render_deploy_allowed = audit.get("render_deploy_allowed") is True

    if not main_merge_allowed:
        blockers.append("FORWARD_OOS_MAIN_MERGE_FORBIDDEN")
    if not render_deploy_allowed:
        blockers.append("FORWARD_OOS_RENDER_DEPLOY_FORBIDDEN")

    spielen_row = ((audit.get("decision_performance") or {}).get("SPIELEN") or {})
    try:
        spielen_exposure = int(spielen_row.get("n") or 0)
    except (TypeError, ValueError):
        spielen_exposure = 0

    if spielen_exposure <= 0:
        blockers.append("FORWARD_OOS_NO_SPIELEN_EXPOSURE")

    return {
        "pass": not blockers,
        "blockers": blockers,
        "main_merge_allowed": main_merge_allowed,
        "render_deploy_allowed": render_deploy_allowed,
        "spielen_exposure": spielen_exposure,
    }


def current_gate_state() -> Dict[str, Any]:
    checks: Dict[str, Any] = {}
    blockers = []

    try:
        frozen = _load(FROZEN_001)
        frozen_hash = verify_frozen_prediction(frozen)
        checks["oos001_frozen"] = {
            "pass": True,
            "frozen_prediction_sha256": frozen_hash,
            "bundle_sha256": frozen.get("bundle_sha256"),
        }
    except Exception as exc:
        frozen = None
        checks["oos001_frozen"] = {"pass": False, "error": str(exc)}
        blockers.append("OOS001_FROZEN_INVALID")

    try:
        spent = _load(SPENT_001)
        spent_ok = (
            spent.get("status") == SPENT_STATUS
            and bool((spent.get("integrity") or {}).get("freeze_verified_before_join"))
            and not bool((spent.get("integrity") or {}).get("freeze_mutated"))
            and bool((spent.get("integrity") or {}).get("all_seven_markets_evaluated"))
        )
        if frozen is not None:
            spent_ok = spent_ok and spent.get("frozen_prediction_sha256") == verify_frozen_prediction(frozen)
        checks["oos001_spent"] = {"pass": bool(spent_ok)}
        if not spent_ok:
            blockers.append("OOS001_SPENT_INVALID")
    except Exception as exc:
        checks["oos001_spent"] = {"pass": False, "error": str(exc)}
        blockers.append("OOS001_SPENT_MISSING")

    for key, path, required_flags in (
        (
            "forward_oos_final_audit",
            FINAL_OOS_AUDIT,
            (
                "untouched_forward_oos_complete",
                "all_predictions_frozen_before_results",
                "no_result_leakage",
                "no_architecture_change_during_validation",
            ),
        ),
        (
            "contract_final_audit",
            FINAL_CONTRACT_AUDIT,
            (
                "architecture_contract_pass",
                "all_seven_markets_full_pipeline",
                "probability_mode_no_odds",
                "no_post_match_leakage",
            ),
        ),
        (
            "dependency_final_audit",
            FINAL_DEPENDENCY_AUDIT,
            (
                "dependencies_pass",
                "model_artifacts_hash_verified",
                "runtime_imports_pass",
            ),
        ),
    ):
        try:
            audit = _load(path)
            passed = audit.get("status") == "PASS" and all(
                audit.get(flag) is True for flag in required_flags
            )
            checks[key] = {
                "pass": passed,
                "status": audit.get("status"),
                "required_flags": {flag: audit.get(flag) for flag in required_flags},
            }
            if not passed:
                blockers.append(key.upper() + "_NOT_PASS")

            if key == "forward_oos_final_audit":
                constraints = evaluate_final_oos_release_constraints(audit)
                checks[key]["release_constraints"] = constraints
                blockers.extend(constraints["blockers"])
        except Exception as exc:
            checks[key] = {"pass": False, "error": str(exc)}
            blockers.append(key.upper() + "_MISSING")

    return {
        "release_gate_version": "FULL7_CONTRACT_RELEASE_GATE_2.0",
        "status": "PASS" if not blockers else "BLOCKED",
        "blockers": blockers,
        "checks": checks,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--require-final", action="store_true")
    args = parser.parse_args()

    state = current_gate_state()
    print(json.dumps(state, indent=2, ensure_ascii=False))

    if args.require_final and state["status"] != "PASS":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
