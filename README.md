# FootyStats + Forebet ELITE Analyse v0.8.0

V0.8.0 verbindet den unveränderten FootyStats-Kern aus V0.4.0 mit den
öffentlichen Pre-Match-Prognosen von Forebet. Der stabile Fünf-Dateien-Stand
bleibt in `main` und `backup/v0.4.0-five-files` erhalten.

## Einzige Eingabe beim iPhone-Lauf

Der Kurzbefehl `FootyStats + Forebet ELITE PICKS` fragt nur:

1. Datum im Format `YYYY-MM-DD`.

Der FootyStats-API-Key wird einmal beim Installieren des Kurzbefehls hinterlegt
und nicht bei jedem Lauf erneut abgefragt. Eine Spielauswahl und eine manuelle
Forebet-Eingabe gibt es nicht mehr. Alle von FootyStats für das Datum gelieferten
Matches werden automatisch durchlaufen und analysiert.

## Nur qualifizierte Spiele, nur eine Datei

Die fünf FootyStats-Quellen und Forebet werden intern für jedes Tagesmatch
zusammengeführt. Gespeichert wird aber ausschließlich, wenn das gemeinsame
ELITE-Modell am Ende `SPIELEN` entscheidet.

Pro qualifiziertem Spiel entsteht genau eine Datei:

`FootyStats_ELITE/YYYY-MM-DD/[MatchID]_ELITE_Analyse.json`

Diese Datei enthält die fünf FootyStats-Datenblöcke, den öffentlichen
Forebet-Snapshot und die vollständige gemeinsame Analyse. Bei `BEOBACHTEN`,
`AUSLASSEN`, fehlenden Daten oder unsicherer Forebet-Zuordnung wird keine Datei
erzeugt und kein Tipp erzwungen. Der Tageslauf geht mit dem nächsten Spiel weiter.

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
Unter `/hubsign-helper` wird ausschließlich der vorab signierte ELITE-PICKS-
Kurzbefehl ausgeliefert. Vor jedem Download wird der Apple-`AEA1`-
Signaturcontainer zwingend geprüft. Dadurch ist der Download nicht von einem
HubSign-Aufruf aus Render abhängig. Der bestehende V2-Kurzbefehl wird nicht
überschrieben.
