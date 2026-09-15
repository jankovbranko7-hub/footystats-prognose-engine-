# FULL-7 Research Checkpoint 0.3.0

## Dataset
- Source corpus: 333 physical archive reports / 322 unique match IDs.
- Strict archive snapshots: 308 reports -> 300 canonical unique matches.
- Verified targets: 300/300.
- Date range: 2026-08-28 through 2026-09-07.
- Historical provenance: `LEGACY_ARCHIVE_STRICT` (observed archive.created_at < kickoff).
- Historical source blocks: Match, League, Form, Table, Player.
- Referee/Manager: `NOT_CAPTURED_HISTORICALLY`; never backfilled by this pipeline.

## Gold 0.3.0
- Reproducible league-context anchors are derived from strict /league-teams rows.
- Local 300-match rebuild: 300/300 processed, 0 mapping errors.
- Gold feature universe: 1,000.
- Deterministic outcome-blind probability core: 620.
- Gold minimum coverage: 94.67%.
- Core minimum coverage: 96.33%.
- 908 Gold features have 100% coverage.
- Odds excluded.
- Provider potentials excluded from the probability core.
- H2H remains secondary/research-only for the probability core.

## Date-block prequential development research
Evaluation starts only after the first four date blocks (120 seed matches). No shuffle.

| Expert | 1X2 LogLoss | BTTS LogLoss | O2.5 LogLoss |
|---|---:|---:|---:|
| CatBoost broad core | 1.0241 | 0.7465 | 0.7114 |
| Rolling prior | 1.0824 | 0.7032 | 0.6727 |
| Prematch-xG Poisson | 1.0740 | 0.7107 | 0.7116 |

Development interpretation:
- 1X2 CatBoost: promising; beats both simple baselines in this run.
- BTTS CatBoost: not promoted; worse than rolling prior.
- O2.5 CatBoost: not promoted; worse than rolling prior.
- No final OOS claim: these blocks have now been inspected.

## Temporal learned stacker
On the later 105 OOF rows:
- 1X2 stacker LogLoss 1.0645 vs raw CatBoost 1.0343.
- BTTS stacker 0.6955 vs rolling prior 0.7001.
- O2.5 stacker 0.6760 vs rolling prior 0.6538.
- No manual ensemble weights. Stacker remains research-only.

## Calibration / decision diagnostics
- 1X2 top-label ECE: 0.0671.
- BTTS ECE: 0.1567.
- O2.5 ECE: 0.1400.
- Learned correctness/reliability layer is not stable enough for production decision gates.
- No manual probability threshold was introduced.

## Promotion state
- Data pipeline: continue.
- Gold 0.3.0 + derived league context: continue.
- 1X2 learned specialist: development candidate.
- BTTS learned specialist: do not promote current form.
- O2.5 learned specialist: do not promote current form.
- Temporal stacker: research-only.
- Learned SPIELEN/BEOBACHTEN reliability gate: do not promote current form.
- Production release: false.

## Production lock
Production `app.py` remains unchanged at SHA:
`5852e4a476ac3f79aab3471623e1d914a0f7068e`

No Render deployment was performed.
