from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from forebet_auto import ForebetAutoError
from forebet_auto_v6 import _candidate_match_links, _direct_fixture_windows, _run_web_pages
import forebet_auto_v3 as core


def debug_direct(home: str, away: str, date: Optional[str] = None) -> Dict[str, Any]:
    links = _candidate_match_links(home, away)
    if not links:
        raise ForebetAutoError("Kein direkter Match-Link gefunden.")

    pages = _run_web_pages(links[:3], include_links=False)
    out_pages: List[Dict[str, Any]] = []
    home_n = core._norm(home)
    away_n = core._norm(away)

    for page in pages:
        text = str(page.get("text") or "")
        lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
        lines = [line for line in lines if line]
        excerpts: List[Dict[str, Any]] = []
        for i in range(len(lines)):
            preview = " ".join(lines[i : i + 5])
            pn = core._norm(preview)
            if home_n and away_n and home_n in pn and away_n in pn:
                start = max(0, i - 25)
                end = min(len(lines), i + 30)
                excerpts.append({
                    "index": i,
                    "lines": lines[start:end],
                })
                if len(excerpts) >= 8:
                    break
        classified = []
        for kind, window in _direct_fixture_windows(text, home, away):
            classified.append({"kind": kind, "window": window})
            if len(classified) >= 8:
                break
        out_pages.append({
            "url": page.get("url"),
            "title": page.get("title"),
            "text_len": len(text),
            "date_variants": core._date_variants(date),
            "contains_date": any(token in text for token in core._date_variants(date)) if date else True,
            "excerpts": excerpts,
            "classified_windows": classified,
        })

    return {
        "ok": True,
        "home": home,
        "away": away,
        "date": date,
        "candidate_links": links,
        "pages": out_pages,
    }
