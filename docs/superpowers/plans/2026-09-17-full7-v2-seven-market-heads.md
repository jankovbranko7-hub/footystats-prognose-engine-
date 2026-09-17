# FULL-7 V2 Seven-Market Decision Heads Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current family-winner-only decision logic with seven genuine market-level reliability/decision heads, while keeping the existing probability core and fixing the release gate so deployment cannot pass when the OOS audit forbids merge/deploy.

**Architecture:** Preserve Bronze/Silver/Gold, the 620-feature model foundation, Goal Model, CatBoost, ensemble, calibration, evidence, and existing production API shape. Compute evidence-adjusted reliability for every market first; then apply family coherence arbitration as a final stage. Keep 1X2/BTTS/TOTALS family structure only for shared parameters and mutual-exclusivity arbitration, not for pre-selecting a single market before scoring.

**Tech Stack:** Python 3.11, FastAPI, unittest, GitHub Actions, Render.

**Spec:** User-approved FULL-7 V2 design in conversation; existing contract reference: `research/FULL7_CONTRACT_STEP5_DECISION_ENGINE.md` plus `full7_contract_decision.py`, `full7_contract_evidence.py`, and `research/check_full7_release_gate.py`.

## Global Constraints

- Probability Mode remains odds-free.
- No post-match fields or targets may enter live features.
- Existing 620-feature probability foundation remains unchanged in this task.
- All seven markets must receive a real reliability score and raw decision before coherence arbitration.
- Coherence may suppress mutually exclusive alternatives only after all seven raw decisions are computed.
- Referee/Manager remain unweighted in learned probability/reliability until strict historical coverage exists.
- `main` and live Render production are not modified by this implementation branch.
- Release gate must fail if final OOS audit says `main_merge_allowed=false` or `render_deploy_allowed=false`.
- Release gate must expose the limitation when forward OOS has zero `SPIELEN` exposure.

---

### Task 1: Branch CI and RED tests for seven market heads

**Files:**
- Modify: `.github/workflows/full7-tests.yml`
- Modify: `tests/test_full7_contract_decision.py`

**Interfaces:**
- Consumes: `build_decision_engine(gold_features, validation_quality=None) -> dict`
- Produces: test contract requiring per-market `raw_decision`, `raw_reliability_score`, and final coherence metadata.

- [ ] Add the feature branch to the FULL-7 test workflow push branches.
- [ ] Replace tests that require exactly one market to be scored with tests requiring all seven markets to have non-null raw reliability and raw decision state.
- [ ] Add a test proving coherence arbitration happens after raw scoring and never erases raw scores.
- [ ] Push tests before production-code changes and verify CI fails because the new fields/behavior are absent.

### Task 2: Implement seven market-level reliability heads

**Files:**
- Modify: `full7_contract_decision.py`
- Modify if necessary: `models/full7_contract_decision_gate.json`

**Interfaces:**
- Consumes: calibrated probabilities, model support, independent cluster evidence, sample security, data-quality/OOD checks.
- Produces: seven market rows with `raw_reliability_score`, `raw_decision`, `raw_decision_reason`, and final `decision` after coherence.

- [ ] Refactor decision feature extraction so it accepts any market instead of only the family-selected market.
- [ ] Compute adjusted reliability for all seven markets using the existing family-shared empirical coefficients as a conservative V2 baseline; do not invent market-specific coefficients.
- [ ] Apply development-support and precision safeguards to each market independently before coherence.
- [ ] Run coherence arbitration only after raw decisions exist for every market.
- [ ] Preserve probability-family sums and complementary-market consistency.
- [ ] Run the decision tests and full FULL-7 suite until green.

### Task 3: Remove structural `SPIELEN` prohibition without claiming unsupported validation

**Files:**
- Modify: `full7_precision_policy.py`
- Modify: `tests/test_full7_contract_decision.py`

**Interfaces:**
- Consumes: raw state, sample status, family margin, CatBoost/Goal directional agreement.
- Produces: market-level safety downgrade rules that do not hard-cap 1X2 or TOTALS solely by family name.

- [ ] Write failing tests proving 1X2/TOTALS are not automatically capped to `BEOBACHTEN` when their own reliability gate reaches `SPIELEN`.
- [ ] Replace family hard caps with evidence/sample/model-agreement downgrade logic applicable to all families.
- [ ] Retain conservative production metadata indicating validation maturity rather than silently blocking a market in decision code.
- [ ] Run focused and full tests.

### Task 4: Fix release-gate contradiction

**Files:**
- Modify: `research/check_full7_release_gate.py`
- Create: `tests/test_full7_release_gate_v2.py`

**Interfaces:**
- Consumes: `research/oos/FULL7_FORWARD_OOS_FINAL_AUDIT.json`.
- Produces: release state `BLOCKED` whenever audit explicitly forbids merge/deploy, and reports zero-`SPIELEN` exposure as a blocker for a production-playing release.

- [ ] Write failing tests using temporary audit fixtures for `main_merge_allowed=false`, `render_deploy_allowed=false`, and zero `SPIELEN` exposure.
- [ ] Refactor gate evaluation into a fixture-testable helper.
- [ ] Make the final gate fail closed on explicit audit prohibitions.
- [ ] Run focused and full tests.

### Task 5: Update API/release semantics for V2 preview only

**Files:**
- Modify: `full7_contract_api.py`
- Modify: `tests/test_full7_contract_api.py`
- Modify: `tests/test_full7_contract_release_semantics.py`

**Interfaces:**
- Consumes: V2 decision engine output.
- Produces: API response exposing raw and final states for all seven markets while keeping production deployment unchanged.

- [ ] Add tests that all seven markets expose raw reliability plus final decision.
- [ ] Version V2 metadata without changing the live Render service or `main`.
- [ ] Ensure no API flag falsely claims release authorization while the corrected gate is blocked.
- [ ] Run full FULL-7 regression suite.

### Task 6: Audit, compare, and review

**Files:**
- Create: `research/FULL7_V2_ARCHITECTURE_AUDIT.md`
- Create: `research/FULL7_V2_ARCHITECTURE_AUDIT.json`

**Interfaces:**
- Consumes: test results, main-vs-feature diff, existing 443-backtest findings.
- Produces: auditable implementation status and explicit remaining validation requirements.

- [ ] Record exactly what changed and what remained frozen.
- [ ] Record that the 443 historical rows are retrospective architecture evidence, not untouched V2 OOS.
- [ ] Record corrected release-gate status and remaining new-forward-OOS requirement.
- [ ] Compare branch against `main` and verify no unrelated files changed.
- [ ] Open a draft PR to `main` for review; do not merge or deploy.
