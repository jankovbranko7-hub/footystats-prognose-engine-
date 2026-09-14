"""Date-block splitting with one distinct match per row and label availability."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from .audit import DataError


@dataclass(frozen=True)
class MatchRow:
    match_id: int
    kickoff: datetime
    captured_at: datetime
    result_available_at: datetime


def split_matches(rows: list[MatchRow], *, train_end: datetime,
                  development_end: datetime, evaluation_as_of: datetime) -> dict:
    times = [train_end, development_end, evaluation_as_of]
    times += [t for r in rows for t in (r.kickoff, r.captured_at, r.result_available_at)]
    if any(t.tzinfo is None or t.utcoffset() is None for t in times):
        raise DataError("TIMEZONE_REQUIRED")
    if not train_end < development_end < evaluation_as_of:
        raise DataError("INVALID_SPLIT_BOUNDARIES")
    if any(type(r.match_id) is not int or r.match_id <= 0 for r in rows):
        raise DataError("INVALID_MATCH_ID")
    if len({r.match_id for r in rows}) != len(rows):
        raise DataError("DUPLICATE_MATCH_ID")
    result = {"train": [], "development": [], "test": [], "excluded": []}
    for row in sorted(rows, key=lambda r: (r.kickoff, r.match_id)):
        reason = None
        if row.captured_at >= row.kickoff:
            reason = "NOT_PREMATCH_CAPTURE"
        elif row.result_available_at <= row.kickoff:
            reason = "INVALID_RESULT_TIME"
        elif row.kickoff >= evaluation_as_of:
            reason = "OUTSIDE_EVALUATION_PERIOD"
        group = ("train" if row.kickoff < train_end else
                 "development" if row.kickoff < development_end else "test")
        cutoff = {"train": train_end, "development": development_end,
                  "test": evaluation_as_of}[group]
        if reason is None and row.result_available_at >= cutoff:
            reason = "LABEL_NOT_AVAILABLE_AT_BOUNDARY"
        if reason:
            result["excluded"].append({"match_id": row.match_id, "reason": reason})
        else:
            result[group].append(row.match_id)
    return result
