# FootyStats v0.4.1 Offline-Gate-Test

Diese Version ist **nicht** in GitHub, Render oder die Live-App eingebaut.

Sie übernimmt die gespeicherten Wahrscheinlichkeiten der v0.4.0 unverändert und testet ausschließlich eine reparierte Entscheidungsebene:

- Gegenmarkt-Edge statt Vergleich korrelierter Märkte
- niedrige Frühphasen-Stichprobe nur bei vollständigem Shrinkage-/Stress-Nachweis kompensierbar
- mindestens 65 % für SPIELEN
- Multi-Block, Removal, Underlying, Datenqualität, Kohärenz und Single-Point-Prüfung bleiben aktiv

`v041_decision_gate.py` enthält die eingefrorene, ergebnisunabhängige Regel. `run_v041_backtest.py` verbindet erst anschließend die tatsächlichen Endstände zur Auswertung.
