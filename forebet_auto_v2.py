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


def _same_match(candidate: Dict[str, Any], best: Dict[str, Any]) -> bool:
    return (
        _norm(candidate.get("home")) == _norm(best.get("home"))
        and _norm(candidate.get("away")) == _norm(best.get("away"))
        and str(candidate.get("matchDate") or "") == str(best.get("matchDate") or "")
    )


def _merge_rows(rows: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    merged: Dict[str, Any] = {}
    for row in rows:
        for key, value in row.items():
            if value not in (None, "", [], {}) and merged.get(key) in (None, "", [], {}):
                merged[key] = value
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

    # Duplicate rows from Forebet's 1X2 / O-U / BTTS pages are one match, not ambiguity.
    same_rows = [item for item in all_items if _same_match(item, best)]
    merged = _merge_rows(same_rows or [best])

    # Ambiguity is only a different fixture with a nearly identical score.
    for other_score, _, _, _, other in ranked[1:]:
        if _same_match(other, best):
            continue
        if other_score > score - 0.035:
            raise ForebetAutoError(
                "Forebet-Zuordnung ist mehrdeutig: "
                f"{best.get('home')} - {best.get('away')} / "
                f"{other.get('home')} - {other.get('away')}."
            )
        break

    merged["_merged_row_count"] = len(same_rows or [best])
    merged["_available_fields"] = sorted(
        key for key, value in merged.items()
        if value not in (None, "", [], {}) and not key.startswith("_")
    )
    return merged


def build_snapshot(match_id: int, home: str, away: str, date: Optional[str] = None, force: bool = False) -> Dict[str, Any]:
    item = select_match_merged(_actor_items(force=force), home, away, date)

    p1 = _pct(_first(item, ["probability_1_percent", "probability1Percent", "homeProbability"]), "1")
    px = _pct(_first(item, ["probability_X_percent", "probability_x_percent", "probabilityXPercent", "drawProbability"]), "X")
    p2 = _pct(_first(item, ["probability_2_percent", "probability2Percent", "awayProbability"]), "2")
    total = p1 + px + p2
    if not 95 <= total <= 105:
        raise ForebetAutoError(f"Forebet-1X2-Summe unplausibel: {total:.1f}%")

    btts_raw = _first(item, [
        "probability_btts_yes_percent",
        "probability_BTTS_yes_percent",
        "probabilityBttsYesPercent",
        "btts_yes_percent",
        "bttsYesPercent",
    ])
    if btts_raw in (None, ""):
        fields = ", ".join(item.get("_available_fields") or [])
        raise ForebetAutoError(
            "Forebet-Feld BTTS Yes fehlt auch nach Zusammenfuehrung aller Match-Zeilen. "
            f"Verfuegbare Felder: {fields}"
        )
    btts_yes = _pct(btts_raw, "BTTS Yes")

    over_raw = _first(item, [
        "probability_over_percent",
        "probability_over_2_5_percent",
        "probabilityOverPercent",
        "over25Percent",
    ])
    if over_raw in (None, ""):
        fields = ", ".join(item.get("_available_fields") or [])
        raise ForebetAutoError(
            "Forebet-Feld Over 2.5 fehlt auch nach Zusammenfuehrung aller Match-Zeilen. "
            f"Verfuegbare Felder: {fields}"
        )
    over25 = _pct(over_raw, "Over 2.5")

    predicted = str(_first(item, ["predictedScore", "predicted_score", "correctScore"]) or "").strip().replace(" ", "")
    if not re.fullmatch(r"\d{1,2}[-:]\d{1,2}", predicted):
        raise ForebetAutoError("Forebet-Ergebnistipp fehlt oder ist ungueltig.")
    predicted = predicted.replace(":", "-")

    avg_raw = _first(item, ["averageGoals", "average_goals", "avgGoals"])
    try:
        avg_goals = float(str(avg_raw).replace(",", "."))
    except Exception as exc:
        raise ForebetAutoError("Forebet Avg. Goals fehlt oder ist ungueltig.") from exc

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


def health() -> Dict[str, Any]:
    from forebet_auto import health as base_health
    result = dict(base_health())
    result["adapter"] = "forebet-auto-v2"
    return result
