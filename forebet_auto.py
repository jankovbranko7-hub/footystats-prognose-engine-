from __future__ import annotations

import difflib
import json
import os
import re
import threading
import time
import unicodedata
import urllib.error
import urllib.request
from typing import Any, Dict, Iterable, List, Optional, Tuple


ACTOR_ID = "locos08~forebet-predictions-scraper"
APIFY_ENDPOINT = f"https://api.apify.com/v2/acts/{ACTOR_ID}/run-sync-get-dataset-items"
CACHE_SECONDS = 30 * 60
_CACHE: Dict[str, Any] = {"at": 0.0, "items": None}
_LOCK = threading.Lock()


class ForebetAutoError(RuntimeError):
    pass


def _norm(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).lower()
    text = re.sub(r"\b(fc|cf|sc|afc|ac|fk|sk|club|cd|ca|sv|vfb|vfl|u21|u23)\b", " ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def _similarity(a: Any, b: Any) -> float:
    aa, bb = _norm(a), _norm(b)
    if not aa or not bb:
        return 0.0
    if aa == bb:
        return 1.0
    seq = difflib.SequenceMatcher(None, aa, bb).ratio()
    aset, bset = set(aa.split()), set(bb.split())
    token = len(aset & bset) / max(1, len(aset | bset))
    containment = 0.96 if aa in bb or bb in aa else 0.0
    return max(seq, token, containment)


def _pct(value: Any, field: str) -> float:
    try:
        number = float(str(value).strip().replace("%", "").replace(",", "."))
    except Exception as exc:
        raise ForebetAutoError(f"Forebet-Feld {field} fehlt oder ist ungueltig.") from exc
    if not 0 <= number <= 100:
        raise ForebetAutoError(f"Forebet-Feld {field} liegt ausserhalb 0-100.")
    return number


def _actor_items(force: bool = False) -> List[Dict[str, Any]]:
    token = os.environ.get("APIFY_TOKEN", "").strip()
    if not token:
        raise ForebetAutoError("APIFY_TOKEN fehlt. Fuer automatische Forebet-Abfragen muss der Token einmalig in Render gesetzt werden.")

    now = time.time()
    with _LOCK:
        cached = _CACHE.get("items")
        if cached is not None and not force and now - float(_CACHE.get("at") or 0) < CACHE_SECONDS:
            return list(cached)

        request = urllib.request.Request(
            APIFY_ENDPOINT + "?clean=true&format=json&timeout=150",
            data=b"{}",
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Authorization": f"Bearer {token}",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=165) as response:
                payload = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:500]
            raise ForebetAutoError(f"Apify HTTP {exc.code}: {detail}") from exc
        except Exception as exc:
            raise ForebetAutoError(f"Forebet-Automatik konnte Apify nicht erreichen: {exc}") from exc

        try:
            items = json.loads(payload)
        except Exception as exc:
            raise ForebetAutoError("Apify lieferte kein gueltiges JSON.") from exc
        if not isinstance(items, list):
            raise ForebetAutoError("Apify lieferte keine Match-Liste.")
        clean = [item for item in items if isinstance(item, dict)]
        _CACHE["items"] = clean
        _CACHE["at"] = now
        return list(clean)


def _date_score(requested: Optional[str], candidate: Any) -> float:
    if not requested:
        return 0.0
    rq = re.sub(r"[^0-9]", "", str(requested))
    cd = re.sub(r"[^0-9]", "", str(candidate or ""))
    if not rq or not cd:
        return 0.0
    if rq == cd:
        return 0.18
    if len(rq) == 8 and len(cd) == 8 and rq[:4].isdigit():
        swapped = rq[6:8] + rq[4:6] + rq[:4]
        if swapped == cd:
            return 0.18
    return -0.12


def _match_score(item: Dict[str, Any], home: str, away: str, date: Optional[str]) -> Tuple[float, float, float]:
    hs = _similarity(home, item.get("home"))
    aw = _similarity(away, item.get("away"))
    score = 0.5 * hs + 0.5 * aw + _date_score(date, item.get("matchDate"))
    return score, hs, aw


def select_match(items: Iterable[Dict[str, Any]], home: str, away: str, date: Optional[str] = None) -> Dict[str, Any]:
    ranked = []
    for item in items:
        score, hs, aw = _match_score(item, home, away, date)
        ranked.append((score, min(hs, aw), hs, aw, item))
    if not ranked:
        raise ForebetAutoError("Forebet lieferte keine Spiele.")
    ranked.sort(key=lambda row: (row[0], row[1]), reverse=True)
    score, minimum, hs, aw, best = ranked[0]
    if minimum < 0.62 or score < 0.70:
        raise ForebetAutoError(
            "Kein Forebet-Spiel konnte sicher zugeordnet werden. "
            f"Bester Treffer: {best.get('home')} - {best.get('away')} "
            f"(Home {hs:.2f}, Away {aw:.2f})."
        )
    if len(ranked) > 1 and ranked[1][0] > score - 0.035:
        other = ranked[1][4]
        raise ForebetAutoError(
            "Forebet-Zuordnung ist mehrdeutig: "
            f"{best.get('home')} - {best.get('away')} / "
            f"{other.get('home')} - {other.get('away')}."
        )
    return best


def build_snapshot(match_id: int, home: str, away: str, date: Optional[str] = None, force: bool = False) -> Dict[str, Any]:
    item = select_match(_actor_items(force=force), home, away, date)

    p1 = _pct(item.get("probability_1_percent"), "1")
    px = _pct(item.get("probability_X_percent"), "X")
    p2 = _pct(item.get("probability_2_percent"), "2")
    total = p1 + px + p2
    if not 95 <= total <= 105:
        raise ForebetAutoError(f"Forebet-1X2-Summe unplausibel: {total:.1f}%")

    btts_yes = _pct(item.get("probability_btts_yes_percent"), "BTTS Yes")
    over25 = _pct(item.get("probability_over_percent"), "Over 2.5")
    predicted = str(item.get("predictedScore") or "").strip().replace(" ", "")
    if not re.fullmatch(r"\d{1,2}[-:]\d{1,2}", predicted):
        raise ForebetAutoError("Forebet-Ergebnistipp fehlt oder ist ungueltig.")
    predicted = predicted.replace(":", "-")
    try:
        avg_goals = float(str(item.get("averageGoals")).replace(",", "."))
    except Exception as exc:
        raise ForebetAutoError("Forebet Avg. Goals fehlt oder ist ungueltig.") from exc

    return {
        "schema": "forebet-auto-v1",
        "match_id": int(match_id),
        "home_win": round(p1, 3),
        "draw": round(px, 3),
        "away_win": round(p2, 3),
        "btts_yes": round(btts_yes, 3),
        "over_2_5": round(over25, 3),
        "predicted_score": predicted,
        "average_goals": round(avg_goals, 3),
        "source_url": "https://www.forebet.com/",
        "source": "Forebet public prediction via Apify automated scraper",
        "captured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "matched_forebet": {
            "home": item.get("home"),
            "away": item.get("away"),
            "match_date": item.get("matchDate"),
            "match_time": item.get("matchTime"),
            "league": item.get("leagueName"),
        },
    }


def health() -> Dict[str, Any]:
    return {
        "ok": True,
        "configured": bool(os.environ.get("APIFY_TOKEN", "").strip()),
        "actor": ACTOR_ID,
        "cache_seconds": CACHE_SECONDS,
    }
