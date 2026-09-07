V1 standalone owns copied core code under V1 filenames. Production files remain untouched.

Planned copied blobs:
- app_v040.py -> v1_base.py
- v041_engine.py -> v1_decision_core.py
- v043_engine.py -> v1_probability_core.py

These copies are frozen into the V1 branch and are not imported from the production filenames at runtime.