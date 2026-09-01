# FootyStats Prognose Engine v0.5.0

Die Weboberfläche verarbeitet sechs JSON-Dateien aus dem V3-Kurzbefehl: `MatchDaten`, `LeagueDaten`, `FormDaten`, `TableDaten`, `PlayerDaten` und `HistoryDaten`.

- `HistoryDaten` wird der Match-ID zugeordnet und auf vollständige Paginierung geprüft.
- Für die Modellwirkung zählen ausschließlich abgeschlossene Spiele derselben Competition vor dem Ziel-Anpfiff.
- Ab 30 verwertbaren Spielen und 8 Low-Score-Spielen schätzt die Engine einen begrenzten, zeitgewichteten Dixon-Coles-Parameter. Dieser verändert das gemeinsame Scoregrid und damit alle sechs Märkte.
- Sind die Sicherheitsbedingungen nicht erfüllt, bleibt die v0.4.0-Basisberechnung aktiv und die Oberfläche nennt den genauen Grund.
- Odds werden weiterhin nicht verwendet; INSUFFICIENT_DATA-Sperre und V5.2-Guardrails bleiben aktiv.
