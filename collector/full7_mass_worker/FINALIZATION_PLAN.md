# FULL-7 Mass Collection — Finalization Plan / Execution Lock

Stand: 2026-09-21

## Locked current state

- Target matches: **17,685**
- `processed = 17685`
- `done_total = 17685`
- `strict_pass = 16267`
- `quarantined = 1418`
- `failed_requests = 309`
- `retry_count = 1862`
- `api_requests = 94188`
- `cache_hits = 57384`
- `unique_raw_responses = 94188`
- Render worker: `full7-mass-collector-17685`
- Render service ID: `srv-damiu0p42hec739a0rig`
- Persistent disk: `full7-mass-data`, disk ID `dsk-damiu0p42hec739a0scg`, 20 GB, mount `/var/data`
- Worker status: **suspended by user**
- Production `main`: `63881adf00c1d3323cb0c45e6031a358c46ee414`
- Collector branch before this finalization preparation: `e9a869c1c34d21799b7af34faf4fb39b795af9a7`

Production is not to be changed during this work.

## Quarantine lock

Final quarantine total: **1,418**.

Known HTTP-417 block: **309 matches**:
- season 17181: 24
- season 17184: 59
- season 17206: 32
- season 17290: 50
- season 17350: 144

The 309 HTTP-417 cases correspond to the final `failed_requests` count and were associated with the temporary FootyStats league-selection change. They are repair candidates, but they must be preflighted and retried only after a raw-data backup / inventory is secured.

Remaining non-417 quarantine: **1,109 matches**. Logs indicate these are predominantly `league_source_count_mismatch`; they stay fail-closed until separately audited. Do not auto-release them.

## Phase 0 — backup / inventory (must happen before destructive action)

1. Keep worker suspended and disk attached.
2. Run `backup_inventory.py` against `/var/data/full7/output`.
3. Preserve its `file_manifest_sha256.jsonl`, `file_manifest_summary.json`, `tree_sha256` and manifest SHA-256.
4. Make a complete external byte-for-byte copy of `/var/data/full7/output`.
5. Re-run/compare the manifest against the external copy.
6. Do not delete Render service or disk until external-copy verification passes.

Current ChatGPT Render connector cannot directly download the persistent-disk bytes, so the full external byte-for-byte copy is still an explicit blocker. Metadata/checkpoint documents are already backed up separately; they are not a substitute for the raw-data backup.

## Phase 1 — Collection Final Audit

Prepared script: `final_audit.py`.

Run once without raw verification for a fast structural pass, then with `--verify-raw` for the full content-addressed cache audit.

Required checks:
- exact 17,685 target IDs vs `done_ids`
- no duplicate match IDs
- exactly one complete match bundle per done ID
- `requested_max_time == kickoff_unix - 1`
- all form source timestamps `< kickoff`
- target match absent from form sources
- league source max timestamp `< kickoff`
- target match absent from league source IDs
- player pagination complete
- payload files match metadata SHA-256
- request provenance uses the target `max_time`
- no forbidden post-match keys in feature files
- no odds-like keys in feature files
- raw cache digest files exist
- full raw gzip SHA-256 verification
- quarantine grouped by season and reason

Any audit failure remains fail-closed.

## Phase 1A — Targeted HTTP-417 repair

Prepared script: `retry_http417.py`.

Safety rules:
- only matches whose quarantine reason contains `417 Client Error`
- expected locked population: 309
- never touches current STRICT_PASS matches
- copies original quarantine reason to `quarantine_history/http417_before_retry/...`
- first run `--preflight`
- bulk execute only if every affected season is accessible and the sample target is found
- `done_ids` population remains 17,685
- strict/quarantine counts are reconciled from metadata after retry
- do not retry the 1,109 non-417 cases in this phase

After repair, rerun the full Collection Final Audit.

## Phase 1B — League source count mismatch research

For the non-417 quarantine population:
- group by season and exact mismatch delta
- distinguish systematic provider semantics from actual history leakage/incompleteness
- compare `league_source_count`, `matchesCompleted`, target kickoff and source IDs
- prove the reason before any validator change
- do not relax the strict validator merely because a mismatch is common
- if a safe correction is proven, rerun only the affected matches and re-audit

## Phase 2 — Master Dataset

Only after Phase 1 is clean enough to define the eligible population.

Rules:
- one row per unique `match_id`
- labels from `ResultTarget` only
- no ResultTarget fields in features
- no odds
- no post-match fields
- no silent replacement values
- quarantine remains excluded unless explicitly repaired and revalidated
- preserve provenance / source coverage indicators

## Phase 3 — Complete Feature Audit

Inventory all usable pre-match data from:
- Match
- League
- Form
- Table
- Player

For every candidate feature report:
- coverage / missingness
- league/season coverage
- temporal availability
- stability over time
- redundancy / collinearity
- leakage risk
- provider dependency
- incremental predictive value

Priority groups include venue xG/xGA, total xG anchor, goals/conceded, sample sizes, league averages/home advantage, home/away form, BTTS/OU overall+venue, CS/FTS, first/second half, PPG/relative table strength/rank percentile, player depth/contribution/concentration, shots/on-target if historically safe, FH-BTTS venue, H2H only if incremental.

Do not blindly reuse the old ~40 features.

## Phase 4 — New Modeling

Chronological only:
`Train -> Development -> Walk-forward OOS`

Requirements:
- compare multiple model families/feature sets
- tune only on train/development
- OOS remains untouched during selection
- current V3.1 is a benchmark, not the new truth
- report 1X2, BTTS and O/U separately and jointly where appropriate

## Phase 5 — Final Probability Calibration

Only after model choice.

Evaluate:
- binary: Platt, isotonic, beta where appropriate
- 1X2: suitable multiclass calibration
- Brier
- LogLoss
- ECE
- MCE
- reliability bins
- calibration slope/intercept

Do not choose decision thresholds before calibration is locked.

## Phase 6 — New Decision Engine

Build `SPIELEN / BEOBACHTEN / AUSLASSEN` from the newly validated/calibrated data.

Do not automatically inherit:
- V3.1 gates
- old manual thresholds
- old 40-feature contract

Keep integrity gates separate from empirical performance gates.

## Phase 7 — Untouched Forward OOS

Use genuinely new matches not used for:
- feature selection
- model training
- hyperparameter tuning
- calibration
- gate construction

No post-result optimization.

## Phase 8 — Final Audit / Release Preparation

Must include:
- regression tests
- dependency audit
- strict data-quality audit
- leakage audit
- probability calibration audit
- decision-gate audit
- architecture/contract audit
- production compatibility smoke test

Production release only on explicit user instruction.

## New-chat start command

Upload the master handoff/checkpoint file and say:

> Setze exakt bei diesem FULL-7-Finalisierungs-Checkpoint fort. Nichts abgeschlossenes wiederholen. Prüfe zuerst Render-Service und Collector-Branch. Produktion main nicht verändern. Beginne mit Phase 0 Backup/Inventory und Phase 1 Collection Final Audit. Quarantäne bleibt fail-closed. Die 309 HTTP-417-Fälle nur nach erfolgreichem Preflight gezielt reparieren; die übrigen Quarantänefälle separat untersuchen. Arbeite anschließend strikt in der festgelegten Reihenfolge bis zum Release-Kandidaten, aber veröffentliche nichts ohne meine ausdrückliche Freigabe.
