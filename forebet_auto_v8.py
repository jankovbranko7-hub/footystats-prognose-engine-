from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any, Dict, Iterable, List, Optional, Tuple

# V7 fixes locale dates and keeps the V6 direct-match link discovery.
import forebet_auto_v7 as v7
import forebet_auto_v6 as v6
import forebet_auto_v3 as core
from forebet_auto import ForebetAutoError

_ORIGINAL_DIRECT_PARSE = v6._parse_direct_match_page


def _run_web_pages(urls: Iterable[str], *, include_links: bool = False) -> List[Dict[str, Any]]:
    """Scrape direct Forebet pages and explicitly click the prediction tabs.

    Forebet only exposes the active market reliably through innerText. For direct
    match pages we therefore click 1X2, Under/Over 2.5 and Btts and capture each
    visible state separately. Team pages still only need their links.
    """
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
        " const wait = ms => new Promise(r => setTimeout(r, ms));"
        " await wait(900);"
        " for (let i=0; i<7; i++) {"
        "   window.scrollTo(0, document.body ? document.body.scrollHeight : 0);"
        "   await wait(300);"
        " }"
        " window.scrollTo(0, 0);"
        " await wait(350);"
        f" {links_js}"
        " const visible = () => document.body ? document.body.innerText : '';"
        " const clickTab = async label => {"
        "   const wanted = String(label).trim().toLowerCase();"
        "   const nodes = Array.from(document.querySelectorAll('a,button,[role=tab],li,span,div'));"
        "   const exact = nodes.filter(el => String(el.innerText || el.textContent || '').trim().toLowerCase() === wanted);"
        "   for (const el of exact) {"
        "     const target = el.closest('a,button,[role=tab]') || el;"
        "     try {"
        "       target.scrollIntoView({block:'center'});"
        "       target.click();"
        "       target.dispatchEvent(new MouseEvent('click',{bubbles:true,cancelable:true,view:window}));"
        "       await wait(850);"
        "       const txt = visible();"
        "       if (txt) return txt;"
        "     } catch (e) {}"
        "   }"
        "   return '';"
        " };"
        " const initial = visible();"
        " const isMatch = String(context.request.url || '').includes('/football/matches/');"
        " let oneX2 = initial, ou = '', btts = '';"
        " if (isMatch) {"
        "   oneX2 = await clickTab('1X2') || initial;"
        "   ou = await clickTab('Under/Over 2.5');"
        "   btts = await clickTab('Btts');"
        " }"
        " return {url: context.request.url, title: document.title, text: initial, links, tabs:{oneX2,ou,btts}};"
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


def _candidate_windows(text: str, home: str, away: str) -> List[List[str]]:
    lines = [re.sub(r"\s+", " ", line).strip() for line in str(text or "").splitlines()]
    lines = [line for line in lines if line]
    home_n, away_n = core._norm(home), core._norm(away)
    out: List[List[str]] = []
    if not home_n or not away_n:
        return out

    for i, line in enumerate(lines):
        if home_n not in core._norm(line):
            continue
        away_at: Optional[int] = None
        for j in range(i, min(len(lines), i + 5)):
            if away_n in core._norm(lines[j]):
                away_at = j
                break
        if away_at is None:
            continue
        out.append(lines[max(0, i - 9): min(len(lines), away_at + 18)])
    return out


def _parse_triple(text: str, home: str, away: str) -> Optional[Tuple[Tuple[float, float, float], Optional[str], Optional[float]]]:
    for window in _candidate_windows(text, home, away):
        triple = core._probability_triple(window)
        if triple is None:
            continue
        score, avg = core._score_and_avg(window)
        return triple, score, avg
    return None


def _parse_pair(text: str, home: str, away: str) -> Optional[Tuple[float, float]]:
    for window in _candidate_windows(text, home, away):
        pair = core._probability_pair(window)
        if pair is not None:
            return float(pair[0]), float(pair[1])
    return None


def _parse_direct_match_page(page: Dict[str, Any], home: str, away: str, date: Optional[str]) -> Optional[Dict[str, Any]]:
    initial = str(page.get("text") or "")
    normalized = core._norm(initial)
    if core._norm(home) not in normalized or core._norm(away) not in normalized:
        return None
    if not v7._date_matches_text(initial, date):
        return None

    tabs = page.get("tabs") if isinstance(page.get("tabs"), dict) else {}
    one_text = str(tabs.get("oneX2") or initial)
    ou_text = str(tabs.get("ou") or "")
    btts_text = str(tabs.get("btts") or "")

    one = _parse_triple(one_text, home, away)
    ou = _parse_pair(ou_text, home, away) if ou_text else None
    btts = _parse_pair(btts_text, home, away) if btts_text else None

    if one and ou and btts:
        triple, score, avg = one
        if score is not None and avg is not None:
            return {
                "home": home,
                "away": away,
                "matchDate": date,
                "home_win": float(triple[0]),
                "draw": float(triple[1]),
                "away_win": float(triple[2]),
                "over_2_5": float(ou[1]),
                "btts_yes": float(btts[1]),
                "predicted_score": score,
                "average_goals": float(avg),
                "_browser_sources": [str(page.get("url") or "")],
                "_direct_match_fallback": True,
                "_direct_tab_clicks": True,
            }

    # Preserve the older parser as a conservative fallback for pages whose markup
    # already matched V6/V7.
    return _ORIGINAL_DIRECT_PARSE(page, home, away, date)


# V6 resolves these globals at runtime.
v6._run_web_pages = _run_web_pages
v6._parse_direct_match_page = _parse_direct_match_page


def build_snapshot(match_id: int, home: str, away: str, date: Optional[str] = None, force: bool = False) -> Dict[str, Any]:
    return v7.build_snapshot(match_id=match_id, home=home, away=away, date=date, force=force)


def debug_match(home: str, away: str, date: Optional[str] = None, force: bool = False) -> Dict[str, Any]:
    return v7.debug_match(home=home, away=away, date=date, force=force)


def health() -> Dict[str, Any]:
    result = dict(v7.health())
    result["adapter"] = "forebet-auto-v8-click-tabs"
    result["direct_tab_clicks"] = True
    return result
