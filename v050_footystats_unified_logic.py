"""Production composition: V0.5.0 + unified qualitative FootyStats context logic.

The V0.4.3 FULL-5 probability core and the result-supervised reliability model
remain frozen. This wrapper makes the additional five-file FootyStats context
part of one final qualitative action without artificial percentage adjustments
or hand-written feature weights.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

from fastapi import File, Response, UploadFile

from research.context_snapshot_archive import snapshot_download_name
from research.footystats_match_logic import (
    FINAL_DECISION_SOURCE,
    apply_footystats_match_logic,
)
from research.research_context_engine import _snapshot_and_persist
from v050_context_release import VERSION, apply_patch as apply_context_patch


def _install_footystats_logic_ui(legacy: Any) -> None:
    html = legacy.INDEX_HTML
    js_anchor = "    const full5=(((goal||{}).hybrid_model||{}).full5)||{};"
    if js_anchor not in html:
        raise RuntimeError("FootyStats unified logic UI anchor not found.")

    js_extra = js_anchor + "\n" + """    const fsLogic=data.footystats_match_logic||{};
    const fsResolution=fsLogic.resolution||{};
    const fsSignals=Array.isArray(fsLogic.signals)?fsLogic.signals:[];
    const fsSignalRows=fsSignals.map(function(sig){
      return '<div class="m"><div class="s">'+escapeHtml(sig.domain||'Kontext')+'</div><div class="b">'+escapeHtml(sig.status||'—')+'</div><div class="s">'+escapeHtml(sig.reason||'')+'</div></div>';
    }).join('');
    const fsLogicCard=fsLogic.name
      ? '<div class="c"><h3>FootyStats Gesamtlogik</h3><div class="g">'+
        '<div class="m"><div class="s">Gesamtbild</div><div class="b">'+escapeHtml(fsLogic.overall_status||'—')+'</div></div>'+
        '<div class="m"><div class="s">Reliability-Aktion</div><div class="b">'+escapeHtml(fsResolution.base_action||'—')+'</div></div>'+
        '<div class="m"><div class="s">Finale Aktion</div><div class="b">'+escapeHtml(fsResolution.final_action||data.decision||'—')+'</div></div>'+
        '<div class="m"><div class="s">Logik</div><div class="b">'+escapeHtml(fsResolution.mode||'—')+'</div></div>'+
        fsSignalRows+'</div><p class="s">'+escapeHtml(fsResolution.reason||'')+'</p>'+
        '<p class="s">Keine künstliche Prozentkorrektur · keine Feature-Gewichte · Wahrscheinlichkeiten bleiben unverändert. Die fünf FootyStats-Dateien werden als eine qualitative Match-Einheit geprüft.</p></div>'
      : '';
"""
    html = html.replace(js_anchor, js_extra, 1)

    card_anchor = "      contextCard+\n      '<div class=\"c\"><h3>FULL-5-Status</h3>"
    if card_anchor not in html:
        raise RuntimeError("FootyStats unified logic card anchor not found.")
    html = html.replace(
        card_anchor,
        "      fsLogicCard+\n      contextCard+\n      '<div class=\"c\"><h3>FULL-5-Status</h3>",
        1,
    )
    legacy.INDEX_HTML = html


def apply_patch(legacy: Any) -> Any:
    app = apply_context_patch(legacy)
    context_analyze = legacy._analyze_bundle

    def unified_analyze(parsed_files: List[Dict[str, Any]]) -> Dict[str, Any]:
        analysis = context_analyze(parsed_files)
        if not isinstance(analysis, dict) or not analysis.get("ok"):
            return analysis
        pair = legacy.select_pair(parsed_files)
        if not pair.get("ok"):
            return pair
        return apply_footystats_match_logic(legacy, pair, analysis)

    legacy._analyze_bundle = unified_analyze

    old_health = next(
        (route.endpoint for route in app.router.routes if getattr(route, "path", None) == "/api/health"),
        None,
    )
    app.router.routes = [
        route
        for route in app.router.routes
        if getattr(route, "path", None) not in {"/api/archive-bundle", "/api/health"}
    ]

    async def archive_bundle(files: List[UploadFile] = File(...)):
        parsed, errors = await legacy._read_bundle_uploads(files)
        if errors:
            return {
                "ok": False,
                "decision": "ANALYSE NICHT MÖGLICH",
                "phase": "FILE_PARSE_FAILED",
                "errors": errors,
            }
        pair = legacy.select_pair(parsed)
        if not pair.get("ok"):
            return pair
        analysis = unified_analyze(parsed)
        if not isinstance(analysis, dict) or not analysis.get("ok"):
            return analysis
        record, persistence = _snapshot_and_persist(parsed, pair, analysis)
        body = json.dumps(
            record,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        ).encode("utf-8")
        return Response(
            content=body,
            media_type="application/json",
            headers={
                "Content-Disposition": f'attachment; filename="{snapshot_download_name(record)}"',
                "Cache-Control": "no-store",
                "X-Context-Record-SHA256": record["record_sha256"],
                "X-Context-Persistence-Status": str(persistence.get("status") or "UNKNOWN"),
            },
        )

    def health() -> Dict[str, Any]:
        base = dict(old_health() if callable(old_health) else {})
        base.update(
            {
                "ok": True,
                "version": VERSION,
                "production": True,
                "final_decision_source": FINAL_DECISION_SOURCE,
                "footystats_unified_context_logic": True,
                "footystats_context_can_change_action": True,
                "footystats_context_changes_probabilities": False,
                "footystats_context_manual_weights": False,
                "footystats_context_global_numeric_cutoffs": False,
            }
        )
        return base

    app.add_api_route("/api/archive-bundle", archive_bundle, methods=["POST"])
    app.add_api_route("/api/health", health, methods=["GET"])
    _install_footystats_logic_ui(legacy)
    app.version = VERSION
    return app
