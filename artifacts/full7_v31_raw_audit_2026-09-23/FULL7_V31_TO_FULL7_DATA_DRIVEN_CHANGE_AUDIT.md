# FULL-7 — V3.1 → FULL-7 Data-Driven Change Audit

Status: **PASS**

This audit is a read-only synthesis of the frozen Phase-4/5/6/7 evidence, the
release-candidate implementation, and the completed V3.1 RAW-input recovery
audit. It performs no collection, API recollection, fitting, calibration,
threshold selection, gate selection, main merge, or production deployment.

## Closed V3.1 reconstruction question

The exact strict-pre-match RAW scan completed over all **16,137** frozen research
rows and all **5,552** Locked-OOS rows.

- Unique strict pre-match RAW hashes scanned: **11,893**
- Complete V3.1 base rows in FULL-7 population: **0**
- Complete V3.1 base rows in Locked OOS: **0**
- Collector projection mismatches: **0**
- V3.1 RAW recovery: **NOT_POSSIBLE**
- Same-cohort V3.1 OOS recovery: **NOT_POSSIBLE**

Therefore V3.1 remains a historical reference only; no exact same-cohort
performance-superiority claim is permitted.

## Data-driven changes

| V3.1 component | FULL-7 RC | Decision |
|---|---|---|
| 30 numeric inputs + league category | 298 locked 1X2 features; 209 locked BTTS features | REPLACE |
| Separate V3.1 logistic family models | Locked Goal-Poisson 1X2 and BTTS goal heads | REPLACE |
| No separate final 1X2 calibrator | Multinomial-logit 1X2 calibrator | REPLACE |
| V3.1 BTTS probability path | Goal-Poisson BTTS with identity final calibration | REPLACE |
| Historical 71% / 70% / 60.5% thresholds | Frozen direction-specific Phase-6 zones and gates | REPLACE |
| Active TOTALS/O25 runtime decision | O25/U25 HOLD; no totals runtime model/calibrator/rule | DISABLE |
| Legacy V3.1 decision override | Explicitly inactive | DISABLE |
| Limited integrity contract | Hash pins, HMAC strict-pre-match contract, schema/coverage/coherence/model gates | REPLACE / STRENGTHEN |
| Manual performance gates | Disabled; frozen Phase-6 gates authoritative | DISABLE |

## Reproducible model evidence

On the 5,552 Locked-OOS rows, FULL-7 improved over its reproducible rolling-prior
baselines:

- **1X2:** LogLoss 1.019582 vs 1.069033; Brier 0.610650 vs 0.646210.
- **BTTS:** LogLoss 0.683397 vs 0.687012; Brier 0.245190 vs 0.246938.
- **O25 research model:** LogLoss 0.677250 vs 0.690084; Brier 0.242230 vs 0.248469,
  but runtime remains HOLD.

After frozen Phase-5 calibration:

- **1X2:** Multinomial Logit; LogLoss 1.018113; Brier 0.609679; ECE 0.003710.
- **BTTS:** Identity; LogLoss 0.683397; Brier 0.245190; ECE 0.025039.

Historical Decision-OOS evidence:

- HOME: 1,709 SPIELEN / 1,026 correct / 60.04%.
- AWAY: 350 SPIELEN / 198 correct / 56.57%.
- BTTS YES: 2,202 SPIELEN / 1,320 correct / 59.95%.
- DRAW: 0 SPIELEN.
- BTTS NO: 0 SPIELEN.
- O25/U25: HOLD.

These results are internal FULL-7 OOS evidence and are **not** a same-cohort
V3.1 comparison.

## RC implementation verification

The frozen RC implementation matches the research decisions:

- Release candidate: `FULL7_FINAL_RC_1.0.0`
- Runtime bundle SHA-256:
  `4e30976c04bd0b1cdfaff4c1def1f88753bbee6f016d617ae00b5536a530ee2b`
- Phase-6 Decision Lock SHA-256:
  `627f581e0e3a11c099166abdc792566a7a8fb5e8d252e748fc8e43457813829e`
- 1X2 locked feature count: 298
- BTTS locked feature count: 209
- OOS rows used for final fit: 0
- Legacy V3.1 thresholds/imports active: false
- O25 runtime active: false
- Manual performance gates: false
- Fail-closed integrity path: active
- Product tests: 223/223 PASS
- Phase-7 tests: 53/53 PASS

## Final assessment

`IS_FULL7_A_DATA_DRIVEN_SUCCESSOR_TO_V3_1 = YES`

`FULL7_RC_MATCHES_RESEARCH_DECISIONS = YES`

`FULL7_VS_REPRODUCIBLE_BASELINES = BETTER`

`V3_1_SAME_COHORT_COMPARISON = NOT_RECONSTRUCTABLE`

`PERFORMANCE_SUPERIORITY_OVER_V3_1 = NOT_PROVEN`

`TARGETED_FIXES_REQUIRED = NONE_FROM_EXISTING_FROZEN_EVIDENCE`

`FULL7_FINAL_RC_STATUS = KEEP`

`PROSPECTIVE_CP7_STATUS = NOT_COMPLETE / DEFERRED BY CURRENT USER DIRECTION`

The remaining release question is procedural, not a missing implementation:
whether the project continues to require the original prospective post-freeze
CP7 before release. No production action is authorized by this audit.
