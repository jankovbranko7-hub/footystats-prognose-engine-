# FootyStats v0.4.1 – Offline-Gate-Test

## Zweck

Die Wahrscheinlichkeiten der v0.4.0 bleiben unverändert. Nur die strukturell blockierte Entscheidungsebene wird repariert. Die Live-App, GitHub und Render wurden nicht verändert.

## Eingefrorene Änderungen

1. Relative Edge wird nur gegen den direkt widersprechenden Ausgang desselben Marktes berechnet.
2. Eine niedrige Frühphasen-Stichprobe darf nur dann kompensiert werden, wenn Empirical-Bayes-Shrinkage aktiv ist und alle übrigen Qualitäts-, Multi-Block-, Underlying-, Kohärenz- und Removal-Prüfungen bestehen.
3. Die SPIELEN-Schwelle bleibt bei mindestens 65 %.
4. Starke Gegenargumente, starke Underlying-Widersprüche oder ein Single Point of Failure bleiben Sperren.

## Vergleich auf 102 sauberen Vor-Spiel-Analysen

- v0.4.0 SPIELEN: **0**
- v0.4.1 SPIELEN: **8**
- Treffer der v0.4.1-SPIELEN-Auswahl: **6/8 (75.0 %)**
- 95-%-Wilson-Intervall: **40.93–92.85 %**

## Kandidaten

| Datum | Spiel | Markt | Modell | Ergebnis | Treffer |
|---|---|---|---:|---:|---:|
| 2026-08-29 | AZ – Go Ahead Eagles | btts_yes | 66.1 % | 5:2 | JA |
| 2026-08-29 | Young Boys – Basel | btts_yes | 66.4 % | 3:3 | JA |
| 2026-08-29 | Cercle Brugge – Lommel United | over_2_5 | 67.7 % | 0:1 | NEIN |
| 2026-08-29 | OH Leuven – Standard Liège | btts_yes | 68.8 % | 1:2 | JA |
| 2026-08-30 | Royal Antwerp FC – Sint-Truiden | btts_yes | 65.4 % | 1:4 | JA |
| 2026-08-30 | VVV – Emmen | btts_yes | 65.9 % | 4:0 | NEIN |
| 2026-08-30 | Skalica – DAC | btts_yes | 66.3 % | 1:6 | JA |
| 2026-08-30 | Widzew Łódź – Lech Poznań | btts_yes | 66.0 % | 2:3 | JA |

## Bewertung

Das Ergebnis zeigt, dass die korrigierte Entscheidungsebene wieder selektieren kann. Es ist noch keine endgültige Produktionsfreigabe: Die acht SPIELEN-Fälle stammen aus demselben Diagnosezeitraum und das Konfidenzintervall ist breit. Die Regel ist nun eingefroren und muss unverändert an neuen, chronologisch späteren Spielen bestätigt werden.

## Integrität

- Der Gate-Code erhält ausschließlich gespeicherte Pre-Match-Analysen.
- Endstände werden erst nach der Entscheidung zum Auswerten verbunden.
- Keine Quoten, kein Value und keine externen Matchinformationen fließen in die Entscheidung ein.
