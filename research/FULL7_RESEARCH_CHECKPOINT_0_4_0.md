# FULL-7 Research Checkpoint 0.4.0

## Completed in this checkpoint
- Added outcome-blind market-specific feature contracts.
- Added coherent Poisson/Dixon-Coles probability core.
- Added temporal goal-intensity research with fold-local rho calibration.
- Added paired date-block bootstrap comparison against rolling market base rates.
- No production threshold and no Render deployment.

## 300-match historical development corpus
- 300 canonical Strict legacy matches.
- 300 verified targets.
- 10 chronological date blocks.
- First 4 blocks used as seed history; 6 later blocks evaluated prequentially.
- Referee/Manager remain NOT_CAPTURED_HISTORICALLY and are never backfilled.

## Goal-intensity specialist
The learned home/away goal model uses football-semantic, outcome-blind inputs and derives coherent
1X2 / BTTS / O2.5 probabilities from one score matrix. Dixon-Coles rho is selected only from
an earlier calibration date inside each temporal fold.

Evaluation over 180 future-block matches:
- 1X2 LogLoss: 1.0364
- BTTS LogLoss: 0.6810
- O2.5 LogLoss: 0.6892

## Best development expert by family
- 1X2: direct CatBoost FULL core — LogLoss 1.0241.
- BTTS: learned goal-intensity / Dixon-Coles specialist — LogLoss 0.6810.
- TOTALS O2.5: no learned feature model promoted; rolling prior remains stronger at 0.6727.

## Date-block bootstrap vs rolling prior
Paired loss deltas are model minus prior; negative is better.

### 1X2 direct CatBoost
- Mean delta: -0.0583
- 95% block-bootstrap interval: [-0.0891, -0.0350]
- Bootstrap probability model is better than prior: 1.000

### BTTS goal-intensity model
- Mean delta: -0.0222
- 95% block-bootstrap interval: [-0.0846, +0.0335]
- Bootstrap probability model is better than prior: 0.781

### O2.5 total-goals model
- Mean delta: +0.0012
- 95% block-bootstrap interval: [-0.0331, +0.0364]
- Bootstrap probability model is better than prior: 0.476

## Readiness
- 1X2: DEVELOPMENT_CANDIDATE_STRONG
- BTTS: DEVELOPMENT_CANDIDATE_NEEDS_NEW_OOS
- TOTALS: HOLD_NO_INCREMENTAL_SIGNAL_YET
- SPIELEN/BEOBACHTEN gate: HOLD
- Production: LOCKED / unchanged

## Integrity
The 620-feature general core is no longer interpreted as 620 independent votes.
Market-specific models consume many factors, while signal-group independence remains separate.
No odds, no provider potentials in the core, no H2H core vote, no target/post-match leakage.
