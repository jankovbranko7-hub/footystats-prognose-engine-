# FootyStats Prognose Engine v0.4.0

Die Weboberfläche verarbeitet weiterhin die bisherigen fünf JSON-Dateien. Optional akzeptiert sie als sechste Datei `HistoryDaten.json` aus dem V3-Kurzbefehl.

- `HistoryDaten` wird der Match-ID zugeordnet, auf erkennbare Datensätze und Paginierung geprüft und in das herunterladbare Archiv aufgenommen.
- `HistoryDaten` fließt **nicht** in Wahrscheinlichkeiten, Schwellenwerte, Kalibrierung oder Entscheidung ein.
- Der liga-relative v0.4.0-Modellkern und die V5.2-Guardrails bleiben unverändert.
