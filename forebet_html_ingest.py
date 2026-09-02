from __future__ import annotations

import html
import re
import time
from html.parser import HTMLParser
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

import forebet_auto_v9 as base
from forebet_auto import ForebetAutoError, _pct

_MAX_HTML_BYTES = 8 * 1024 * 1024
_FOREBET_ORIGIN = "https://www.forebet.com"
_MISSING = (None, "", [], {})


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
    if len(raw.strip()) < 300:
        raise ForebetAutoError("Forebet-HTML ist leer oder unvollstaendig.")
    return raw


def _parse_html(payload: bytes | str) -> _VisibleHTMLParser:
    raw = _decode_html(payload)
    parser = _VisibleHTMLParser()
    try:
        parser.feed(raw)
        parser.close()
    except Exception as exc:
        raise ForebetAutoError(f"Forebet-HTML konnte nicht gelesen werden: {exc}") from exc
    return parser


def parse_fixture(fixture: str) -> Tuple[str, str]:
    value = " ".join(str(fixture or "").replace("\xa0", " ").split()).strip()
    if not value:
        raise ForebetAutoError("Teamnamen fehlen in der Spielauswahl.")
    patterns = (
        r"\s+vs\.?\s+",
        r"\s+v\.?\s+",
        r"\s+[–—]\s+",
        r"\s+-\s+",
    )
    for pattern in patterns:
        parts = re.split(pattern, value, maxsplit=1, flags=re.I)
        if len(parts) == 2 and parts[0].strip() and parts[1].strip():
            return parts[0].strip(), parts[1].strip()
    raise ForebetAutoError(f"Spielauswahl konnte nicht in Heim/Auswaerts getrennt werden: {value}")


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


def _candidate_contains_teams(value: str, home: str, away: str) -> bool:
    hay = base._norm(value)
    hn, an = base._norm(home), base._norm(away)
    return bool(hn and an and hn in hay and an in hay)


def locate_match_url_from_html(payload: bytes | str, home: str, away: str, date: Optional[str] = None) -> str:
    parser = _parse_html(payload)
    found: List[str] = []
    for href, anchor_text in parser.links:
        absolute = urljoin(_FOREBET_ORIGIN, href)
        if not _valid_match_url(absolute):
            continue
        slug = urlparse(absolute).path.rsplit("/", 1)[-1]
        evidence = f"{slug} {anchor_text}"
        if _candidate_contains_teams(evidence, home, away):
            found.append(absolute)

    unique = list(dict.fromkeys(found))
    if not unique:
        raise ForebetAutoError(
            f"Forebet-Tagesseite enthaelt keinen sicheren Match-Link fuer {home} - {away}."
        )
    if len(unique) > 1:
        # The daily page itself is already date-scoped. Multiple different URLs
        # for the same pair are unsafe, so do not guess.
        raise ForebetAutoError(
            "Forebet-Tagesseite enthaelt mehrere unterschiedliche Match-Links fuer dieselbe Begegnung."
        )
    return unique[0]


def _split_compact_probabilities(digits: str, count: int) -> Optional[Tuple[float, ...]]:
    split = base._split_compact(digits, count)
    if split is None:
        return None
    return tuple(float(v) for v in split)


def _probability_suffix(digits: str) -> Optional[Tuple[float, float, float]]:
    for width in range(min(9, len(digits)), 2, -1):
        triple = _split_compact_probabilities(digits[-width:], 3)
        if triple is not None and 95 <= sum(triple) <= 105:
            return float(triple[0]), float(triple[1]), float(triple[2])
    return None


def _main_prediction_row(text: str) -> Optional[Dict[str, Any]]:
    normalized = re.sub(r"\s+", " ", text)
    marker_positions = [
        m.end() for m in re.finditer(r"\b1\s*X\s*2\b", normalized, re.I)
    ] or [0]
    triple_pattern = re.compile(
        r"(?=(?<!\d)(100|\d{1,2})\s+(100|\d{1,2})\s+(100|\d{1,2})(?!\d))"
    )
    score_pattern = re.compile(r"\b([12X])\s+(\d{1,2})\s*-\s*(\d{1,2})\b", re.I)
    avg_pattern = re.compile(r"(?<!\d)(\d(?:[.,]\d{2}))(?!\d)")

    for start in marker_positions[:8]:
        section = normalized[start : start + 2200]
        for triple_match in triple_pattern.finditer(section):
            triple = tuple(float(triple_match.group(i)) for i in (1, 2, 3))
            if not 95 <= sum(triple) <= 105:
                continue
            tail = section[triple_match.end() : triple_match.end() + 650]
            score_match = score_pattern.search(tail)
            if not score_match:
                continue
            avg_match = avg_pattern.search(tail[score_match.end() :])
            if not avg_match:
                continue
            avg = float(avg_match.group(1).replace(",", "."))
            if not 0 <= avg <= 10:
                continue
            return {
                "p1": triple[0],
                "px": triple[1],
                "p2": triple[2],
                "score": f"{int(score_match.group(2))}-{int(score_match.group(3))}",
                "avg": avg,
            }

    compact = re.sub(r"\s+", "", text)
    compact_patterns = (
        re.compile(
            r"([12X])(\d{1,2})-(\d{1,2})(\d{1,2})-(\d{1,2})(\d(?:[.,]\d{2}))",
            re.I,
        ),
        re.compile(r"([12X])(\d{1,2})-(\d{1,2})(\d(?:[.,]\d{2}))", re.I),
    )
    for pattern_index, pattern in enumerate(compact_patterns):
        for match in pattern.finditer(compact):
            if pattern_index == 0:
                _, home_score, away_score, dup_home, dup_away, avg_raw = match.groups()
                if (int(home_score), int(away_score)) != (int(dup_home), int(dup_away)):
                    continue
            else:
                _, home_score, away_score, avg_raw = match.groups()
            prefix = compact[max(0, match.start() - 18) : match.start()]
            block = re.search(r"(\d{3,12})$", prefix)
            if not block:
                continue
            triple = _probability_suffix(block.group(1))
            if triple is None:
                continue
            avg = float(avg_raw.replace(",", "."))
            if not 0 <= avg <= 10:
                continue
            return {
                "p1": triple[0],
                "px": triple[1],
                "p2": triple[2],
                "score": f"{int(home_score)}-{int(away_score)}",
                "avg": avg,
            }
    return None


def _last_section(compact: str, marker_pattern: str, limit: int = 3200) -> str:
    matches = list(re.finditer(marker_pattern, compact, re.I))
    if not matches:
        return ""
    pos = matches[-1].end()
    return compact[pos : pos + limit]


def _pair_from_compact_section(section: str, label_pattern: str) -> Optional[Tuple[float, float]]:
    if not section:
        return None
    for match in re.finditer(rf"(\d{{2,6}})({label_pattern})", section, re.I):
        pair = _split_compact_probabilities(match.group(1), 2)
        if pair is not None and 95 <= sum(pair) <= 105:
            return float(pair[0]), float(pair[1])
    return None


def _pair_from_spaced_section(text: str, marker_pattern: str, label_pattern: str) -> Optional[Tuple[float, float]]:
    marker = list(re.finditer(marker_pattern, text, re.I))
    if not marker:
        return None
    section = text[marker[-1].end() : marker[-1].end() + 1800]
    match = re.search(
        rf"(?<!\d)(100|\d{{1,2}})\s+(100|\d{{1,2}})\s+({label_pattern})\b",
        section,
        re.I,
    )
    if not match:
        return None
    pair = (float(match.group(1)), float(match.group(2)))
    return pair if 95 <= sum(pair) <= 105 else None


def _canonical_score(value: Any) -> str:
    text = str(value or "")
    pairs = []
    for h, a in re.findall(r"(\d{1,2})\s*[-:]\s*(\d{1,2})", text):
        hh, aa = int(h), int(a)
        if 0 <= hh <= 15 and 0 <= aa <= 15:
            pairs.append((hh, aa))
    unique = list(dict.fromkeys(pairs))
    if not unique:
        raise ForebetAutoError("Forebet-Ergebnistipp fehlt oder ist ungueltig.")
    return f"{unique[0][0]}-{unique[0][1]}"


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
    identity = base._norm(text[:60000])
    if base._norm(home) not in identity or base._norm(away) not in identity:
        raise ForebetAutoError("Forebet-Matchseite passt nicht zur ausgewaehlten Begegnung.")

    main = _main_prediction_row(text)
    if not main:
        raise ForebetAutoError("Forebet 1X2/Ergebnistipp/Avg. Goals konnten nicht gelesen werden.")

    compact = re.sub(r"\s+", "", text)
    ou_pair = _pair_from_compact_section(
        _last_section(compact, r"Under/Over2\.5"), r"Over|Under"
    )
    if ou_pair is None:
        ou_pair = _pair_from_spaced_section(text, r"Under\s*/?\s*Over\s*2[.,]?5", r"Over|Under")
    if ou_pair is None:
        raise ForebetAutoError("Forebet Under/Over 2.5 konnte nicht gelesen werden.")

    btts_pair = _pair_from_compact_section(
        _last_section(compact, r"NoYesPred"), r"Yes|No"
    )
    if btts_pair is None:
        btts_pair = _pair_from_spaced_section(text, r"No\s+Yes\s+Pred", r"Yes|No")
    if btts_pair is None:
        raise ForebetAutoError("Forebet BTTS konnte nicht gelesen werden.")

    # Forebet's tables are ordered Under/Over and No/Yes.
    under, over = ou_pair
    btts_no, btts_yes = btts_pair

    p1 = _pct(main["p1"], "1")
    px = _pct(main["px"], "X")
    p2 = _pct(main["p2"], "2")
    if not 95 <= p1 + px + p2 <= 105:
        raise ForebetAutoError("Forebet-1X2-Summe ist unplausibel.")
    over = _pct(over, "Over 2.5")
    under = _pct(under, "Under 2.5")
    if not 95 <= under + over <= 105:
        raise ForebetAutoError("Forebet-Over/Under-Summe ist unplausibel.")
    btts_yes = _pct(btts_yes, "BTTS Yes")
    btts_no = _pct(btts_no, "BTTS No")
    if not 95 <= btts_yes + btts_no <= 105:
        raise ForebetAutoError("Forebet-BTTS-Summe ist unplausibel.")

    try:
        avg = float(str(main["avg"]).replace(",", "."))
    except Exception as exc:
        raise ForebetAutoError("Forebet Avg. Goals fehlt oder ist ungueltig.") from exc
    if not 0 <= avg <= 10:
        raise ForebetAutoError("Forebet Avg. Goals liegt ausserhalb 0-10.")

    return {
        "schema": "forebet-auto-v1",
        "match_id": int(match_id),
        "home_win": round(p1, 3),
        "draw": round(px, 3),
        "away_win": round(p2, 3),
        "btts_yes": round(btts_yes, 3),
        "over_2_5": round(over, 3),
        "predicted_score": _canonical_score(main["score"]),
        "average_goals": round(avg, 3),
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
    daily = b'''<html><body><div><a href="/en/football/matches/dundee-st-johnstone-2476454">Dundee - St. Johnstone</a></div></body></html>'''
    url = locate_match_url_from_html(daily, "Dundee", "St. Johnstone", "2026-09-02")
    if url != "https://www.forebet.com/en/football/matches/dundee-st-johnstone-2476454":
        raise AssertionError(url)

    dundee = b'''<html><body>
    <h1>Dundee - St. Johnstone</h1>
    <div>1 X 2 Pred Correct Score Avg. Goals 47 27 26 1 2-0 2 - 0 2.25</div>
    <div>Under/Over 2.5 55 45 Under 2.25</div>
    <div>No Yes Pred 51 49 No 2-0</div>
    </body></html>'''
    result = parse_match_html(dundee, 8558476, "Dundee", "St. Johnstone", "2026-09-02", url)
    expected = (47.0, 27.0, 26.0, 49.0, 45.0, "2-0", 2.25)
    actual = (
        result["home_win"], result["draw"], result["away_win"], result["btts_yes"],
        result["over_2_5"], result["predicted_score"], result["average_goals"],
    )
    if actual != expected:
        raise AssertionError((actual, expected))

    luzern_url = "https://www.forebet.com/en/football/matches/fc-luzern-fc-vaduz-9999999"
    luzern = b'''<html><body>
    <h1>FC Luzern - FC Vaduz</h1>
    <div>1 X 2 Pred Correct Score Avg. Goals 53 26 21 1 3-2 3 - 2 3.38</div>
    <div>Under/Over 2.5 32 68 Over 3.38</div>
    <div>No Yes Pred 19 81 Yes 3-2</div>
    </body></html>'''
    result2 = parse_match_html(luzern, 8554458, "Luzern", "Vaduz", "2026-09-02", luzern_url)
    if (
        result2["home_win"], result2["draw"], result2["away_win"], result2["btts_yes"],
        result2["over_2_5"], result2["predicted_score"], result2["average_goals"],
    ) != (53.0, 26.0, 21.0, 81.0, 68.0, "3-2", 3.38):
        raise AssertionError(result2)

    return {"ok": True, "dundee": result, "luzern": result2}
