# FULL-7 Contract — Step 5 Empirical Decision Engine

Status: DEVELOPMENT ONLY — NEW UNTOUCHED OOS REQUIRED

## Decision architecture

The decision layer is learned on the 180 temporally out-of-fold development rows created by the frozen Step-2 model foundation.

It does not use a hand-written rule such as:
- probability >= 65%
- 6 of 12 confirmations
- 4 confirmations for low sample

Instead, each family uses:
1. calibrated ensemble probability,
2. model disagreement,
3. independent-cluster removal evidence,
4. confirmation/counterargument breadth,
5. removal robustness / family preference flips,
6. feature coverage,
7. OOD fraction,
8. sample-security diagnostics,
9. family probability margin,
10. CatBoost/Goal-model directional agreement.

The three families remain:
- 1X2 → Home / Draw / Away
- BTTS → Yes / No
- TOTALS → Over 2.5 / Under 2.5

Every one of the seven markets receives a final decision state.

## Coherence rule

For each mutually exclusive family, only the ensemble-preferred market may be an active candidate.

Example:
- BTTS Yes selected → BTTS Yes can be SPIELEN / BEOBACHTEN / AUSLASSEN
- BTTS No → AUSLASSEN with reason COHERENCE_NOT_SELECTED

This is not a structural market exclusion. The preferred side is recalculated for every match.

The same rule applies to:
- Home / Draw / Away
- BTTS Yes / BTTS No
- Over 2.5 / Under 2.5

## Evidence-adjustment model

The calibrated model probability is the base log-odds offset.

Evidence can adjust the log-odds using a regularized logistic adjustment:

logit(reliability) = logit(base probability) + beta * standardized evidence vector

The L2 regularization strength is selected by forward date-block LogLoss, not hand-picked.

All three final family models selected lambda = 100 on the full development OOF history.

## Decision-strategy candidates

Only evidence-active decision strategies were eligible:

### EVIDENCE_ADJUSTED
Use the evidence-adjusted reliability score directly.

### EVIDENCE_DOWNGRADE
Evidence may reduce the base probability reliability score but may not inflate it:

score = min(base_probability, evidence_adjusted_probability)

Selection rule:
- require prospective SPIELEN >= BEOBACHTEN >= AUSLASSEN hit-rate ordering;
- among eligible evidence-active strategies choose the lowest prospective LogLoss.

Prospective evaluation window:
- 2026-09-05
- 2026-09-06
- 2026-09-07
- 105 selected-family cases per family

The gate for each of those dates was fitted only from earlier OOF dates.

## Selected family strategies

### 1X2
Selected: EVIDENCE_ADJUSTED

Prospective:
- SPIELEN: 9 / 15 = 60.00%
- BEOBACHTEN: 32 / 59 = 54.24%
- AUSLASSEN: 10 / 31 = 32.26%
- LogLoss: 0.6838716953
- Brier: 0.2457417125

Final development thresholds, refit from temporal cross-fit scores:
- AUSLASSEN → BEOBACHTEN: 0.4540733503
- BEOBACHTEN → SPIELEN: 0.6787245914

### BTTS
Selected: EVIDENCE_DOWNGRADE

Prospective:
- SPIELEN: 10 / 13 = 76.92%
- BEOBACHTEN: 11 / 17 = 64.71%
- AUSLASSEN: 38 / 75 = 50.67%
- LogLoss: 0.6750185463
- Brier: 0.2414006665

Final development thresholds:
- AUSLASSEN → BEOBACHTEN: 0.5814200942
- BEOBACHTEN → SPIELEN: 0.6298345464

### TOTALS
Selected: EVIDENCE_DOWNGRADE

Prospective:
- SPIELEN: 10 / 14 = 71.43%
- BEOBACHTEN: 29 / 52 = 55.77%
- AUSLASSEN: 20 / 39 = 51.28%
- LogLoss: 0.6717996343
- Brier: 0.2402064899

Final development thresholds:
- AUSLASSEN → BEOBACHTEN: 0.5683940094
- BEOBACHTEN → SPIELEN: 0.7577724475

## Three-state threshold learning

Thresholds are not manually set.

Temporal cross-fit reliability scores are sorted and segmented into three ordered states using:
- leave-one-out predictive LogLoss,
- monotonic posterior event rates,
- data-dependent regularization min-bin = ceil(sqrt(n)).

This creates the three required states:
- AUSLASSEN
- BEOBACHTEN
- SPIELEN

without a hand-written probability rule.

## Sample security

Sample Security is derived from development-relative exposure.

The runtime compares relevant sample features with their development q25 levels and summarizes the fraction below those levels.

Development low-sample-fraction reference:
- q25 = 0.0555555556
- median = 0.1111111111
- q75 = 0.1666666667

Runtime:
- <= q25 → HIGH
- <= q75 → MEDIUM
- > q75 → LOW

These boundaries are empirical development quantiles, not fixed match-count rules.

## Data-quality / OOD fail-closed behavior

A selected market is forced to AUSLASSEN if:
- core coverage falls below the observed development minimum;
- OOD fraction q01-q99 exceeds the observed development maximum;
- probability coherence fails;
- an odds feature appears in the probability-mode Gold features.

Development references:
- coverage min = 0.9903225806
- OOD q01-q99 max = 0.0870967742

## H2H / Referee / Manager

These remain full architecture blocks.

Current historical 300-match model corpus does not contain strict historical Referee/Manager outcome coverage sufficient for learned decision coefficients.

Therefore:
- valid live block → reported and sample-audited;
- no fabricated weight;
- no silent exclusion from the architecture;
- learned decision weight remains pending future strict FULL-7 history.

H2H remains secondary and sample/age-aware; it is not given fabricated independent predictive weight without incremental OOS proof.

## Current contract completion

Implemented:
- 7-file Bronze/Silver/Gold foundation
- Feature Registry
- broad 620-feature core
- signal-group independence
- CatBoost all 7 markets
- Dixon-Coles Goal Model all 7 markets
- learned OOS ensemble
- explicit Calibration layer
- Evidence Engine all 7 markets
- Counterarguments
- Removal / Robustness
- Sample Security
- Data Quality / OOD
- Coherence
- empirical Decision Engine all 7 markets

Still required before production promotion:
- NEW UNTOUCHED FORWARD OOS using real 7-file snapshots collected after this architecture freeze
- final regression / dependency / live release audit

The existing production FULL7_GATED_1.0.0 is not changed by this checkpoint.
