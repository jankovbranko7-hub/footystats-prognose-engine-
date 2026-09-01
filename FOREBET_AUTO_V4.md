# FootyStats + Forebet AUTO V4

Status: **separater Teststand**. `main`, der alte V2-Kurzbefehl und der bestehende Render-Produktionsstand werden durch diesen Branch nicht weiter verändert.

## Ziel

Der Nutzer macht pro Match nur noch:

1. Datum wählen.
2. FootyStats-Spiel wählen.

Danach erzeugt der Kurzbefehl automatisch:

- MatchDaten
- LeagueDaten
- FormDaten
- TableDaten
- PlayerDaten
- ForebetDaten

Es gibt **kein Forebet-Texteingabefeld** mehr.

## Warum ein Scraper-Dienst nötig ist

Forebet schützt seine Seiten mit Cloudflare. Direkte Requests von einem Render-Server oder einem einfachen HTTP-Client können deshalb mit einer Challenge statt der Vorhersagedaten beantwortet werden. Der Teststand nutzt den Apify Actor `locos08/forebet-predictions-scraper`, der die Forebet-Seiten automatisiert lädt und 1X2, BTTS, Under/Over, Ergebnistipp und Average Goals gemeinsam bereitstellt.

## Einmalige Konfiguration

Im separaten Render-Testservice:

- Branch: `feat/forebet-auto-v4`
- Start Command: `uvicorn auto_app:app --host 0.0.0.0 --port $PORT`
- Environment Variable: `APIFY_TOKEN=<dein Apify API Token>`

Der Token wird nur serverseitig gespeichert und kommt **nicht** in die Match-Dateien oder in den iPhone-Kurzbefehl.

## Auto-API

Health:

`GET /api/forebet-auto/health`

Match:

`GET /api/forebet-auto?match_id=123&home=Home%20Team&away=Away%20Team`

Die API führt eine normalisierte Fuzzy-Zuordnung der Teamnamen durch. Mehrdeutige oder schwache Matches werden abgelehnt statt geraten.

## Ausgabe

Beispielstruktur:

```json
{
  "schema": "forebet-auto-v1",
  "match_id": 123,
  "home_win": 45.0,
  "draw": 28.0,
  "away_win": 27.0,
  "btts_yes": 58.0,
  "over_2_5": 61.0,
  "predicted_score": "2-1",
  "average_goals": 2.9,
  "source_url": "https://www.forebet.com/"
}
```

## Sicherheit

- Keine Odds werden für die Prognose übernommen.
- Kein Apify-Token wird in Archive geschrieben.
- Unsichere Forebet-Teamzuordnungen werden blockiert.
- Ergebnisse werden nicht zur Pre-Match-Auswahl benutzt.
- Der Actor-Datensatz wird im Prozess 30 Minuten gecacht, damit nicht für jedes einzelne Match erneut der komplette Forebet-Crawl gestartet wird.
