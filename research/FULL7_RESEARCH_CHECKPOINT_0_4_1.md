# FULL-7 Research Checkpoint 0.4.1

## Additional completed work
- Market-specific outcome-blind feature contracts committed.
- Coherent Poisson/Dixon-Coles probability core committed.
- Probability-source/readiness contract committed.
- Development validation API now exposes per-market feature counts and research readiness.
- Temporal calibration experiment completed and rejected because it degraded later OOF performance.

## Temporal calibration result on later 105 OOF matches
### 1X2
Raw direct CatBoost:
- LogLoss 1.03435
- Brier 0.62157

Temperature-scaled:
- LogLoss 1.04707
- Brier 0.62959

### BTTS
Raw learned goal-intensity probability:
- LogLoss 0.67141
- Brier 0.23983

Temporal Platt calibration:
- LogLoss 0.68597
- Brier 0.24646

Conclusion: no post-hoc calibrator is promoted from this inspected development corpus.

## Current candidate architecture
1. 1X2 probability candidate:
   - direct CatBoost FULL outcome-blind core
   - readiness: DEVELOPMENT_CANDIDATE_STRONG

2. BTTS probability candidate:
   - learned home/away goal intensities
   - coherent score matrix + Dixon-Coles correction
   - rho learned only from earlier calibration data
   - readiness: DEVELOPMENT_CANDIDATE_NEEDS_NEW_OOS

3. O/U 2.5:
   - no learned probability candidate promoted yet
   - readiness: HOLD_NO_INCREMENTAL_SIGNAL_YET

4. Decision/recommendation layer:
   - not promoted
   - no manual probability threshold
   - family readiness cannot be borrowed across markets

## Production
Production app.py remains outside the development wiring.
No Render deployment.
