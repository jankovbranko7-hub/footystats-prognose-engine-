# Forebet AUTO – Produktionshinweise

Dieser Branch ist die vollständige ELITE-AUTO-Ausführung. `main`,
`backup/v0.4.0-five-files` und der alte V2-Kurzbefehl bleiben unverändert.

## Tageslauf

Der Nutzer gibt ausschließlich das Datum ein. Danach verarbeitet der
Kurzbefehl automatisch alle von FootyStats gelieferten Tagesmatches und legt
pro Match fünf FootyStats-Dateien plus `ForebetDaten.json` im selben Ordner ab.

Es gibt weder eine Spielauswahl noch eine Forebet-Texteingabe.

## Forebet-Zugriff

Forebet schützt öffentliche Seiten mit Cloudflare. Der Server nutzt deshalb
den Apify Actor `locos08/forebet-predictions-scraper` und datumsspezifische
Browser-Fallbacks. `APIFY_TOKEN` wird ausschließlich serverseitig gesetzt.

## Endpunkte

- `GET /api/forebet-auto/health`
- `GET /api/forebet-auto?match_id=...&home=...&away=...&date=...`
- `GET /api/forebet-auto/export?match_id=...&home=...&away=...&date=...`

Der Export-Endpunkt antwortet auch bei einem nicht gefundenen Forebet-Spiel
mit einer JSON-Datei und `FOREBET_UNAVAILABLE`. So bricht ein einzelner Fehler
nicht den kompletten Tageslauf ab. Die spätere Analyse bleibt für dieses Match
gesperrt.

## Schutzregeln

- normalisierte, mehrdeutigkeitssichere Teamzuordnung;
- Datumskontrolle und kein stilles Ersetzen durch eine andere Partie;
- Plausibilitätscheck der 1X2-Summe;
- Pflichtfelder für BTTS, Over 2,5, Ergebnistipp und Average Goals;
- keine Quoten und keine Ergebnisdaten in der Pre-Match-Prognose;
- kein Token in Dateien, Kurzbefehl oder Analysearchiv.
