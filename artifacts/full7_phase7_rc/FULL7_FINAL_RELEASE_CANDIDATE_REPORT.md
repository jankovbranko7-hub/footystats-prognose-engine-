# FULL-7 Phase 7 Final Release Candidate

Generated: 2026-09-23 UTC

## Final status

| Field | Result |
|---|---|
| FULL7_FINAL_ENGINE_STATUS | PASS_RELEASE_CANDIDATE |
| FULL7_RELEASE_CANDIDATE_VERSION | FULL7_FINAL_RC_1.0.0 |
| MODEL_LOCK_1X2 | GOAL_POISSON_LOCKED / 298 features |
| MODEL_LOCK_BTTS | GOAL_POISSON_LOCKED / 209 features |
| CALIBRATION_1X2 | MULTINOMIAL_LOGIT |
| CALIBRATION_BTTS | IDENTITY |
| FINAL_DECISION_SOURCE | full7_phase7_decision.py; PHASE6_DECISION_LOCK_SHA256 627f581e0e3a11c099166abdc792566a7a8fb5e8d252e748fc8e43457813829e |
| HOME_RULE | Top-1; SPIELEN 0.50–0.80; BEOBACHTEN 0.40–0.85; coverage >= 97.775%; all gates |
| DRAW_RULE | AUSLASSEN_ONLY; SPIELEN and BEOBACHTEN disabled |
| AWAY_RULE | Top-1; SPIELEN 0.50–0.65; BEOBACHTEN 0.40–0.70; coverage >= 97.775%; all gates |
| BTTS_YES_RULE | SPIELEN 0.55–0.70; BEOBACHTEN 0.50–0.70; coverage >= 98.086%; all gates; no extrapolation above 0.70 |
| BTTS_NO_RULE | SPIELEN disabled; BEOBACHTEN 0.50–0.60 only |
| O25_STATUS | HOLD / NICHT_FREIGEGEBEN |
| MANUAL_PERFORMANCE_GATES | DISABLED; frozen Phase-6 gates are authoritative |
| LEGACY_V3_1_OVERRIDE_AUDIT | PASS_INACTIVE |
| O25_HOLD_AUDIT | PASS_NO_RUNTIME_NO_CALIBRATOR_NO_RULES |
| PRODUCTION_CHANGED | false |
| MAIN_CHANGED | false |
| RELEASE_CANDIDATE_COMMIT | c89e701087e6046569e0f4fd5bc1b602defb4616 |
| READY_FOR_EXPLICIT_PRODUCTION_APPROVAL | true |

## Integrity and decision dependencies

INTEGRITY_GATES:

- aggregate calibration
- coherence
- development segment support
- development total support
- feature coverage
- global calibration intercept
- global calibration slope
- HMAC-trusted strict-pre-match input
- externally pinned manifest SHA-256
- model artifact SHA-256
- no severe overconfidence segment
- predicted mean inside Wilson interval
- probability-bin support
- segment calibration
- TRAIN calibration
- TRAIN-forward support
- Wilson interval width

FINAL_DECISION_DEPENDENCY_AUDIT:

- Final decision module: `full7_phase7_decision`.
- Runtime imports no V3.1 decision module and activates none of the historical 71% / 70% / 60.5% thresholds.
- Runtime bundle contains no totals model and no O25 calibrator.
- Runtime manifest must match an external SHA-256 pin before the pickle is decoded.
- Input integrity is server-verified HMAC over the strict CP2 pre-match source contract; missing, malformed, replayed, post-match, mismatched or unsigned input fails closed.
- Probability and coherence validation is applied before direction handling.
- Frozen performance-gate attestations plus dynamic schema, feature, artifact and input checks are required. Probability never overrides a failed gate.

## Frozen artifact hash audit

FROZEN_ARTIFACT_HASH_AUDIT: PASS.

| Frozen lock | Expected and observed SHA-256 |
|---|---|
| PHASE5_CALIBRATION_DECISION_LOCK | cb48662360cd66b4e7daaf84ff47294c04d8bb7983e3da9cceecc30207984a99 |
| FINAL_PHASE5_MANIFEST | 189057b6bc81c0e86b1eb1eb7d131e9592c320dd01f7a4ccaaf9b46ae885ab1a |
| PHASE6_DECISION_LOCK | 627f581e0e3a11c099166abdc792566a7a8fb5e8d252e748fc8e43457813829e |
| PHASE6_MANIFEST | dff0689bfa2c81bb7c7c9f0b1ce9beeb4dd3bcbd6de4779ee205d86dbe15cca4 |

The remote one-shot worker verified all members referenced by the Phase-4/5/6 manifests before fitting. No missing artifact was reconstructed. Its six-artifact output manifest is SHA-256 `1a10d825b027eee793d3a91b70ace13ca6620f1907fc950f90e3c364a9c577b2`; `artifact_count=6` and `all_artifacts_verified=true`.

## Model fit and packaged artifacts

- Dataset: frozen Phase-4 TRAIN + DEVELOPMENT only.
- TRAIN rows: 8,082.
- DEVELOPMENT rows: 2,503.
- Fit rows: 10,585.
- OOS rows available but unopened for fitting: 5,552.
- OOS rows used for fit or selection: 0.
- Fit-row index SHA-256: `f95e4881cd8dff57afdfaf576b99dd5bf434271efaa7c8baf8a0b10b3dbd0b82`.
- Runtime bundle SHA-256: `4e30976c04bd0b1cdfaff4c1def1f88753bbee6f016d617ae00b5536a530ee2b` (530,399 bytes).
- Repository runtime manifest SHA-256: `d003e9b9ae0f93667ed3d7a459f38a704eaa49dcb7f0e7d5612784bd357cbce7`.
- Source/build commit executed by the worker: `176c39e82b0d36db33241d7093ff178bde732932`.
- RC package commit containing source, bundle and manifest: `c89e701087e6046569e0f4fd5bc1b602defb4616`.

The worker's real-model serialization canary passed both 1X2 and BTTS coherence. It produced HOME=SPIELEN, BTTS_NO=BEOBACHTEN and O25/U25=HOLD on the deterministic canary row.

## Regression tests

REGRESSION_TESTS: PASS for the complete product test suite and all required Phase-7 cases.

| Scope | Result |
|---|---|
| `.venv/bin/python -m pytest -q tests` | 223 passed |
| Phase-7 API/artifact/decision/dispatcher/feature/runtime tests | 53 passed |
| Hash-pinned packaged-bundle load through configured API manifest | PASS; 298/209 features and four expected models |
| Worker real-model serialization/coherence canary | PASS |

The broader repository-root collection also discovers two historical `research/test_spec11_*.py` module-level assertions expecting app version `1.1.6-cross-market-normalized`, while the pre-existing application version is `1.1.6-full5-joint-outcome`. The same two collection errors reproduce unchanged at main `63881adf00c1d3323cb0c45e6031a358c46ee414`; they are baseline test debt, not Phase-7 regressions, and were not modified.

## Shadow comparison

Status: `NOT_TECHNICALLY_POSSIBLE_NO_COMPLETE_IDENTICAL_INPUTS`.

No complete identical normalized inputs were available to both the legacy V3.1 path and the FULL-7 RC path. No labels were used, no inference was presented as a comparison, and no rule was changed.

## Production stop

- GitHub `main` remains `63881adf00c1d3323cb0c45e6031a358c46ee414`.
- The Render production service remains on `main`; no production environment or deployment was changed.
- Only the non-production audit worker performed the one-shot build.
- No merge, production deployment or Render production mutation is authorized by this report.

READY_FOR_EXPLICIT_PRODUCTION_APPROVAL = true

Publication remains blocked until the explicit instruction `JETZT VERÖFFENTLICHEN`.

## Created or changed files

Source and tests:

- `app_phase7_rc.py`
- `full7_phase7_api.py`
- `full7_phase7_decision.py`
- `full7_phase7_features.py`
- `full7_phase7_runtime.py`
- `research/full7_phase7_finalize.py`
- `research/run_full7_phase2_phase3.py`
- `research/run_full7_phase7_only.py`
- `tests/test_full7_phase7_api.py`
- `tests/test_full7_phase7_artifacts.py`
- `tests/test_full7_phase7_decision.py`
- `tests/test_full7_phase7_dispatcher.py`
- `tests/test_full7_phase7_features.py`
- `tests/test_full7_phase7_runtime.py`

Packaged audit artifacts:

- `artifacts/full7_phase7_rc/FULL7_FINAL_RC_BUNDLE.pkl.gz`
- `artifacts/full7_phase7_rc/FULL7_FINAL_RC_MANIFEST.json`
- `artifacts/full7_phase7_rc/RENDER_ARTIFACT_MANIFEST_AUDIT.json`
- `artifacts/full7_phase7_rc/FULL7_FINAL_RELEASE_CANDIDATE_REPORT.md`
