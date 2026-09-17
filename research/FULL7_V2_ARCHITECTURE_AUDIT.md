# FULL-7 V2 — Architecture / Release Audit

**Status:** IMPLEMENTATION PASS — RELEASE BLOCKED

**Date:** 2026-09-17

**Branch:** `feat/full7-v2-seven-market-heads`

**Draft PR:** #35

**Base main commit:** `e51ecb51bf043a7381e7b72fd1aa5244f1a5a70e`

**Implementation snapshot before this audit document:** `bbfb9d379b75f45953e7c51df4b643216c54d233`

## Scope implemented

FULL-7 V2 removes the former family-winner-only decision shortcut. The probability foundation remains unchanged. All seven supported markets now receive a real raw reliability/decision head before family coherence arbitration:

- Home Win
- Draw
- Away Win
- BTTS Yes
- BTTS No
- Over 2.5
- Under 2.5

For each market the runtime now computes the existing family-shared empirical reliability transform against that market's own probability/evidence vector and emits:

- `raw_reliability_score`
- `raw_decision`
- `raw_decision_reason`

Only after all seven raw heads exist does coherence arbitrate mutually exclusive markets. The final family candidate is selected by raw reliability score, with calibrated probability as the deterministic tie-breaker. Non-selected alternatives retain their raw head but fail closed in the final decision as `AUSLASSEN / COHERENCE_NOT_SELECTED`.

## Structural market exclusion removed

The former hard policy that capped 1X2 and TOTALS at `BEOBACHTEN` was removed from the decision layer. 1X2, BTTS and TOTALS are now structurally decision-capable. This does **not** authorize production play: release authorization is a separate gate.

Low sample security still downgrades a prospective `SPIELEN` state to `BEOBACHTEN` for every family. The existing BTTS-specific margin and CatBoost/Goal directional-agreement safeguards remain intact.

## Probability / model layers intentionally frozen

This V2 implementation does not retrain or alter the probability foundation. The following remain unchanged from main:

- Bronze / Silver / Gold foundation
- 620-feature common model core
- CatBoost model bundle
- Dixon-Coles / goal-model bundle
- OOS ensemble policy
- calibration policy/artifacts
- evidence reference artifact
- feature registry and signal-group mapping
- referee/manager learned weight policy

The model bundle SHA-256 remains:

`62dc5ff31fdb144d40c9c873ab2cd35de5b349a6497c2e50fe2c1ea3019a6187`

Referee and Manager remain architecture/data-quality evidence blocks but are not assigned invented learned predictive weight without sufficient strict historical FULL-7 outcome coverage.

## Empirical limitation of the V2 raw heads

The current decision artifact was originally fitted on family-selected development cases. V2 deliberately reuses those family-shared coefficients as a conservative architecture baseline for all sides in a family rather than inventing market-specific coefficients.

Therefore the seven raw heads are now structurally real and fully computed, but their extension to previously non-selected sides is **not claimed as untouched OOS validated**. Signed family margin and other decision features may enter regions that were less represented in the original selected-family fit. This is the primary remaining statistical validation requirement.

`DECISION_GATE_VERSION` consequently remains `FULL7_CONTRACT_DECISION_GATE_1.0`; V2 is a runtime/decision-architecture release candidate, not a falsely relabeled retrained empirical model.

## 443 historical backtests

The 443 verified historical rows used during architecture review are retrospective evidence only:

- 300 historical archive rows
- 143 later historical/OOS rows from the earlier FULL-7 work

They were already known during V2 design. They may support diagnostics, regression comparison and architecture selection, but they **must not** be described as untouched V2 Forward-OOS.

The previously observed global-max market selector was highly imbalanced toward BTTS Yes, supporting the V2 requirement to score all seven markets before coherence rather than choose a single market by raw probability first.

## TDD / regression evidence

The implementation was performed test-first on the isolated feature branch.

Baseline after correcting one stale release-state assertion:

- 152 FULL-7 tests
- 152 passed
- 0 failed

Seven-head RED stage failed for the intended reasons: no raw heads/coherence-after-scoring contract and 1X2/TOTALS hard caps still present.

Release-gate RED stage failed because the new explicit OOS release-constraint helper did not yet exist.

API RED stage ran 157 tests and failed exactly the three new V2 release-semantics assertions before the API change.

Final regression on implementation snapshot `bbfb9d379b75f45953e7c51df4b643216c54d233`:

- 157 FULL-7 tests
- 157 passed
- 0 failed

## Corrected final release gate

`FULL7_CONTRACT_RELEASE_GATE_2.0` now honors the explicit release authorization contained in the Forward-OOS audit. The final release check is currently and intentionally:

**BLOCKED**

Blockers:

1. `FORWARD_OOS_MAIN_MERGE_FORBIDDEN`
2. `FORWARD_OOS_RENDER_DEPLOY_FORBIDDEN`
3. `FORWARD_OOS_NO_SPIELEN_EXPOSURE`

The underlying historical Forward-OOS integrity audit can remain internally `PASS` while the release gate correctly refuses promotion. The current counted forward sample has zero `SPIELEN` exposure and explicitly sets `main_merge_allowed=false` and `render_deploy_allowed=false`.

## API / release semantics

V2 exposes all seven computed candidates and their raw/final states, but it does not falsely publish them as playable:

- engine version: `FULL7_CONTRACT_V2_RC1`
- architecture: `SEVEN_MARKET_RAW_HEADS_THEN_COHERENCE`
- release status: `BLOCKED_PENDING_V2_FORWARD_OOS`
- release authorized: `false`
- decision-capable families: `1X2`, `BTTS`, `TOTALS`
- release-authorized `SPIELEN` families: none

Raw/final `SPIELEN` candidates may be inspected as `candidate_spielen`, while `playable` remains empty until a future release gate is explicitly authorized.

## Diff / scope audit

Compared with main, the implementation changes only:

- FULL-7 branch CI trigger
- implementation plan
- decision engine
- precision policy
- release-gate checker
- contract API release semantics
- associated FULL-7 tests
- this V2 audit

No model binary, model feature list, decision artifact, ensemble artifact, calibration artifact or evidence reference file was modified.

## Production state

`main` has not been merged from this branch and the Render production service has not been intentionally deployed from V2. The draft PR remains open for review.

## Remaining release requirement

Before FULL-7 V2 can be promoted to production play, freeze this V2 architecture and collect a genuinely new untouched Strict-Pre-Match Forward-OOS block produced after that freeze. The block must include actual exposure to `SPIELEN` candidates and must satisfy the release audit without overriding, deleting or ignoring the explicit authorization flags.

No existing 443-row retrospective dataset can substitute for that untouched validation step.
