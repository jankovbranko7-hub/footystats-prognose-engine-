# FULL-7 Phase 2/3 Execution Specification

Status date: 2026-09-22

This specification records the user's binding continuation instruction on top
of `FULL7_MASTER_HANDOFF_V2_FINAL_2026-09-22.txt`,
`FULL7_WORK_PLAYBOOK_V1.2`, and the persisted CP1 artifacts.

## Immutable CP1 state

- `CP1_STRICT_DATASET` remains `BLOCKED_REPAIR_REQUIRED`; it must never be
  rewritten or represented as `PASS`.
- The collection target is 17,685 unique matches.
- The Phase-2 eligible population is exactly 16,137 match IDs.
- The original 1,418 quarantine IDs stay excluded.
- The 130 `LEAGUE_TARGET_TEAM_ROWS_MISSING` CP1 holds stay excluded.
- No replay or API request is authorized for those 130 matches.

## Phase 2 master dataset contract

- Exactly one row and one unique record per `match_id`.
- Exactly the 16,137 CP1-eligible matches, with no quarantine or hold ID.
- Join MatchDaten, LeagueDaten, FormDaten, TableDaten, and PlayerDaten by
  verified match, team, and season identifiers.
- ResultTarget is label-only and is never embedded in a feature payload.
- No odds and no target-match post-match field may enter the feature payload.
- No invented, defaulted, or silently substituted values.
- Preserve source nulls and explicit missingness.
- Preserve file hashes, request provenance, source paths, cutoff, and
  reproducible ID mappings.
- Produce `FULL7_MASTER_STRICT.parquet`, a streaming CSV representation,
  a data dictionary, per-match provenance, and final exclusions.

## CP2 gate

`CP2_MASTER_DATASET` may pass only when all of the following are evidenced by
fresh output audits:

- 16,137 rows and 16,137 unique non-null match IDs.
- Exact ID equality with collector strict IDs minus the 130 holds.
- Zero overlap with the 1,418 quarantine IDs or 130 hold IDs.
- Valid label domains and zero missing labels.
- Source file hashes and source-to-row hashes verified.
- Zero target-match post-match leakage and zero odds-like feature paths.
- Every source join passes match/team/season checks without row multiplication.
- Missingness is reported, not imputed.

CP2 failure is fail-closed and blocks Phase 3.

## Phase 3 full feature audit contract

On a passing CP2, inventory every leaf field and candidate derived feature in
the five feature sources. For each candidate record source, definition, type,
coverage, missingness, distribution, outliers, season stability, redundancy,
leakage risk, provider dependency, transformation, and research eligibility.
Include the mandatory A1/A2/B1/B2/B3/B4/C groups from the master handoff.
Do not select models or use post-match labels to manufacture features.

## Operational locks

- Keep the Render collector suspended unless the user gives a new, explicit
  authorization for a disk-bound offline execution window.
- Make no API call and start no collection.
- Do not alter `main`, the production service, production deploy, or release
  state.
- Store code and checkpoint evidence only on audit branches.
