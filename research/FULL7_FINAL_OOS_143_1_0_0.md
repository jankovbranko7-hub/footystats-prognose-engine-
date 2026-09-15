# FULL-7 GATED 1.0.0 — FINAL OOS / RELEASE AUDIT

## Data separation
- Development corpus: 300 canonical Strict pre-match matches, 2026-08-28 through 2026-09-07.
- Final OOS corpus: 143 later Strict pre-match matches, 2026-09-11 through 2026-09-13.
- Match-ID overlap between development and final OOS: 0.
- Final OOS Gold processing: 143/143, 0 mapping failures.
- Historical OOS sources: Match, League, Form, Table, Player.
- Referee/Manager were not historically captured for the 300+143 model-validation corpus and are not assigned unvalidated model weight.

## Frozen model artifacts
- Engine: FULL7_GATED_1.0.0
- Model contract: FULL7_MODEL_CONTRACT_1.0
- Core 1X2 feature count: 620
- BTTS goal-intensity feature count: 594
- Totals feature count: 556
- Dixon-Coles rho used by the final BTTS score model: -0.20
- Bundle SHA-256: 1e78d4d6db40f6c7cd66a0c189c40bd7cae31462c03cbc082e3dc04917647dd3

## Final 143-match OOS
### 1X2
- Model LogLoss: 1.0738
- Rolling-prior LogLoss: 1.0799
- Model accuracy: 39.9%
- Rolling-prior accuracy: 42.7%
- Status: OOS_OBSERVE_ONLY. Small LogLoss advantage, not robust enough for SPIELEN.

### BTTS
- Model LogLoss: 0.6597
- Rolling-prior LogLoss: 0.6834
- Model Brier: 0.2338
- Rolling-prior Brier: 0.2451
- Status: OOS_VALIDATED_SELECTIVE.

### Over/Under 2.5
- Model LogLoss: 0.6887
- Rolling-prior LogLoss: 0.6960
- Model Brier: 0.2475
- Rolling-prior Brier: 0.2513
- Status: OOS_OBSERVE_ONLY. Improvement is too small/not robust enough for SPIELEN.

## Decision gate
The decision threshold was frozen from the 300-match development corpus before the 143-match OOS evaluation.

- BTTS SPIELEN confidence threshold: 0.632489
- BTTS feature coverage floor: 0.98989898989899
- Minimum available BTTS signal families: 8
- Allowed direction flips under single-family removal stress: 0

Final OOS decision performance:
- SPIELEN: 21/30 = 70.0%
- BEOBACHTEN: 38/60 = 63.3%
- AUSLASSEN: 25/53 = 47.2%

The observed ordering is therefore monotonic in the intended direction on this OOS block.

## Production policy
- BTTS may emit SPIELEN / BEOBACHTEN / AUSLASSEN under the frozen gate.
- 1X2 probabilities are exposed but cannot emit SPIELEN in FULL7_GATED_1.0.0.
- O/U 2.5 probabilities are exposed but cannot emit SPIELEN in FULL7_GATED_1.0.0.
- Odds are not model inputs.
- Provider potentials are not model-core inputs.
- H2H is not a core evidence vote.
- Referee/Manager remain validated live inputs but are not model-weighted until strict historical evidence exists.
- Missing/insufficient model features fail closed to AUSLASSEN.
