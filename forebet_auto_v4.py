from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

import forebet_auto_v3 as core


def _fixture_windows(text: str, home: str, away: str, date: Optional[str]) -> List[List[str]]:
    """Find fixture rows on a date-specific Forebet page.

    The requested date is already encoded in the page URL. Forebet prints that date
    in the page heading, not in every match row, so requiring the date inside the
    local match window incorrectly discards valid fixtures.
    """
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    home_n, away_n = core._norm(home), core._norm(away)
    windows: List[List[str]] = []

    for i in range(len(lines)):
        preview = " ".join(lines[i : i + 10])
        preview_n = core._norm(preview)
        if home_n and away_n and home_n in preview_n and away_n in preview_n:
            windows.append(lines[max(0, i - 3) : min(len(lines), i + 30)])
    return windows


# Patch only the row-window finder; all strict probability validation remains in v3.
core._fixture_windows = _fixture_windows


def build_snapshot(match_id: int, home: str, away: str, date: Optional[str] = None, force: bool = False) -> Dict[str, Any]:
    return core.build_snapshot(match_id=match_id, home=home, away=away, date=date, force=force)


def debug_match(home: str, away: str, date: Optional[str] = None, force: bool = False) -> Dict[str, Any]:
    return core.debug_match(home=home, away=away, date=date, force=force)


def health() -> Dict[str, Any]:
    result = dict(core.health())
    result["adapter"] = "forebet-auto-v4-match-window"
    return result
