from __future__ import annotations

from typing import Any, Dict, List, Optional

from forebet_auto_v3 import _browser_pages


_PROBES = ["Barranquilla", "Boca Juniors", "Bay Olympic", "Birkenhead"]


def _snippets(text: str) -> Dict[str, List[str]]:
    lower = text.lower()
    result: Dict[str, List[str]] = {}
    for probe in _PROBES:
        needle = probe.lower()
        found: List[str] = []
        start = 0
        while len(found) < 4:
            pos = lower.find(needle, start)
            if pos < 0:
                break
            lo = max(0, pos - 500)
            hi = min(len(text), pos + 1200)
            found.append(text[lo:hi])
            start = pos + len(needle)
        if found:
            result[probe] = found
    return result


def debug_pages(date: Optional[str] = None, force: bool = False) -> Dict[str, Any]:
    pages = _browser_pages(date=date, force=force)
    safe: List[Dict[str, Any]] = []
    for page in pages:
        text = str(page.get("text") or "")
        safe.append(
            {
                "url": str(page.get("url") or ""),
                "title": str(page.get("title") or ""),
                "text_length": len(text),
                "text_head": text[:1200],
                "probe_snippets": _snippets(text),
            }
        )
    return {"ok": True, "date": date, "page_count": len(safe), "pages": safe}
