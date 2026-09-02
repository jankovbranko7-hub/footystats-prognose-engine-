from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

import forebet_auto_v9 as base
from forebet_auto import ACTOR_ID, CACHE_SECONDS, ForebetAutoError, _pct

_MISSING = (None, "", [], {})


# Forebet uses several team-slug conventions (fc-luzern, dundee-fc, ...).
_original_team_page_urls = base._team_page_urls


def _team_page_urls_with_suffixes(team: str) -> List[str]:
    roots = list(dict.fromkeys(
        root for root in (base._slug(team), base._slug(base._norm(team))) if root
    ))
    club_tags = ("fc", "sc", "fk", "afc", "ac", "cf", "sv")
    urls: List[str] = []
    for root in roots:
        ordered = [root]
        for tag in club_tags:
            ordered.extend((f"{root}-{tag}", f"{tag}-{root}"))
        for candidate in ordered:
            url = f"https://www.forebet.com/en/teams/{candidate}"
            if url not in urls:
                urls.append(url)
    for url in _original_team_page_urls(team):
        if url not in urls:
            urls.append(url)
    return urls[:20]


base._team_page_urls = _team_page_urls_with_suffixes


def _last_section(compact: str, marker_pattern: str, limit: int = 3000) -> str:
    matches = list(re.finditer(marker_pattern, compact, re.I))
    if not matches:
        return ""
    return compact[matches[-1].end(): matches[-1].end() + limit]


def _pair_from_section(section: str, label_pattern: str) -> Optional[Tuple[float, float]]:
    if not section:
        return None
    for match in re.finditer(rf"(\d{{2,6}})({label_pattern})", section, re.I):
        pair = base._split_compact(match.group(1), 2)
        if pair is not None:
            return float(pair[0]), float(pair[1])
    return None


def _probability_suffix(digits: str) -> Optional[Tuple[float, float, float]]:
    for width in range(min(9, len(digits)), 2, -1):
        triple = base._split_compact(digits[-width:], 3)
        if triple is not None:
            return float(triple[0]), float(triple[1]), float(triple[2])
    return None


def _main_prediction_row(text: str) -> Optional[Dict[str, Any]]:
    normalized = re.sub(r"\s+", " ", text)
    marker_positions = [m.end() for m in re.finditer(r"\b1\s*X\s*2\b", normalized, re.I)] or [0]
    triple_pattern = re.compile(
        r"(?=(?<!\d)(100|\d{1,2})\s+(100|\d{1,2})\s+(100|\d{1,2})(?!\d))"
    )
    score_pattern = re.compile(r"\b([12X])\s+(\d{1,2})\s*-\s*(\d{1,2})\b", re.I)
    avg_pattern = re.compile(r"(?<!\d)(\d(?:[.,]\d{2}))(?!\d)")

    for start in marker_positions[:6]:
        section = normalized[start:start + 1800]
        for triple_match in triple_pattern.finditer(section):
            triple = tuple(float(triple_match.group(i)) for i in (1, 2, 3))
            if not 95 <= sum(triple) <= 105:
                continue
            tail = section[triple_match.end():triple_match.end() + 500]
            score_match = score_pattern.search(tail)
            if not score_match:
                continue
            avg_match = avg_pattern.search(tail[score_match.end():])
            if not avg_match:
                continue
            avg = float(avg_match.group(1).replace(",", "."))
            if 0 <= avg <= 10:
                return {
                    "p1": triple[0], "px": triple[1], "p2": triple[2],
                    "score": f"{int(score_match.group(2))}-{int(score_match.group(3))}",
                    "avg": avg,
                }

    compact = re.sub(r"\s+", "", text)
    patterns = (
        re.compile(r"([12X])(\d{1,2})-(\d{1,2})(\d{1,2})-(\d{1,2})(\d(?:[.,]\d{2}))", re.I),
        re.compile(r"([12X])(\d{1,2})-(\d{1,2})(\d(?:[.,]\d{2}))", re.I),
    )
    for pattern_index, pattern in enumerate(patterns):
        for match in pattern.finditer(compact):
            if pattern_index == 0:
                _, hs, as_, dh, da, avg_raw = match.groups()
                if (int(hs), int(as_)) != (int(dh), int(da)):
                    continue
            else:
                _, hs, as_, avg_raw = match.groups()
            prefix = compact[max(0, match.start() - 16):match.start()]
            block = re.search(r"(\d{3,12})$", prefix)
            if not block:
                continue
            triple = _probability_suffix(block.group(1))
            if triple is None or not 95 <= sum(triple) <= 105:
                continue
            avg = float(avg_raw.replace(",", "."))
            if 0 <= avg <= 10:
                return {
                    "p1": triple[0], "px": triple[1], "p2": triple[2],
                    "score": f"{int(hs)}-{int(as_)}", "avg": avg,
                }
    return None


def _parse_complete_match_page(text: str, source_url: str, home: str, away: str, date: Optional[str]) -> Dict[str, Any]:
    identity = base._norm(text[:30000])
    if base._norm(home) not in identity or base._norm(away) not in identity:
        raise ForebetAutoError("Forebet-Matchseite passt nicht zur angeforderten Begegnung.")
    if not base._date_matches(text, date):
        raise ForebetAutoError("Forebet-Matchseite passt nicht zum angeforderten Datum.")

    compact = re.sub(r"\s+", "", text)
    out: Dict[str, Any] = {"source_url": source_url}
    main = _main_prediction_row(text)
    if main:
        out.update(main)

    ou_section = _last_section(compact, r"Under/Over2\.5")
    ou_pair = _pair_from_section(ou_section, r"Over|Under")
    if ou_pair is None:
        for match in re.finditer(r"(\d{2,6})(Over|Under)(\d[.,]\d{2})", compact, re.I):
            pair = base._split_compact(match.group(1), 2)
            if pair is not None:
                ou_pair = (float(pair[0]), float(pair[1]))
                break
    if ou_pair is not None:
        out["under"], out["over"] = ou_pair

    btts_section = _last_section(compact, r"NoYesPred")
    btts_pair = _pair_from_section(btts_section, r"Yes|No")
    if btts_pair is None:
        for match in re.finditer(r"(\d{2,6})(Yes|No)(\d)\s*-\s*(\d)", compact, re.I):
            pair = base._split_compact(match.group(1), 2)
            if pair is not None:
                btts_pair = (float(pair[0]), float(pair[1]))
                break
    if btts_pair is not None:
        out["btts_no"], out["btts_yes"] = btts_pair

    required = ("p1", "px", "p2", "score", "avg", "over", "btts_yes")
    missing = [key for key in required if out.get(key) in _MISSING]
    if missing:
        raise ForebetAutoError("Forebet-Matchseite unvollstaendig: " + ", ".join(missing))
    return out


def _single_browser_snapshot(home: str, away: str, date: Optional[str]) -> Dict[str, Any]:
    token = os.environ.get("APIFY_TOKEN", "").strip()
    if not token:
        raise ForebetAutoError("APIFY_TOKEN fehlt fuer den Forebet-Einzellauf.")

    # Seven candidates cover plain, FC/SC/FK prefix and suffix forms. They run
    # concurrently and have no retries, so wrong slugs cannot consume the budget.
    team_urls = list(dict.fromkeys(base._team_page_urls(home)[:7]))
    if not team_urls:
        raise ForebetAutoError("Keine Forebet-Teamseiten fuer den Einzellauf gefunden.")

    home_key = re.sub(r"[^a-z0-9]+", "", base._norm(home))
    away_key = re.sub(r"[^a-z0-9]+", "", base._norm(away))

    page_function = (
        "async function pageFunction(context){"
        "const wait=ms=>new Promise(r=>setTimeout(r,ms));"
        "const canon=s=>String(s||'').toLowerCase().normalize('NFD')"
        ".replace(/[\\u0300-\\u036f]/g,'').replace(/[^a-z0-9]+/g,'');"
        f"const homeKey={json.dumps(home_key)};"
        f"const awayKey={json.dumps(away_key)};"
        "const url=String(context.request.url||'');"
        "const title=document.title||'';"
        "if(url.includes('/football/matches/')){"
        "let text='';"
        "for(let i=0;i<21;i++){"
        "text=document.body?(document.body.textContent||document.body.innerText||''):'';"
        "const c=canon(text);"
        "if(c.includes(homeKey)&&c.includes(awayKey)&&"
        "(text.includes('Under/Over')||text.includes('No Yes')||text.includes('NoYes')||text.includes('1 X 2')||text.length>18000))break;"
        "await wait(100);"
        "}"
        "return {kind:'match',url,title,text};"
        "}"
        "let queued=0;"
        "for(let attempt=0;attempt<21&&queued===0;attempt++){"
        "for(const a of Array.from(document.querySelectorAll('a[href]'))){"
        "const href=String(a.href||'');"
        "if(!href.includes('/football/matches/'))continue;"
        "const hay=canon(href+' '+String(a.textContent||''));"
        "if(hay.includes(homeKey)&&hay.includes(awayKey)){"
        "await context.enqueueRequest({url:href,userData:{label:'MATCH'}});queued++;"
        "}"
        "}"
        "if(queued===0)await wait(100);"
        "}"
        "return {kind:'team',url,title,queued};"
        "}"
    )

    max_pages = len(team_urls) + 3
    payload = {
        "startUrls": [{"url": url} for url in team_urls],
        "pageFunction": page_function,
        "proxyConfiguration": {"useApifyProxy": True},
        "maxPagesPerCrawl": max_pages,
        "maxResultsPerCrawl": max_pages,
        "maxRequestRetries": 0,
        "maxConcurrency": 5,
        "pageLoadTimeoutSecs": 7,
        "pageFunctionTimeoutSecs": 4,
        "downloadMedia": False,
        "downloadCss": False,
        "maxScrollHeightPixels": 0,
        "linkSelector": "",
        "injectJQuery": False,
        "waitUntil": ["domcontentloaded"],
    }
    request = urllib.request.Request(
        base._WEB_ENDPOINT + "?clean=true&format=json&timeout=22",
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/json", "Accept": "application/json",
            "Authorization": f"Bearer {token}",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:500]
        raise ForebetAutoError(f"Forebet-Einzellauf Apify HTTP {exc.code}: {detail}") from exc
    except Exception as exc:
        raise ForebetAutoError(f"Forebet-Einzellauf nicht erreichbar: {exc}") from exc

    try:
        pages = json.loads(raw)
    except Exception as exc:
        raise ForebetAutoError("Forebet-Einzellauf lieferte kein gueltiges JSON.") from exc
    if not isinstance(pages, list):
        raise ForebetAutoError("Forebet-Einzellauf lieferte keine Seitenliste.")

    match_pages = [p for p in pages if isinstance(p, dict) and p.get("kind") == "match"]
    if not match_pages:
        queued = sum(int(p.get("queued") or 0) for p in pages if isinstance(p, dict))
        raise ForebetAutoError(f"Forebet-Einzellauf fand keine Matchseite (enqueue={queued}).")

    errors: List[str] = []
    for page in match_pages[:3]:
        try:
            return _parse_complete_match_page(
                str(page.get("text") or ""), str(page.get("url") or ""), home, away, date
            )
        except Exception as exc:
            errors.append(str(exc))
    raise ForebetAutoError("Forebet-Matchseite konnte nicht ausgewertet werden: " + " | ".join(errors[:3]))


def _actor_complete_snapshot(home: str, away: str, date: Optional[str]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    item = base._pick_match(base._actor_items(force=False), home, away, date)
    values = base._resolved(item)
    required = ("p1", "px", "p2", "score", "avg", "over", "btts_yes")
    missing = [key for key in required if values.get(key) in _MISSING]
    if missing:
        raise ForebetAutoError("Forebet-Dataset unvollstaendig: " + ", ".join(missing))
    return values, item


def _validate(values: Dict[str, Any]) -> Tuple[float, float, float, float, float, str, float]:
    p1 = _pct(values["p1"], "1")
    px = _pct(values["px"], "X")
    p2 = _pct(values["p2"], "2")
    if not 95 <= p1 + px + p2 <= 105:
        raise ForebetAutoError(f"Forebet-1X2-Summe unplausibel: {p1 + px + p2:.1f}%")
    over = _pct(values["over"], "Over 2.5")
    btts = _pct(values["btts_yes"], "BTTS Yes")
    if values.get("under") not in _MISSING:
        under = _pct(values["under"], "Under 2.5")
        if not 95 <= under + over <= 105:
            raise ForebetAutoError("Forebet-Over/Under-Summe ist unplausibel.")
    if values.get("btts_no") not in _MISSING:
        btts_no = _pct(values["btts_no"], "BTTS No")
        if not 95 <= btts + btts_no <= 105:
            raise ForebetAutoError("Forebet-BTTS-Summe ist unplausibel.")
    predicted = base._canonical_score(values["score"])
    try:
        avg = float(str(values["avg"]).replace(",", "."))
    except Exception as exc:
        raise ForebetAutoError("Forebet Avg. Goals fehlt oder ist ungueltig.") from exc
    if not 0 <= avg <= 10:
        raise ForebetAutoError("Forebet Avg. Goals liegt ausserhalb 0-10.")
    return p1, px, p2, over, btts, predicted, avg


def build_snapshot(match_id: int, home: str, away: str, date: Optional[str] = None, force: bool = False) -> Dict[str, Any]:
    actor_error: Optional[Exception] = None
    source_url = "https://www.forebet.com/"

    # Fastest path first: a complete already-successful dataset returns in ~1s.
    try:
        values, item = _actor_complete_snapshot(home, away, date)
        source = "Forebet latest successful 6-in-1 dataset"
        source_url = str(base._first_direct(item, ["matchUrl", "match_url", "url", "sourceUrl", "source_url"]) or source_url)
    except Exception as exc:
        actor_error = exc
        try:
            values = _single_browser_snapshot(home, away, date)
            item = {"home": home, "away": away, "matchDate": date, "matchTime": None, "leagueName": None}
            source_url = str(values.get("source_url") or source_url)
            source = "Forebet public match page via single browser crawl"
        except Exception as browser_exc:
            raise ForebetAutoError(f"Forebet automatisch fehlgeschlagen: Dataset: {actor_error}; Browser: {browser_exc}") from browser_exc

    p1, px, p2, over, btts, predicted, avg = _validate(values)
    return {
        "schema": "forebet-auto-v1",
        "match_id": int(match_id),
        "home_win": round(p1, 3), "draw": round(px, 3), "away_win": round(p2, 3),
        "btts_yes": round(btts, 3), "over_2_5": round(over, 3),
        "predicted_score": predicted, "average_goals": round(avg, 3),
        "source_url": source_url, "source": source,
        "captured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "matched_forebet": {
            "home": item.get("home"), "away": item.get("away"),
            "match_date": item.get("matchDate"), "match_time": item.get("matchTime"),
            "league": item.get("leagueName"),
        },
    }


def debug_match(home: str, away: str, date: Optional[str] = None, force: bool = False) -> Dict[str, Any]:
    start = time.time()
    try:
        values, item = _actor_complete_snapshot(home, away, date)
        return {"ok": True, "path": "complete_dataset", "elapsed_seconds": round(time.time()-start, 3), "resolved": values, "matched": {"home": item.get("home"), "away": item.get("away")}}
    except Exception as actor_exc:
        values = _single_browser_snapshot(home, away, date)
        return {"ok": True, "path": "single_browser_crawl", "elapsed_seconds": round(time.time()-start, 3), "dataset_error": str(actor_exc), "resolved": values}


def health() -> Dict[str, Any]:
    return {
        "ok": True,
        "configured": bool(os.environ.get("APIFY_TOKEN", "").strip()),
        "actor": ACTOR_ID,
        "cache_seconds": CACHE_SECONDS,
        "adapter": "forebet-auto-deterministic-single-browser",
        "actor_primary": False,
        "latest_dataset_first": True,
        "single_browser_crawl": True,
        "serial_browser_fallbacks": False,
        "dom_textcontent": True,
        "browser_timeout_seconds": 22,
        "final_adapter": True,
    }
