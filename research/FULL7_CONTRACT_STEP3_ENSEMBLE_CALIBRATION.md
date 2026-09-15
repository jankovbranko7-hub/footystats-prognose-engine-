# FULL-7 Contract — Step 3 OOS Ensemble + Calibration

Status: DEVELOPMENT ONLY

## Prospective temporal ensemble selection
The saved 180 OOF predictions from Step 2 were kept in chronological order.

For ensemble-strategy selection, the later four OOF date blocks (126 rows) were evaluated prospectively. At each date only earlier OOF blocks were available to fit a blend weight.

### 1X2 — 126 prospective rows
- CatBoost LogLoss: 1.0409452499
- Goal Model LogLoss: 1.0645148840
- temporally learned blend LogLoss: 1.0467326144

Selected strategy:
- CATBOOST_ONLY
- CatBoost weight: 1.0
- Goal Model weight: 0.0

Reason: the learned blend did not improve prospective LogLoss over CatBoost alone.

### BTTS — 126 prospective rows
- CatBoost LogLoss: 0.7304763119
- Goal Model LogLoss: 0.6821684794
- temporally learned blend LogLoss: 0.6826483812

Selected strategy:
- GOAL_ONLY
- CatBoost weight: 0.0
- Goal Model weight: 1.0

Reason: the learned blend did not improve prospective LogLoss over the Goal Model alone.

### Over/Under 2.5 — 126 prospective rows
- CatBoost LogLoss: 0.6849355138
- Goal Model LogLoss: 0.6997856926
- temporally learned blend LogLoss: 0.6819501785

Selected strategy:
- LEARNED_BLEND

After the blend strategy itself was selected prospectively, its coefficient was refit on all 180 development OOF rows:
- CatBoost weight: 0.5317803954
- Goal Model weight: 0.4682196046
- 180-row OOF blend LogLoss: 0.6760082574

## Calibration
Calibration is retained as an explicit architecture layer.

Temporal calibration candidates were selected only from earlier blocks and applied to future blocks:
- 1X2: Identity vs Temperature
- BTTS: Identity vs Platt vs Isotonic
- O/U: Identity vs Platt vs Isotonic

Aggregate prospective 126-row results:

### 1X2
- uncalibrated selected ensemble: 1.0467326144
- temporally selected calibrator: 1.0711681580

### BTTS
- uncalibrated selected ensemble: 0.6826483812
- temporally selected calibrator: 0.6850359677

### O/U
- uncalibrated selected ensemble: 0.6819501785
- temporally selected calibrator: 0.6871355993

Therefore the empirically selected calibration method for all three target families is:

IDENTITY / NO_ADJUSTMENT

This does not remove the calibration layer. It records that the tested nonlinear calibrators worsened forward development performance.

## Architecture interpretation
Both CatBoost and the Goal Model remain computed and visible for all seven markets.

A 0.0 ensemble weight is not a structural market exclusion. It is an empirically learned development result for the ensemble output. The unused source remains available for model-disagreement diagnostics, robustness and future retraining.

No SPIELEN / BEOBACHTEN / AUSLASSEN gate is introduced in this step.
