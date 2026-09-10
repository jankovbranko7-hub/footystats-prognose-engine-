"""UI/text cleanup layered on the frozen SPEC v1.1 ranking-consistency engine.

No market logic changes. This patch only:
- shows the data-spec version separately from the engine implementation version;
- removes the obsolete SPIELEN wording from H2H diagnostics.
"""
from __future__ import annotations
from typing import Any, Dict, List

from spec11_target_player_scope_patch import (
    ENGINE_VERSION,
    apply_patch as apply_target_patch,
)


def _clean_h2h_wording(result: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(result, dict) or not result.get("ok"):
        return result
    for market in result.get("markets") or []:
        for signal in market.get("signals") or []:
            if signal.get("source") == "H2H" and signal.get("domain") == "H2H_RESULT":
                signal["reason"] = (
                    "H2H ist ausschließlich sekundäre Diagnostik und kann allein "
                    "keine klare Markt-Empfehlung erzeugen."
                )
    return result


def apply_patch(legacy: Any) -> Any:
    app = apply_target_patch(legacy)

    base_analyze = legacy._analyze_bundle

    def analyze_with_clean_text(parsed_files: List[Dict[str, Any]]) -> Dict[str, Any]:
        return _clean_h2h_wording(base_analyze(parsed_files))

    legacy._analyze_bundle = analyze_with_clean_text

    short_version = str(ENGINE_VERSION).split("-", 1)[0]
    legacy.INDEX_HTML = legacy.INDEX_HTML.replace(
        "<title>FootyStats SPEC v1.1 – Stärkster Markt</title>",
        f"<title>FootyStats SPEC v1.1 · Engine v{short_version}</title>",
    ).replace(
        "<h2>SPEC-v1.1-Auswertung der FootyStats-Daten</h2>",
        f"<h2>SPEC v1.1 · Engine v{short_version}</h2>"
        f"<p class=\"s\">FootyStats 5-Dateien-Auswertung · Build {ENGINE_VERSION}</p>",
    ).replace(
        "<button id=\"go\">SPEC v1.1 auswerten</button>",
        f"<button id=\"go\">SPEC v1.1 / Engine v{short_version} auswerten</button>",
    ).replace(
        "Technischer SPEC-v1.1-Audit",
        f"Technischer SPEC v1.1 / Engine v{short_version}-Audit",
    )

    app.title = f"FootyStats SPEC v1.1 · Engine v{short_version}"
    app.version = ENGINE_VERSION
    return app
