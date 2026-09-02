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
    _match_score,
    _norm,
    _pct,
)

WEB_ACTOR_ID = "apify~web-scraper"
WEB_ENDPOINT = f"https://api.apify.com/v2/acts/{WEB_ACTOR_ID}/run-sync-get-dataset-items"
_BROWSER_CACHE_SECONDS = 30 * 60
_BROWSER_CACHE: Dict[str, Any] = {"at": 0.0, "pages": None}
_BROWSER_LOCK = threading.Lock()

_PAGE_URLS = {
    "1x2_today": "https://www.forebet.com/en/football-tips-and-predictions-for-today",
    "1x2_tomorrow": "https://www.forebet.com/en/football-tips-and-predictions-for-tomorrow",
    "btts_today": "https://www.forebet.com/en/football-tips-and-predictions-for-today/predictions-both-to-score",
    "btts_tomorrow": "https://www.forebet.com/en/football-tips-and-predictions-for-tomorrow/both-to-score",
    "btts_all": "https://www.forebet.com/en/component/forebet/bothtoscore",
    "ou_today": "https://www.forebet.com/en/football-tips-and-predictions-for-today/predictions-under-over-goals/by-league",
    "ou_tomorrow": "https://www.forebet.com/en/football-tips-and-predictions-for-tomorrow/under-over-25-goals/by-league",
    "ou_all": "https://www.forebet.com/en/component/forebet/under-over",
}


def _first(item: Dict[str, Any], aliases: Iterable[str]) -> Any:
    for key in aliases:
        value = item.get(key)
        if value not in (None, "", [], {}):
            return value
    return None


def _date_key(value: Any) -> str:
    digits = re.sub(r"[^0-9]", "", str(value or ""))
    if len(digits) != 8:
        return ""
    if digits[:4].isdigit() and 1900 <= int(digits[:4]) <= 2200:
        return digits
    if digits[-4:].isdigit() and 1900 <= int(digits[-4:]) <= 2200:
        return digits[-4:] + digits[2:4] + digits[:2]
    return digits


def _same_fixture(candidate: Dict[str, Any], best: Dict[str, Any], requested_date: Optional[str]) -> bool:
    if _norm(candidate.get("home")) != _norm(best.get("home")):
        return False
    if _norm(candidate.get("away")) != _norm(best.get("away")):
        return False

    wanted = _date_key(requested_date)
    cand_date = _date_key(candidate.get("matchDate"))
    best_date = _date_key(best.get("matchDate"))
    if wanted and cand_date and cand_date != wanted:
        return False
    if wanted and best_date and best_date != wanted:
        return False
    if not wanted and cand_date and best_date and cand_date != best_date:
        return False
    return True


def _merge_rows(rows: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    merged: Dict[str, Any] = {}
    source_fields: set[str] = set()
    row_count = 0
    for row in rows:
        row_count += 1
        for key, value in row.items():
            if value not in (None, "", [], {}):
                source_fields.add(str(key))
                if merged.get(key) in (None, "", [], {}):
                    merged[key] = value
    merged["_merged_row_count"] = row_count
    merged["_available_fields"] = sorted(source_fields)
    return merged


def select_match_merged(items: Iterable[Dict[str, Any]], home: str, away: str, date: Optional[str] = None) -> Dict[str, Any]:
    ranked: List[Tuple[float, float, float, float, Dict[str, Any]]] = []
    all_items = [item for item in items if isinstance(item, dict)]
    for item in all_items:
        score, hs, aw = _match_score(item, home, away, date)
        ranked.append((score, min(hs, aw), hs, aw, item))

    if not ranked:
        raise ForebetAutoError("Forebet lieferte keine Spiele.")

    ranked.sort(key=lambda row: (row[0], row[1]), reverse=True)
    score, minimum, hs, aw, best = ranked[0]
    if minimum < 0.62 or score < 0.70:
        raise ForebetAutoError(
            "Kein Forebet-Spiel konnte sicher zugeordnet werden. "
            f"Bester Treffer: {best.get('home')} - {best.get('away')} "
            f"(Home {hs:.2f}, Away {aw:.2f})."
        )

    same_rows = [item for item in all_items if _same_fixture(item, best, date)]
    merged = _merge_rows(same_rows or [best])

    for other_score, _, _, _, other in ranked[1:]:
        if _same_fixture(other, best, date):
            continue
        if other_score > score - 0.035:
            raise ForebetAutoError(
                "Forebet-Zuordnung ist mehrdeutig: "
                f"{best.get('home')} - {best.get('away')} / "
                f"{other.get('home')} - {other.get('away')}."
            )
        break

    for key in ("home", "away", "matchDate", "matchTime", "leagueName"):
        if merged.get(key) in (None, "") and best.get(key) not in (None, ""):
            merged[key] = best.get(key)
    return merged


def _browser_pages(force: bool = False) -> List[Dict[str, Any]]:
    token = os.environ.get("APIFY_TOKEN", "").strip()
    if not token:
        raise ForebetAutoError("APIFY_TOKEN fehlt fuer den Forebet-Browser-Fallback.")

    now = time.time()
    with _BROWSER_LOCK:
        cached = _BROWSER_CACHE.get("pages")
        if cached is not None and not force and now - float(_BROWSER_CACHE.get("at") or 0) < _BROWSER_CACHE_SECONDS:
            return list(cached)

        page_function = (
            "async function pageFunction(context) {"
            " const body = document.body ? document.body.innerText : '';"
            " return {url: context.request.url, title: document.title, text: body};"
            "}"
        )
        payload = {
            "startUrls": [{"url": url} for url in _PAGE_URLS.values()],
            "pageFunction": page_function,
            "proxyConfiguration": {"useApifyProxy": True},
            "maxPagesPerCrawl": len(_PAGE_URLS),
            "maxResultsPerCrawl": len(_PAGE_URLS),
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
        _BROWSER_CACHE["pages"] = clean
        _BROWSER_CACHE["at"] = now
        return list(clean)


def _date_variants(date: Optional[str]) -> List[str]:
    if not date:
        return []
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
        preview = " ".join(lines[i:i + 4])
        preview_n = _norm(preview)
        if home_n and away_n and home_n in preview_n and away_n in preview_n:
            window = lines[max(0, i - 1):min(len(lines), i + 12)]
            joined = " ".join(window)
            if date_tokens and not any(token in joined for token in date_tokens):
                if _norm(lines[i]) != _norm(f"{home} {away}"):
                    continue
            windows.append(window)
    return windows


def _probability_pair(window: List[str]) -> Optional[Tuple[float, float]]:
    for line in window[1:8]:
        nums = [int(x) for x in re.findall(r"(?<!\d)(\d{1,3})(?!\d)", line)]
        if len(nums) == 2 and all(0 <= n <= 100 for n in nums) and 95 <= sum(nums) <= 105:
            return float(nums[0]), float(nums[1])
    return None


def _probability_triple(window: List[str]) -> Optional[Tuple[float, float, float]]:
    for line in window[1:8]:
        nums = [int(x) for x in re.findall(r"(?<!\d)(\d{1,3})(?!\d)", line)]
        if len(nums) == 3 and all(0 <= n <= 100 for n in nums) and 95 <= sum(nums) <= 105:
            return float(nums[0]), float(nums[1]), float(nums[2])
    return None


def _score_and_avg(window: List[str]) -> Tuple[Optional[str], Optional[float]]:
    score: Optional[str] = None
    avg: Optional[float] = None
    for line in window[1:10]:
        if score is None:
            m = re.search(r"(?<!\d)(\d{1,2})\s*-\s*(\d{1,2})(?!\d)", line)
            if m:
                score = f"{m.group(1)}-{m.group(2)}"
                continue
        if score is not None and avg is None:
            m = re.fullmatch(r"(\d{1,2}(?:[.,]\d{1,3}))", line)
            if m:
                try:
                    avg = float(m.group(1).replace(",", "."))
                except Exception:
                    pass
                if avg is not None:
                    break
    return score, avg


def _page_kind(url: str) -> str:
    low = url.lower()
    if "both-to-score" in low or "bothtoscore" in low:
        return "btts"
    if "under-over" in low:
        return "ou"
    return "1x2"


def _browser_snapshot(home: str, away: str, date: Optional[str], force: bool = False) -> Dict[str, Any]:
    pages = _browser_pages(force=force)
    out: Dict[str, Any] = {
        "home": home,
        "away": away,
        "matchDate": date,
        "_browser_sources": [],
    }
    found_any = False
    for page in pages:
        url = str(page.get("url") or "")
        kind = _page_kind(url)
        windows = _fixture_windows(str(page.get("text") or ""), home, away, date)
        if not windows:
            continue
        found_any = True
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

    if not found_any:
        raise ForebetAutoError("Forebet-Browser-Fallback fand das Spiel auf keiner Forebet-Liste.")
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

    p1 = _pct(p1_raw if p1_raw not in (None, "") else browser.get("home_win"), "1")
    px = _pct(px_raw if px_raw not in (None, "") else browser.get("draw"), "X")
    p2 = _pct(p2_raw if p2_raw not in (None, "") else browser.get("away_win"), "2")
    total = p1 + px + p2
    if not 95 <= total <= 105:
        raise ForebetAutoError(f"Forebet-1X2-Summe unplausibel: {total:.1f}%")

    btts_yes = _pct(btts_raw if btts_raw not in (None, "") else browser.get("btts_yes"), "BTTS Yes")
    over25 = _pct(over_raw if over_raw not in (None, "") else browser.get("over_2_5"), "Over 2.5")

    predicted = str(predicted_raw if predicted_raw not in (None, "") else browser.get("predicted_score") or "").strip().replace(" ", "")
    if not re.fullmatch(r"\d{1,2}[-:]\d{1,2}", predicted):
        raise ForebetAutoError("Forebet-Ergebnistipp fehlt oder ist ungueltig.")
    predicted = predicted.replace(":", "-")

    avg_source = avg_raw if avg_raw not in (None, "") else browser.get("average_goals")
    try:
        avg_goals = float(str(avg_source).replace(",", "."))
    except Exception as exc:
        raise ForebetAutoError("Forebet Avg. Goals fehlt oder ist ungueltig.") from exc

    actor_fields = set(actor_item.get("_available_fields") or []) if actor_item else set()
    sources = list(dict.fromkeys((browser or {}).get("_browser_sources") or []))
    return {
        "schema": "forebet-auto-v3",
        "match_id": int(match_id),
        "home_win": round(p1, 3),
        "draw": round(px, 3),
        "away_win": round(p2, 3),
        "btts_yes": round(btts_yes, 3),
        "over_2_5": round(over25, 3),
        "predicted_score": predicted,
        "average_goals": round(avg_goals, 3),
        "source_url": "https://www.forebet.com/",
        "source": "Forebet public prediction via Apify actor with browser fallback",
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
    browser: Optional[Dict[str, Any]] = None
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
        "actor": {
            "matched": bool(actor_item),
            "values": safe_values,
        },
        "browser": browser,
    }


def health() -> Dict[str, Any]:
    from forebet_auto import health as base_health
    result = dict(base_health())
    result["adapter"] = "forebet-auto-v3"
    result["browser_fallback_actor"] = WEB_ACTOR_ID
    result["browser_cache_seconds"] = _BROWSER_CACHE_SECONDS
    return result
