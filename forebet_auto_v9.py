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

_MISSING = (None, "", [], {})


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


def build_snapshot(match_id: int, home: str, away: str, date: Optional[str] = None, force: bool = False) -> Dict[str, Any]:
    item = _pick_match(_actor_items(force=force), home, away, date)
    values = _resolved(item)

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

    source_url = (
        _first_direct(item, ["matchUrl", "match_url", "url", "sourceUrl", "source_url"])
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
    values = _resolved(item)
    return {
        "ok": True,
        "requested": {"home": home, "away": away, "date": date},
        "matched": {
            "home": item.get("home"),
            "away": item.get("away"),
            "matchDate": item.get("matchDate"),
            "leagueName": item.get("leagueName"),
        },
        "resolved": values,
        "available_keys": sorted(str(k) for k in item.keys()),
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
        "schema_tolerant": True,
    }
