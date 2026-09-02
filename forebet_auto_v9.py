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
from forebet_auto import (
    ACTOR_ID,
    CACHE_SECONDS,
    ForebetAutoError,
    _actor_items,
    _norm,
    _pct,
    _similarity,
)

_MISSING = (None, "", [], {})
_WEB_ACTOR_ID = "apify~web-scraper"
_WEB_ENDPOINT = f"https://api.apify.com/v2/acts/{_WEB_ACTOR_ID}/run-sync-get-dataset-items"


def _date_key(value: Any) -> str:
    digits = re.sub(r"[^0-9]", "", str(value or ""))
    if len(digits) != 8:
        return ""
    if digits[:4].isdigit() and 1900 <= int(digits[:4]) <= 2200:
        return digits
    if digits[-4:].isdigit() and 1900 <= int(digits[-4:]) <= 2200:
        return digits[-4:] + digits[2:4] + digits[:2]
    return ""


def _deep_merge(target: Dict[str, Any], source: Dict[str, Any]) -> None:
    for key, value in source.items():
        if value in _MISSING:
            continue
        current = target.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            _deep_merge(current, value)
        elif current in _MISSING:
            target[key] = value


def _merge_rows(rows: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    merged: Dict[str, Any] = {}
    for row in rows:
        _deep_merge(merged, row)
    return merged


def _same_fixture(a: Dict[str, Any], b: Dict[str, Any], wanted_date: str) -> bool:
    if _norm(a.get("home")) != _norm(b.get("home")):
        return False
    if _norm(a.get("away")) != _norm(b.get("away")):
        return False
    ad = _date_key(a.get("matchDate"))
    bd = _date_key(b.get("matchDate"))
    if wanted_date:
        return (not ad or ad == wanted_date) and (not bd or bd == wanted_date)
    return not (ad and bd and ad != bd)


def _pick_match(items: Iterable[Dict[str, Any]], home: str, away: str, date: Optional[str]) -> Dict[str, Any]:
    rows = [row for row in items if isinstance(row, dict)]
    if not rows:
        raise ForebetAutoError("Forebet-Actor lieferte keine Spiele.")

    wanted_date = _date_key(date)
    home_n, away_n = _norm(home), _norm(away)

    exact = [
        row for row in rows
        if _norm(row.get("home")) == home_n
        and _norm(row.get("away")) == away_n
        and (not wanted_date or not _date_key(row.get("matchDate")) or _date_key(row.get("matchDate")) == wanted_date)
    ]
    if exact:
        return _merge_rows(exact)

    ranked: List[Tuple[float, float, float, Dict[str, Any]]] = []
    for row in rows:
        hs = _similarity(home, row.get("home"))
        aw = _similarity(away, row.get("away"))
        row_date = _date_key(row.get("matchDate"))
        date_bonus = 0.18 if wanted_date and row_date == wanted_date else (-0.15 if wanted_date and row_date else 0.0)
        score = 0.5 * hs + 0.5 * aw + date_bonus
        ranked.append((score, hs, aw, row))

    ranked.sort(key=lambda x: (x[0], min(x[1], x[2])), reverse=True)
    score, hs, aw, best = ranked[0]
    if min(hs, aw) < 0.78 or score < 0.78:
        raise ForebetAutoError(
            "Kein Forebet-Spiel konnte sicher zugeordnet werden. "
            f"Bester Treffer: {best.get('home')} - {best.get('away')} "
            f"(Home {hs:.2f}, Away {aw:.2f})."
        )

    for other_score, _, _, other in ranked[1:]:
        if _same_fixture(other, best, wanted_date):
            continue
        if other_score > score - 0.04:
            raise ForebetAutoError(
                "Forebet-Zuordnung ist mehrdeutig: "
                f"{best.get('home')} - {best.get('away')} / "
                f"{other.get('home')} - {other.get('away')}."
            )
        break

    same = [row for row in rows if _same_fixture(row, best, wanted_date)]
    return _merge_rows(same or [best])


def _canon_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def _flatten(value: Any, prefix: str = "") -> List[Tuple[str, Any]]:
    out: List[Tuple[str, Any]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            out.extend(_flatten(child, path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            out.extend(_flatten(child, f"{prefix}.{index}"))
    elif value not in _MISSING:
        out.append((prefix, value))
    return out


def _first_direct(item: Dict[str, Any], aliases: Iterable[str]) -> Any:
    by_key = {_canon_key(key): value for key, value in item.items()}
    for alias in aliases:
        value = by_key.get(_canon_key(alias))
        if value not in _MISSING:
            return value
    return None


def _semantic_value(item: Dict[str, Any], aliases: Iterable[str], kind: str) -> Any:
    direct = _first_direct(item, aliases)
    if direct not in _MISSING:
        return direct

    leaves = [(_canon_key(path), value) for path, value in _flatten(item)]

    def clean(path: str) -> bool:
        return not any(token in path for token in ("halftime", "probabilityht", "corner", "card"))

    for path, value in leaves:
        if not clean(path):
            continue
        if kind == "home" and "prob" in path and (
            "home" in path or path.endswith("probability1percent") or path.endswith("probability1") or "1x2home" in path
        ):
            return value
        if kind == "draw" and "prob" in path and (
            "draw" in path or path.endswith("probabilityxpercent") or path.endswith("probabilityx") or "1x2draw" in path
        ):
            return value
        if kind == "away" and "prob" in path and (
            "away" in path or path.endswith("probability2percent") or path.endswith("probability2") or "1x2away" in path
        ):
            return value
        if kind == "over" and "prob" in path and "over" in path and not any(x in path for x in ("corner", "card")):
            return value
        if kind == "under" and "prob" in path and "under" in path and not any(x in path for x in ("corner", "card")):
            return value
        if kind == "btts_yes" and "btts" in path and "yes" in path and ("prob" in path or "percent" in path):
            return value
        if kind == "btts_no" and "btts" in path and "no" in path and ("prob" in path or "percent" in path):
            return value
        if kind == "score" and any(x in path for x in ("predictedscore", "correctscore")):
            return value
        if kind == "avg" and any(x in path for x in ("averagegoals", "avggoals")):
            return value
    return None


def _resolved(item: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "p1": _semantic_value(item, ["probability_1_percent", "probability1Percent", "homeProbability", "predictionHome"], "home"),
        "px": _semantic_value(item, ["probability_X_percent", "probability_x_percent", "probabilityXPercent", "drawProbability", "predictionDraw"], "draw"),
        "p2": _semantic_value(item, ["probability_2_percent", "probability2Percent", "awayProbability", "predictionAway"], "away"),
        "over": _semantic_value(item, ["probability_over_percent", "probability_over_2_5_percent", "probabilityOverPercent", "over25Percent"], "over"),
        "under": _semantic_value(item, ["probability_under_percent", "probabilityUnderPercent", "under25Percent"], "under"),
        "btts_yes": _semantic_value(item, ["probability_btts_yes_percent", "probability_BTTS_yes_percent", "probabilityBttsYesPercent", "btts_yes_percent", "bttsYesPercent"], "btts_yes"),
        "btts_no": _semantic_value(item, ["probability_btts_no_percent", "probabilityBttsNoPercent", "btts_no_percent", "bttsNoPercent"], "btts_no"),
        "score": _semantic_value(item, ["predictedScore", "predicted_score", "correctScore"], "score"),
        "avg": _semantic_value(item, ["averageGoals", "average_goals", "avgGoals"], "avg"),
    }


def _slug(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).lower()
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")


def _web_pages(urls: Iterable[str], include_links: bool) -> List[Dict[str, Any]]:
    token = os.environ.get("APIFY_TOKEN", "").strip()
    if not token:
        raise ForebetAutoError("APIFY_TOKEN fehlt fuer den direkten Forebet-Fallback.")

    clean_urls = list(dict.fromkeys(str(url) for url in urls if str(url).startswith("http")))
    if not clean_urls:
        return []

    links_js = (
        "const links=Array.from(document.querySelectorAll('a[href]')).map(a=>({href:a.href||'',text:(a.innerText||a.textContent||'').trim()}));"
        if include_links else "const links=[];"
    )
    page_function = (
        "async function pageFunction(context){"
        "const wait=ms=>new Promise(r=>setTimeout(r,ms));"
        "await wait(700);"
        "for(let i=0;i<4;i++){window.scrollTo(0,document.body?document.body.scrollHeight:0);await wait(250);}"
        "window.scrollTo(0,0);await wait(250);"
        + links_js +
        "const text=document.body?document.body.innerText:'';"
        "return {url:context.request.url,title:document.title,text,links};}"
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
        _WEB_ENDPOINT + "?clean=true&format=json&timeout=120",
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json", "Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=135) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:500]
        raise ForebetAutoError(f"Forebet-Direktfallback Apify HTTP {exc.code}: {detail}") from exc
    except Exception as exc:
        raise ForebetAutoError(f"Forebet-Direktfallback nicht erreichbar: {exc}") from exc

    try:
        pages = json.loads(raw)
    except Exception as exc:
        raise ForebetAutoError("Forebet-Direktfallback lieferte kein gueltiges JSON.") from exc
    return [page for page in pages if isinstance(page, dict)] if isinstance(pages, list) else []


def _team_page_urls(home: str) -> List[str]:
    base = _slug(home)
    normalized = _slug(_norm(home))
    roots = list(dict.fromkeys(x for x in (base, normalized) if x))
    candidates: List[str] = []
    for root in roots:
        candidates.append(root)
        if not re.match(r"^(fc|sc|fk|afc|ac|cf|sv)-", root):
            candidates.extend([f"fc-{root}", f"sc-{root}", f"fk-{root}"])
    return [f"https://www.forebet.com/en/teams/{x}" for x in list(dict.fromkeys(candidates))[:6]]


def _direct_match_links(home: str, away: str) -> List[str]:
    home_n, away_n = _norm(home), _norm(away)
    found: List[str] = []
    for page in _web_pages(_team_page_urls(home), include_links=True):
        for link in page.get("links") or []:
            if not isinstance(link, dict):
                continue
            href = str(link.get("href") or "").strip()
            text = str(link.get("text") or "").strip()
            if "/football/matches/" not in href:
                continue
            if href.startswith("/"):
                href = urllib.parse.urljoin("https://www.forebet.com", href)
            hay = _norm(f"{href} {text}")
            if home_n and away_n and home_n in hay and away_n in hay:
                found.append(href)
    return list(dict.fromkeys(found))[:3]


def _split_compact(digits: str, count: int) -> Optional[Tuple[float, ...]]:
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
            token = digits[pos:pos + width]
            if not token or (len(token) > 1 and token.startswith("0")):
                continue
            value = int(token)
            if 0 <= value <= 100 and sum(parts) + value <= 100:
                walk(pos + width, parts + [value])
    walk(0, [])
    unique = list(dict.fromkeys(solutions))
    return tuple(float(v) for v in unique[0]) if len(unique) == 1 else None


def _date_matches(text: str, date: Optional[str]) -> bool:
    key = _date_key(date)
    if not key:
        return True
    y, m, d = key[:4], key[4:6], key[6:8]
    return any(token in text for token in (f"{y}-{m}-{d}", f"{d}/{m}/{y}", f"{d}.{m}.{y}", f"{m}/{d}/{y}", f"{m}.{d}.{y}"))


def _direct_1x2(home: str, away: str, date: Optional[str]) -> Dict[str, Any]:
    links = _direct_match_links(home, away)
    if not links:
        raise ForebetAutoError("Direkter Forebet-Fallback fand keinen sicheren Match-Link.")

    for page in _web_pages(links, include_links=False):
        text = str(page.get("text") or "")
        title = str(page.get("title") or "")
        identity = _norm(f"{title} {text[:12000]}")
        if _norm(home) not in identity or _norm(away) not in identity or not _date_matches(f"{title} {text}", date):
            continue
        compact = re.sub(r"\s+", "", text)
        for match in re.finditer(r"(\d{3,9})([12X])(\d)\s*-\s*(\d)(\d[.,]\d{2})", compact, re.I):
            triple = _split_compact(match.group(1), 3)
            if triple is None:
                continue
            avg = float(match.group(5).replace(",", "."))
            if not 0 <= avg <= 10:
                continue
            return {
                "p1": triple[0], "px": triple[1], "p2": triple[2],
                "score": f"{int(match.group(3))}-{int(match.group(4))}",
                "avg": avg,
                "source_url": str(page.get("url") or ""),
            }
    raise ForebetAutoError("Direkter Forebet-Fallback konnte 1X2/Score/Avg nicht sicher extrahieren.")


def _canonical_score(value: Any) -> str:
    text = str(value or "").strip()
    pairs: List[Tuple[int, int]] = []
    for h, a in re.findall(r"(\d{1,2})\s*[-:]\s*(\d{1,2})", text):
        hh, aa = int(h), int(a)
        if 0 <= hh <= 15 and 0 <= aa <= 15:
            pairs.append((hh, aa))
    unique = list(dict.fromkeys(pairs))
    if len(unique) == 1:
        return f"{unique[0][0]}-{unique[0][1]}"
    raise ForebetAutoError("Forebet-Ergebnistipp fehlt oder ist ungueltig.")


def _float_value(value: Any, field: str) -> float:
    try:
        return float(str(value).strip().replace(",", "."))
    except Exception as exc:
        raise ForebetAutoError(f"Forebet-Feld {field} fehlt oder ist ungueltig.") from exc


def build_snapshot(match_id: int, home: str, away: str, date: Optional[str] = None, force: bool = False) -> Dict[str, Any]:
    item = _pick_match(_actor_items(force=force), home, away, date)
    values = _resolved(item)
    direct: Dict[str, Any] = {}

    if any(values[key] in _MISSING for key in ("p1", "px", "p2", "score", "avg")):
        direct = _direct_1x2(home, away, date)
        for key in ("p1", "px", "p2", "score", "avg"):
            if values[key] in _MISSING:
                values[key] = direct.get(key)

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

    predicted = _canonical_score(values["score"])
    avg = _float_value(values["avg"], "Avg. Goals")
    if not 0 <= avg <= 10:
        raise ForebetAutoError("Forebet Avg. Goals liegt ausserhalb 0-10.")

    source_url = direct.get("source_url") or _first_direct(item, ["matchUrl", "match_url", "url", "sourceUrl", "source_url"]) or "https://www.forebet.com/"
    source = "Forebet via Apify 6-in-1 actor"
    if direct:
        source += " + direct match 1X2 fallback"

    return {
        "schema": "forebet-auto-v1", "match_id": int(match_id),
        "home_win": round(p1, 3), "draw": round(px, 3), "away_win": round(p2, 3),
        "btts_yes": round(btts, 3), "over_2_5": round(over, 3),
        "predicted_score": predicted, "average_goals": round(avg, 3),
        "source_url": source_url, "source": source,
        "captured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "matched_forebet": {
            "home": item.get("home"), "away": item.get("away"), "match_date": item.get("matchDate"),
            "match_time": item.get("matchTime"), "league": item.get("leagueName"),
        },
    }


def debug_match(home: str, away: str, date: Optional[str] = None, force: bool = False) -> Dict[str, Any]:
    item = _pick_match(_actor_items(force=force), home, away, date)
    return {
        "ok": True,
        "requested": {"home": home, "away": away, "date": date},
        "matched": {"home": item.get("home"), "away": item.get("away"), "matchDate": item.get("matchDate"), "leagueName": item.get("leagueName")},
        "resolved": _resolved(item),
        "available_keys": sorted(str(k) for k in item.keys()),
    }


def health() -> Dict[str, Any]:
    return {
        "ok": True, "configured": True, "actor": ACTOR_ID, "cache_seconds": CACHE_SECONDS,
        "adapter": "forebet-auto-v9-direct-first", "actor_primary": True,
        "direct_1x2_fallback": True, "tab_clicks": False,
    }
