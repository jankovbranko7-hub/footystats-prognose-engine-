# V0.4.2 Dixon-Coles — 137 strict pre-match comparison

Status: parallel candidate only. Production `main` remains V0.4.1.

## Fair comparison design

- Population: 137 unique V0.4.x snapshots created strictly before kickoff.
- Competitions: 36.
- Same V0.4.1 hybrid lambda engine for both models.
- Only score-distribution layer changes:
  - V0.4.1: independent Poisson.
  - V0.4.2 candidate: Dixon-Coles, rho = -0.25.
- Dixon-Coles rho was selected in every competition-grouped training fold at the frozen lower grid bound -0.25.
- No odds and no external match data are used by the candidate.

## Out-of-fold probability metrics

| Metric | V0.4.1 Poisson | V0.4.2 Dixon-Coles | Better |
|---|---:|---:|---|
| 1X2 Brier | 0.630496 | 0.620568 | V0.4.2 |
| 1X2 Log Loss | 1.050250 | 1.034000 | V0.4.2 |
| BTTS Brier | 0.226341 | 0.221117 | V0.4.2 |
| BTTS Log Loss | 0.644998 | 0.634075 | V0.4.2 |
| O/U 2.5 Brier | 0.222202 | 0.222202 | equal |
| O/U 2.5 Log Loss | 0.636279 | 0.636279 | equal |
| Aggregate Brier | 0.254597 | 0.251201 | V0.4.2 |
| Aggregate Log Loss | 0.777176 | 0.768118 | V0.4.2 |

Lower Brier and Log Loss are better.

## V0.4.1 family-normalized selection rerun

The same family normalization used by V0.4.1 was applied to each model's probabilities.

| Selection cut | V0.4.1 | V0.4.2 |
|---|---:|---:|
| All 137 selected-family hits | 84/137 = 61.3% | 91/137 = 66.4% |
| Family strength >= 20% | 62/96 = 64.6% | 68/97 = 70.1% |
| Family strength >= 30% | 39/52 = 75.0% | 38/49 = 77.6% |

The selected market changed in 39 of 137 matches.

## Interpretation

Dixon-Coles improves 1X2 and BTTS calibration while leaving O/U 2.5 essentially unchanged in this sample. It also improves the accuracy of the market selected by the V0.4.1 family-normalization layer. This is evidence in favor of V0.4.2 as the next candidate, not proof of future superiority: the historical window is short and the parameter must still be validated on new unseen matches.

## Release rule

Do not promote to production solely from this backtest. Keep V0.4.1 as production/control and collect new strict pre-match snapshots. Promote V0.4.2 only after an independent live sample confirms the calibration gain or after the user explicitly chooses the measured historical improvement over the remaining validation risk.
