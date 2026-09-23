"""Standalone, non-production ASGI entry point for the FULL-7 final RC."""
from fastapi import FastAPI

from full7_phase7_api import FULL7_RELEASE_CANDIDATE_VERSION, router


app = FastAPI(
    title="FULL-7 Final Engine Release Candidate",
    version=FULL7_RELEASE_CANDIDATE_VERSION,
)
app.include_router(router)
