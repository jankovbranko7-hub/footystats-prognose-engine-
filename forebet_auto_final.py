from __future__ import annotations

import html
import re
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, Optional, Tuple

import forebet_auto_v9 as base
from forebet_auto import ForebetAutoError, _pct


def _date_parts(date: Optional[str]) -> Tuple[str, str]:
    raw = str(date or "").strip()
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", raw)
    if not m:
        return time.strftime("%Y-%m-%d", time.gmtime()), time.strftime("%d/%m/%Y", time.gmtime())
    y, mo, d = m.groups()
    return raw, f"{d}/{mo}/{y}"


def _reader(url: str) -> str:
    reader_url = "https://r.jina.ai/" + url
    req = urllib.request.Request(
        reader_url,
        headers={
            "User-Agent": "FootyStats-Forebet-Elite/0.6.1",
            "Accept": "text/plain,text/markdown;q=0.9,*/*;q=0.8",
            "X-Engine": "default",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=18) as response:
            text = response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        raise ForebetAutoError(f"Forebet Reader HTTP {exc.code}: {detail}") from exc
    except Exception as exc:
        raise ForebetAutoError(f"Forebet Reader nicht erreichbar: {exc}") from exc
    if len(text) < 500:
        raise ForebetAutoError("Forebet Reader lieferte zu wenig Inhalt.")
    return text


def _plain(markdown: str) -> str:
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", markdown)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"https?://\S+", " ", text)
    text = html.unescape(text).replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def _fixture_tail(markdown: str, home: str, away: str, human_date: str) -> str:
    text = _plain(markdown)
    hn, an = base._norm(home), base._norm(away)
    candidates = []
    for m in re.finditer(re.escape(human_date), text):
        before = text[max(0, m.start() - 260):m.start()]
        norm_before = base._norm(before)
        if hn in norm_before and an in norm_before:
            candidates.append(text[m.end():m.end() + 320])
    if not candidates:
        raise ForebetAutoError(f"Forebet fand {home} - {away} am {human_date} nicht.")
    tail = candidates[0]
    return re.sub(r"^\s*\d{1,2}:\d{2}\s*", "", tail)


def _match_url(markdown: str, home: str, away: str, fallback: str) -> str:
    hn, an = base._norm(home), base._norm(away)
    for url in re.findall(r"https://www\.forebet\.com/en/football/matches/[^\s)\]<>]+", markdown):
        slug = url.rsplit("/", 1)[-1].replace("-", " ")
        n = base._norm(slug)
        if hn in n and an in n:
            return url.rstrip(".,;\"")
    return fallback


def _parse_1x2(markdown: str, home: str, away: str, human_date: str) -> Dict[str, Any]:
    t = _fixture_tail(markdown, home, away, human_date)
    m = re.search(
        r"(?<!\d)(100|\d{1,2})\s+(100|\d{1,2})\s+(100|\d{1,2})\s+([12X])\s+(\d{1,2})\s*-\s*(\d{1,2})",
        t, re.I,
    )
    if not m:
        raise ForebetAutoError("Forebet 1X2-Zeile konnte nicht gelesen werden.")
    p1, px, p2 = (float(m.group(i)) for i in (1, 2, 3))
    if not 95 <= p1 + px + p2 <= 105:
        raise ForebetAutoError("Forebet 1X2-Summe ist unplausibel.")
    rest = t[m.end():m.end() + 180]
    avg_match = re.search(r"(?<!\d)(\d(?:[.,]\d{2}))(?!\d)", rest)
    if not avg_match:
        raise ForebetAutoError("Forebet Avg. Goals fehlt.")
    avg = float(avg_match.group(1).replace(",", "."))
    if not 0 <= avg <= 10:
        raise ForebetAutoError("Forebet Avg. Goals ist unplausibel.")
    return {
        "p1": p1,
        "px": px,
        "p2": p2,
        "score": f"{int(m.group(5))}-{int(m.group(6))}",
        "avg": avg,
    }


def _parse_ou(markdown: str, home: str, away: str, human_date: str) -> Dict[str, float]:
    t = _fixture_tail(markdown, home, away, human_date)
    m = re.search(r"(?<!\d)(100|\d{1,2})\s+(100|\d{1,2})\s+(Under|Over)\b", t, re.I)
    if not m:
        raise ForebetAutoError("Forebet Under/Over-Zeile konnte nicht gelesen werden.")
    under, over = float(m.group(1)), float(m.group(2))
    if not 95 <= under + over <= 105:
        raise ForebetAutoError("Forebet Under/Over-Summe ist unplausibel.")
    return {"under": under, "over": over}


def _parse_btts(markdown: str, home: str, away: str, human_date: str) -> Dict[str, float]:
    t = _fixture_tail(markdown, home, away, human_date)
    m = re.search(r"(?<!\d)(100|\d{1,2})\s+(100|\d{1,2})\s+(No|Yes)\b", t, re.I)
    if not m:
        raise ForebetAutoError("Forebet BTTS-Zeile konnte nicht gelesen werden.")
    no, yes = float(m.group(1)), float(m.group(2))
    if not 95 <= no + yes <= 105:
        raise ForebetAutoError("Forebet BTTS-Summe ist unplausibel.")
    return {"btts_no": no, "btts_yes": yes}


def build_snapshot(match_id: int, home: str, away: str, date: Optional[str] = None, force: bool = False) -> Dict[str, Any]:
    iso_date, human_date = _date_parts(date)
    urls = {
        "1x2": f"https://www.forebet.com/en/football-predictions/predictions-1x2/{iso_date}/by-league",
        "ou": f"https://www.forebet.com/en/football-predictions/under-over-25-goals/{iso_date}/by-league",
        "btts": f"https://www.forebet.com/en/football-predictions/both-to-score/{iso_date}/by-league",
    }

    pages: Dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(_reader, url): key for key, url in urls.items()}
        for future in as_completed(futures):
            pages[futures[future]] = future.result()

    one = _parse_1x2(pages["1x2"], home, away, human_date)
    ou = _parse_ou(pages["ou"], home, away, human_date)
    btts = _parse_btts(pages["btts"], home, away, human_date)

    p1 = _pct(one["p1"], "1")
    px = _pct(one["px"], "X")
    p2 = _pct(one["p2"], "2")
    over = _pct(ou["over"], "Over 2.5")
    btts_yes = _pct(btts["btts_yes"], "BTTS Yes")
    source_url = _match_url(pages["1x2"], home, away, urls["1x2"])

    return {
        "schema": "forebet-auto-v1",
        "match_id": int(match_id),
        "home_win": round(p1, 3),
        "draw": round(px, 3),
        "away_win": round(p2, 3),
        "btts_yes": round(btts_yes, 3),
        "over_2_5": round(over, 3),
        "predicted_score": one["score"],
        "average_goals": round(float(one["avg"]), 3),
        "source_url": source_url,
        "source": "Forebet public prediction pages via Jina Reader (no Apify)",
        "captured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "matched_forebet": {
            "home": home,
            "away": away,
            "match_date": iso_date,
            "match_time": None,
            "league": None,
        },
    }


def debug_match(home: str, away: str, date: Optional[str] = None, force: bool = False) -> Dict[str, Any]:
    start = time.time()
    result = build_snapshot(1, home, away, date, force)
    return {
        "ok": True,
        "path": "jina_reader_public_pages",
        "elapsed_seconds": round(time.time() - start, 3),
        "resolved": result,
    }


def health() -> Dict[str, Any]:
    return {
        "ok": True,
        "configured": True,
        "adapter": "forebet-jina-public-pages",
        "actor_primary": False,
        "apify_used": False,
        "jina_reader": True,
        "parallel_market_fetch": True,
        "serial_browser_fallbacks": False,
        "dom_textcontent": True,
        "final_adapter": True,
    }
