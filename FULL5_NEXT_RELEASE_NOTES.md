# FULL-5 NEXT AI 2.1.0 — Release Notes

Diese Version korrigiert den finalen Decision-Pfad, ohne Probability Core oder
Six-Market-Ranking zu verändern.

- V0.4.3 FULL-5 Core unverändert: 40 Features, Alpha 3.0, rho -0.25.
- V0.4.2 Hybrid-Lambda bleibt Basis/Fallback; Elite-Lambda bleibt aus.
- Bestehendes Ranking unverändert: 247 Matches, 1.482 Kandidaten, 18 Inputs,
  80 Bootstrap-Modelle.
- Neue finale Modellstufe: trainierte Ridge-logistische Reliability-/
  Abstention-Policy mit 55 Inputs und 80 Bootstrap-Modellen.
- PLAY-/OBSERVE-Grenzen werden durch KMeans auf Development-internen
  Reliability-Werten gelernt und im Modellartefakt gespeichert.
- Entfernt aus dem finalen Decision-Pfad: Confirmation Ratio 0.75/0.50,
  Counter-Grenzen 0/1, Rank-Stability 0.50 sowie Robustheits-Boolean-Gate.
- Evidence-, Confirmation- und Counter-Regeln bleiben rein diagnostisch.
- Harte Overrides sind nur Integrität: Strict Pre-Match, fünf Dateien, Audit,
  Leakage-Schutz, gültige Kerninputs.
- Export: `FINAL_DECISION_SOURCE = TRAINED_AI_POLICY`,
  `MANUAL_PERFORMANCE_GATES = NONE`.
- Development-only rolling grouped OOF: 60 Matches, 29 Plays, 18 Treffer
  (62,07 %), Play Rate 48,33 %; zwei Zeitblöcke mit 61,54 % und 62,50 %.
- Das frühere 87-Match-OOS wurde nicht für Policy-Training oder Grenzwahl
  benutzt und wird nicht als unangetastete Validierung beworben.

Der geschützte Branch `backup/v0.4.3-full5-2026-09-07` bleibt unangetastet.
