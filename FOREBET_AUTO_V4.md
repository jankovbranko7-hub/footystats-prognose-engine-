# Forebet AUTO – Produktionshinweise

Dieser Branch ist die vollständige ELITE-AUTO-Ausführung. `main`,
`backup/v0.4.0-five-files` und der alte V2-Kurzbefehl bleiben unverändert.

## Tageslauf

Der Nutzer gibt das Datum ein und wählt danach wie in V2 selbst ein Spiel aus.
Nur dieses Spiel wird verarbeitet. Die fünf FootyStats-Quellen und Forebet werden
intern an `/api/selected-analysis-file` gesendet und von Render gemeinsam analysiert.
Danach wird genau eine gemeinsame Datei gespeichert.

Es gibt keine automatische Spielentscheidung und keine Forebet-Texteingabe.

## Forebet-Zugriff

Forebet schützt öffentliche Seiten mit Cloudflare. Der Server nutzt deshalb
den Apify Actor `locos08/forebet-predictions-scraper` und datumsspezifische
Browser-Fallbacks. `APIFY_TOKEN` wird ausschließlich serverseitig gesetzt.

## Endpunkte

- `GET /api/forebet-auto/health`
- `GET /api/forebet-auto?match_id=...&home=...&away=...&date=...`
- `GET /api/forebet-auto/export?match_id=...&home=...&away=...&date=...`
- `POST /api/elite-candidate`
- `POST /api/selected-analysis`
- `POST /api/selected-analysis-file`

Der Export-Endpunkt antwortet auch bei einem nicht gefundenen Forebet-Spiel
mit `FOREBET_UNAVAILABLE`. So bricht ein einzelner Fehler nicht den kompletten
Lauf ab. Die Analyse bleibt für dieses Match korrekt gesperrt; der Fehler und
alle sechs gelieferten Quellen werden trotzdem gemeinsam dokumentiert.

## Schutzregeln

- normalisierte, mehrdeutigkeitssichere Teamzuordnung;
- Datumskontrolle und kein stilles Ersetzen durch eine andere Partie;
- Plausibilitätscheck der 1X2-Summe;
- Pflichtfelder für BTTS, Over 2,5, Ergebnistipp und Average Goals;
- keine Quoten und keine Ergebnisdaten in der Pre-Match-Prognose;
- kein Token in Dateien, Kurzbefehl oder Analysearchiv.
