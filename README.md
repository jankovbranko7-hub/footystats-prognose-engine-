# FootyStats Prognose Engine — 6-Dateien Release v0.6.0

Dieses Repository ist der saubere 6-Dateien-Workflow für die FootyStats Match Engine.

## Erwartetes Paket pro Match

1. `[MatchID]_MatchDaten.json`
2. `[SeasonID]_LeagueDaten.json`
3. `[MatchID]_FormDaten.json`
4. `[MatchID]_TableDaten.json`
5. `[MatchID]_PlayerDaten.json`
6. `[MatchID]_HistoryDaten.json`

Die sechs Dateien werden über IDs und Dateitypen geprüft. Die `HistoryDaten` stammen aus `league-matches`, werden im iPhone-Kurzbefehl mit `max_time=<Anpfiff>` und `max_per_page=1000` abgerufen und vollständig paginiert.

## Rollen

- MatchDaten: Zielspiel und Pre-Match-Felder.
- LeagueDaten: Saison-, Team- und Venue-Statistiken; zentrale Modellquelle.
- FormDaten: aktuelle Last-X-Entwicklung als Gegencheck.
- TableDaten: Tabellen- und Positionskontext.
- PlayerDaten: Spielerproduktion/Kaderstatistik ohne erfundene Verfügbarkeit.
- HistoryDaten: abgeschlossene Ligaspiele vor dem Ziel-Anpfiff; ausschließlich für die zeitlich gesicherte Dixon-Coles-Low-Score-Kalibrierung.

## Modell und Regeln

Der Release-Wrapper ist v0.6.0. Der bewährte probabilistische Kern bleibt v0.5.0 / V5.5 und wird als `engine_core.py` eingebunden. Damit bleiben die bestehenden Regeln erhalten: sechs Märkte, keine Odds, INSUFFICIENT_DATA-Sperre, Result-vs-Underlying und V5.2-Decision-Gates.

## Render

`render.yaml` startet die App mit:

```bash
uvicorn app:app --host 0.0.0.0 --port $PORT
```

Healthcheck: `/api/health`

## iPhone-Kurzbefehl

Die App bietet unter `/api/shortcut-source` den neuen **FootyStats API Export V3 — 6 Dateien** als unsignierte `.shortcut`-Datei an. Der API-Key wird nicht im Repository gespeichert; iOS fragt ihn beim Import als Importfrage ab. Die Datei danach auf dem iPhone über **Sign Shortcut File** signieren.
