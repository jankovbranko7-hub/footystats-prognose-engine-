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
APIFY_RUN_ENDPOINT = f"https://api.apify.com/v2/acts/{ACTOR_ID}/runs"
APIFY_LAST_RUN_ENDPOINT = f"https://api.apify.com/v2/acts/{ACTOR_ID}/runs/last?status=SUCCEEDED"
APIFY_DATASET_ENDPOINT = "https://api.apify.com/v2/datasets/{dataset_id}/items?clean=true&format=json"
CACHE_SECONDS = 30 * 60
_CACHE: Dict[str, Any] = {
    "at": 0.0,
    "items": None,
    "source": None,
    "dataset_id": None,
    "finished_at": None,
}
_LOCK = threading.Lock()
_REFRESH_LOCK = threading.Lock()
_LAST_REFRESH_TRIGGER_AT = 0.0


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


def _request_json(url: str, token: str, *, method: str = "GET", data: bytes | None = None, timeout: float = 20.0) -> Any:
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:500]
        raise ForebetAutoError(f"Apify HTTP {exc.code}: {detail}") from exc
    except Exception as exc:
        raise ForebetAutoError(f"Forebet-Automatik konnte Apify nicht erreichen: {exc}") from exc
    try:
        return json.loads(raw)
    except Exception as exc:
        raise ForebetAutoError("Apify lieferte kein gueltiges JSON.") from exc


def _latest_successful_items(token: str) -> Tuple[List[Dict[str, Any]], str, Optional[str]]:
    run_payload = _request_json(APIFY_LAST_RUN_ENDPOINT, token, timeout=15.0)
    if not isinstance(run_payload, dict):
        raise ForebetAutoError("Apify lieferte keine gueltigen Metadaten fuer den letzten erfolgreichen Lauf.")
    run = run_payload.get("data")
    if not isinstance(run, dict):
        raise ForebetAutoError("Apify meldete keinen letzten erfolgreichen Forebet-Lauf.")
    dataset_id = str(run.get("defaultDatasetId") or "").strip()
    if not dataset_id:
        raise ForebetAutoError("Der letzte erfolgreiche Forebet-Lauf hat kein Dataset.")

    items = _request_json(
        APIFY_DATASET_ENDPOINT.format(dataset_id=dataset_id),
        token,
        timeout=25.0,
    )
    if not isinstance(items, list):
        raise ForebetAutoError("Das letzte Forebet-Dataset ist keine Match-Liste.")
    clean = [item for item in items if isinstance(item, dict)]
    if not clean:
        raise ForebetAutoError("Das letzte Forebet-Dataset enthaelt keine Spiele.")
    return clean, dataset_id, str(run.get("finishedAt") or "") or None


def _run_actor_sync(token: str) -> List[Dict[str, Any]]:
    items = _request_json(
        APIFY_ENDPOINT + "?clean=true&format=json&timeout=150",
        token,
        method="POST",
        data=b"{}",
        timeout=165.0,
    )
    if not isinstance(items, list):
        raise ForebetAutoError("Apify lieferte keine Match-Liste.")
    clean = [item for item in items if isinstance(item, dict)]
    if not clean:
        raise ForebetAutoError("Apify lieferte keine Forebet-Spiele.")
    return clean


def _trigger_refresh_background(token: str) -> None:
    global _LAST_REFRESH_TRIGGER_AT
    now = time.time()
    with _REFRESH_LOCK:
        if now - _LAST_REFRESH_TRIGGER_AT < CACHE_SECONDS:
            return
        _LAST_REFRESH_TRIGGER_AT = now

    def worker() -> None:
        try:
            _request_json(
                APIFY_RUN_ENDPOINT,
                token,
                method="POST",
                data=b"{}",
                timeout=15.0,
            )
        except Exception:
            pass

    threading.Thread(target=worker, daemon=True, name="forebet-apify-refresh").start()


def _actor_items(force: bool = False) -> List[Dict[str, Any]]:
    token = os.environ.get("APIFY_TOKEN", "").strip()
    if not token:
        raise ForebetAutoError("APIFY_TOKEN fehlt. Fuer automatische Forebet-Abfragen muss der Token einmalig in Render gesetzt werden.")

    now = time.time()
    with _LOCK:
        cached = _CACHE.get("items")
        if cached is not None and not force and now - float(_CACHE.get("at") or 0) < CACHE_SECONDS:
            return list(cached)

        if not force:
            try:
                clean, dataset_id, finished_at = _latest_successful_items(token)
                _CACHE["items"] = clean
                _CACHE["at"] = now
                _CACHE["source"] = "latest_successful_dataset"
                _CACHE["dataset_id"] = dataset_id
                _CACHE["finished_at"] = finished_at
                _trigger_refresh_background(token)
                return list(clean)
            except ForebetAutoError:
                pass

        clean = _run_actor_sync(token)
        _CACHE["items"] = clean
        _CACHE["at"] = now
        _CACHE["source"] = "synchronous_actor_run"
        _CACHE["dataset_id"] = None
        _CACHE["finished_at"] = None
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
        "actor_fetch_mode": "latest_successful_dataset_first",
        "cache_source": _CACHE.get("source"),
        "dataset_id": _CACHE.get("dataset_id"),
        "dataset_finished_at": _CACHE.get("finished_at"),
    }
