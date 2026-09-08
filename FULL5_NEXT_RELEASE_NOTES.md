# FootyStats FULL-5 NEXT AI 2.0.0

Finaler Produktionsstand auf Basis von V0.4.3 FULL-5.

- Probability Core unverändert: 40 Features, Alpha 3.0, Dixon-Coles rho -0.25.
- V0.4.2 Hybrid-Lambda bleibt Basis und Fallback.
- Elite-Lambda bleibt deaktiviert.
- Keine Änderung an den 40 Probability-Core-Features.
- Keine Datei 6 oder Datei 7.
- Trainierte, stark regularisierte sechs-Markt-Decision-Engine auf 247 Strict- und resultverifizierten Matches beziehungsweise 1.482 Match×Markt-Kandidaten.
- Kontinuierliche Decision-Signale aus Match-, League-, Form-, Table- und PlayerDaten; alle sechs Märkte werden gleichzeitig gescort und gerankt.
- 80 gruppierte Bootstrap-Modelle bestimmen die modellinterne Rangstabilität.
- Kein universeller Probability-Cutoff für SPIELEN oder BEOBACHTEN.
- Sample Quality ist kontinuierlicher Modellinput und besitzt keinen harten Cutoff.
- SPIELEN verlangt 75 % der für die Marktfamilie anwendbaren Evidenzblöcke, null Counter, mehrheitsstabilen AI-Rang, bestandene Core-Robustheit, alle fünf Dateien und Strict Pre-Match.
- BEOBACHTEN und AUSLASSEN / KEIN BET sind eigenständige Zustände.
- Rolling-OOF: fünf expandierende chronologische Außenblöcke mit je 30 Matches; 94/150 Marktauswahlen korrekt und 52/70 Plays korrekt (74,29 %).
- Zeitblock-Playraten: 77,78 %, 76,47 %, 71,43 %, 78,95 %, 63,64 %.
- Die frühere 87-Match-OOS-Periode war vor Entwicklung dieser Architektur bereits ausgewertet und wird ausdrücklich nicht als unangetastetes OOS der AI 2.0 beansprucht.
- Fehlende AI-Kerninputs werden nicht imputiert; der sichere Zustand ist KEIN BET.

V1 ist nicht Bestandteil dieser Veröffentlichung. Der geschützte Backup-Branch `backup/v0.4.3-full5-2026-09-07` bleibt unverändert.
