from __future__ import annotations

import html
import re
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional

import forebet_auto_v9 as base
from forebet_auto import ACTOR_ID, CACHE_SECONDS, ForebetAutoError, _pct


class _ForebetRows(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: List[Dict[str, Any]] = []
        self.row: Optional[Dict[str, Any]] = None
        self.div_depth = 0
        self.span_stack: List[Optional[str]] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        a = {str(k): str(v or "") for k, v in attrs}
        classes = set(a.get("class", "").split())
        if tag == "div" and self.row is None and "rcnt" in classes:
            self.row = {"text": [], "home": [], "away": [], "hrefs": [], "meta_name": ""}
            self.div_depth = 1
        elif self.row is not None and tag == "div":
            self.div_depth += 1

        if self.row is None:
            return

        if tag == "span":
            inherited = self.span_stack[-1] if self.span_stack else None
            if "homeTeam" in classes:
                inherited = "home"
            elif "awayTeam" in classes:
                inherited = "away"
            self.span_stack.append(inherited)
        elif tag == "a":
            href = a.get("href", "").strip()
            if href:
                self.row["hrefs"].append(href)
        elif tag == "meta" and a.get("itemprop") == "name" and a.get("content"):
            self.row["meta_name"] = a["content"].strip()

    def handle_endtag(self, tag: str) -> None:
        if self.row is None:
            return
        if tag == "span" and self.span_stack:
            self.span_stack.pop()
        if tag == "div":
            self.div_depth -= 1
            if self.div_depth == 0:
                self.row["text"] = " ".join(" ".join(self.row["text"]).split())
                self.row["home"] = " ".join(" ".join(self.row["home"]).split())
                self.row["away"] = " ".join(" ".join(self.row["away"]).split())
                self.rows.append(self.row)
                self.row = None
                self.span_stack = []

    def handle_data(self, data: str) -> None:
        if self.row is None:
            return
        value = html.unescape(data).strip()
        if not value:
            return
        self.row["text"].append(value)
        if self.span_stack:
            if self.span_stack[-1] == "home":
                self.row["home"].append(value)
            elif self.span_stack[-1] == "away":
                self.row["away"].append(value)


def _date_parts(date: Optional[str]) -> tuple[str, str]:
    raw = str(date or "").strip()
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", raw)
    if not m:
        today = time.gmtime()
        iso = time.strftime("%Y-%m-%d", today)
        human = time.strftime("%d/%m/%Y", today)
        return iso, human
    y, mo, d = m.groups()
    return raw, f"{d}/{mo}/{y}"


def _fetch_html(url: str) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Version/18.0 Mobile/15E148 Safari/604.1",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Cache-Control": "no-cache",
            "Cookie": "jfcookie[lang]=en",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=9) as response:
            body = response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        raise ForebetAutoError(f"Forebet Direktabruf HTTP {exc.code} fuer {url}") from exc
    except Exception as exc:
        raise ForebetAutoError(f"Forebet Direktabruf nicht erreichbar: {exc}") from exc
    if len(body) < 3000 or "forebet" not in body.lower():
        raise ForebetAutoError("Forebet Direktabruf lieferte keine gueltige Prognoseseite.")
    return body


def _rows(page: str) -> List[Dict[str, Any]]:
    parser = _ForebetRows()
    parser.feed(page)
    if not parser.rows:
        raise ForebetAutoError("Forebet Prognoseseite enthielt keine Spielzeilen.")
    return parser.rows


def _row_score(row: Dict[str, Any], home: str, away: str, human_date: str) -> float:
    rh, ra = row.get("home") or "", row.get("away") or ""
    text = str(row.get("text") or "")
    hs = base._similarity(home, rh) if rh else (0.96 if base._norm(home) in base._norm(text) else 0.0)
    aw = base._similarity(away, ra) if ra else (0.96 if base._norm(away) in base._norm(text) else 0.0)
    date_bonus = 0.10 if human_date in text else 0.0
    return 0.45 * hs + 0.45 * aw + date_bonus


def _pick_row(rows: List[Dict[str, Any]], home: str, away: str, human_date: str) -> Dict[str, Any]:
    ranked = sorted((( _row_score(r, home, away, human_date), r) for r in rows), key=lambda x: x[0], reverse=True)
    if not ranked or ranked[0][0] < 0.82:
        best = ranked[0][1] if ranked else {}
        raise ForebetAutoError(
            f"Forebet fand das Spiel nicht sicher. Bester Treffer: {best.get('home')} - {best.get('away')}"
        )
    if len(ranked) > 1 and ranked[1][0] > ranked[0][0] - 0.025:
        raise ForebetAutoError("Forebet-Spielzuordnung ist mehrdeutig.")
    return ranked[0][1]


def _tail(row: Dict[str, Any], human_date: str) -> str:
    text = str(row.get("text") or "")
    pos = text.find(human_date)
    if pos >= 0:
        text = text[pos + len(human_date):]
    text = re.sub(r"^\s*\d{1,2}:\d{2}\s*", "", text)
    return text


def _parse_1x2(row: Dict[str, Any], human_date: str) -> Dict[str, Any]:
    t = _tail(row, human_date)
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
    avgs = re.findall(r"(?<!\d)(\d(?:[.,]\d{2}))(?!\d)", rest)
    if not avgs:
        raise ForebetAutoError("Forebet Avg. Goals fehlt in der 1X2-Zeile.")
    avg = float(avgs[0].replace(",", "."))
    if not 0 <= avg <= 10:
        raise ForebetAutoError("Forebet Avg. Goals ist unplausibel.")
    source_url = ""
    for href in row.get("hrefs") or []:
        if "/football/matches/" in href:
            source_url = href if href.startswith("http") else "https://www.forebet.com" + href
            break
    return {
        "p1": p1, "px": px, "p2": p2,
        "score": f"{int(m.group(5))}-{int(m.group(6))}",
        "avg": avg,
        "source_url": source_url,
    }


def _parse_ou(row: Dict[str, Any], human_date: str) -> Dict[str, Any]:
    t = _tail(row, human_date)
    m = re.search(r"(?<!\d)(100|\d{1,2})\s+(100|\d{1,2})\s+(Under|Over)\b", t, re.I)
    if not m:
        raise ForebetAutoError("Forebet Under/Over-Zeile konnte nicht gelesen werden.")
    under, over = float(m.group(1)), float(m.group(2))
    if not 95 <= under + over <= 105:
        raise ForebetAutoError("Forebet Under/Over-Summe ist unplausibel.")
    return {"under": under, "over": over}


def _parse_btts(row: Dict[str, Any], human_date: str) -> Dict[str, Any]:
    t = _tail(row, human_date)
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
        futures = {pool.submit(_fetch_html, url): key for key, url in urls.items()}
        for future in as_completed(futures):
            key = futures[future]
            pages[key] = future.result()

    r1 = _pick_row(_rows(pages["1x2"]), home, away, human_date)
    rou = _pick_row(_rows(pages["ou"]), home, away, human_date)
    rb = _pick_row(_rows(pages["btts"]), home, away, human_date)

    one = _parse_1x2(r1, human_date)
    ou = _parse_ou(rou, human_date)
    btts = _parse_btts(rb, human_date)

    p1 = _pct(one["p1"], "1")
    px = _pct(one["px"], "X")
    p2 = _pct(one["p2"], "2")
    over = _pct(ou["over"], "Over 2.5")
    btts_yes = _pct(btts["btts_yes"], "BTTS Yes")

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
        "source_url": one.get("source_url") or urls["1x2"],
        "source": "Forebet public daily prediction pages (direct HTTP, no Apify)",
        "captured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "matched_forebet": {
            "home": r1.get("home") or home,
            "away": r1.get("away") or away,
            "match_date": iso_date,
            "match_time": None,
            "league": None,
        },
    }


def debug_match(home: str, away: str, date: Optional[str] = None, force: bool = False) -> Dict[str, Any]:
    start = time.time()
    snapshot = build_snapshot(1, home, away, date, force)
    return {
        "ok": True,
        "path": "direct_public_daily_pages",
        "elapsed_seconds": round(time.time() - start, 3),
        "resolved": snapshot,
    }


def health() -> Dict[str, Any]:
    return {
        "ok": True,
        "configured": True,
        "actor": ACTOR_ID,
        "cache_seconds": CACHE_SECONDS,
        "adapter": "forebet-direct-public-daily-pages",
        "actor_primary": False,
        "apify_used": False,
        "direct_public_pages": True,
        "parallel_market_fetch": True,
        "serial_browser_fallbacks": False,
        "dom_textcontent": True,
        "final_adapter": True,
    }
