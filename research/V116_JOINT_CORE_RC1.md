# V1.1.6 Joint-Core Research RC1

Status: research only. Main and Render production are unchanged.

## Integration contract

- Five SPEC-v1.1 FootyStats files and all strict integrity checks remain mandatory.
- The complete V1.1.6 signal comparison remains available as `evidence_diagnostic`.
- Final market selection comes from a coherent joint Poisson score matrix.
- Home/away venue xG and xGA are continuously shrunk to their live competition distributions by empirical Bayes.
- Four attack/defence compositions are averaged.
- Match `total_xg_prematch` anchors the total goal rate when available.
- No historical residual correction and no ML market reranker are used.
- The market-conditional conservative action layer uses historical OOF Wilson lower-bound ordering, not a manual probability cutoff.

## Backtest evidence used for the research action layer

Historical OOF market selections:

- Over 2.5: 48/63 = 76.2%, Wilson lower 64.4%.
- BTTS Yes: 115/194 = 59.3%, Wilson lower 52.2%.
- Under 2.5: 12/20 = 60.0%, Wilson lower 38.7%.

Later 143-match block for the complete research concept:

- Joint-Core selection: 89/143 = 62.2%.
- SPIELEN: 25/38 = 65.8%.
- BEOBACHTEN: 62/100 = 62.0%.
- AUSLASSEN: 2/5 = 40.0%.

The SPIELEN advantage is not statistically established (Fisher exact p=0.697).
RC1 therefore must not be promoted without another unchanged forward block and
explicit release authorization.
