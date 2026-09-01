# FootyStats + Forebet Super Analyse v0.6.0

Die Anwendung kombiniert das unveränderte FootyStats-Modell aus v0.4.0 mit
einem separat validierten Forebet-Snapshot. Der bisherige Fünf-Dateien-Stand
bleibt im Backup-Branch `backup/v0.4.0-five-files` erhalten.

## Eingabedateien

Der neue V4-Kurzbefehl legt pro Match sechs JSON-Dateien gemeinsam ab:

1. `MatchDaten`
2. `LeagueDaten`
3. `FormDaten`
4. `TableDaten`
5. `PlayerDaten`
6. `ForebetDaten`

Für Forebet fragt der Kurzbefehl genau diese, mit Semikolon getrennten Werte ab:

```text
1;X;2;BTTS-Ja;Over-2,5;Ergebnistipp;Durchschnittstore;Forebet-URL
```

Beispiel:

```text
45;28;27;58;61;2-1;2,9;https://www.forebet.com/...
```

Die Prozentwerte 1/X/2 müssen zusammen ungefähr 100 ergeben. Quoten werden
weder abgefragt noch verarbeitet.

## Gemeinsame Berechnung

- FootyStats läuft zuerst vollständig über den v0.4.0-Kern und seine
  INSUFFICIENT_DATA- sowie V5.2-Schutzregeln.
- Forebet wird unabhängig auf Match-ID, Wertebereiche, Ergebnistipp und
  Quellenlink geprüft.
- Danach werden beide Wahrscheinlichkeitsmodelle mit einem symmetrischen
  logarithmischen Opinion-Pool (50/50) kombiniert.
- `SPIELEN` ist nur möglich, wenn bereits FootyStats alle Schutzregeln besteht,
  beide Quellen denselben Top-Markt nennen, die gemeinsame Wahrscheinlichkeit
  mindestens 65 % beträgt und die Quellen höchstens 8 Prozentpunkte abweichen.
- Die 50/50-Gewichte sind transparent, aber noch nicht anhand eines ausreichend
  großen gemeinsamen Forebet-/FootyStats-Backtests kalibriert.

## Speicherung

Das gemeinsame Archiv enthält die sechs Eingabequellen, beide Einzelmodelle,
den Vergleich und das kombinierte Ergebnis. Es wird als JSON auf das iPhone
oder in iCloud heruntergeladen. Render speichert diese Matchdaten nicht
dauerhaft. API-Schlüssel und Quoten werden aus dem Archiv entfernt.

## Kurzbefehl

`/hubsign-helper` signiert ausschließlich den neuen separaten
`FootyStats + Forebet Export V4`-Kurzbefehl. Der bestehende V2-Kurzbefehl wird
nicht überschrieben.
