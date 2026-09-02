from __future__ import annotations

import json
import os
import re
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Iterable, List, Optional, Tuple

import forebet_auto_v3 as core
from forebet_auto import ForebetAutoError, _pct

_CACHE_SECONDS = 30 * 60
_CACHE: Dict[str, Dict[str, Any]] = {}


def _slug(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).lower()
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")


def _split_probs(digits: str, count: int) -> Optional[Tuple[float, ...]]:
    solutions: List[Tuple[int, ...]] = []

    def walk(pos: int, parts: List[int]) -> None:
        if len(parts) == count:
            if pos == len(digits) and sum(parts) == 100:
                solutions.append(tuple(parts))
            return
        remaining = count - len(parts)
        chars = len(digits) - pos
        if chars < remaining or chars > remaining * 3:
            return
        for width in (1, 2, 3):
            token = digits[pos : pos + width]
            if not token or (len(token) > 1 and token.startswith("0")):
                continue
            value = int(token)
            if not 0 <= value <= 100 or sum(parts) + value > 100:
                continue
            walk(pos + width, parts + [value])

    walk(0, [])
    unique = list(dict.fromkeys(solutions))
    if len(unique) != 1:
        return None
    return tuple(float(v) for v in unique[0])


def _apify_pages(urls: Iterable[str], *, links_only: bool) -> List[Dict[str, Any]]:
    token = os.environ.get("APIFY_TOKEN", "").strip()
    if not token:
        raise ForebetAutoError("APIFY_TOKEN fehlt fuer die automatische Forebet-Abfrage.")

    clean_urls = list(dict.fromkeys(str(u) for u in urls if str(u).startswith("http")))
    if not clean_urls:
        return []

    if links_only:
        page_function = (
            "async function pageFunction(context) {"
            " await new Promise(r => setTimeout(r, 700));"
            " const links = Array.from(document.querySelectorAll('a[href]')).map(a => "
            " ({href:a.href || '', text:(a.innerText || a.textContent || '').trim()}));"
            " return {url:context.request.url,title:document.title,links};"
            "}"
        )
    else:
        page_function = (
            "async function pageFunction(context) {"
            " await new Promise(r => setTimeout(r, 900));"
            " const body = document.body ? (document.body.textContent || document.body.innerText || '') : '';"
            " return {url:context.request.url,title:document.title,text:body};"
            "}"
        )

    payload = {
        "startUrls": [{"url": u} for u in clean_urls],
        "pageFunction": page_function,
        "proxyConfiguration": {"useApifyProxy": True},
        "maxPagesPerCrawl": len(clean_urls),
        "maxResultsPerCrawl": len(clean_urls),
        "linkSelector": "",
        "injectJQuery": False,
        "waitUntil": ["domcontentloaded"],
    }
    request = urllib.request.Request(
        core.WEB_ENDPOINT + "?clean=true&format=json&timeout=90",
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=105) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:500]
        raise ForebetAutoError(f"Forebet-Direktabruf Apify HTTP {exc.code}: {detail}") from exc
    except Exception as exc:
        raise ForebetAutoError(f"Forebet-Direktabruf nicht erreichbar: {exc}") from exc

    try:
        pages = json.loads(raw)
    except Exception as exc:
        raise ForebetAutoError("Forebet-Direktabruf lieferte kein gueltiges JSON.") from exc
    if not isinstance(pages, list):
        raise ForebetAutoError("Forebet-Direktabruf lieferte keine Seitenliste.")
    return [p for p in pages if isinstance(p, dict)]


def _team_urls(home: str) -> Tuple[List[str], List[str]]:
    raw = _slug(home)
    stripped = _slug(core._norm(home))
    bases = list(dict.fromkeys(x for x in (raw, stripped) if x))
    primary: List[str] = []
    fallback: List[str] = []
    for base in bases:
        if re.match(r"^(fc|sc|fk|afc|ac|cf|sv)-", base):
            primary.append(f"https://www.forebet.com/en/teams/{base}")
        else:
            primary.extend([
                f"https://www.forebet.com/en/teams/{base}",
                f"https://www.forebet.com/en/teams/fc-{base}",
            ])
            fallback.extend([
                f"https://www.forebet.com/en/teams/sc-{base}",
                f"https://www.forebet.com/en/teams/fk-{base}",
                f"https://www.forebet.com/en/teams/afc-{base}",
                f"https://www.forebet.com/en/teams/ac-{base}",
            ])
    return list(dict.fromkeys(primary))[:4], list(dict.fromkeys(fallback))[:8]


def _candidate_links_from_pages(pages: Iterable[Dict[str, Any]], home: str, away: str) -> List[str]:
    home_n, away_n = core._norm(home), core._norm(away)
    found: List[str] = []
    for page in pages:
        for link in page.get("links") or []:
            if not isinstance(link, dict):
                continue
            href = str(link.get("href") or "").strip()
            text = str(link.get("text") or "").strip()
            if "/football/matches/" not in href:
                continue
            if href.startswith("/"):
                href = urllib.parse.urljoin("https://www.forebet.com", href)
            hay = core._norm(f"{href} {text}")
            if home_n and away_n and home_n in hay and away_n in hay:
                found.append(href)
    return list(dict.fromkeys(found))


def _find_match_links(home: str, away: str) -> List[str]:
    primary, fallback = _team_urls(home)
    links = _candidate_links_from_pages(_apify_pages(primary, links_only=True), home, away)
    if links:
        return links[:3]
    if fallback:
        links = _candidate_links_from_pages(_apify_pages(fallback, links_only=True), home, away)
    return links[:3]


def _date_matches(text: str, date: Optional[str]) -> bool:
    key = core._date_key(date)
    if not key:
        return True
    y, m, d = key[:4], key[4:6], key[6:8]
    variants = (
        f"{y}-{m}-{d}", f"{d}/{m}/{y}", f"{d}.{m}.{y}",
        f"{m}/{d}/{y}", f"{m}.{d}.{y}",
    )
    return any(v in text for v in variants)


def _first_valid_triple(compact: str) -> Optional[Tuple[Tuple[float, float, float], re.Match[str]]]:
    for match in re.finditer(r"(\d{3,9})([12X])(\d)-(\d)(\d[.,]\d{2})", compact, re.I):
        triple = _split_probs(match.group(1), 3)
        if triple is not None:
            return triple, match
    return None


def _first_valid_pair(compact: str, labels: str) -> Optional[Tuple[Tuple[float, float], re.Match[str]]]:
    pattern = rf"(\d{{2,6}})({labels})(\d[.,]\d{{2}})?"
    for match in re.finditer(pattern, compact, re.I):
        pair = _split_probs(match.group(1), 2)
        if pair is not None:
            return pair, match
    return None


def _first_valid_btts(compact: str) -> Optional[Tuple[Tuple[float, float], re.Match[str]]]:
    for match in re.finditer(r"(\d{2,6})(Yes|No)(\d)-(\d)(\d[.,]\d{2})", compact, re.I):
        pair = _split_probs(match.group(1), 2)
        if pair is not None:
            return pair, match
    return None


def _parse_direct_page(page: Dict[str, Any], home: str, away: str, date: Optional[str]) -> Optional[Dict[str, Any]]:
    text = str(page.get("text") or "")
    title = str(page.get("title") or "")
    identity = core._norm(f"{title} {text[:16000]}")
    if core._norm(home) not in identity or core._norm(away) not in identity:
        return None
    if not _date_matches(f"{title} {text}", date):
        return None

    compact = re.sub(r"\s+", "", text)

    one = _first_valid_triple(compact)
    ou = _first_valid_pair(compact, "Over|Under")
    btts = _first_valid_btts(compact)
    if one is None or ou is None or btts is None:
        return None

    triple, one_match = one
    ou_pair, _ = ou
    btts_pair, _ = btts

    score = f"{int(one_match.group(3))}-{int(one_match.group(4))}"
    avg = float(one_match.group(5).replace(",", "."))
    if not 0 <= avg <= 10:
        return None

    return {
        "home_win": triple[0],
        "draw": triple[1],
        "away_win": triple[2],
        "over_2_5": ou_pair[1],
        "btts_yes": btts_pair[1],
        "predicted_score": score,
        "average_goals": avg,
        "source_url": str(page.get("url") or ""),
    }


def _direct_snapshot(home: str, away: str, date: Optional[str], force: bool = False) -> Dict[str, Any]:
    key = f"{core._norm(home)}|{core._norm(away)}|{core._iso_date(date)}"
    now = time.time()
    cached = _CACHE.get(key)
    if cached and not force and now - float(cached.get("at") or 0) < _CACHE_SECONDS:
        value = cached.get("value")
        if isinstance(value, dict):
            return dict(value)

    links = _find_match_links(home, away)
    if not links:
        raise ForebetAutoError("Forebet fand keinen sicheren direkten Match-Link.")

    pages = _apify_pages(links[:2], links_only=False)
    for page in pages:
        parsed = _parse_direct_page(page, home, away, date)
        if parsed:
            _CACHE[key] = {"at": now, "value": parsed}
            return dict(parsed)

    raise ForebetAutoError("Forebet-Match-Seite gefunden, aber die kompakten Prognosewerte konnten nicht sicher extrahiert werden.")


def build_snapshot(match_id: int, home: str, away: str, date: Optional[str] = None, force: bool = False) -> Dict[str, Any]:
    snap = _direct_snapshot(home, away, date, force=force)
    p1 = _pct(snap.get("home_win"), "1")
    px = _pct(snap.get("draw"), "X")
    p2 = _pct(snap.get("away_win"), "2")
    if not 95 <= p1 + px + p2 <= 105:
        raise ForebetAutoError("Forebet-1X2-Summe ist unplausibel.")
    btts = _pct(snap.get("btts_yes"), "BTTS Yes")
    over = _pct(snap.get("over_2_5"), "Over 2.5")
    predicted = str(snap.get("predicted_score") or "")
    if not re.fullmatch(r"\d{1,2}-\d{1,2}", predicted):
        raise ForebetAutoError("Forebet-Ergebnistipp ist ungueltig.")
    avg = float(snap.get("average_goals"))

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
        "source_url": snap.get("source_url"),
        "source": "Forebet public direct match page via Apify",
        "captured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "matched_forebet": {
            "home": home,
            "away": away,
            "match_date": date,
        },
    }


def debug_match(home: str, away: str, date: Optional[str] = None, force: bool = False) -> Dict[str, Any]:
    result = _direct_snapshot(home, away, date, force=force)
    return {"ok": True, "home": home, "away": away, "date": date, **result}


def health() -> Dict[str, Any]:
    return {
        "ok": True,
        "configured": bool(os.environ.get("APIFY_TOKEN", "").strip()),
        "actor": "apify~web-scraper",
        "cache_seconds": _CACHE_SECONDS,
        "adapter": "forebet-auto-v9-direct-first",
        "direct_first": True,
        "single_page_parser": True,
        "tab_clicks": False,
        "global_compact_parser": True,
    }
