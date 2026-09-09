"""Render entry point for FootyStats V0.5.0 CONTEXT-AWARE production."""
import app_v040 as legacy
import v043_engine
from v050_footystats_unified_logic import apply_patch as apply_v050_patch
from v050_official_spec_patch import apply_patch as apply_official_spec_patch

# Keep the frozen V0.4.3 FULL-5 probability stack bound exactly as before.
v043_engine.legacy = legacy

app = apply_official_spec_patch(legacy, apply_v050_patch(legacy))

# The old V0.4.3/V5.2 protocol remains available in backend diagnostics for
# auditability, but it has no role in the V0.5.0 final action and therefore is
# removed completely from the normal short-decision UI.
_legacy_diag_labels = (
    "Legacy V5.2-Diagnostik",
    "V5.2-Protokoll",
    "Interne Diagnose (ohne Einfluss)",
)
for _label in _legacy_diag_labels:
    _tile = (
        "'<div class=\"m\"><div class=\"s\">" + _label + "</div><b>'+"
        "escapeHtml(protocol.phase_1_data_audit||'—')+' / '+"
        "escapeHtml(protocol.phase_2_all_six_markets||'—')+'</b></div>'+"
    )
    legacy.INDEX_HTML = legacy.INDEX_HTML.replace(_tile, "", 1)

# Collapse the inherited two-card start screen into one actual V0.5.0 mask.
# This is presentation-only: upload handling and V0.4.3 probabilities are untouched.
_v050_banner = (
    '<div class="c"><h2>FootyStats V0.5.0 CONTEXT-AWARE</h2>'
    '<div class="s">Eine Engine · Probability Core: V0.4.3 FULL-5 · 5 Dateien · '
    'gelernte Reliability-Policy · Trend + News/Verfügbarkeit + optionale Aufstellung '
    'ohne erfundene Strafwerte</div></div>'
)
legacy.INDEX_HTML = legacy.INDEX_HTML.replace(_v050_banner, "", 1)
legacy.INDEX_HTML = legacy.INDEX_HTML.replace(
    "V0.5.0 CONTEXT-AWARE – 5-Dateien Analyse",
    "FootyStats V0.5.0 CONTEXT-AWARE",
    1,
).replace(
    "Eine gemeinsame Analyse: V0.4.3 FULL-5 Probability Core + gelernte Reliability-Policy + aktueller Match-Kontext · 5 FootyStats-Dateien · keine Odds",
    "5-Dateien Pre-Match Analyse · V0.4.3 FULL-5 Probability Core · ergebnisvalidierte OOF-Reliability-Policy + FootyStats Gesamtlogik · Official Analysis Spec 1.1 · keine Odds",
    1,
).replace(
    "Match-Ordner auswählen",
    "5-Dateien Match-Paket auswählen",
    1,
).replace(
    ">Analyse starten<",
    ">V0.5.0 Analyse starten<",
    1,
)

# The reliability model supplies the starting action. The five-file FootyStats
# context then becomes one qualitative decision unit without changing any
# probability or introducing hand-written percentage adjustments.
legacy.INDEX_HTML = legacy.INDEX_HTML.replace(
    "gelernten Reliability-Policy der mittleren Zuverlässigkeitsgruppe",
    "ergebnisvalidierten OOF-Reliability-Policy der mittleren Zuverlässigkeitsgruppe",
).replace(
    "Die finale V0.5.0-Entscheidung stammt aus der gelernten Reliability-Cluster-Policy. Alte V0.4.3 Decision Gates sind nur Diagnostik und beeinflussen SPIELEN / BEOBACHTEN / AUSLASSEN nicht.",
    "Die OOF-Reliability-Policy liefert die Ausgangsaktion. Danach prüft die FootyStats Gesamtlogik die zusätzlichen fünf-Dateien-Kontextblöcke als eine qualitative Einheit. Ein klarer Widerspruch kann die Aktion eine Stufe senken; nur vollständige einstimmige Bestätigung kann sie eine Stufe erhöhen. Wahrscheinlichkeiten werden dabei nicht verändert.",
).replace(
    "Zentrum der gelernten Gruppe: '+(assignedCentroid*100).toFixed(2)+' % · Zuordnung nach nächstem gelerntem Clusterzentrum · keine manuell gesetzte Performance-Schwelle.",
    "Ergebnisvalidierte Zuverlässigkeitsgruppe · keine manuell gesetzte Performance-Schwelle.",
)
