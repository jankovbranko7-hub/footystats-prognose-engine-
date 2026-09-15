from __future__ import annotations

import gzip
import hashlib
import io
import json
import math
import tarfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Mapping, Sequence

from full7_goal_probability import market_probabilities

MODEL_FOUNDATION_VERSION = "FULL7_CONTRACT_MODEL_FOUNDATION_1.0"
MODEL_BUNDLE_SHA256 = "62dc5ff31fdb144d40c9c873ab2cd35de5b349a6497c2e50fe2c1ea3019a6187"
MARKETS = (
    "home_win", "draw", "away_win",
    "btts_yes", "btts_no", "over_2_5", "under_2_5",
)

_BASE = Path(__file__).resolve().parent
_MODEL_DIR = _BASE / "models"
_PART_PREFIX = "full7_contract_bundle.part"

_MEMBER_SHA256 = {
    "full7_1x2_catboost.py.gz": "f1130988558d302c3bdfe0c92794798897f86c9e5d572afee8631792e0d7f997",
    "full7_btts_catboost.py.gz": "db647c08eda81dcdef31817da02af969a97d368a493710df3478b0c8fe0b6648",
    "full7_totals_catboost.py.gz": "8a6d04b010fe9239749e40db190526ad774e5f8043818aefc0ccb61597612942",
    "full7_goal_home.py.gz": "59018e955e74b5ce2bccdcb602031b282a9dcc6ead1a99ca16180d0a07217c6e",
    "full7_goal_away.py.gz": "9119c788480487970585a4e252e300fa075e79142ae2004b6e3c9c125049d868",
    "full7_contract_feature_lists.json.gz": "a9b0b884b978091bb1324e8d0607e9619c0a0ddb18e89e143bc1edab2a3a0de4",
    "full7_contract_model_meta.json.gz": "2be7de8e56791fa301290b0421811ce44dba4af942b70e83284ed4c7f87afb74",
}


def _load_members() -> Dict[str, bytes]:
    parts = sorted(_MODEL_DIR.glob(f"{_PART_PREFIX}*"))
    if not parts:
        raise RuntimeError("FULL-7 contract model bundle parts missing")
    bundle = b"".join(path.read_bytes() for path in parts)
    if hashlib.sha256(bundle).hexdigest() != MODEL_BUNDLE_SHA256:
        raise RuntimeError("FULL-7 contract model bundle SHA-256 mismatch")
    out: Dict[str, bytes] = {}
    with tarfile.open(fileobj=io.BytesIO(bundle), mode="r:gz") as tar:
        for member in tar.getmembers():
            if not member.isfile():
                continue
            fh = tar.extractfile(member)
            if fh is not None:
                out[Path(member.name).name] = fh.read()
    missing = set(_MEMBER_SHA256) - set(out)
    if missing:
        raise RuntimeError(f"FULL-7 contract bundle members missing: {sorted(missing)}")
    for name, expected in _MEMBER_SHA256.items():
        if hashlib.sha256(out[name]).hexdigest() != expected:
            raise RuntimeError(f"FULL-7 contract member SHA-256 mismatch: {name}")
    return out


_MEMBERS = _load_members()


def _load_python(name: str) -> SimpleNamespace:
    source = gzip.decompress(_MEMBERS[name]).decode("utf-8")
    ns: Dict[str, Any] = {}
    exec(compile(source, name, "exec"), ns, ns)
    return SimpleNamespace(**ns)


def _load_json(name: str) -> Dict[str, Any]:
    return json.loads(gzip.decompress(_MEMBERS[name]).decode("utf-8"))


_MODELS = {
    "1X2": _load_python("full7_1x2_catboost.py.gz"),
    "BTTS": _load_python("full7_btts_catboost.py.gz"),
    "TOTALS": _load_python("full7_totals_catboost.py.gz"),
    "GOAL_HOME": _load_python("full7_goal_home.py.gz"),
    "GOAL_AWAY": _load_python("full7_goal_away.py.gz"),
}
_FEATURES = _load_json("full7_contract_feature_lists.json.gz")
_META = _load_json("full7_contract_model_meta.json.gz")
CORE_FEATURES = tuple(_FEATURES["core"])
MODEL_META = dict(_META)


def _finite(value: Any) -> float:
    if value is None or isinstance(value, bool):
        return float("nan")
    try:
        x = float(value)
    except (TypeError, ValueError):
        return float("nan")
    return x if math.isfinite(x) else float("nan")


def _vector(features: Mapping[str, Any], names: Sequence[str]) -> List[float]:
    return [_finite(features.get(name)) for name in names]


def _softmax(raw: Sequence[float]) -> List[float]:
    m = max(float(v) for v in raw)
    ex = [math.exp(float(v) - m) for v in raw]
    den = sum(ex)
    return [v / den for v in ex]


def _sigmoid(raw: float) -> float:
    x = max(-40.0, min(40.0, float(raw)))
    return 1.0 / (1.0 + math.exp(-x))


def _goal_lambda(model: SimpleNamespace, vector: Sequence[float]) -> float:
    raw = float(model.apply_catboost_model(list(vector)))
    return min(8.0, max(0.03, math.exp(raw)))


def _coverage(vector: Sequence[float]) -> float:
    if not vector:
        return 0.0
    return sum(math.isfinite(v) for v in vector) / len(vector)


def contract_model_support(gold_features: Mapping[str, Any]) -> Dict[str, Any]:
    """Return both required model sources for all seven markets.

    This is the architecture-contract model foundation only. It deliberately does
    not invent ensemble weights, calibration or decision gates; those are learned
    from saved temporal OOF predictions in the next contract stages.
    """
    features = gold_features.get("features") or {}
    names = list(CORE_FEATURES)
    if not names or len(names) != 620:
        raise RuntimeError("FULL-7 contract core feature list must contain 620 features")
    if any(list(_FEATURES[key]) != names for key in ("1X2", "BTTS", "TOTALS", "GOAL")):
        raise RuntimeError("FULL-7 contract requires the same broad feature universe for all model families")

    vector = _vector(features, names)

    p1 = _softmax(_MODELS["1X2"].apply_catboost_model_multi(list(vector)))
    p_btts_yes = _sigmoid(_MODELS["BTTS"].apply_catboost_model(list(vector)))
    p_over = _sigmoid(_MODELS["TOTALS"].apply_catboost_model(list(vector)))

    lambda_home = _goal_lambda(_MODELS["GOAL_HOME"], vector)
    lambda_away = _goal_lambda(_MODELS["GOAL_AWAY"], vector)
    rho = float(_META["rho_final"])
    goal = market_probabilities(lambda_home, lambda_away, rho)

    catboost = {
        "home_win": p1[0],
        "draw": p1[1],
        "away_win": p1[2],
        "btts_yes": p_btts_yes,
        "btts_no": 1.0 - p_btts_yes,
        "over_2_5": p_over,
        "under_2_5": 1.0 - p_over,
    }
    structural = {market: float(goal[market]) for market in MARKETS}

    return {
        "model_foundation_version": MODEL_FOUNDATION_VERSION,
        "status": "DEVELOPMENT_ONLY",
        "markets": list(MARKETS),
        "feature_count": len(names),
        "feature_coverage": _coverage(vector),
        "same_broad_core_all_target_families": True,
        "catboost": catboost,
        "goal_model": structural,
        "goal_parameters": {
            "lambda_home": lambda_home,
            "lambda_away": lambda_away,
            "rho": rho,
        },
        "coherence": {
            "catboost_1x2_sum": catboost["home_win"] + catboost["draw"] + catboost["away_win"],
            "catboost_btts_sum": catboost["btts_yes"] + catboost["btts_no"],
            "catboost_totals_sum": catboost["over_2_5"] + catboost["under_2_5"],
            "goal_1x2_sum": structural["home_win"] + structural["draw"] + structural["away_win"],
            "goal_btts_sum": structural["btts_yes"] + structural["btts_no"],
            "goal_totals_sum": structural["over_2_5"] + structural["under_2_5"],
        },
        "contract_stage": {
            "goal_model_all_7": True,
            "catboost_all_7": True,
            "oos_ensemble": "PENDING",
            "calibration": "PENDING",
            "evidence_engine_all_7": "PENDING",
            "decision_all_7": "PENDING",
            "new_untouched_oos": "PENDING",
        },
        "training": {
            "rows": int(_META["training_rows"]),
            "start": _META["training_start"],
            "end": _META["training_end"],
            "walk_forward_evaluation_rows": int(_META["walk_forward_metrics"]["rows"]),
        },
        "referee_manager_policy": {
            "architecture_blocks_required": True,
            "strict_live_features_allowed": True,
            "trained_ml_weight": False,
            "reason": "The 300-match historical model corpus did not contain strict Referee/Manager history; these blocks remain evidence/data-quality inputs until enough strict historical FULL-7 rows exist.",
        },
    }
