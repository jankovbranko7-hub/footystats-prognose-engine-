# FULL-7 Phase 6 Decision Research — frozen protocol

Status: implementation-only research artifact. Not wired into the Render service runner.

## Binding inputs

- Phase-4 manifest SHA-256: \`fd4d33b289602e09b7d6ad82565a83c310d444f20f517af687d255792e3f50b5\`
- Phase-5 calibration decision lock SHA-256: \`cb48662360cd66b4e7daaf84ff47294c04d8bb7983e3da9cceecc30207984a99\`
- Phase-5 manifest SHA-256: \`189057b6bc81c0e86b1eb1eb7d131e9592c320dd01f7a4ccaaf9b46ae885ab1a\`
- 1X2: GOAL_POISSON_LOCKED / 298 / MULTINOMIAL_LOGIT
- BTTS: GOAL_POISSON_LOCKED / 209 / IDENTITY
- O25: HOLD

## Leakage barrier

Before \`PHASE6_DECISION_LOCK.json\` is persisted, Phase 6 reads only:

- \`PHASE5_PREOOS_1X2.npz\`
- \`PHASE5_PREOOS_BTTS.npz\`
- Phase-5 calibration decision lock
- Phase-4 feature matrix / metadata / pre-OOS locked-feature definitions

It does not open Phase-4 OOS predictions or labels.

After the decision lock is written and SHA-256 hashed, the runner opens the frozen OOS artifacts once and reports OOS1/OOS2/OOS3/ALL. No rule is modified after this point.

## Gate dimensions

PLAY/WATCH/SKIP are not probability-only. Rules combine:

1. probability threshold
2. preferred direction / 1X2 argmax coherence
3. empirical support
4. 0.05 probability-bin support
5. aggregate calibration gap
6. segment calibration gap
7. calibration slope/intercept
8. Wilson 95% uncertainty
9. chronological DEV1/DEV2/DEV3 stability
10. selected-feature row coverage (TRAIN-forward 1% lower-tail guard)
11. prediction integrity/coherence
12. upper-tail extrapolation guard

The threshold candidate grid is fixed in source. Hit rate is never a candidate-ranking term. Among fully passing candidates the selector prefers a robust no-margin rule, then maximal coverage, then lower calibration gap and lower log loss.

## O25

No Phase-6 O25 path exists. The module cannot research or evaluate O25 thresholds.

## Production boundary

The module is deliberately not imported by \`research/run_full7_phase2_phase3.py\`. It requires explicit invocation and performs no deploy, production edit, main merge, collection, or API request.
