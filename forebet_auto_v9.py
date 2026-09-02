from __future__ import annotations

from typing import Any, Dict, Optional

# V8 supplies tab-click parsing; V6 supplies direct-link discovery + caches.
import forebet_auto_v8 as v8
import forebet_auto_v6 as v6
import forebet_auto_v3 as core
from forebet_auto import ForebetAutoError

# Keep the original list-browser snapshot only as a fallback.
_LIST_BROWSER_SNAPSHOT = v6._ORIGINAL_BROWSER_SNAPSHOT


def _browser_snapshot_direct_first(home: str, away: str, date: Optional[str], force: bool = False) -> Dict[str, Any]:
    """Try the direct Forebet match page first, then fall back to legacy date/today pages.

    The previous order could spend several minutes on list pages before the direct
    match-page route was attempted. V9 reverses that order so normal requests stay
    inside the client timeout while preserving the old path as a safety net.
    """
    try:
        return v6._direct_match_snapshot(home, away, date, force=force)
    except ForebetAutoError as direct_error:
        try:
            return _LIST_BROWSER_SNAPSHOT(home, away, date, force=force)
        except ForebetAutoError as list_error:
            raise ForebetAutoError(
                f"Direkter Match-Pfad: {direct_error} Listen-Fallback: {list_error}"
            ) from list_error


# v5/v7/v8 resolve core._browser_snapshot dynamically at runtime.
core._browser_snapshot = _browser_snapshot_direct_first


def build_snapshot(match_id: int, home: str, away: str, date: Optional[str] = None, force: bool = False) -> Dict[str, Any]:
    return v8.build_snapshot(match_id=match_id, home=home, away=away, date=date, force=force)


def debug_match(home: str, away: str, date: Optional[str] = None, force: bool = False) -> Dict[str, Any]:
    return v8.debug_match(home=home, away=away, date=date, force=force)


def health() -> Dict[str, Any]:
    result = dict(v8.health())
    result["adapter"] = "forebet-auto-v9-direct-first"
    result["direct_first"] = True
    return result
