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

# Import v5 first so its strict compact-DOM parsers are installed in v3.
import forebet_auto_v5 as v5
import forebet_auto_v3 as core
from forebet_auto import ForebetAutoError

_ORIGINAL_BROWSER_SNAPSHOT = core._browser_snapshot
_DIRECT_CACHE_SECONDS = 30 * 60
_DIRECT_CACHE: Dict[str, Dict[str, Any]] = {}


def _slug(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text


def _team_page_urls(name: str) -> List[str]:
    raw = _slug(name)
    normalized = _slug(core._norm(name))
    bases: List[str] = []
    for base in (raw, normalized):
        if base and base not in bases:
            bases.append(base)
    variants: List[str] = []
    for base in bases:
        candidates = [base]
        if not re.match(r"^(fc|sc|fk|afc|ac|cf|sv)-", base):
            candidates += [f"fc-{base}", f"sc-{base}", f"fk-{base}", f"afc-{base}"]
        for candidate in candidates:
            url = f"https://www.forebet.com/en/teams/{candidate}"
            if url not in variants:
                variants.append(url)
    return variants[:8]


def _run_web_pages(urls: Iterable[str], *, include_links: bool = False) -> List[Dict[str, Any]]:
    token = os.environ.get("APIFY_TOKEN", "").strip()
    if not token:
        raise ForebetAutoError("APIFY_TOKEN fehlt fuer den direkten Forebet-Match-Fallback.")

    clean_urls = list(dict.fromkeys(str(url) for url in urls if str(url).startswith("http")))
    if not clean_urls:
        return []

    links_js = (
        "const links = Array.from(document.querySelectorAll('a[href]')).map(a => "
        "({href:a.href || '', text:(a.innerText || a.textContent || '').trim()}));"
        if include_links
        else "const links = [];"
    )
    page_function = (
        "async function pageFunction(context) {"
        " await new Promise(r => setTimeout(r, 900));"
        " for (let i=0; i<8; i++) {"
        "   window.scrollTo(0, document.body ? document.body.scrollHeight : 0);"
        "   await new Promise(r => setTimeout(r, 350));"
        " }"
        " window.scrollTo(0, 0);"
        " await new Promise(r => setTimeout(r, 400));"
        f" {links_js}"
        " const body = document.body ? document.body.innerText : '';"
        " return {url: context.request.url, title: document.title, text: body, links};"
        "}"
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
        core.WEB_ENDPOINT + "?clean=true&format=json&timeout=240",
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
        raise ForebetAutoError(f"Direkter Forebet-Fallback Apify HTTP {exc.code}: {detail}") from exc
    except Exception as exc:
        raise ForebetAutoError(f"Direkter Forebet-Fallback nicht erreichbar: {exc}") from exc

    try:
        pages = json.loads(raw)
    except Exception as exc:
        raise ForebetAutoError("Direkter Forebet-Fallback lieferte kein gueltiges JSON.") from exc
    if not isinstance(pages, list):
        return []
    return [page for page in pages if isinstance(page, dict)]


def _candidate_match_links(home: str, away: str) -> List[str]:
    pages = _run_web_pages(_team_page_urls(home) + _team_page_urls(away), include_links=True)
    home_n = core._norm(home)
    away_n = core._norm(away)
    ranked: List[Tuple[int, str]] = []

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
            haystack = core._norm(f"{href} {text}")
            if not (home_n and away_n and home_n in haystack and away_n in haystack):
                continue
            score = 0
            if home_n in core._norm(href):
                score += 2
            if away_n in core._norm(href):
                score += 2
            if home_n in core._norm(text):
                score += 1
            if away_n in core._norm(text):
                score += 1
            ranked.append((score, href))

    ranked.sort(key=lambda row: row[0], reverse=True)
    return list(dict.fromkeys(url for _, url in ranked))[:6]


def _date_matches_text(text: str, date: Optional[str]) -> bool:
    variants = core._date_variants(date)
    if not variants:
        return True
    return any(token in text for token in variants)


def _direct_fixture_windows(text: str, home: str, away: str) -> List[Tuple[str, List[str]]]:
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    home_n = core._norm(home)
    away_n = core._norm(away)
    windows: List[Tuple[str, List[str]]] = []

    for i in range(len(lines)):
        preview = " ".join(lines[i : i + 5])
        preview_n = core._norm(preview)
        if not (home_n and away_n and home_n in preview_n and away_n in preview_n):
            continue

        before = lines[max(0, i - 22) : i]
        header = " ".join(before[-18:]).lower()
        window = lines[max(0, i - 5) : min(len(lines), i + 20)]

        kind = "unknown"
        if re.search(r"\bno\b.*\byes\b", header) or "both teams" in header:
            kind = "btts"
        elif "under/over" in header or ("under" in header and "over" in header and "2.5" in header):
            kind = "ou"
        elif re.search(r"\b1\s+x\s+2\b", header) or "1 x 2" in header:
            kind = "1x2"
        windows.append((kind, window))

    return windows


def _parse_direct_match_page(page: Dict[str, Any], home: str, away: str, date: Optional[str]) -> Optional[Dict[str, Any]]:
    text = str(page.get("text") or "")
    normalized = core._norm(text)
    if core._norm(home) not in normalized or core._norm(away) not in normalized:
        return None
    if not _date_matches_text(text, date):
        return None

    out: Dict[str, Any] = {
        "home": home,
        "away": away,
        "matchDate": date,
        "_browser_sources": [str(page.get("url") or "")],
        "_direct_match_fallback": True,
    }
    windows = _direct_fixture_windows(text, home, away)

    # First pass: use section classification from the direct match page.
    for kind, window in windows:
        if kind == "1x2" and "home_win" not in out:
            triple = core._probability_triple(window)
            if triple:
                out["home_win"], out["draw"], out["away_win"] = triple
                score, avg = core._score_and_avg(window)
                if score is not None:
                    out["predicted_score"] = score
                if avg is not None:
                    out["average_goals"] = avg
        elif kind == "btts" and "btts_yes" not in out:
            pair = core._probability_pair(window)
            if pair:
                out["btts_yes"] = pair[1]
        elif kind == "ou" and "over_2_5" not in out:
            pair = core._probability_pair(window)
            if pair:
                out["over_2_5"] = pair[1]

    # Second pass: fill score/avg from any repeated fixture block if needed.
    if "predicted_score" not in out or "average_goals" not in out:
        for _, window in windows:
            score, avg = core._score_and_avg(window)
            if score is not None and "predicted_score" not in out:
                out["predicted_score"] = score
            if avg is not None and "average_goals" not in out:
                out["average_goals"] = avg
            if "predicted_score" in out and "average_goals" in out:
                break

    required = {"home_win", "draw", "away_win", "btts_yes", "over_2_5", "predicted_score", "average_goals"}
    if not required.issubset(out):
        return None
    return out


def _direct_match_snapshot(home: str, away: str, date: Optional[str], force: bool = False) -> Dict[str, Any]:
    cache_key = f"{core._norm(home)}|{core._norm(away)}|{core._iso_date(date)}"
    now = time.time()
    cached = _DIRECT_CACHE.get(cache_key)
    if cached and not force and now - float(cached.get("at") or 0) < _DIRECT_CACHE_SECONDS:
        value = cached.get("value")
        if isinstance(value, dict):
            return dict(value)

    links = _candidate_match_links(home, away)
    if not links:
        raise ForebetAutoError("Direkter Forebet-Fallback fand keinen passenden Match-Link auf den Teamseiten.")

    pages = _run_web_pages(links, include_links=False)
    for page in pages:
        parsed = _parse_direct_match_page(page, home, away, date)
        if parsed:
            _DIRECT_CACHE[cache_key] = {"at": now, "value": parsed}
            return dict(parsed)

    raise ForebetAutoError("Direkter Forebet-Match-Link wurde gefunden, aber die Prognosefelder konnten nicht sicher extrahiert werden.")


def _browser_snapshot_with_direct(home: str, away: str, date: Optional[str], force: bool = False) -> Dict[str, Any]:
    try:
        return _ORIGINAL_BROWSER_SNAPSHOT(home, away, date, force=force)
    except ForebetAutoError as list_error:
        try:
            return _direct_match_snapshot(home, away, date, force=force)
        except ForebetAutoError as direct_error:
            raise ForebetAutoError(f"{list_error} Direkter Match-Fallback: {direct_error}") from direct_error


# Install only the final browser fallback. All v5 strict parsing/matching stays intact.
core._browser_snapshot = _browser_snapshot_with_direct


def build_snapshot(match_id: int, home: str, away: str, date: Optional[str] = None, force: bool = False) -> Dict[str, Any]:
    return v5.build_snapshot(match_id=match_id, home=home, away=away, date=date, force=force)


def debug_match(home: str, away: str, date: Optional[str] = None, force: bool = False) -> Dict[str, Any]:
    return v5.debug_match(home=home, away=away, date=date, force=force)


def health() -> Dict[str, Any]:
    result = dict(v5.health())
    result["adapter"] = "forebet-auto-v6-direct-match-fallback"
    result["direct_match_fallback"] = True
    return result
