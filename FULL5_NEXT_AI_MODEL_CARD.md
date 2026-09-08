# FULL-5 NEXT AI 2.1 — Model Card

## Unveränderter Probability Core

V0.4.3 FULL-5 bleibt unverändert: 40 Features, Alpha 3.0, Dixon-Coles rho
-0.25 und V0.4.2 Hybrid-Lambda als Basis/Fallback. Datei 6/7 und Elite-Lambda
sind deaktiviert.

## Trainiertes Six-Market-Ranking

- Ridge-logistische Regression (`C = 0.003`)
- 247 Strict-/resultverifizierte Matches, 1.482 Match×Markt-Kandidaten
- 18 Ranking-Inputs
- 80 nach Match gruppierte Bootstrap-Modelle
- Ranking-Parametersatz gegenüber AI 2.0 unverändert

## Trainierte Reliability-/Abstention-Policy

Die zweite Modellstufe lernt, ob der ausgewählte Markt zuverlässig genug für
SPIELEN, BEOBACHTEN oder KEIN BET ist. Sie verwendet 55 kontinuierliche bzw.
rohe Inputs: Ranking-Score und Gap, Bootstrap-Stabilität/Dispersion,
Core-Wahrscheinlichkeit, Lambda, rohe Match-/League-/Form-/Table-/Player-Werte
und kontinuierliche Robustheits-Stresswerte.

- Modelltyp: Ridge-logistische Reliability-Regression (`C = 0.001`)
- 80 Bootstrap-Modelle
- Training ausschließlich auf 120 Development-internen Ranking-OOF-Zeilen
- Aktionsgrenzen aus 3-Cluster-KMeans der trainierten Reliability-Werte
- gelernte Observe-Grenze: `0.6422845219898217`
- gelernte Play-Grenze: `0.6788983142117558`
- das frühere 87-Match-OOS wurde weder für Training noch Grenzwahl verwendet

K=3 folgt aus den drei benötigten Produktzuständen; die Lage der Cluster und
beide Grenzen wurden aus Development-Daten gelernt.

## Chronologische interne Validierung

Development-only second-level rolling grouped OOF: 60 Matches in zwei
disjunkten 30-Match-Zeitblöcken. 29 Plays, 18 Treffer, 62,07 % Trefferquote,
48,33 % Play Rate, Brier 0,26245 und Log Loss 0,73994. Die Zeitblöcke lagen bei
8/13 (61,54 %) und 10/16 (62,50 %). Das ist interne OOF-Validierung und kein
unangetastetes OOS.

## Decision Contract

`FINAL_DECISION_SOURCE = TRAINED_AI_POLICY` und
`MANUAL_PERFORMANCE_GATES = NONE`. Confirmation-/Counter- und Evidence-
Schwellen werden nur für Diagnose/Erklärung berechnet. Auch Robustheitsstatus,
Sample Quality und Rangstabilität besitzen kein Boolean- bzw. manuelles
Performance-Gate.

Nur Integritätsregeln dürfen die gelernte Aktion zu KEIN BET überschreiben:
Strict Pre-Match, alle fünf Dateien, Audit, Leakage-Schutz und gültige
AI-Kerninputs.

Ohne historische Quoten optimiert das Modell Trefferrisiko, nicht Profit oder
ROI. Automatisches Online-Nachlernen ist deaktiviert.
