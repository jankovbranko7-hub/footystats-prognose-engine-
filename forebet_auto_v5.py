from __future__ import annotations

import datetime as _dt
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Dict, Iterable, List, Optional, Tuple

# Import v4 first so the v3 core is initialized with the date-page browser adapter.
import forebet_auto_v4  # noqa: F401
import forebet_auto_v3 as core
import forebet_auto as base
from forebet_auto import ForebetAutoError

_ORIGINAL_PROBABILITY_SEQUENCE = core._probability_sequence
_ORIGINAL_SCORE_AND_AVG = core._score_and_avg
_ORIGINAL_ACTOR_VALUE = core._actor_value
_ORIGINAL_BROWSER_SNAPSHOT = core._browser_snapshot

_SCORE_ALIASES = {"predictedScore", "predicted_score", "correctScore"}

# iOS Shortcuts aborts long-running "Get Contents of URL" actions before the
# old Apify sync limits (150-255 seconds). Keep each external Forebet attempt
# short enough that the API can return a structured error instead of an iOS
# transport timeout. A second server-side repair of the same failed fixture is
# suppressed briefly so one Shortcut run never pays the slow path twice.
_FAST_APIFY_API_TIMEOUT = 10
_FAST_APIFY_SOCKET_TIMEOUT = 12
_FAILURE_CACHE_SECONDS = 60
_FAILURE_CACHE: Dict[str, Dict[str, Any]] = {}
_FAILURE_LOCK = threading.Lock()


def _failure_key(home: str, away: str, date: Optional[str]) -> str:
    return f"{core._norm(home)}|{core._norm(away)}|{core._iso_date(date) or str(date or '')}"


def _cached_failure(home: str, away: str, date: Optional[str], force: bool) -> Optional[str]:
    if force:
        return None
    key = _failure_key(home, away, date)
    now = time.time()
    with _FAILURE_LOCK:
        item = _FAILURE_CACHE.get(key)
        if not item:
            return None
        if now - float(item.get("at") or 0) >= _FAILURE_CACHE_SECONDS:
            _FAILURE_CACHE.pop(key, None)
            return None
        return str(item.get("error") or "Forebet-Automatik ist vorübergehend nicht verfügbar.")


def _remember_failure(home: str, away: str, date: Optional[str], error: Exception) -> None:
    key = _failure_key(home, away, date)
    with _FAILURE_LOCK:
        _FAILURE_CACHE[key] = {"at": time.time(), "error": str(error)}


def _clear_failure(home: str, away: str, date: Optional[str]) -> None:
    key = _failure_key(home, away, date)
    with _FAILURE_LOCK:
        _FAILURE_CACHE.pop(key, None)


def _fast_actor_items(force: bool = False) -> List[Dict[str, Any]]:
    """Actor fetch with a hard iOS-safe upper bound while preserving v1 cache."""
    token = os.environ.get("APIFY_TOKEN", "").strip()
    if not token:
        raise ForebetAutoError("APIFY_TOKEN fehlt. Fuer automatische Forebet-Abfragen muss der Token einmalig in Render gesetzt werden.")

    now = time.time()
    with base._LOCK:
        cached = base._CACHE.get("items")
        if cached is not None and not force and now - float(base._CACHE.get("at") or 0) < base.CACHE_SECONDS:
            return list(cached)

        request = urllib.request.Request(
            base.APIFY_ENDPOINT + f"?clean=true&format=json&timeout={_FAST_APIFY_API_TIMEOUT}",
            data=b"{}",
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Authorization": f"Bearer {token}",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=_FAST_APIFY_SOCKET_TIMEOUT) as response:
                payload = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:500]
            raise ForebetAutoError(f"Apify HTTP {exc.code}: {detail}") from exc
        except Exception as exc:
            raise ForebetAutoError(f"Forebet-Automatik Timeout/Netzwerkfehler: {exc}") from exc

        try:
            items = json.loads(payload)
        except Exception as exc:
            raise ForebetAutoError("Apify lieferte kein gueltiges JSON.") from exc
        if not isinstance(items, list):
            raise ForebetAutoError("Apify lieferte keine Match-Liste.")
        clean = [item for item in items if isinstance(item, dict)]
        base._CACHE["items"] = clean
        base._CACHE["at"] = now
        return list(clean)


def _fast_browser_pages(date: Optional[str], force: bool = False) -> List[Dict[str, Any]]:
    """Browser fallback with the same iOS-safe external request budget."""
    token = os.environ.get("APIFY_TOKEN", "").strip()
    if not token:
        raise ForebetAutoError("APIFY_TOKEN fehlt fuer den Forebet-Browser-Fallback.")

    urls = core._page_urls(date)
    cache_key = core._iso_date(date) or "today"
    now = time.time()
    with core._BROWSER_LOCK:
        cached = core._BROWSER_CACHE.get(cache_key)
        if (
            cached
            and not force
            and now - float(cached.get("at") or 0) < core._BROWSER_CACHE_SECONDS
            and isinstance(cached.get("pages"), list)
        ):
            return list(cached["pages"])

        page_function = (
            "async function pageFunction(context) {"
            " await new Promise(r => setTimeout(r, 1200));"
            " const body = document.body ? document.body.innerText : '';"
            " return {url: context.request.url, title: document.title, text: body};"
            "}"
        )
        payload = {
            "startUrls": [{"url": url} for url in urls.values()],
            "pageFunction": page_function,
            "proxyConfiguration": {"useApifyProxy": True},
            "maxPagesPerCrawl": len(urls),
            "maxResultsPerCrawl": len(urls),
            "linkSelector": "",
            "injectJQuery": False,
            "waitUntil": ["domcontentloaded"],
        }
        request = urllib.request.Request(
            core.WEB_ENDPOINT + f"?clean=true&format=json&timeout={_FAST_APIFY_API_TIMEOUT}",
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Authorization": f"Bearer {token}",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=_FAST_APIFY_SOCKET_TIMEOUT) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:500]
            raise ForebetAutoError(f"Forebet-Browser-Fallback Apify HTTP {exc.code}: {detail}") from exc
        except Exception as exc:
            raise ForebetAutoError(f"Forebet-Browser-Fallback Timeout/Netzwerkfehler: {exc}") from exc

        try:
            pages = json.loads(raw)
        except Exception as exc:
            raise ForebetAutoError("Forebet-Browser-Fallback lieferte kein gueltiges JSON.") from exc
        if not isinstance(pages, list):
            raise ForebetAutoError("Forebet-Browser-Fallback lieferte keine Seitenliste.")
        clean = [p for p in pages if isinstance(p, dict) and isinstance(p.get("text"), str)]
        if not clean:
            raise ForebetAutoError("Forebet-Browser-Fallback lieferte keinen Seitentext.")
        core._BROWSER_CACHE[cache_key] = {"at": now, "pages": clean}
        return list(clean)


# v5 is the execution core used by Render. Bound only its external Apify waits;
# the strict matching and probability validation remain unchanged.
core._actor_items = _fast_actor_items
core._browser_pages = _fast_browser_pages


def _split_compact_probabilities(digits: str, count: int) -> Optional[Tuple[float, ...]]:
    """Split Forebet's concatenated probabilities into a unique sum-100 tuple."""
    solutions: List[Tuple[int, ...]] = []

    def walk(pos: int, parts: List[int]) -> None:
        remaining_parts = count - len(parts)
        if remaining_parts == 0:
            if pos == len(digits) and sum(parts) == 100:
                solutions.append(tuple(parts))
            return

        remaining_chars = len(digits) - pos
        if remaining_chars < remaining_parts or remaining_chars > remaining_parts * 3:
            return

        for width in (1, 2, 3):
            end = pos + width
            if end > len(digits):
                continue
            token = digits[pos:end]
            if len(token) > 1 and token.startswith("0"):
                continue
            value = int(token)
            if not 0 <= value <= 100:
                continue
            if sum(parts) + value > 100:
                continue
            walk(end, parts + [value])

    walk(0, [])
    unique = list(dict.fromkeys(solutions))
    if len(unique) != 1:
        return None
    return tuple(float(v) for v in unique[0])


def _canonical_actor_score(value: Any) -> Optional[str]:
    """Repair actor strings such as '1-31 - 3' -> '1-3'.

    The actor sometimes concatenates the predicted score and the displayed score.
    We only repair it when both embedded scores are identical; otherwise we fail
    closed and let the browser fallback supply the value.
    """
    if value in (None, ""):
        return None

    compact = re.sub(r"\s+", "", str(value))
    normal = re.fullmatch(r"(\d{1,2})-(\d{1,2})", compact)
    if normal:
        home, away = int(normal.group(1)), int(normal.group(2))
        if 0 <= home <= 15 and 0 <= away <= 15:
            return f"{home}-{away}"

    duplicated = re.fullmatch(r"(\d{1,2})-(\d{2,4})-(\d{1,2})", compact)
    if duplicated:
        home1 = int(duplicated.group(1))
        middle = duplicated.group(2)
        away2 = int(duplicated.group(3))
        candidates: List[Tuple[int, int]] = []
        for split_at in range(1, len(middle)):
            away1 = int(middle[:split_at])
            home2 = int(middle[split_at:])
            if max(home1, away1, home2, away2) > 15:
                continue
            if home1 == home2 and away1 == away2:
                candidates.append((home1, away1))
        candidates = list(dict.fromkeys(candidates))
        if len(candidates) == 1:
            return f"{candidates[0][0]}-{candidates[0][1]}"

    return None


def _actor_value(item: Optional[Dict[str, Any]], aliases: Iterable[str]) -> Any:
    aliases_list = list(aliases)
    value = _ORIGINAL_ACTOR_VALUE(item, aliases_list)
    if any(alias in _SCORE_ALIASES for alias in aliases_list):
        return _canonical_actor_score(value)
    return value


def _fixture_windows(text: str, home: str, away: str, date: Optional[str]) -> List[List[str]]:
    """Anchor a fixture window on the actual home-team row.

    Starting several lines before the home team can include the previous fixture's
    compact probability row. That was the cause of Bay Olympic receiving Fortaleza's
    values. We start at the home-team row (plus at most one harmless league-code line).
    """
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    home_n, away_n = core._norm(home), core._norm(away)
    windows: List[List[str]] = []

    if not home_n or not away_n:
        return windows

    for i, line in enumerate(lines):
        if home_n not in core._norm(line):
            continue
        away_index: Optional[int] = None
        for j in range(i, min(len(lines), i + 4)):
            if away_n in core._norm(lines[j]):
                away_index = j
                break
        if away_index is None:
            continue
        start = max(0, i - 1)
        end = min(len(lines), away_index + 12)
        windows.append(lines[start:end])

    return windows


def _compact_score_avg_match(line: str) -> Optional[re.Match[str]]:
    # Forebet renders e.g. score 1-3 + avg 4.19 + weather 57 as "1 - 34.1957".
    # Football score digits are single-digit in this table; Avg. Goals uses 2 decimals.
    return re.search(r"(\d)\s*-\s*(\d)(\d[.,]\d{2})", line)


def _probability_sequence(window: List[str], count: int) -> Optional[Tuple[float, ...]]:
    for line in window:
        score_avg = _compact_score_avg_match(line)
        if not score_avg:
            continue
        prefix = line[: score_avg.start()]

        if count == 3:
            match = re.search(r"(\d{3,9})([12X])\s*$", prefix, re.IGNORECASE)
        elif count == 2:
            match = re.search(r"(\d{2,6})(Yes|No|Over|Under)\s*$", prefix, re.IGNORECASE)
        else:
            match = None

        if not match:
            continue
        split = _split_compact_probabilities(match.group(1), count)
        if split is not None:
            return split

    return _ORIGINAL_PROBABILITY_SEQUENCE(window, count)


def _score_and_avg(window: List[str]) -> Tuple[Optional[str], Optional[float]]:
    for line in window:
        match = _compact_score_avg_match(line)
        if not match:
            continue
        score = f"{int(match.group(1))}-{int(match.group(2))}"
        try:
            avg = float(match.group(3).replace(",", "."))
        except Exception:
            continue
        if 0 <= avg <= 10:
            return score, avg
    return _ORIGINAL_SCORE_AND_AVG(window)


def _browser_snapshot(home: str, away: str, date: Optional[str], force: bool = False) -> Dict[str, Any]:
    """Try the requested date page, then today's broader Forebet pages for same-day games.

    Some competitions are omitted from the first DOM batch of Forebet's date pages,
    while the same fixture is present on the public Today pages. This retry is only
    allowed when the requested date is actually today, so historical/future matches
    are never silently substituted with a different date.
    """
    try:
        return _ORIGINAL_BROWSER_SNAPSHOT(home, away, date, force=force)
    except ForebetAutoError as first_error:
        iso = core._iso_date(date)
        today = _dt.datetime.now(_dt.timezone.utc).date().isoformat()
        if iso != today:
            raise
        try:
            result = _ORIGINAL_BROWSER_SNAPSHOT(home, away, None, force=True)
            result["matchDate"] = date
            result["_same_day_today_fallback"] = True
            return result
        except ForebetAutoError as second_error:
            raise ForebetAutoError(
                f"Datumseite ohne Treffer ({first_error}); Today-Fallback ebenfalls ohne Treffer ({second_error})."
            ) from second_error


# Install the strict repairs into the v3 execution core used by build_snapshot().
core._actor_value = _actor_value
core._fixture_windows = _fixture_windows
core._probability_sequence = _probability_sequence
core._score_and_avg = _score_and_avg
core._browser_snapshot = _browser_snapshot


def build_snapshot(match_id: int, home: str, away: str, date: Optional[str] = None, force: bool = False) -> Dict[str, Any]:
    cached_error = _cached_failure(home, away, date, force)
    if cached_error is not None:
        raise ForebetAutoError(cached_error)
    try:
        result = core.build_snapshot(match_id=match_id, home=home, away=away, date=date, force=force)
    except ForebetAutoError as exc:
        _remember_failure(home, away, date, exc)
        raise
    _clear_failure(home, away, date)
    return result


def debug_match(home: str, away: str, date: Optional[str] = None, force: bool = False) -> Dict[str, Any]:
    return core.debug_match(home=home, away=away, date=date, force=force)


def health() -> Dict[str, Any]:
    result = dict(core.health())
    result["adapter"] = "forebet-auto-v5.3-ios-bounded"
    result["apify_api_timeout_seconds"] = _FAST_APIFY_API_TIMEOUT
    result["apify_socket_timeout_seconds"] = _FAST_APIFY_SOCKET_TIMEOUT
    result["failure_cache_seconds"] = _FAILURE_CACHE_SECONDS
    return result
