from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

# Importing v4 first installs the corrected match-window finder into the v3 core.
import forebet_auto_v4  # noqa: F401
import forebet_auto_v3 as core

_ORIGINAL_PROBABILITY_SEQUENCE = core._probability_sequence
_ORIGINAL_SCORE_AND_AVG = core._score_and_avg


def _split_compact_probabilities(digits: str, count: int) -> Optional[Tuple[float, ...]]:
    """Split Forebet's concatenated probability text into values summing to 100.

    Example: 151174 -> 15, 11, 74; 2377 -> 23, 77.
    We only accept a unique valid split, so ambiguous strings fail closed.
    """
    solutions: List[Tuple[int, ...]] = []

    def walk(pos: int, parts: List[int]) -> None:
        remaining_parts = count - len(parts)
        if remaining_parts == 0:
            if pos == len(digits) and sum(parts) == 100:
                solutions.append(tuple(parts))
            return
        remaining_chars = len(digits) - pos
        if remaining_chars < remaining_parts or remaining_chars > remaining_parts * 3:
            return
        for width in (1, 2, 3):
            end = pos + width
            if end > len(digits):
                continue
            token = digits[pos:end]
            if len(token) > 1 and token.startswith("0"):
                continue
            value = int(token)
            if not 0 <= value <= 100:
                continue
            if sum(parts) + value > 100:
                continue
            walk(end, parts + [value])

    walk(0, [])
    unique = list(dict.fromkeys(solutions))
    if len(unique) != 1:
        return None
    return tuple(float(v) for v in unique[0])


def _probability_sequence(window: List[str], count: int) -> Optional[Tuple[float, ...]]:
    # Forebet's rendered table concatenates probability columns with prediction,
    # correct score and average goals, e.g. 15117421 - 34.19 or 2377Yes1 - 34.19.
    for line in window:
        if count == 3:
            match = re.search(
                r"(?<!\d)(\d{3,9})([12X])\s*(\d{1,2})\s*-\s*(\d{1,2})(\d{1,2}[.,]\d{1,3})",
                line,
                re.IGNORECASE,
            )
        elif count == 2:
            match = re.search(
                r"(?<!\d)(\d{2,6})(Yes|No|Over|Under)\s*(\d{1,2})\s*-\s*(\d{1,2})(\d{1,2}[.,]\d{1,3})",
                line,
                re.IGNORECASE,
            )
        else:
            match = None

        if match:
            split = _split_compact_probabilities(match.group(1), count)
            if split is not None:
                return split

    return _ORIGINAL_PROBABILITY_SEQUENCE(window, count)


def _score_and_avg(window: List[str]) -> Tuple[Optional[str], Optional[float]]:
    # Compact Forebet form: "...2 1 - 3 4.19 57°F..." is rendered as
    # "...21 - 34.1957°F...". Parse score and decimal avg from the same line.
    for line in window:
        match = re.search(
            r"(\d{1,2})\s*-\s*(\d{1,2})(\d{1,2}[.,]\d{1,3})",
            line,
        )
        if not match:
            continue
        score = f"{int(match.group(1))}-{int(match.group(2))}"
        try:
            avg = float(match.group(3).replace(",", "."))
        except Exception:
            continue
        if 0 <= avg <= 10:
            return score, avg
    return _ORIGINAL_SCORE_AND_AVG(window)


core._probability_sequence = _probability_sequence
core._score_and_avg = _score_and_avg


def build_snapshot(match_id: int, home: str, away: str, date: Optional[str] = None, force: bool = False) -> Dict[str, Any]:
    return core.build_snapshot(match_id=match_id, home=home, away=away, date=date, force=force)


def debug_match(home: str, away: str, date: Optional[str] = None, force: bool = False) -> Dict[str, Any]:
    return core.debug_match(home=home, away=away, date=date, force=force)


def health() -> Dict[str, Any]:
    result = dict(core.health())
    result["adapter"] = "forebet-auto-v5-compact-dom"
    return result
