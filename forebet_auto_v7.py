from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any, Dict, Iterable, List, Optional, Tuple

# V6 supplies link discovery + direct-match orchestration. V5 parsers remain active below it.
import forebet_auto_v6 as v6
import forebet_auto_v3 as core
from forebet_auto import ForebetAutoError


def _run_web_pages(urls: Iterable[str], *, include_links: bool = False) -> List[Dict[str, Any]]:
    """Scrape pages while preserving both visible and hidden Forebet tab content."""
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
        " const visible = document.body ? document.body.innerText : '';"
        " const allDom = document.body ? (document.body.textContent || '') : '';"
        " const body = visible + '\n\n__HIDDEN_DOM__\n' + allDom;"
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


def _date_matches_text(text: str, date: Optional[str]) -> bool:
    """Accept Forebet's locale-dependent dd/mm and mm/dd renderings."""
    key = core._date_key(date)
    if not key:
        return True
    y, m, d = key[:4], key[4:6], key[6:8]
    variants = {
        f"{y}-{m}-{d}",
        f"{d}/{m}/{y}",
        f"{d}.{m}.{y}",
        f"{m}/{d}/{y}",
        f"{m}.{d}.{y}",
    }
    return any(token in text for token in variants)


def _direct_fixture_windows(text: str, home: str, away: str) -> List[Tuple[str, List[str]]]:
    """Classify each repeated direct-match table from its nearest real table header."""
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

        before = lines[max(0, i - 16) : i]
        kind = "unknown"
        # Search backwards so the nearest table header wins. Navigation labels such as
        # "Under/Over 2.5" are ignored unless they also look like a table header.
        for raw in reversed(before):
            low = raw.lower()
            has_table_shape = "pred" in low or "correct score" in low or "prob." in low
            if re.search(r"\bno\b.*\byes\b", low) and has_table_shape:
                kind = "btts"
                break
            if "under/over" in low and has_table_shape:
                kind = "ou"
                break
            if "1x2" in low and has_table_shape:
                kind = "1x2"
                break

        # Forebet may split the header across adjacent lines; inspect the last six as a unit.
        if kind == "unknown":
            header = " ".join(before[-6:]).lower()
            if re.search(r"\bno\b.*\byes\b", header) and "pred" in header:
                kind = "btts"
            elif "under/over" in header and "pred" in header:
                kind = "ou"
            elif "1x2" in header and "pred" in header:
                kind = "1x2"

        window = lines[max(0, i - 7) : min(len(lines), i + 22)]
        windows.append((kind, window))

    return windows


# Patch V6's dynamic globals. Its direct-match snapshot calls these names at runtime.
v6._run_web_pages = _run_web_pages
v6._date_matches_text = _date_matches_text
v6._direct_fixture_windows = _direct_fixture_windows


def build_snapshot(match_id: int, home: str, away: str, date: Optional[str] = None, force: bool = False) -> Dict[str, Any]:
    return v6.build_snapshot(match_id=match_id, home=home, away=away, date=date, force=force)


def debug_match(home: str, away: str, date: Optional[str] = None, force: bool = False) -> Dict[str, Any]:
    return v6.debug_match(home=home, away=away, date=date, force=force)


def health() -> Dict[str, Any]:
    result = dict(v6.health())
    result["adapter"] = "forebet-auto-v7-direct-dom"
    result["direct_dom_hidden_tabs"] = True
    result["us_date_format"] = True
    return result
