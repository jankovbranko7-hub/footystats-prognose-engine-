"""Envelope validation for collector-produced snapshots, separate from raw JSON."""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .audit import DataError, SOURCES, decode, inventory

Source = Literal["MATCH", "LEAGUE", "FORM", "TABLE", "PLAYER"]
ENDPOINTS = {
    "MATCH": {"match"},
    "LEAGUE": {"league-season", "league-teams"},
    "FORM": {"lastx"},
    "TABLE": {"league-tables"},
    "PLAYER": {"league-players"},
}


class Snapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    source: Source
    endpoint: str
    match_id: int = Field(gt=0)
    season_id: int = Field(gt=0)
    home_id: int = Field(gt=0)
    away_id: int = Field(gt=0)
    kickoff: datetime
    requested_at: datetime
    received_at: datetime
    raw_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    # A caller-supplied max_time is not proof of historical source availability.
    requested_max_time: int | None = Field(default=None, gt=0)

    @field_validator("kickoff", "requested_at", "received_at")
    @classmethod
    def timezone_required(cls, value):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("TIMEZONE_REQUIRED")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def validate_context(self):
        if self.home_id == self.away_id:
            raise ValueError("IDENTICAL_TEAMS")
        if self.endpoint not in ENDPOINTS[self.source]:
            raise ValueError("SOURCE_ENDPOINT_MISMATCH")
        if self.requested_at > self.received_at:
            raise ValueError("INVALID_CAPTURE_ORDER")
        if self.requested_max_time is not None:
            if self.source == "FORM":
                raise ValueError("LASTX_HISTORICAL_CUTOFF_UNVERIFIED")
            if self.requested_max_time >= self.kickoff.timestamp():
                raise ValueError("CUTOFF_NOT_PREMATCH")
        return self


def validate_bundle(items: list[tuple[Snapshot, bytes]], *, now: datetime) -> dict:
    """Audit only. Does not certify user metadata, identity mappings or features.

    This requires five logical sources; a later collector adapter may aggregate
    multiple endpoint responses/pages while preserving their original bytes.
    """
    if now.tzinfo is None or now.utcoffset() is None:
        raise DataError("TIMEZONE_REQUIRED")
    if len(items) != 5:
        raise DataError("EXACTLY_FIVE_SOURCES_REQUIRED")
    sources = [meta.source for meta, _ in items]
    if len(set(sources)) != 5 or set(sources) != SOURCES:
        raise DataError("DUPLICATE_OR_MISSING_SOURCE")
    contexts = {(m.match_id, m.season_id, m.home_id, m.away_id, m.kickoff)
                for m, _ in items}
    if len(contexts) != 1:
        raise DataError("CONFLICTING_BUNDLE_CONTEXT")
    reports = []
    all_pre = True
    for meta, raw in items:
        if meta.received_at > now:
            raise DataError("FUTURE_CAPTURE")
        if sha256(raw).hexdigest() != meta.raw_sha256:
            raise DataError("PAYLOAD_HASH_MISMATCH")
        payload = decode(raw)
        if isinstance(payload, dict) and payload.get("success") is False:
            raise DataError("PROVIDER_ERROR_RESPONSE")
        if meta.source == "MATCH":
            match = payload.get("data", payload) if isinstance(payload, dict) else None
            if not isinstance(match, dict):
                raise DataError("UNSUPPORTED_MATCH_SCHEMA")
            expected = {"id": meta.match_id, "homeID": meta.home_id, "awayID": meta.away_id}
            if any(type(match.get(k)) is not int or match[k] != v for k, v in expected.items()):
                raise DataError("MATCH_IDENTITY_MISMATCH")
            kickoff = match.get("date_unix")
            if type(kickoff) is not int or kickoff != int(meta.kickoff.timestamp()):
                raise DataError("MATCH_KICKOFF_MISMATCH")
            if match.get("status") != "incomplete":
                raise DataError("MATCH_NOT_PREMATCH")
        before = meta.received_at < meta.kickoff
        all_pre = all_pre and before
        reports.append({"source": meta.source, "captured_before_kickoff": before,
                        "inventory": inventory(meta.source, raw)})
    return {
        "match_id": items[0][0].match_id,
        "five_sources_present": True,
        "capture_timing": "BEFORE_KICKOFF" if all_pre else "HISTORICAL_UNVERIFIED",
        "strict_prematch_certified": False,
        "training_ready": False,
        "decision": "AUSLASSEN",
        "blocking_reasons": [
            "SOURCE_ADAPTERS_AND_PROVENANCE_NOT_YET_VERIFIED",
            "FEATURE_REGISTRY_NOT_YET_APPROVED",
            "NO_TRAINED_VALIDATED_MODEL",
        ],
        "sources": reports,
    }
