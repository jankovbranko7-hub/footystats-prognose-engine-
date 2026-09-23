# FULL-7 V3.1 RAW Input Recovery Audit

Status: **COMPLETE**

- Frozen FULL-7 rows scanned: **16,137**
- Locked OOS rows checked: **5,552**
- Unique strict pre-match RAW hashes scanned: **11,893**
- Strict cutoff: `requested_max_time == kickoff_unix - 1`
- Source manifest SHA-256: `86c05accd2f1cb56e5afed13057b5dbb2e857e847b5dd75d927863e7879999d6`

## Result

All seven exact V3.1 provider inputs have **0/16,137 numeric coverage** and **0/5,552 OOS coverage** in the frozen strict-pre-match RAW snapshots:

- `team_a_xg_prematch`
- `team_b_xg_prematch`
- `o25_potential`
- `btts_potential`
- `avg_potential`
- `pre_match_home_ppg`
- `pre_match_away_ppg`

Collector projection mismatches: **0**.

Therefore:

- `V3_1_RAW_RECOVERY = NOT_POSSIBLE`
- `V3_1_SAME_COHORT_OOS_RECOVERY = NOT_POSSIBLE`

No collection, API call, training, calibration change, RC change, main change, or production change was performed.
