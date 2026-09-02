from __future__ import annotations

import re
import time
from typing import Any, Dict, Iterable, List, Optional, Tuple

from forebet_auto import (
    ACTOR_ID,
    CACHE_SECONDS,
    ForebetAutoError,
    _actor_items,
    _match_score,
    _norm,
    _pct,
)


def _first(item: Dict[str, Any], aliases: Iterable[str]) -> Any:
    for key in aliases:
        value = item.get(key)
        if value not in (None, "", [], {}):
            return value
    return None


def _date_key(value: Any) -> str:
    digits = re.sub(r"[^0-9]", "", str(value or ""))
    if len(digits) != 8:
        return ""
    # YYYYMMDD
    if digits[:4].isdigit() and 1900 <= int(digits[:4]) <= 2200:
        return digits
    # DDMMYYYY -> YYYYMMDD
    if digits[-4:].isdigit() and 1900 <= int(digits[-4:]) <= 2200:
        return digits[-4:] + digits[2:4] + digits[:2]
    return digits


def _same_fixture(candidate: Dict[str, Any], best: Dict[str, Any], requested_date: Optional[str]) -> bool:
    if _norm(candidate.get("home")) != _norm(best.get("home")):
        return False
    if _norm(candidate.get("away")) != _norm(best.get("away")):
        return False

    wanted = _date_key(requested_date)
    cand_date = _date_key(candidate.get("matchDate"))
    best_date = _date_key(best.get("matchDate"))

    # A missing date on one of Forebet's page variants must not prevent merging.
    # Reject only when we have explicit evidence that the row belongs to another date.
    if wanted and cand_date and cand_date != wanted:
        return False
    if wanted and best_date and best_date != wanted:
        return False
    if not wanted and cand_date and best_date and cand_date != best_date:
        return False
    return True


def _merge_rows(rows: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    merged: Dict[str, Any] = {}
    source_fields: set[str] = set()
    row_count = 0
    for row in rows:
        row_count += 1
        for key, value in row.items():
            if value not in (None, "", [], {}):
                source_fields.add(str(key))
                if merged.get(key) in (None, "", [], {}):
                    merged[key] = value
    merged["_merged_row_count"] = row_count
    merged["_available_fields"] = sorted(source_fields)
    return merged


def select_match_merged(items: Iterable[Dict[str, Any]], home: str, away: str, date: Optional[str] = None) -> Dict[str, Any]:
    ranked: List[Tuple[float, float, float, float, Dict[str, Any]]] = []
    all_items = [item for item in items if isinstance(item, dict)]
    for item in all_items:
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

    same_rows = [item for item in all_items if _same_fixture(item, best, date)]
    merged = _merge_rows(same_rows or [best])

    # Ambiguity only applies to a genuinely different fixture, never another page row
    # for the same home/away pair.
    for other_score, _, _, _, other in ranked[1:]:
        if _same_fixture(other, best, date):
            continue
        if other_score > score - 0.035:
            raise ForebetAutoError(
                "Forebet-Zuordnung ist mehrdeutig: "
                f"{best.get('home')} - {best.get('away')} / "
                f"{other.get('home')} - {other.get('away')}."
            )
        break

    # Preserve identity fields from the best row if page-variant merging did not set them.
    for key in ("home", "away", "matchDate", "matchTime", "leagueName"):
        if merged.get(key) in (None, "") and best.get(key) not in (None, ""):
            merged[key] = best.get(key)
    return merged


def _required(item: Dict[str, Any], aliases: Iterable[str], label: str) -> Any:
    value = _first(item, aliases)
    if value in (None, ""):
        fields = ", ".join(item.get("_available_fields") or [])
        raise ForebetAutoError(
            f"Forebet-Feld {label} fehlt nach Zusammenfuehrung aller Match-Zeilen. "
            f"Verfuegbare Felder: {fields}"
        )
    return value


def build_snapshot(match_id: int, home: str, away: str, date: Optional[str] = None, force: bool = False) -> Dict[str, Any]:
    item = select_match_merged(_actor_items(force=force), home, away, date)

    p1 = _pct(_required(item, ["probability_1_percent", "probability1Percent", "homeProbability", "predictionHome"], "1"), "1")
    px = _pct(_required(item, ["probability_X_percent", "probability_x_percent", "probabilityXPercent", "drawProbability", "predictionDraw"], "X"), "X")
    p2 = _pct(_required(item, ["probability_2_percent", "probability2Percent", "awayProbability", "predictionAway"], "2"), "2")
    total = p1 + px + p2
    if not 95 <= total <= 105:
        raise ForebetAutoError(f"Forebet-1X2-Summe unplausibel: {total:.1f}%")

    btts_yes = _pct(_required(item, [
        "probability_btts_yes_percent",
        "probability_BTTS_yes_percent",
        "probabilityBttsYesPercent",
        "btts_yes_percent",
        "bttsYesPercent",
    ], "BTTS Yes"), "BTTS Yes")

    over25 = _pct(_required(item, [
        "probability_over_percent",
        "probability_over_2_5_percent",
        "probabilityOverPercent",
        "over25Percent",
    ], "Over 2.5"), "Over 2.5")

    predicted = str(_required(item, ["predictedScore", "predicted_score", "correctScore"], "Ergebnistipp")).strip().replace(" ", "")
    if not re.fullmatch(r"\d{1,2}[-:]\d{1,2}", predicted):
        raise ForebetAutoError("Forebet-Ergebnistipp ist ungueltig.")
    predicted = predicted.replace(":", "-")

    avg_raw = _required(item, ["averageGoals", "average_goals", "avgGoals"], "Avg. Goals")
    try:
        avg_goals = float(str(avg_raw).replace(",", "."))
    except Exception as exc:
        raise ForebetAutoError("Forebet Avg. Goals ist ungueltig.") from exc

    return {
        "schema": "forebet-auto-v2",
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
            "merged_rows": item.get("_merged_row_count", 1),
        },
    }


def debug_match(home: str, away: str, date: Optional[str] = None, force: bool = False) -> Dict[str, Any]:
    items = _actor_items(force=force)
    item = select_match_merged(items, home, away, date)
    safe_values: Dict[str, Any] = {}
    for key in item.get("_available_fields") or []:
        value = item.get(key)
        if isinstance(value, (str, int, float, bool)) and len(str(value)) <= 160:
            safe_values[key] = value
    return {
        "ok": True,
        "home": item.get("home"),
        "away": item.get("away"),
        "matchDate": item.get("matchDate"),
        "merged_rows": item.get("_merged_row_count", 1),
        "available_fields": item.get("_available_fields") or [],
        "values": safe_values,
    }


def health() -> Dict[str, Any]:
    from forebet_auto import health as base_health
    result = dict(base_health())
    result["adapter"] = "forebet-auto-v2"
    return result
