from __future__ import annotations

import gzip
import io
import json
import math
import tarfile
import hashlib
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Mapping, Sequence

from full7_goal_probability import market_probabilities
from full7_market_feature_sets import domain_family

ENGINE_VERSION = "FULL7_GATED_1.0.0"
MODEL_CONTRACT_VERSION = "FULL7_MODEL_CONTRACT_1.0"
BTTS_GATE_VERSION = "FULL7_BTTS_DECISION_GATE_0.1"
BTTS_RHO = -0.20
BTTS_PLAY_CONFIDENCE = 0.632489
BTTS_COVERAGE_FLOOR = 0.98989898989899
BTTS_FAMILY_FLOOR = 8
BTTS_REMOVAL_FLIPS_ALLOWED = 0

READINESS = {
    "1X2": "OOS_OBSERVE_ONLY",
    "BTTS": "OOS_VALIDATED_SELECTIVE",
    "TOTALS": "OOS_OBSERVE_ONLY",
}

_BASE = Path(__file__).resolve().parent
_MODEL_DIR = _BASE / "models"
_BUNDLE_PART_PREFIX = "full7_bundle.part"
_BUNDLE_SHA256 = "1e78d4d6db40f6c7cd66a0c189c40bd7cae31462c03cbc082e3dc04917647dd3"

_MODEL_FILES = {
    "1X2": "full7_1x2_model.py.gz",
    "GOAL_HOME": "full7_goal_home_model.py.gz",
    "GOAL_AWAY": "full7_goal_away_model.py.gz",
    "TOTALS": "full7_totals_model.py.gz",
}

_MODEL_SHA256 = {
    "1X2": "20b585890d16d2e65b89de658606948c321006c6d4369ca3c0705164265bef9a",
    "GOAL_HOME": "29dc8108cbe541e27a3eaaae93b96a822413b15a3ce187593b5ef510d99822ce",
    "GOAL_AWAY": "8feebc19e0978c2259cf3ac8d7cc38b4cca370236f756e64ce5a0ad2f0884767",
    "TOTALS": "5075c2440377851f06ebf62ff788b4ed3552f65fc8d42d400d9ad1d1b79799ab",
}
_FEATURE_LIST_SHA256 = "ff6afd34f6a9eb6bd270018a2a7fdd63f2f0deef7df08e8f396a33335bf46cab"


def _load_bundle_members() -> Dict[str, bytes]:
    parts = sorted(_MODEL_DIR.glob(f"{_BUNDLE_PART_PREFIX}*"))
    if not parts:
        raise RuntimeError("FULL-7 model bundle parts are missing")
    bundle = b"".join(path.read_bytes() for path in parts)
    if hashlib.sha256(bundle).hexdigest() != _BUNDLE_SHA256:
        raise RuntimeError("FULL-7 model bundle SHA-256 mismatch")
    members: Dict[str, bytes] = {}
    with tarfile.open(fileobj=io.BytesIO(bundle), mode="r:gz") as tar:
        for member in tar.getmembers():
            if not member.isfile():
                continue
            fh = tar.extractfile(member)
            if fh is not None:
                members[Path(member.name).name] = fh.read()
    return members


_BUNDLE_MEMBERS = _load_bundle_members()


def _load_export(key: str, filename: str) -> SimpleNamespace:
    compressed = _BUNDLE_MEMBERS.get(filename)
    if compressed is None:
        raise RuntimeError(f"FULL-7 model artifact missing: {filename}")
    if hashlib.sha256(compressed).hexdigest() != _MODEL_SHA256[key]:
        raise RuntimeError(f"FULL-7 model SHA-256 mismatch: {key}")
    source = gzip.decompress(compressed).decode("utf-8")
    ns: Dict[str, Any] = {}
    exec(compile(source, filename, "exec"), ns, ns)
    return SimpleNamespace(**ns)


def _load_feature_lists() -> Dict[str, List[str]]:
    compressed = _BUNDLE_MEMBERS.get("full7_feature_lists.json.gz")
    if compressed is None:
        raise RuntimeError("FULL-7 feature-list artifact missing")
    if hashlib.sha256(compressed).hexdigest() != _FEATURE_LIST_SHA256:
        raise RuntimeError("FULL-7 feature-list SHA-256 mismatch")
    raw = json.loads(gzip.decompress(compressed).decode("utf-8"))
    return {k: list(v) for k, v in raw.items()}


_MODELS = {key: _load_export(key, name) for key, name in _MODEL_FILES.items()}
_FEATURES = _load_feature_lists()


def _finite(v: Any) -> float:
    if v is None or isinstance(v, bool):
        return float("nan")
    try:
        x = float(v)
    except (TypeError, ValueError):
        return float("nan")
    return x if math.isfinite(x) else float("nan")


def _vector(features: Mapping[str, Any], names: Sequence[str]) -> List[float]:
    return [_finite(features.get(name)) for name in names]


def _softmax(raw: Sequence[float]) -> List[float]:
    m = max(raw)
    ex = [math.exp(v - m) for v in raw]
    s = sum(ex)
    return [v / s for v in ex]


def _regression_prediction(model: SimpleNamespace, vector: Sequence[float]) -> float:
    raw = float(model.apply_catboost_model(list(vector)))
    return math.exp(raw)


def _multiclass_probability(vector: Sequence[float]) -> List[float]:
    raw = _MODELS["1X2"].apply_catboost_model_multi(list(vector))
    return _softmax(raw)


def _btts_probability(vector: Sequence[float]) -> Dict[str, float]:
    lh = min(8.0, max(0.03, _regression_prediction(_MODELS["GOAL_HOME"], vector)))
    la = min(8.0, max(0.03, _regression_prediction(_MODELS["GOAL_AWAY"], vector)))
    probs = market_probabilities(lh, la, BTTS_RHO)
    return {"lambda_home": lh, "lambda_away": la, **probs}


def _totals_probability(vector: Sequence[float]) -> Dict[str, float]:
    lam = min(12.0, max(0.03, _regression_prediction(_MODELS["TOTALS"], vector)))
    under = math.exp(-lam) * (1.0 + lam + lam * lam / 2.0)
    return {"lambda_total": lam, "over_2_5": 1.0 - under, "under_2_5": under}


def _btts_family_indices() -> Dict[str, List[int]]:
    out: Dict[str, List[int]] = {}
    for i, name in enumerate(_FEATURES["btts"]):
        family = domain_family(name)
        if family in {
            "XG", "SCORING_DEFENCE", "SHOTS", "GOAL_PATTERN", "HALF",
            "PLAYER", "FORM", "LEAGUE_CONTEXT", "MATCH_CONTEXT", "STRENGTH",
        }:
            out.setdefault(family, []).append(i)
    return out


_BTTS_FAMILY_INDEX = _btts_family_indices()


def _btts_gate(features: Mapping[str, Any], base: Dict[str, float]) -> Dict[str, Any]:
    names = _FEATURES["btts"]
    vec = _vector(features, names)
    finite = [math.isfinite(v) for v in vec]
    coverage = sum(finite) / len(vec) if vec else 0.0
    family_available = sum(
        any(math.isfinite(vec[i]) for i in indices)
        for indices in _BTTS_FAMILY_INDEX.values()
    )

    p_yes = float(base["btts_yes"])
    direction_yes = p_yes >= 0.5
    confidence = max(p_yes, 1.0 - p_yes)
    removal_flips = 0
    removal_details: Dict[str, Dict[str, Any]] = {}

    for family, indices in sorted(_BTTS_FAMILY_INDEX.items()):
        removed = list(vec)
        for i in indices:
            removed[i] = float("nan")
        alt = _btts_probability(removed)
        alt_yes = float(alt["btts_yes"])
        flipped = (alt_yes >= 0.5) != direction_yes
        removal_flips += int(flipped)
        removal_details[family] = {
            "p_btts_yes": alt_yes,
            "direction_flipped": flipped,
            "absolute_move": abs(alt_yes - p_yes),
        }

    integrity_ok = coverage >= BTTS_COVERAGE_FLOOR and family_available >= BTTS_FAMILY_FLOOR
    robustness_ok = removal_flips <= BTTS_REMOVAL_FLIPS_ALLOWED
    if not integrity_ok or not robustness_ok:
        decision = "AUSLASSEN"
    elif confidence >= BTTS_PLAY_CONFIDENCE:
        decision = "SPIELEN"
    else:
        decision = "BEOBACHTEN"

    direction = "btts_yes" if direction_yes else "btts_no"
    return {
        "decision": decision,
        "market": direction,
        "probability": p_yes if direction_yes else 1.0 - p_yes,
        "confidence": confidence,
        "coverage": coverage,
        "family_available_count": family_available,
        "family_required_count": BTTS_FAMILY_FLOOR,
        "removal_flip_count": removal_flips,
        "integrity_ok": integrity_ok,
        "robustness_ok": robustness_ok,
        "threshold": BTTS_PLAY_CONFIDENCE,
        "removal_test": removal_details,
    }


def predict_gold_features(gold_features: Mapping[str, Any]) -> Dict[str, Any]:
    features = gold_features.get("features") or {}
    x1 = _vector(features, _FEATURES["core"])
    xb = _vector(features, _FEATURES["btts"])
    xt = _vector(features, _FEATURES["totals"])

    p1 = _multiclass_probability(x1)
    goal = _btts_probability(xb)
    totals = _totals_probability(xt)
    gate = _btts_gate(features, goal)

    return {
        "engine": "FOOTYSTATS_FULL7_GATED",
        "engine_version": ENGINE_VERSION,
        "model_contract_version": MODEL_CONTRACT_VERSION,
        "probabilities": {
            "home_win": p1[0],
            "draw": p1[1],
            "away_win": p1[2],
            "btts_yes": goal["btts_yes"],
            "btts_no": goal["btts_no"],
            "over_2_5": totals["over_2_5"],
            "under_2_5": totals["under_2_5"],
        },
        "goal_model": {
            "lambda_home": goal["lambda_home"],
            "lambda_away": goal["lambda_away"],
            "lambda_total_specialist": totals["lambda_total"],
            "rho": BTTS_RHO,
            "alpha": None,
        },
        "family_readiness": dict(READINESS),
        "decision": gate,
        "recommendation": {
            "decision": gate["decision"],
            "market": gate["market"],
            "probability": gate["probability"],
            "source_family": "BTTS",
        },
        "non_btts_policy": {
            "1X2": "probability exposed; no SPIELEN because final OOS advantage was not robust",
            "TOTALS": "probability exposed; no SPIELEN because development and final OOS evidence were not robust enough",
        },
        "referee_manager_policy": {
            "status": "VALIDATED_INPUT_NOT_MODEL_WEIGHTED",
            "reason": "Historical 300+143 probability training/OOS did not contain strict Referee/Manager captures; values remain visible in Gold but are not assigned unvalidated predictive weight.",
        },
        "model_integrity": {
            "model_sha256_gzip": dict(_MODEL_SHA256),
            "feature_counts": {k: len(v) for k, v in _FEATURES.items()},
        },
    }
