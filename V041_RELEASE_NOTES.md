# FootyStats Prognose Engine V0.4.1

Backtest-driven release based on 190 archived analyses, 180 unique final results and 137 strict V0.4.0 pre-match snapshots.

## Changes

- Keeps the exact V0.4.0 production app as `app_v040.py` for compatibility and rollback.
- Caps league empirical-Bayes prior exposure at 2.0 instead of allowing extreme early-season shrinkage.
- Builds one coherent Poisson score grid from an 85% raw team core plus 15% capped league-relative stabilizer.
- Uses MatchDaten pre-match xG and PPG through the raw team core and as a directional evidence block.
- Uses FormDaten as one Last10-level + Last5-momentum block; Last5/6/10 are not counted independently.
- Uses TableDaten as 1X2 context without double-counting LeagueDaten GF/GA/PPG.
- Uses PlayerDaten only as O/U goal-intensity evidence (goals/90 + assists/90), never as an unconfirmed lineup adjustment.
- Replaces raw cross-family ranking with normalized 1X2 / BTTS / O-U family strength.
- Replaces the impossible global 5pp edge gate with family-relative conviction and real directional confirmation blocks.
- Adds strict kickoff integrity from `date_unix` and blocks post-kickoff `SPIELEN` decisions.
- Keeps the five-file iPhone workflow and archive format intact.

## Validation reference

Historical offline gate simulation on the 137 strict pre-match snapshots produced 27 `SPIELEN` cases with 23 correct (85.2%). This is an in-sample historical validation of the gate structure, not a guarantee of future performance.

## Rollback

Frozen V0.4.0 backup branch: `backup/v0.4.0-pre-v0.4.1-20260903`.
