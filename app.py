"""Render entry point for FootyStats V0.5.0 CONTEXT-AWARE production."""
import app_v040 as legacy
import v043_engine
from v050_context_release import apply_patch

# Keep the frozen V0.4.3 FULL-5 probability stack bound exactly as before.
v043_engine.legacy = legacy

app = apply_patch(legacy)

# V0.5.0 is the only visible product identity. Historical protocol internals
# remain available in backend diagnostics, but old V5.2 naming must not appear
# as if it were the active decision engine.
legacy.INDEX_HTML = legacy.INDEX_HTML.replace(
    "Legacy V5.2-Diagnostik", "Interne Diagnose (ohne Einfluss)"
).replace(
    "V5.2-Protokoll", "Interne Diagnose (ohne Einfluss)"
)

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
    "5-Dateien Pre-Match Analyse · V0.4.3 FULL-5 Probability Core · ergebnisvalidierte OOF-Reliability-Policy · Trend + News/Verfügbarkeit + optionale Aufstellung · keine Odds",
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

# The normal user view explains the result-supervised reliability group without
# exposing learned cluster centers as if they were manual betting thresholds.
legacy.INDEX_HTML = legacy.INDEX_HTML.replace(
    "gelernten Reliability-Policy der mittleren Zuverlässigkeitsgruppe",
    "ergebnisvalidierten OOF-Reliability-Policy der mittleren Zuverlässigkeitsgruppe",
).replace(
    "Die finale V0.5.0-Entscheidung stammt aus der gelernten Reliability-Cluster-Policy. Alte V0.4.3 Decision Gates sind nur Diagnostik und beeinflussen SPIELEN / BEOBACHTEN / AUSLASSEN nicht.",
    "Die finale V0.5.0-Entscheidung stammt aus der ergebnisvalidierten OOF-Reliability-Policy. Sie wurde aus chronologischen OOF-Prognosen und tatsächlichen Ergebnissen gelernt. Alte V0.4.3 Decision Gates sind nur Diagnostik und beeinflussen die finale Aktion nicht.",
).replace(
    "Zentrum der gelernten Gruppe: '+(assignedCentroid*100).toFixed(2)+' % · Zuordnung nach nächstem gelerntem Clusterzentrum · keine manuell gesetzte Performance-Schwelle.",
    "Ergebnisvalidierte Zuverlässigkeitsgruppe · keine manuell gesetzte Performance-Schwelle.",
)
