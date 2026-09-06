"""Render/test entry point for Gate V1 FULL-DATA challenger.

Production app.py/main remain untouched. For a separate Render test service use:
python -m uvicorn app_v1:app --host 0.0.0.0 --port $PORT
"""
import app_v040 as legacy
import v1_full_data_engine

app = v1_full_data_engine.apply_patch(legacy)
