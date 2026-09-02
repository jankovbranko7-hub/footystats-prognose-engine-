from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Dict, Iterable, List, Optional, Tuple

from forebet_auto import (
    ACTOR_ID,
    CACHE_SECONDS,
    ForebetAutoError,
    _actor_items,
    _norm,
    _pct,
)
from forebet_auto_v2 import _first, select_match_merged

WEB_ACTOR_ID = "apify~web-scraper"
WEB_ENDPOINT = f"https://api.apify.com/v2/acts/{WEB_ACTOR_ID}/run-sync-get-dataset-items"
_BROWSER_CACHE_SECONDS = 30 * 60
_BROWSER_CACHE: Dict[str, Dict[str, Any]] = {}
_BROWSER_LOCK = threading.Lock()


def _date_key(value: Any) -> str:
    digits = re.sub(r"[^0-9]", "", str(value or ""))
    if len(digits) != 8:
        return ""
    if digits[:4].isdigit() and 1900 <= int(digits[:4]) <= 2200:
        return digits
    if digits[-4:].isdigit() and 1900 <= int(digits[-4:]) <= 2200:
        return digits[-4:] + digits[2:4] + digits[:2]
    return ""


def _iso_date(value: Any) -> str:
    key = _date_key(value)
    if len(key) != 8:
        return ""
    return f"{key[:4]}-{key[4:6]}-{key[6:8]}"


def _page_urls(date: Optional[str]) -> Dict[str, str]:
    iso = _iso_date(date)
    if iso:
        return {
            "1x2": f"https://www.forebet.com/en/football-predictions/predictions-1x2/{iso}",
            "btts": f"https://www.forebet.com/en/football-predictions/both-to-score/{iso}",
            "ou": f"https://www.forebet.com/en/football-predictions/under-over-25-goals/{iso}",
        }
    return {
        "1x2": "https://www.forebet.com/en/football-tips-and-predictions-for-today",
        "btts": "https://www.forebet.com/en/football-tips-and-predictions-for-today/both-to-score",
        "ou": "https://www.forebet.com/en/football-tips-and-predictions-for-today/under-over-25-goals",
    }


def _browser_pages(date: Optional[str], force: bool = False) -> List[Dict[str, Any]]:
    token = os.environ.get("APIFY_TOKEN", "").strip()
    if not token:
        raise ForebetAutoError("APIFY_TOKEN fehlt fuer den Forebet-Browser-Fallback.")

    urls = _page_urls(date)
    cache_key = _iso_date(date) or "today"
    now = time.time()
    with _BROWSER_LOCK:
        cached = _BROWSER_CACHE.get(cache_key)
        if (
            cached
            and not force
            and now - float(cached.get("at") or 0) < _BROWSER_CACHE_SECONDS
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
            WEB_ENDPOINT + "?clean=true&format=json&timeout=240",
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Authorization": f"Bearer {token}",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=255) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:500]
            raise ForebetAutoError(f"Forebet-Browser-Fallback Apify HTTP {exc.code}: {detail}") from exc
        except Exception as exc:
            raise ForebetAutoError(f"Forebet-Browser-Fallback nicht erreichbar: {exc}") from exc

        try:
            pages = json.loads(raw)
        except Exception as exc:
            raise ForebetAutoError("Forebet-Browser-Fallback lieferte kein gueltiges JSON.") from exc
        if not isinstance(pages, list):
            raise ForebetAutoError("Forebet-Browser-Fallback lieferte keine Seitenliste.")
        clean = [p for p in pages if isinstance(p, dict) and isinstance(p.get("text"), str)]
        if not clean:
            raise ForebetAutoError("Forebet-Browser-Fallback lieferte keinen Seitentext.")
        _BROWSER_CACHE[cache_key] = {"at": now, "pages": clean}
        return list(clean)


def _date_variants(date: Optional[str]) -> List[str]:
    key = _date_key(date)
    if len(key) != 8:
        return []
    y, m, d = key[:4], key[4:6], key[6:8]
    return [f"{y}-{m}-{d}", f"{d}/{m}/{y}", f"{d}.{m}.{y}"]


def _fixture_windows(text: str, home: str, away: str, date: Optional[str]) -> List[List[str]]:
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    home_n, away_n = _norm(home), _norm(away)
    date_tokens = _date_variants(date)
    windows: List[List[str]] = []

    for i in range(len(lines)):
        # Forebet sometimes renders home / away / date in separate DOM lines.
        preview = " ".join(lines[i : i + 8])
        preview_n = _norm(preview)
        if not (home_n and away_n and home_n in preview_n and away_n in preview_n):
            continue
        window = lines[max(0, i - 2) : min(len(lines), i + 24)]
        joined = " ".join(window)
        if date_tokens and not any(token in joined for token in date_tokens):
            continue
        windows.append(window)
    return windows


def _line_numbers(line: str) -> List[int]:
    # Remove date and clock tokens first, so 02/09/2026 and 09:15 cannot masquerade as probabilities.
    cleaned = re.sub(r"\b\d{1,2}[./-]\d{1,2}[./-]\d{4}\b", " ", line)
    cleaned = re.sub(r"\b\d{4}-\d{1,2}-\d{1,2}\b", " ", cleaned)
    cleaned = re.sub(r"\b\d{1,2}:\d{2}\b", " ", cleaned)
    return [int(x) for x in re.findall(r"(?<![\d.])(\d{1,3})(?![\d.])", cleaned)]


def _probability_sequence(window: List[str], count: int) -> Optional[Tuple[float, ...]]:
    # Case A: probabilities are on one line (e.g. "15 11 74").
    for line in window:
        nums = _line_numbers(line)
        if len(nums) == count and all(0 <= n <= 100 for n in nums) and 95 <= sum(nums) <= 105:
            return tuple(float(n) for n in nums)

    # Case B: mobile/JS DOM splits probabilities into one number per line.
    standalone: List[int] = []
    for line in window:
        stripped = line.strip().replace("%", "").strip()
        if re.fullmatch(r"\d{1,3}", stripped):
            number = int(stripped)
            if 0 <= number <= 100:
                standalone.append(number)
                if len(standalone) >= count:
                    for start in range(max(0, len(standalone) - count - 3), len(standalone) - count + 1):
                        chunk = standalone[start : start + count]
                        if len(chunk) == count and 95 <= sum(chunk) <= 105:
                            return tuple(float(n) for n in chunk)
        elif standalone:
            # Keep short runs only; unrelated sections should not combine.
            if len(standalone) > count + 3:
                standalone = standalone[-(count + 2) :]
    return None


def _probability_pair(window: List[str]) -> Optional[Tuple[float, float]]:
    result = _probability_sequence(window, 2)
    if result is None:
        return None
    return float(result[0]), float(result[1])


def _probability_triple(window: List[str]) -> Optional[Tuple[float, float, float]]:
    result = _probability_sequence(window, 3)
    if result is None:
        return None
    return float(result[0]), float(result[1]), float(result[2])


def _score_and_avg(window: List[str]) -> Tuple[Optional[str], Optional[float]]:
    score: Optional[str] = None
    avg: Optional[float] = None
    for line in window:
        if score is None:
            m = re.search(r"(?<!\d)(\d{1,2})\s*-\s*(\d{1,2})(?!\d)", line)
            if m:
                score = f"{m.group(1)}-{m.group(2)}"
                continue
        if avg is None:
            # Avg goals is decimal on Forebet; weather/odds are filtered by requiring a bare decimal line.
            m = re.fullmatch(r"(\d{1,2}(?:[.,]\d{1,3}))", line.strip())
            if m:
                try:
                    candidate = float(m.group(1).replace(",", "."))
                except Exception:
                    continue
                if 0 <= candidate <= 10:
                    avg = candidate
        if score is not None and avg is not None:
            break
    return score, avg


def _page_kind(url: str) -> str:
    low = url.lower()
    if "both-to-score" in low:
        return "btts"
    if "under-over-25-goals" in low:
        return "ou"
    return "1x2"


def _browser_snapshot(home: str, away: str, date: Optional[str], force: bool = False) -> Dict[str, Any]:
    pages = _browser_pages(date=date, force=force)
    out: Dict[str, Any] = {
        "home": home,
        "away": away,
        "matchDate": date,
        "_browser_sources": [],
    }
    matched_pages = 0

    for page in pages:
        url = str(page.get("url") or "")
        kind = _page_kind(url)
        windows = _fixture_windows(str(page.get("text") or ""), home, away, date)
        if not windows:
            continue
        matched_pages += 1
        for window in windows:
            if kind == "1x2" and "home_win" not in out:
                triple = _probability_triple(window)
                if triple:
                    out["home_win"], out["draw"], out["away_win"] = triple
                    score, avg = _score_and_avg(window)
                    if score is not None:
                        out["predicted_score"] = score
                    if avg is not None:
                        out["average_goals"] = avg
                    out["_browser_sources"].append(url)
                    break
            elif kind == "btts" and "btts_yes" not in out:
                pair = _probability_pair(window)
                if pair:
                    out["btts_yes"] = pair[1]
                    out["_browser_sources"].append(url)
                    break
            elif kind == "ou" and "over_2_5" not in out:
                pair = _probability_pair(window)
                if pair:
                    out["over_2_5"] = pair[1]
                    out["_browser_sources"].append(url)
                    break

    if matched_pages == 0:
        raise ForebetAutoError("Forebet-Browser-Fallback fand das Spiel auf keiner datumsspezifischen Forebet-Seite.")
    return out


def _actor_snapshot(home: str, away: str, date: Optional[str], force: bool = False) -> Optional[Dict[str, Any]]:
    try:
        return select_match_merged(_actor_items(force=force), home, away, date)
    except ForebetAutoError:
        return None


def _actor_value(item: Optional[Dict[str, Any]], aliases: Iterable[str]) -> Any:
    if not item:
        return None
    return _first(item, aliases)


def build_snapshot(match_id: int, home: str, away: str, date: Optional[str] = None, force: bool = False) -> Dict[str, Any]:
    actor_item = _actor_snapshot(home, away, date, force=force)
    browser: Optional[Dict[str, Any]] = None

    p1_raw = _actor_value(actor_item, ["probability_1_percent", "probability1Percent", "homeProbability", "predictionHome"])
    px_raw = _actor_value(actor_item, ["probability_X_percent", "probability_x_percent", "probabilityXPercent", "drawProbability", "predictionDraw"])
    p2_raw = _actor_value(actor_item, ["probability_2_percent", "probability2Percent", "awayProbability", "predictionAway"])
    btts_raw = _actor_value(actor_item, [
        "probability_btts_yes_percent",
        "probability_BTTS_yes_percent",
        "probabilityBttsYesPercent",
        "btts_yes_percent",
        "bttsYesPercent",
    ])
    over_raw = _actor_value(actor_item, [
        "probability_over_percent",
        "probability_over_2_5_percent",
        "probabilityOverPercent",
        "over25Percent",
    ])
    predicted_raw = _actor_value(actor_item, ["predictedScore", "predicted_score", "correctScore"])
    avg_raw = _actor_value(actor_item, ["averageGoals", "average_goals", "avgGoals"])

    if None in (p1_raw, px_raw, p2_raw, btts_raw, over_raw, predicted_raw, avg_raw):
        browser = _browser_snapshot(home, away, date, force=force)

    def browser_value(key: str) -> Any:
        return (browser or {}).get(key)

    p1 = _pct(p1_raw if p1_raw not in (None, "") else browser_value("home_win"), "1")
    px = _pct(px_raw if px_raw not in (None, "") else browser_value("draw"), "X")
    p2 = _pct(p2_raw if p2_raw not in (None, "") else browser_value("away_win"), "2")
    total = p1 + px + p2
    if not 95 <= total <= 105:
        raise ForebetAutoError(f"Forebet-1X2-Summe unplausibel: {total:.1f}%")

    btts_yes = _pct(btts_raw if btts_raw not in (None, "") else browser_value("btts_yes"), "BTTS Yes")
    over25 = _pct(over_raw if over_raw not in (None, "") else browser_value("over_2_5"), "Over 2.5")

    predicted = str(
        predicted_raw if predicted_raw not in (None, "") else browser_value("predicted_score") or ""
    ).strip().replace(" ", "")
    if not re.fullmatch(r"\d{1,2}[-:]\d{1,2}", predicted):
        raise ForebetAutoError("Forebet-Ergebnistipp fehlt oder ist ungueltig.")
    predicted = predicted.replace(":", "-")

    avg_source = avg_raw if avg_raw not in (None, "") else browser_value("average_goals")
    try:
        avg_goals = float(str(avg_source).replace(",", "."))
    except Exception as exc:
        raise ForebetAutoError("Forebet Avg. Goals fehlt oder ist ungueltig.") from exc

    actor_fields = set(actor_item.get("_available_fields") or []) if actor_item else set()
    sources = list(dict.fromkeys((browser or {}).get("_browser_sources") or []))
    return {
        "schema": "forebet-auto-v4",
        "match_id": int(match_id),
        "home_win": round(p1, 3),
        "draw": round(px, 3),
        "away_win": round(p2, 3),
        "btts_yes": round(btts_yes, 3),
        "over_2_5": round(over25, 3),
        "predicted_score": predicted,
        "average_goals": round(avg_goals, 3),
        "source_url": "https://www.forebet.com/",
        "source": "Forebet public prediction via Apify actor with date-specific browser fallback",
        "captured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "matched_forebet": {
            "home": actor_item.get("home") if actor_item else home,
            "away": actor_item.get("away") if actor_item else away,
            "match_date": actor_item.get("matchDate") if actor_item else date,
            "match_time": actor_item.get("matchTime") if actor_item else None,
            "league": actor_item.get("leagueName") if actor_item else None,
            "merged_rows": actor_item.get("_merged_row_count", 0) if actor_item else 0,
            "actor_fields": sorted(actor_fields),
            "browser_fallback": bool(browser),
            "browser_sources": sources,
        },
    }


def debug_match(home: str, away: str, date: Optional[str] = None, force: bool = False) -> Dict[str, Any]:
    actor_item = _actor_snapshot(home, away, date, force=force)
    browser: Dict[str, Any]
    try:
        browser = _browser_snapshot(home, away, date, force=force)
    except ForebetAutoError as exc:
        browser = {"error": str(exc)}
    safe_values: Dict[str, Any] = {}
    if actor_item:
        for key in actor_item.get("_available_fields") or []:
            value = actor_item.get(key)
            if isinstance(value, (str, int, float, bool)) and len(str(value)) <= 160:
                safe_values[key] = value
    return {
        "ok": True,
        "home": home,
        "away": away,
        "date": date,
        "actor": {"matched": bool(actor_item), "values": safe_values},
        "browser": browser,
    }


def health() -> Dict[str, Any]:
    return {
        "ok": True,
        "configured": bool(os.environ.get("APIFY_TOKEN", "").strip()),
        "actor": ACTOR_ID,
        "cache_seconds": CACHE_SECONDS,
        "adapter": "forebet-auto-v4-date-pages",
        "browser_fallback_actor": WEB_ACTOR_ID,
        "browser_cache_seconds": _BROWSER_CACHE_SECONDS,
    }
