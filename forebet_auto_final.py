from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from typing import Any, Dict, Iterable, List, Optional, Tuple

import forebet_auto_v9 as base
from forebet_auto import ACTOR_ID, CACHE_SECONDS, ForebetAutoError, _pct

_MISSING = (None, "", [], {})


def _web_pages_textcontent(urls: Iterable[str]) -> List[Dict[str, Any]]:
    token = os.environ.get("APIFY_TOKEN", "").strip()
    if not token:
        raise ForebetAutoError("APIFY_TOKEN fehlt fuer den direkten Forebet-Markt-Fallback.")

    clean_urls = list(dict.fromkeys(str(url) for url in urls if str(url).startswith("http")))
    if not clean_urls:
        return []

    page_function = (
        "async function pageFunction(context){"
        "const wait=ms=>new Promise(r=>setTimeout(r,ms));"
        "await wait(800);"
        "for(let i=0;i<4;i++){window.scrollTo(0,document.body?document.body.scrollHeight:0);await wait(250);}"
        "window.scrollTo(0,0);await wait(250);"
        "const text=document.body?(document.body.textContent||document.body.innerText||''):'';"
        "return {url:context.request.url,title:document.title,text};}"
    )
    payload = {
        "startUrls": [{"url": url} for url in clean_urls],
        "pageFunction": page_function,
        "proxyConfiguration": {"useApifyProxy": True},
        "maxPagesPerCrawl": len(clean_urls),
        "maxResultsPerCrawl": len(clean_urls),
        "linkSelector": "",
        "injectJQuery": False,
        "waitUntil": ["domcontentloaded"],
    }
    request = urllib.request.Request(
        base._WEB_ENDPOINT + "?clean=true&format=json&timeout=120",
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=135) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:500]
        raise ForebetAutoError(f"Forebet-Markt-Fallback Apify HTTP {exc.code}: {detail}") from exc
    except Exception as exc:
        raise ForebetAutoError(f"Forebet-Markt-Fallback nicht erreichbar: {exc}") from exc

    try:
        pages = json.loads(raw)
    except Exception as exc:
        raise ForebetAutoError("Forebet-Markt-Fallback lieferte kein gueltiges JSON.") from exc
    if not isinstance(pages, list):
        return []
    return [page for page in pages if isinstance(page, dict)]


def _last_section(compact: str, marker_pattern: str, limit: int = 2600) -> str:
    matches = list(re.finditer(marker_pattern, compact, re.I))
    if not matches:
        return ""
    pos = matches[-1].end()
    return compact[pos : pos + limit]


def _pair_from_section(section: str, label_pattern: str) -> Optional[Tuple[float, float]]:
    if not section:
        return None
    pattern = rf"(\d{{2,6}})({label_pattern})"
    for match in re.finditer(pattern, section, re.I):
        pair = base._split_compact(match.group(1), 2)
        if pair is not None:
            return float(pair[0]), float(pair[1])
    return None


def _direct_goal_markets(home: str, away: str, date: Optional[str], source_url: Optional[str] = None) -> Dict[str, Any]:
    links = [str(source_url)] if source_url and str(source_url).startswith("http") else base._direct_match_links(home, away)
    if not links:
        raise ForebetAutoError("Direkter Forebet-Markt-Fallback fand keinen sicheren Match-Link.")

    home_n, away_n = base._norm(home), base._norm(away)
    for page in _web_pages_textcontent(links[:2]):
        text = str(page.get("text") or "")
        title = str(page.get("title") or "")
        identity = base._norm(f"{title} {text[:18000]}")
        if home_n not in identity or away_n not in identity:
            continue
        if not base._date_matches(f"{title} {text}", date):
            continue

        compact = re.sub(r"\s+", "", text)
        out: Dict[str, Any] = {"source_url": str(page.get("url") or source_url or "")}

        # Forebet goal table is explicitly Under/Over 2.5; order is Under, Over.
        ou_section = _last_section(compact, r"Under/Over2\.5")
        ou_pair = _pair_from_section(ou_section, r"Over|Under")
        if ou_pair is None:
            # Safe global fallback: first valid football-goals pair carrying Over/Under.
            for match in re.finditer(r"(\d{2,6})(Over|Under)(\d[.,]\d{2})", compact, re.I):
                pair = base._split_compact(match.group(1), 2)
                if pair is not None:
                    ou_pair = (float(pair[0]), float(pair[1]))
                    break
        if ou_pair is not None:
            out["under"] = ou_pair[0]
            out["over"] = ou_pair[1]

        # Forebet BTTS table is explicitly No / Yes; order is No, Yes.
        btts_section = _last_section(compact, r"NoYesPred")
        btts_pair = _pair_from_section(btts_section, r"Yes|No")
        if btts_pair is None:
            for match in re.finditer(r"(\d{2,6})(Yes|No)(\d)\s*-\s*(\d)", compact, re.I):
                pair = base._split_compact(match.group(1), 2)
                if pair is not None:
                    btts_pair = (float(pair[0]), float(pair[1]))
                    break
        if btts_pair is not None:
            out["btts_no"] = btts_pair[0]
            out["btts_yes"] = btts_pair[1]

        if "over" in out or "btts_yes" in out:
            return out

    raise ForebetAutoError("Direkter Forebet-Markt-Fallback konnte Over/BTTS nicht sicher extrahieren.")


def _fill_missing(values: Dict[str, Any], source: Dict[str, Any], keys: Iterable[str]) -> None:
    for key in keys:
        if values.get(key) in _MISSING and source.get(key) not in _MISSING:
            values[key] = source.get(key)


def build_snapshot(match_id: int, home: str, away: str, date: Optional[str] = None, force: bool = False) -> Dict[str, Any]:
    item = base._pick_match(base._actor_items(force=force), home, away, date)
    values = base._resolved(item)

    direct_1x2: Dict[str, Any] = {}
    if any(values[key] in _MISSING for key in ("p1", "px", "p2", "score", "avg")):
        direct_1x2 = base._direct_1x2(home, away, date)
        _fill_missing(values, direct_1x2, ("p1", "px", "p2", "score", "avg"))

    direct_markets: Dict[str, Any] = {}
    if values["over"] in _MISSING or values["btts_yes"] in _MISSING:
        direct_markets = _direct_goal_markets(
            home,
            away,
            date,
            source_url=direct_1x2.get("source_url"),
        )
        _fill_missing(values, direct_markets, ("over", "under", "btts_yes", "btts_no"))

    p1 = _pct(values["p1"], "1")
    px = _pct(values["px"], "X")
    p2 = _pct(values["p2"], "2")
    if not 95 <= p1 + px + p2 <= 105:
        raise ForebetAutoError(f"Forebet-1X2-Summe unplausibel: {p1 + px + p2:.1f}%")

    over = _pct(values["over"], "Over 2.5")
    btts = _pct(values["btts_yes"], "BTTS Yes")

    if values["under"] not in _MISSING:
        under = _pct(values["under"], "Under 2.5")
        if not 95 <= under + over <= 105:
            raise ForebetAutoError("Forebet-Over/Under-Summe ist unplausibel.")
    if values["btts_no"] not in _MISSING:
        btts_no = _pct(values["btts_no"], "BTTS No")
        if not 95 <= btts + btts_no <= 105:
            raise ForebetAutoError("Forebet-BTTS-Summe ist unplausibel.")

    predicted = base._canonical_score(values["score"])
    avg = base._float_value(values["avg"], "Avg. Goals")
    if not 0 <= avg <= 10:
        raise ForebetAutoError("Forebet Avg. Goals liegt ausserhalb 0-10.")

    source_url = (
        direct_markets.get("source_url")
        or direct_1x2.get("source_url")
        or base._first_direct(item, ["matchUrl", "match_url", "url", "sourceUrl", "source_url"])
        or "https://www.forebet.com/"
    )
    source_parts = ["Forebet via Apify 6-in-1 actor"]
    if direct_1x2:
        source_parts.append("direct match 1X2 fallback")
    if direct_markets:
        source_parts.append("direct DOM goal-market fallback")

    return {
        "schema": "forebet-auto-v1",
        "match_id": int(match_id),
        "home_win": round(p1, 3),
        "draw": round(px, 3),
        "away_win": round(p2, 3),
        "btts_yes": round(btts, 3),
        "over_2_5": round(over, 3),
        "predicted_score": predicted,
        "average_goals": round(avg, 3),
        "source_url": source_url,
        "source": " + ".join(source_parts),
        "captured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "matched_forebet": {
            "home": item.get("home"),
            "away": item.get("away"),
            "match_date": item.get("matchDate"),
            "match_time": item.get("matchTime"),
            "league": item.get("leagueName"),
        },
    }


def debug_match(home: str, away: str, date: Optional[str] = None, force: bool = False) -> Dict[str, Any]:
    item = base._pick_match(base._actor_items(force=force), home, away, date)
    values = base._resolved(item)
    return {
        "ok": True,
        "requested": {"home": home, "away": away, "date": date},
        "matched": {
            "home": item.get("home"),
            "away": item.get("away"),
            "matchDate": item.get("matchDate"),
            "leagueName": item.get("leagueName"),
        },
        "resolved_actor": values,
    }


def health() -> Dict[str, Any]:
    return {
        "ok": True,
        "configured": bool(os.environ.get("APIFY_TOKEN", "").strip()),
        "actor": ACTOR_ID,
        "cache_seconds": CACHE_SECONDS,
        "adapter": "forebet-auto-v9-direct-first",
        "actor_primary": True,
        "direct_1x2_fallback": True,
        "direct_goal_market_fallback": True,
        "dom_textcontent": True,
        "tab_clicks": False,
        "final_adapter": True,
    }
