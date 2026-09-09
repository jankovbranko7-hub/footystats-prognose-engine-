"""Attach FootyStats Official Analysis Spec v1.1 to the V0.5.0 runtime.

This patch is deliberately non-invasive: it wraps the already-active V0.5.0
analysis, adds provenance/official-guidance output and read-only spec endpoints,
and leaves probabilities plus final action untouched.
"""
from __future__ import annotations

import json
import time
from typing import Any, Dict, List

from fastapi import File, UploadFile

from research.footystats_official_spec import (
    SPEC_NAME,
    SPEC_VERSION,
    build_official_spec_report,
    load_field_registry,
    load_shortcut_schema,
)


def _install_official_spec_ui(legacy: Any) -> None:
    html = legacy.INDEX_HTML
    js_anchor = "    const fsLogic=data.footystats_match_logic||{};"
    if js_anchor not in html:
        return

    js_extra = js_anchor + "\n" + """    const officialSpec=data.footystats_official_spec||{};
    const officialRules=(officialSpec.official_tutorial_examples||{});
    const bttsOfficial=(officialRules.btts_yes_example||{});
    const lowOfficial=(officialRules.low_scoring_example||{});
    const temporalOfficial=(officialSpec.temporal_safety||{});
    const officialSpecCard=officialSpec.name
      ? '<div class="c"><h3>FootyStats Official Analysis Spec '+escapeHtml(officialSpec.version||'')+'</h3><div class="g">'+
        '<div class="m"><div class="s">Temporal Audit</div><div class="b">'+escapeHtml(temporalOfficial.overall||'—')+'</div></div>'+
        '<div class="m"><div class="s">BTTS Tutorial-Regel</div><div class="b">'+escapeHtml(bttsOfficial.live_status||bttsOfficial.strict_historical_status||'—')+'</div></div>'+
        '<div class="m"><div class="s">Low-Scoring Tutorial-Regel</div><div class="b">'+escapeHtml(lowOfficial.live_status||lowOfficial.strict_historical_status||'—')+'</div></div>'+
        '</div><p class="s">Offizielle FootyStats-Definitionen und Tutorial-Regeln werden getrennt ausgewiesen. Sie sind Evidenz-Flags, keine kalibrierten Wahrscheinlichkeiten und verändern weder den V0.4.3 Probability Core noch automatisch die finale Aktion.</p></div>'
      : '';
"""
    html = html.replace(js_anchor, js_extra, 1)

    card_anchor = "      fsLogicCard+\n      contextCard+"
    if card_anchor in html:
        html = html.replace(
            card_anchor,
            "      officialSpecCard+\n      fsLogicCard+\n      contextCard+",
            1,
        )
    legacy.INDEX_HTML = html


def apply_patch(legacy: Any, app: Any) -> Any:
    current_analyze = legacy._analyze_bundle

    def official_spec_analyze(parsed_files: List[Dict[str, Any]]) -> Dict[str, Any]:
        result = current_analyze(parsed_files)
        if not isinstance(result, dict) or not result.get("ok"):
            return result
        pair = legacy.select_pair(parsed_files)
        if not isinstance(pair, dict) or not pair.get("ok"):
            return pair
        result["footystats_official_spec"] = build_official_spec_report(legacy, pair)
        return result

    legacy._analyze_bundle = official_spec_analyze

    old_health = next(
        (route.endpoint for route in app.router.routes if getattr(route, "path", None) == "/api/health"),
        None,
    )
    app.router.routes = [
        route
        for route in app.router.routes
        if getattr(route, "path", None)
        not in {
            "/api/health",
            "/api/footystats-official-spec",
            "/api/shortcut-api-schema",
            "/api/predict-shortcut-v1-1",
        }
    ]

    def health() -> Dict[str, Any]:
        base = dict(old_health() if callable(old_health) else {})
        base.update(
            {
                "ok": True,
                "footystats_official_analysis_spec": SPEC_VERSION,
                "footystats_official_spec_name": SPEC_NAME,
                "official_spec_runtime": True,
                "strict_prematch_validator": True,
                "official_rules_decision_influence": False,
                "official_rules_probability_influence": False,
                "field_registry_version": str(load_field_registry().get("schema_version") or ""),
                "shortcut_api_schema_version": str(load_shortcut_schema().get("schema_version") or ""),
                "shortcut_capture_unix": int(time.time()),
                "shortcut_named_upload_endpoint": "/api/predict-shortcut-v1-1",
            }
        )
        return base

    def official_spec() -> Dict[str, Any]:
        return load_field_registry()

    def shortcut_schema() -> Dict[str, Any]:
        return load_shortcut_schema()

    async def predict_shortcut_v1_1(
        match_file: UploadFile = File(...),
        league_file: UploadFile = File(...),
        form_file: UploadFile = File(...),
        table_file: UploadFile = File(...),
        player_file: UploadFile = File(...),
    ) -> Dict[str, Any]:
        """Shortcut-safe 5-file upload with unique multipart field names.

        iOS Shortcuts does not reliably preserve repeated Form keys. The normal
        browser endpoint keeps the historical ``files`` list contract, while
        this endpoint gives each of the five required files its own key.
        """
        ordered = [
            ("match_file", match_file, "MatchDaten.json"),
            ("league_file", league_file, "LeagueDaten.json"),
            ("form_file", form_file, "FormDaten.json"),
            ("table_file", table_file, "TableDaten.json"),
            ("player_file", player_file, "PlayerDaten.json"),
        ]
        parsed: List[Dict[str, Any]] = []
        errors: List[Dict[str, Any]] = []
        received: Dict[str, str] = {}
        for field_name, upload, fallback_name in ordered:
            filename = upload.filename or fallback_name
            received[field_name] = filename
            try:
                raw = await upload.read()
                data = json.loads(raw.decode("utf-8"))
                parsed.append({"name": filename, "data": data})
            except Exception as exc:
                errors.append({"field": field_name, "name": filename, "error": str(exc)})

        if errors:
            return {
                "ok": False,
                "decision": "ANALYSE NICHT MÖGLICH",
                "phase": "FILE_READ_FAILED",
                "error": "Mindestens eine der fünf Shortcut-Dateien konnte nicht gelesen werden.",
                "received": received,
                "files": errors,
            }

        result = legacy._analyze_bundle(parsed)
        if isinstance(result, dict):
            result.setdefault("shortcut_upload", {})
            result["shortcut_upload"].update(
                {
                    "endpoint": "/api/predict-shortcut-v1-1",
                    "mode": "FIVE_NAMED_MULTIPART_FIELDS",
                    "received": received,
                    "file_count": len(parsed),
                }
            )
        return result

    app.add_api_route("/api/health", health, methods=["GET"])
    app.add_api_route("/api/footystats-official-spec", official_spec, methods=["GET"])
    app.add_api_route("/api/shortcut-api-schema", shortcut_schema, methods=["GET"])
    app.add_api_route("/api/predict-shortcut-v1-1", predict_shortcut_v1_1, methods=["POST"])

    _install_official_spec_ui(legacy)
    return app
