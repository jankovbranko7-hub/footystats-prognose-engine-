# FULL-7 Phase 2/3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and audit the 16,137-row strict master dataset, then run the complete Phase-3 feature audit without API access or production changes.

**Architecture:** A standard-library streaming reader validates every source bundle and emits a canonical one-row-per-match JSON record plus CSV. A bounded-memory PyArrow writer creates Parquet when PyArrow is available and otherwise fails closed. Independent CP2 and CP3 auditors consume only emitted artifacts and write immutable checkpoint reports.

**Tech Stack:** Python 3.11+, standard library, PyArrow for Parquet, pytest.

**Spec:** `docs/full7/FULL7_PHASE2_PHASE3_EXECUTION_SPEC_2026-09-22.md`

## Global Constraints

- CP1 remains `BLOCKED_REPAIR_REQUIRED` and must not be rewritten.
- Use exactly 16,137 CP1-eligible matches; exclude 1,418 quarantine and 130 holds.
- No API calls, collection, replay, odds, target post-match features, imputation, or silent defaults.
- Keep Collector suspended and leave `main` and production unchanged.
- ResultTarget is label-only.
- Preserve nulls, missingness, hashes, lineage, and deterministic IDs.

## Review Focus

- A strict-labelled match that appears in the 130-ID hold list must fail the population gate and never reach an output row.
- A source payload with an odds-like key or target post-match key must fail closed before output publication.
- A LeagueDaten team row mismatch or missing home/away identity must fail the join instead of producing a partial row.
- A missing PyArrow dependency must prevent a false CP2 pass and leave no claimed Parquet artifact.
- A duplicate match ID or partial rerun must not create duplicate rows or a mixed checkpoint.

---

### Task 1: Strict population and bundle validator

**Files:**
- Create: `research/full7_master_dataset.py`
- Test: `research/test_full7_master_dataset.py`

**Interfaces:**
- Consumes: collection root, 130-ID hold file, and CP1 checkpoint.
- Produces: `derive_population(root, hold_ids) -> PopulationAudit` and `load_validated_bundle(root, match_id, season_id) -> BundleRecord`.

- [ ] Write fixture-based tests that prove exact exclusion arithmetic, duplicate rejection, hash validation, match/team/season join validation, label separation, explicit null-path capture, and forbidden-key rejection.
- [ ] Run `pytest -q research/test_full7_master_dataset.py` and verify failures are caused by missing implementation.
- [ ] Implement deterministic population derivation and fail-closed bundle validation without API imports or fallback values.
- [ ] Run `pytest -q research/test_full7_master_dataset.py` and verify all tests pass.
- [ ] Commit the task.

### Task 2: Streaming master outputs and CP2 audit

**Files:**
- Modify: `research/full7_master_dataset.py`
- Modify: `research/test_full7_master_dataset.py`

**Interfaces:**
- Consumes: validated `BundleRecord` values.
- Produces: canonical JSONL, CSV.GZ, Parquet, data dictionary, provenance JSONL, exclusions CSV, `FULL7_MASTER_BUILD_MANIFEST.json`, and `CP2_MASTER_DATASET.json/.txt`.

- [ ] Add failing tests for one-row grain, deterministic row hashes, atomic staging, exact labels, output checksums, Parquet dependency failure, and CP2 leakage/join/missingness gates.
- [ ] Run the focused tests and verify the expected failures.
- [ ] Implement bounded-memory writers, atomic publication, and an independent reread audit of all emitted rows and IDs.
- [ ] Run focused tests and the repository test suite; verify green output.
- [ ] Commit the task.

### Task 3: Full feature inventory and CP3 audit

**Files:**
- Create: `research/full7_feature_audit.py`
- Test: `research/test_full7_feature_audit.py`

**Interfaces:**
- Consumes: passing CP2 manifest/checkpoint and canonical JSONL master rows.
- Produces: full leaf-path catalog, candidate derived-feature audit, mandatory-group coverage, and `CP3_FEATURE_AUDIT.json/.txt`.

- [ ] Write failing tests for leaf-path inventory, missingness/coverage, numeric distributions, outlier summaries, season stability, correlation redundancy, leakage/provider classifications, and every mandatory A1/A2/B1/B2/B3/B4/C group.
- [ ] Run `pytest -q research/test_full7_feature_audit.py` and verify failures are due to absent behavior.
- [ ] Implement streaming field profiling and explicitly documented candidate transformations; never impute or train a model.
- [ ] Run focused tests and the repository suite; verify green output.
- [ ] Commit the task.

### Task 4: Offline execution and immutable checkpoint publication

**Files:**
- Create: `research/run_full7_phase2_phase3.py`
- Create: `research/test_run_full7_phase2_phase3.py`
- Create after real execution: `artifacts/full7_cp2_2026-09-22/*`
- Create after real execution: `artifacts/full7_cp3_2026-09-22/*`

**Interfaces:**
- Consumes: actual persistent-disk collection root and Tasks 1-3.
- Produces: real CP2/CP3 outputs and a resume-safe execution ledger.

- [ ] Write failing orchestration tests proving CP3 never starts on non-PASS CP2 and that no network/API module is invoked.
- [ ] Run tests and verify expected failures.
- [ ] Implement the offline runner with lockfile, staging directory, checksums, and phase gate.
- [ ] Run all tests.
- [ ] At the genuine permission point, obtain explicit authorization for the only feasible persistent-disk access method if the collector must be temporarily resumed in offline mode.
- [ ] Execute against `/var/data/full7/output`, inspect all audit outputs, and copy only checkpoint reports/manifests to the audit branch.
- [ ] Freshly verify Collector suspended, no API/collection/raw/state mutation, `main` unchanged, and production unchanged.
- [ ] Commit and push the checkpoint branch.
