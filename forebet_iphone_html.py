from __future__ import annotations

import html
import re
import time
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

from forebet_auto import ForebetAutoError, _norm, _pct

_MAX_HTML_BYTES = 8 * 1024 * 1024
_FOREBET_ORIGIN = "https://www.forebet.com"


class _VisibleHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self._anchor_stack: List[Dict[str, Any]] = []
        self.text_parts: List[str] = []
        self.links: List[Tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "noscript", "svg"}:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if tag == "a":
            amap = {str(k).lower(): str(v or "") for k, v in attrs}
            self._anchor_stack.append({"href": amap.get("href", "").strip(), "parts": []})
        elif tag in {"br", "p", "div", "tr", "td", "th", "li", "section", "article"}:
            self.text_parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "noscript", "svg"}:
            if self._skip_depth:
                self._skip_depth -= 1
            return
        if self._skip_depth:
            return
        if tag == "a" and self._anchor_stack:
            anchor = self._anchor_stack.pop()
            href = str(anchor.get("href") or "").strip()
            text = " ".join(" ".join(anchor.get("parts") or []).split())
            if href:
                self.links.append((href, text))
        elif tag in {"p", "div", "tr", "td", "th", "li", "section", "article"}:
            self.text_parts.append(" ")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        value = html.unescape(str(data or "")).replace("\xa0", " ")
        if not value.strip():
            return
        self.text_parts.append(value)
        for anchor in self._anchor_stack:
            anchor["parts"].append(value)

    @property
    def text(self) -> str:
        return " ".join(" ".join(self.text_parts).split())


def _decode_html(payload: bytes | str) -> str:
    if isinstance(payload, bytes):
        if len(payload) > _MAX_HTML_BYTES:
            raise ForebetAutoError("Forebet-HTML ist groesser als 8 MB.")
        raw = payload.decode("utf-8", "replace")
    else:
        raw = str(payload or "")
        if len(raw.encode("utf-8", "ignore")) > _MAX_HTML_BYTES:
            raise ForebetAutoError("Forebet-HTML ist groesser als 8 MB.")
    if len(raw.strip()) < 50:
        raise ForebetAutoError("Forebet-HTML ist leer oder unvollstaendig.")
    return raw


def _parse_html(payload: bytes | str) -> _VisibleHTMLParser:
    parser = _VisibleHTMLParser()
    parser.feed(_decode_html(payload))
    parser.close()
    return parser


def _valid_match_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    return (
        parsed.scheme == "https"
        and (parsed.hostname or "").lower() in {"forebet.com", "www.forebet.com"}
        and "/football/matches/" in parsed.path
    )


def locate_match_url_from_html(payload: bytes | str, home: str, away: str, date: Optional[str] = None) -> str:
    parser = _parse_html(payload)
    home_n, away_n = _norm(home), _norm(away)
    found: List[str] = []
    for href, anchor_text in parser.links:
        absolute = urljoin(_FOREBET_ORIGIN, href)
        if not _valid_match_url(absolute):
            continue
        slug = urlparse(absolute).path.rsplit("/", 1)[-1]
        evidence = _norm(f"{slug} {anchor_text}")
        if home_n and away_n and home_n in evidence and away_n in evidence:
            found.append(absolute)
    unique = list(dict.fromkeys(found))
    if not unique:
        raise ForebetAutoError(f"Forebet-Tagesseite enthaelt keinen sicheren Match-Link fuer {home} - {away}.")
    if len(unique) > 1:
        raise ForebetAutoError("Forebet-Tagesseite enthaelt mehrere unterschiedliche Match-Links fuer dieselbe Begegnung.")
    return unique[0]


def _split_compact_probabilities(digits: str, count: int) -> Optional[Tuple[float, ...]]:
    solutions: List[Tuple[int, ...]] = []

    def walk(pos: int, parts: List[int]) -> None:
        remaining = count - len(parts)
        if remaining == 0:
            if pos == len(digits) and sum(parts) == 100:
                solutions.append(tuple(parts))
            return
        chars = len(digits) - pos
        if chars < remaining or chars > remaining * 3:
            return
        for width in (1, 2, 3):
            end = pos + width
            if end > len(digits):
                continue
            token = digits[pos:end]
            if len(token) > 1 and token.startswith("0"):
                continue
            value = int(token)
            if not 0 <= value <= 100 or sum(parts) + value > 100:
                continue
            walk(end, parts + [value])

    walk(0, [])
    unique = list(dict.fromkeys(solutions))
    return tuple(float(v) for v in unique[0]) if len(unique) == 1 else None


def _probability_suffix(digits: str) -> Optional[Tuple[float, float, float]]:
    for width in range(min(9, len(digits)), 2, -1):
        triple = _split_compact_probabilities(digits[-width:], 3)
        if triple is not None:
            return float(triple[0]), float(triple[1]), float(triple[2])
    return None


def _main_prediction_row(text: str) -> Optional[Dict[str, Any]]:
    normalized = re.sub(r"\s+", " ", text)
    marker_positions = [m.end() for m in re.finditer(r"\b1\s*X\s*2\b", normalized, re.I)] or [0]
    triple_pattern = re.compile(r"(?=(?<!\d)(100|\d{1,2})\s+(100|\d{1,2})\s+(100|\d{1,2})(?!\d))")
    score_pattern = re.compile(r"\b([12X])\s+(\d{1,2})\s*-\s*(\d{1,2})\b", re.I)
    avg_pattern = re.compile(r"(?<!\d)(\d(?:[.,]\d{2}))(?!\d)")
    for start in marker_positions[:8]:
        section = normalized[start:start + 2500]
        for tm in triple_pattern.finditer(section):
            triple = tuple(float(tm.group(i)) for i in (1, 2, 3))
            if not 95 <= sum(triple) <= 105:
                continue
            tail = section[tm.end():tm.end() + 700]
            sm = score_pattern.search(tail)
            if not sm:
                continue
            am = avg_pattern.search(tail[sm.end():])
            if not am:
                continue
            avg = float(am.group(1).replace(",", "."))
            if 0 <= avg <= 10:
                return {
                    "p1": triple[0],
                    "px": triple[1],
                    "p2": triple[2],
                    "score": f"{int(sm.group(2))}-{int(sm.group(3))}",
                    "avg": avg,
                }
    compact = re.sub(r"\s+", "", text)
    pat = re.compile(r"([12X])(\d{1,2})-(\d{1,2})(?:\d{1,2}-\d{1,2})?(\d(?:[.,]\d{2}))", re.I)
    for m in pat.finditer(compact):
        prefix = compact[max(0, m.start() - 18):m.start()]
        block = re.search(r"(\d{3,12})$", prefix)
        if not block:
            continue
        triple = _probability_suffix(block.group(1))
        if triple is None:
            continue
        avg = float(m.group(4).replace(",", "."))
        if 0 <= avg <= 10:
            return {
                "p1": triple[0],
                "px": triple[1],
                "p2": triple[2],
                "score": f"{int(m.group(2))}-{int(m.group(3))}",
                "avg": avg,
            }
    return None


def _section_after(text: str, marker_pattern: str, limit: int = 2200) -> str:
    matches = list(re.finditer(marker_pattern, text, re.I))
    if not matches:
        return ""
    return text[matches[-1].end():matches[-1].end() + limit]


def _pair(text: str, marker_pattern: str, label_pattern: str) -> Optional[Tuple[float, float]]:
    section = _section_after(text, marker_pattern)
    if not section:
        return None
    spaced = re.search(
        rf"(?<!\d)(100|\d{{1,2}})\s+(100|\d{{1,2}})\s+({label_pattern})\b",
        section,
        re.I,
    )
    if spaced:
        pair = (float(spaced.group(1)), float(spaced.group(2)))
        if 95 <= sum(pair) <= 105:
            return pair
    compact = re.sub(r"\s+", "", section)
    for m in re.finditer(rf"(\d{{2,6}})({label_pattern})", compact, re.I):
        pair = _split_compact_probabilities(m.group(1), 2)
        if pair is not None:
            return float(pair[0]), float(pair[1])
    return None


def parse_match_html(
    payload: bytes | str,
    match_id: int,
    home: str,
    away: str,
    date: Optional[str],
    source_url: str,
) -> Dict[str, Any]:
    if not _valid_match_url(source_url):
        raise ForebetAutoError("Forebet-Quell-URL ist kein gueltiger Match-Link.")
    parser = _parse_html(payload)
    text = parser.text
    identity = _norm(text[:60000])
    if _norm(home) not in identity or _norm(away) not in identity:
        raise ForebetAutoError("Forebet-Matchseite passt nicht zur ausgewaehlten Begegnung.")
    main = _main_prediction_row(text)
    if not main:
        raise ForebetAutoError("Forebet 1X2/Ergebnistipp/Avg. Goals konnten nicht gelesen werden.")
    ou = _pair(text, r"Under\s*/?\s*Over\s*2[.,]?\s*5", r"Over|Under")
    btts = _pair(text, r"(?:No\s+Yes\s+Pred|Both\s+To\s+Score|Btts)", r"Yes|No")
    if ou is None:
        raise ForebetAutoError("Forebet Under/Over 2.5 konnte nicht gelesen werden.")
    if btts is None:
        raise ForebetAutoError("Forebet BTTS konnte nicht gelesen werden.")
    under, over = ou
    btts_no, btts_yes = btts
    p1, px, p2 = (_pct(main["p1"], "1"), _pct(main["px"], "X"), _pct(main["p2"], "2"))
    if not 95 <= p1 + px + p2 <= 105:
        raise ForebetAutoError("Forebet-1X2-Summe ist unplausibel.")
    if not 95 <= under + over <= 105:
        raise ForebetAutoError("Forebet-Over/Under-Summe ist unplausibel.")
    if not 95 <= btts_yes + btts_no <= 105:
        raise ForebetAutoError("Forebet-BTTS-Summe ist unplausibel.")
    return {
        "schema": "forebet-auto-v1",
        "match_id": int(match_id),
        "home_win": round(p1, 3),
        "draw": round(px, 3),
        "away_win": round(p2, 3),
        "btts_yes": round(float(btts_yes), 3),
        "over_2_5": round(float(over), 3),
        "predicted_score": str(main["score"]),
        "average_goals": round(float(main["avg"]), 3),
        "source_url": source_url,
        "source": "Forebet public match page fetched by iPhone Shortcut; parsed by Render",
        "captured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "matched_forebet": {
            "home": home,
            "away": away,
            "match_date": date,
            "match_time": None,
            "league": None,
        },
    }


def self_test() -> Dict[str, Any]:
    daily = b'''<html><body><div><a href="/en/football/matches/toulouse-lille-2495944">Toulouse - Lille</a></div></body></html>'''
    url = locate_match_url_from_html(daily, "Toulouse", "Lille", "2026-09-03")
    page = b'''<html><body>
    <h1>Toulouse - Lille</h1>
    <div>1 X 2 Pred Correct Score Avg. Goals 18 28 55 2 0-3 0 - 3 2.54</div>
    <div>Under/Over 2.5 49 51 Over 2.54</div>
    <div>No Yes Pred 51 49 No 0-3</div>
    </body></html>'''
    result = parse_match_html(page, 8548724, "Toulouse", "Lille", "2026-09-03", url)
    expected = (18.0, 28.0, 55.0, 49.0, 51.0, "0-3", 2.54)
    actual = (
        result["home_win"],
        result["draw"],
        result["away_win"],
        result["btts_yes"],
        result["over_2_5"],
        result["predicted_score"],
        result["average_goals"],
    )
    if actual != expected:
        raise AssertionError((actual, expected))
    return {"ok": True, "toulouse_lille": result}


def register_routes(app) -> None:
    """Register iPhone HTML ingest endpoints on the existing FastAPI app."""
    from fastapi import Request
    from fastapi.responses import JSONResponse

    @app.get("/api/forebet-auto/iphone-html-health")
    def iphone_html_health():
        try:
            test = self_test()
            return {
                "ok": True,
                "mode": "iphone-html",
                "apify_required": False,
                "server_forebet_fetch_required": False,
                "toulouse_lille_test": test["toulouse_lille"]["predicted_score"],
            }
        except Exception as exc:
            return JSONResponse(
                status_code=500,
                content={
                    "ok": False,
                    "phase": "FOREBET_IPHONE_HTML_SELF_TEST_FAILED",
                    "error": str(exc),
                },
            )

    @app.post("/api/forebet-auto/locate-json")
    async def locate_json(request: Request):
        try:
            body = await request.json()
            html_text = body.get("html") if isinstance(body, dict) else None
            home = str((body or {}).get("home") or "").strip()
            away = str((body or {}).get("away") or "").strip()
            date = str((body or {}).get("date") or "").strip() or None
            source_url = locate_match_url_from_html(html_text or "", home=home, away=away, date=date)
            return {
                "ok": True,
                "home": home,
                "away": away,
                "date": date,
                "source_url": source_url,
            }
        except Exception as exc:
            return {
                "ok": False,
                "phase": "FOREBET_HTML_LOCATE_FAILED",
                "error": str(exc),
                "source_url": "https://www.forebet.com/",
            }

    @app.post("/api/forebet-auto/parse-json")
    async def parse_json(request: Request):
        body: Dict[str, Any] = {}
        try:
            body = await request.json()
            if not isinstance(body, dict):
                raise ForebetAutoError("Forebet-HTML-Request ist kein Wörterbuch.")
            match_id = int(body.get("match_id") or 0)
            home = str(body.get("home") or "").strip()
            away = str(body.get("away") or "").strip()
            date = str(body.get("date") or "").strip() or None
            source_url = str(body.get("source_url") or "").strip()
            result = parse_match_html(
                body.get("html") or "",
                match_id=match_id,
                home=home,
                away=away,
                date=date,
                source_url=source_url,
            )
            return {"ok": True, **result}
        except Exception as exc:
            return {
                "ok": False,
                "schema": "forebet-auto-error-v1",
                "phase": "FOREBET_HTML_PARSE_FAILED",
                "error": str(exc),
                "match_id": int(body.get("match_id") or 0) if isinstance(body, dict) else 0,
                "home": str(body.get("home") or "") if isinstance(body, dict) else "",
                "away": str(body.get("away") or "") if isinstance(body, dict) else "",
                "match_date": str(body.get("date") or "") if isinstance(body, dict) else "",
                "source_url": str(body.get("source_url") or "https://www.forebet.com/") if isinstance(body, dict) else "https://www.forebet.com/",
                "odds_used": False,
            }
