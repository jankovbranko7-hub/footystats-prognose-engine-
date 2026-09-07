"""V1 runtime contract.

`app_v1` must import only V1-owned modules. The production `main` application is
not part of the V1 runtime path.
"""
FORBIDDEN_RUNTIME_MODULES = ("app_v040", "v041_engine", "v042_engine", "v043_engine")
V1_MODULES = ("v1_base", "v1_decision_core", "v1_score_core", "v1_probability_core", "v1_full_data_engine")
