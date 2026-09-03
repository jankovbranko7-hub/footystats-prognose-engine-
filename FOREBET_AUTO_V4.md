# Forebet AUTO – Produktionshinweise

Dieser Branch ist die vollständige ELITE-AUTO-Ausführung. `main`,
`backup/v0.4.0-five-files` und der alte V2-Kurzbefehl bleiben unverändert.

## Tageslauf

Der Nutzer gibt ausschließlich das Datum ein. Danach verarbeitet der
Kurzbefehl automatisch alle von FootyStats gelieferten Tagesmatches. Die sechs
Quellen werden intern an `/api/elite-candidate` gesendet. Nur bei der endgültigen
Entscheidung `SPIELEN` wird ein gemeinsames Archiv mit fünf FootyStats-Quellen,
Forebet und Analyse gespeichert. Dadurch entstehen null oder eine Datei pro
qualifiziertem Match statt sechs Dateien für jede Tagespartie.

Es gibt weder eine Spielauswahl noch eine Forebet-Texteingabe.

## Forebet-Zugriff

Forebet schützt öffentliche Seiten mit Cloudflare. Der Server nutzt deshalb
den Apify Actor `locos08/forebet-predictions-scraper` und datumsspezifische
Browser-Fallbacks. `APIFY_TOKEN` wird ausschließlich serverseitig gesetzt.

## Endpunkte

- `GET /api/forebet-auto/health`
- `GET /api/forebet-auto?match_id=...&home=...&away=...&date=...`
- `GET /api/forebet-auto/export?match_id=...&home=...&away=...&date=...`
- `POST /api/elite-candidate`

Der Export-Endpunkt antwortet auch bei einem nicht gefundenen Forebet-Spiel
mit `FOREBET_UNAVAILABLE`. So bricht ein einzelner Fehler nicht den kompletten
Tageslauf ab. Die spätere Analyse bleibt für dieses Match gesperrt und es wird
keine Ergebnisdatei gespeichert.

## Schutzregeln

- normalisierte, mehrdeutigkeitssichere Teamzuordnung;
- Datumskontrolle und kein stilles Ersetzen durch eine andere Partie;
- Plausibilitätscheck der 1X2-Summe;
- Pflichtfelder für BTTS, Over 2,5, Ergebnistipp und Average Goals;
- keine Quoten und keine Ergebnisdaten in der Pre-Match-Prognose;
- kein Token in Dateien, Kurzbefehl oder Analysearchiv.
