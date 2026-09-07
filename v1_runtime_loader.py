"""Load only V1-owned engine modules.

The copied V1 cores retain historical import statements internally, therefore this
loader aliases those names to the V1-owned copies before the probability core is
loaded. No production V0.4.x module is executed by app_v1.
"""
from __future__ import annotations
import importlib
import sys


def load_probability_core():
    decision = importlib.import_module("v1_decision_core")
    sys.modules["v041_engine"] = decision
    score = importlib.import_module("v1_score_compat_core")
    sys.modules["v042_engine"] = score
    probability = importlib.import_module("v1_probability_core")
    return decision, score, probability
