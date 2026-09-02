# FootyStats + Forebet ELITE Analyse v0.7.2

V0.7.2 verbindet den unveränderten FootyStats-Kern aus V0.4.0 mit den
öffentlichen Pre-Match-Prognosen von Forebet. Der stabile Fünf-Dateien-Stand
bleibt in `main` und `backup/v0.4.0-five-files` erhalten.

## Einzige Eingabe beim iPhone-Lauf

Der Kurzbefehl `FootyStats + Forebet ELITE AUTO` fragt nur:

1. Datum im Format `YYYY-MM-DD`.

Der FootyStats-API-Key wird einmal beim Installieren des Kurzbefehls hinterlegt
und nicht bei jedem Lauf erneut abgefragt. Eine Spielauswahl und eine manuelle
Forebet-Eingabe gibt es nicht mehr. Alle von FootyStats für das Datum gelieferten
Matches werden automatisch durchlaufen.

## Gemeinsamer Matchordner

Für jedes Match wird ein eigener Ordner mit sechs Dateien erzeugt:

1. `[MatchID]_MatchDaten.json`
2. `[SeasonID]_LeagueDaten.json`
3. `[MatchID]_FormDaten.json`
4. `[MatchID]_TableDaten.json`
5. `[MatchID]_PlayerDaten.json`
6. `[MatchID]_ForebetDaten.json`

Wenn Forebet ein Match nicht sicher findet, wird trotzdem eine
`ForebetDaten.json` mit `FOREBET_UNAVAILABLE` gespeichert. Dadurch läuft der
restliche Tag weiter; die Analyse dieses einzelnen Matches wird anschließend
korrekt gesperrt statt Daten zu erfinden.

## ELITE-Analyse

- Match-ID, Team-IDs, Wettbewerb, Datum und Pagination werden geprüft.
- Der FootyStats-Kern berechnet 1X2, BTTS und Over/Under 2,5 aus xG/xGA,
  Liga-Niveau, Home-/Away-Splits und datenabhängigem Shrinkage.
- FormDaten, TableDaten und PlayerDaten dienen als aktuelle Gegenargument-,
  Abdeckungs- und Robustheitsblöcke; sie werden nicht unkalibriert doppelt
  gewichtet.
- Forebet liefert 1/X/2, BTTS, Over 2,5, Ergebnistipp und Average Goals.
- Die Wahrscheinlichkeiten beider unabhängigen Modelle werden transparent mit
  einem 50/50 logarithmischen Opinion-Pool verbunden.
- Forebet-Ergebnistipp und Average Goals werden zusätzlich als Kohärenz-Gates
  genutzt, nicht als erfundene zweite Wahrscheinlichkeit.
- `SPIELEN` ist nur möglich, wenn die FootyStats-V5.2-Schutzregeln bereits
  bestanden sind, beide Quellen denselben Top-Markt nennen, die gemeinsame
  Wahrscheinlichkeit mindestens 65 % beträgt, die Differenz höchstens acht
  Prozentpunkte beträgt und der Forebet-Kohärenzcheck passt.
- Quoten werden weder abgerufen noch verarbeitet.

Die 50/50-Gewichte sind bewusst transparent und noch nicht als „optimal“
behauptet. Belastbar bessere Gewichte dürfen erst aus einem gemeinsamen
historischen FootyStats-/Forebet-Backtest abgeleitet werden.

## Betrieb

Render startet den separaten Branch mit:

```text
uvicorn auto_app:app --host 0.0.0.0 --port $PORT
```

Benötigte serverseitige Variable:

```text
APIFY_TOKEN=<Token>
```

Der Token wird nicht in Matchdateien oder den iPhone-Kurzbefehl geschrieben.
Unter `/hubsign-helper` wird ausschließlich der vorab signierte ELITE-AUTO-
Kurzbefehl ausgeliefert. Vor jedem Download wird der Apple-`AEA1`-
Signaturcontainer zwingend geprüft. Dadurch ist der Download nicht von einem
HubSign-Aufruf aus Render abhängig. Der bestehende V2-Kurzbefehl wird nicht
überschrieben.
