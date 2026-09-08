# FULL-5 NEXT AI 2.0 — Model Card

## Zweck

Die Decision Engine rankt sechs Wettmärkte pro Match. Sie verändert weder
Lambda Home/Away noch eine der sieben Wahrscheinlichkeiten des V0.4.3-Cores.

## Trainingsstand

- 247 eindeutige Strict-Pre-Match-Spiele mit verifiziertem Resultat
- 1.482 abhängige Match×Markt-Kandidaten; zeitliche Splits erfolgen immer auf Match-Ebene
- Ridge-logistische Regression, `C = 0.003`
- 18 Modellinputs: zwölf kontinuierliche Decision-Signale und sechs Marktindikatoren
- 80 nach Match gruppierte Bootstrap-Fits für Rangstabilität
- versionierter Parametersatz: `full5_next_ai_model.json`

## Genutzte Decision-Signale

- MatchDaten: Pre-Match-xG und Pre-Match-PPG
- LeagueDaten: Venue-PPG, BTTS, Over 2.5, First-Half-BTTS, Halbzeit-Tore, CS/FTS-Zero-Goal-Profil
- FormDaten: Last-5/Last-10-PPG sowie Last-10-BTTS/Over-Profile
- TableDaten: relatives Venue-PPG
- PlayerDaten: Goal-Contribution pro 90, Player Depth
- V0.4.3 Core: Markt-Wahrscheinlichkeit und normalisierte Marktfamilienstärke

Nicht anwendbare Marktfamilienfelder werden durch die fest definierte
Markttransformation als strukturell neutral geführt; fehlende tatsächlich
benötigte Werte werden nicht ersetzt und führen zu KEIN BET.

## Chronologische interne Validierung

Die ersten 97 Matches bilden das anfängliche Training. Danach folgen fünf
nicht überlappende Zeitblöcke mit je 30 Matches.

- AI-Marktranking: 94/150 = 62,67 %
- höchste rohe Core-Wahrscheinlichkeit: 86/150 = 57,33 %
- bisherige Familiennormalisierung: 93/150 = 62,00 %
- finale AI-Plays: 52/70 = 74,29 %

Die 74,29 % sind Rolling-OOF und keine Garantie für zukünftige Ergebnisse. Die
frühere 87-Match-OOS-Periode war bereits benutzt und ist daher kein unangetastetes
OOS für diese neue Architektur.

## Entscheidung

Das Modell wählt den Markt mit dem höchsten gelernten Correctness-Score.
SPIELEN ist nur möglich, wenn zusätzlich Strict Pre-Match, Fünf-Dateien-Audit,
75 % der anwendbaren Evidenzblöcke, null Counter, Core-Robustheit und eine
mehrheitlich stabile Bootstrap-Rangfolge erfüllt sind. Es existiert kein harter
Core-Probability-Cutoff. Sample Quality wirkt kontinuierlich.

## Grenzen

Ohne historische Quoten optimiert das Modell Trefferrisiko, nicht Profit oder
ROI. Automatisches Online-Nachlernen ist deaktiviert: Ein neuer Parametersatz
erfordert erneut chronologisch gruppiertes Training, Versionierung und Tests.
