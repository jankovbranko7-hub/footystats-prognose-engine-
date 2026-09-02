from __future__ import annotations

import re
import time
from typing import Any, Dict, Iterable, List, Optional, Tuple

from forebet_auto import (
    ACTOR_ID,
    CACHE_SECONDS,
    ForebetAutoError,
    _actor_items,
    _norm,
    _pct,
    _similarity,
)

_REQUIRED_FIELDS = (
    "probability_1_percent",
    "probability_X_percent",
    "probability_2_percent",
    "probability_over_percent",
    "probability_btts_yes_percent",
    "predictedScore",
    "averageGoals",
)


def _date_key(value: Any) -> str:
    digits = re.sub(r"[^0-9]", "", str(value or ""))
    if len(digits) != 8:
        return ""
    if 1900 <= int(digits[:4]) <= 2200:
        return digits
    if 1900 <= int(digits[-4:]) <= 2200:
        return digits[-4:] + digits[2:4] + digits[:2]
    return ""


def _merge_rows(rows: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    merged: Dict[str, Any] = {}
    for row in rows:
        for key, value in row.items():
            if value not in (None, "", [], {}) and merged.get(key) in (None, "", [], {}):
                merged[key] = value
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
        best = max(exact, key=lambda row: sum(row.get(k) not in (None, "", [], {}) for k in _REQUIRED_FIELDS))
        same = [row for row in exact if _same_fixture(row, best, wanted_date)]
        merged = _merge_rows(same or [best])
        return merged

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


def _canonical_score(value: Any) -> str:
    text = str(value or "").strip()
    pairs = []
    for h, a in re.findall(r"(\d{1,2})\s*-\s*(\d{1,2})", text):
        hh, aa = int(h), int(a)
        if 0 <= hh <= 15 and 0 <= aa <= 15:
            pairs.append((hh, aa))
    unique = list(dict.fromkeys(pairs))
    if len(unique) == 1:
        return f"{unique[0][0]}-{unique[0][1]}"

    compact = re.sub(r"\s+", "", text)
    normal = re.fullmatch(r"(\d{1,2})[-:](\d{1,2})", compact)
    if normal:
        h, a = int(normal.group(1)), int(normal.group(2))
        if 0 <= h <= 15 and 0 <= a <= 15:
            return f"{h}-{a}"
    raise ForebetAutoError("Forebet-Ergebnistipp fehlt oder ist ungueltig.")


def _float_value(value: Any, field: str) -> float:
    try:
        number = float(str(value).strip().replace(",", "."))
    except Exception as exc:
        raise ForebetAutoError(f"Forebet-Feld {field} fehlt oder ist ungueltig.") from exc
    return number


def build_snapshot(match_id: int, home: str, away: str, date: Optional[str] = None, force: bool = False) -> Dict[str, Any]:
    item = _pick_match(_actor_items(force=force), home, away, date)

    p1 = _pct(item.get("probability_1_percent"), "1")
    px = _pct(item.get("probability_X_percent"), "X")
    p2 = _pct(item.get("probability_2_percent"), "2")
    if not 95 <= p1 + px + p2 <= 105:
        raise ForebetAutoError(f"Forebet-1X2-Summe unplausibel: {p1 + px + p2:.1f}%")

    over = _pct(item.get("probability_over_percent"), "Over 2.5")
    btts = _pct(item.get("probability_btts_yes_percent"), "BTTS Yes")

    under_raw = item.get("probability_under_percent")
    if under_raw not in (None, ""):
        under = _pct(under_raw, "Under 2.5")
        if not 95 <= under + over <= 105:
            raise ForebetAutoError("Forebet-Over/Under-Summe ist unplausibel.")

    btts_no_raw = item.get("probability_btts_no_percent")
    if btts_no_raw not in (None, ""):
        btts_no = _pct(btts_no_raw, "BTTS No")
        if not 95 <= btts + btts_no <= 105:
            raise ForebetAutoError("Forebet-BTTS-Summe ist unplausibel.")

    predicted = _canonical_score(item.get("predictedScore"))
    avg = _float_value(item.get("averageGoals"), "Avg. Goals")
    if not 0 <= avg <= 10:
        raise ForebetAutoError("Forebet Avg. Goals liegt ausserhalb 0-10.")

    source_url = (
        item.get("matchUrl")
        or item.get("match_url")
        or item.get("url")
        or "https://www.forebet.com/"
    )

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
        "source_url": source_url,
        "source": "Forebet public prediction via Apify 6-in-1 actor",
        "captured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "matched_forebet": {
            "home": item.get("home"),
            "away": item.get("away"),
            "match_date": item.get("matchDate"),
            "match_time": item.get("matchTime"),
            "league": item.get("leagueName"),
        },
    }


def debug_match(home: str, away: str, date: Optional[str] = None, force: bool = False) -> Dict[str, Any]:
    item = _pick_match(_actor_items(force=force), home, away, date)
    fields = {key: item.get(key) for key in _REQUIRED_FIELDS}
    return {
        "ok": True,
        "requested": {"home": home, "away": away, "date": date},
        "matched": {
            "home": item.get("home"),
            "away": item.get("away"),
            "matchDate": item.get("matchDate"),
            "leagueName": item.get("leagueName"),
        },
        "fields": fields,
    }


def health() -> Dict[str, Any]:
    return {
        "ok": True,
        "configured": True,
        "actor": ACTOR_ID,
        "cache_seconds": CACHE_SECONDS,
        "adapter": "forebet-auto-v9-direct-first",
        "actor_only": True,
        "browser_scraping": False,
    }
