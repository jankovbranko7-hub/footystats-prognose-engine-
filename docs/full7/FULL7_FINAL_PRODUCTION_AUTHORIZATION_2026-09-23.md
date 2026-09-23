# FULL-7 FINAL Production Authorization — 2026-09-23

## Explicit user authorization

The user explicitly instructed: **"Jetzt veröffentlichen"** on 2026-09-23.

This authorization permits promotion of `FULL7_FINAL_RC_1.0.0` to `main`
and deployment to the Render production service.

## Known validation status

The historical final-release workflow still reports these release-constraint
blockers:

- `FORWARD_OOS_MAIN_MERGE_FORBIDDEN`
- `FORWARD_OOS_RENDER_DEPLOY_FORBIDDEN`
- `FORWARD_OOS_NO_SPIELEN_EXPOSURE`

The same workflow confirms:

- regression suite: PASS
- forward-OOS audit flags: PASS
- all predictions frozen before results: true
- no result leakage: true
- no architecture change during validation: true
- architecture contract audit: PASS
- dependency audit: PASS
- prospective/current-RC playing exposure requirement is not satisfied

No claim is made that prospective CP7/current-RC SPIELEN exposure has been
completed. That requirement remains **DEFERRED / NOT SATISFIED** for this
user-authorized release.

## Production semantics

- Engine: `FULL7_FINAL_RC_1.0.0`
- Existing seven-file browser workflow retained.
- HOME: Phase-6 frozen rules.
- AWAY: Phase-6 frozen rules.
- DRAW: `AUSLASSEN_ONLY`.
- BTTS YES: Phase-6 frozen rules.
- BTTS NO: `BEOBACHTEN_ONLY`.
- O25/U25: `HOLD`.
- Legacy V3.1 override: inactive.
- V3.1 remains recoverable from Git history as rollback.
