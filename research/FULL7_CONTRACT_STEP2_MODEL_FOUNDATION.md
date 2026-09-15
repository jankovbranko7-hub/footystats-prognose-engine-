# FULL-7 Contract — Step 2 Model Foundation

Status: DEVELOPMENT ONLY

## Architecture lock
This checkpoint implements the model foundation required by FULL7_ARCHITEKTURVERTRAG:
- one broad outcome-blind 620-feature core is offered to 1X2, BTTS and Totals;
- no hard-coded football-domain exclusions by target family;
- CatBoost probabilities exist for all seven markets;
- the learned Home/Away goal-intensity model + Dixon-Coles produces structural probabilities for all seven markets;
- no manual ensemble weights, calibration or decision thresholds are introduced here.

## Temporal development corpus
- 300 strict pre-match development matches
- 2026-08-28 through 2026-09-07
- 10 chronological date blocks
- first 4 blocks seed training
- 6 future date blocks
- 180 saved walk-forward OOF predictions
- shuffle: false
- odds: false
- same broad core for all model families: true

## CatBoost OOF — 180 rows
- 1X2 LogLoss: 1.0262874401
- 1X2 Brier: 0.6160721928
- 1X2 Accuracy: 0.4666666667
- BTTS LogLoss: 0.7463238883
- BTTS Brier: 0.2688426433
- BTTS Accuracy: 0.5666666667
- O2.5 LogLoss: 0.6967809410
- O2.5 Brier: 0.2489060986
- O2.5 Accuracy: 0.6055555556

## Goal Model OOF — 180 rows
Home and away goals are learned with CatBoost Poisson regressors. The resulting lambdas are converted to a Dixon-Coles score matrix.

- 1X2 LogLoss: 1.0406464078
- 1X2 Brier: 0.6245114104
- 1X2 Accuracy: 0.4777777778
- BTTS LogLoss: 0.6805888180
- BTTS Brier: 0.2440167665
- BTTS Accuracy: 0.5666666667
- O2.5 LogLoss: 0.6987703786
- O2.5 Brier: 0.2523567956
- O2.5 Accuracy: 0.5222222222

## Frozen development artifacts
Five 300-row development models:
1. 1X2 CatBoost multiclass
2. BTTS CatBoost binary
3. O/U 2.5 CatBoost binary
4. Home-goals CatBoost Poisson regressor
5. Away-goals CatBoost Poisson regressor

Feature count for every model: 620.

Final development rho fitted from the 300-row development corpus:
- rho = -0.275

Model bundle:
- SHA-256: 62dc5ff31fdb144d40c9c873ab2cd35de5b349a6497c2e50fe2c1ea3019a6187
- bytes: 287049

## Important
This is NOT the final engine and is NOT production-ready.
The following architecture layers still have to be learned/built without arbitrary rules:
1. OOS ensemble per target/market
2. calibration per market
3. evidence engine for all 7 markets
4. counterargument tests
5. removal/robustness tests
6. sample security
7. data quality
8. coherence/OOD
9. SPIELEN/BEOBACHTEN/AUSLASSEN for every market
10. new untouched forward OOS
