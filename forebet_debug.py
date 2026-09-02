from __future__ import annotations

from typing import Any, Dict, List, Optional

from forebet_auto_v3 import _browser_pages


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
            }
        )
    return {"ok": True, "date": date, "page_count": len(safe), "pages": safe}
