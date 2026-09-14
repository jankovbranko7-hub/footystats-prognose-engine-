# FULL-5 data pipeline — implementation checkpoint 0.1.0

This package is separate from production V1.1.6. No production imports, parameters,
requirements or Render resources are changed. No deploy authorization is implied.

## Implemented
- Strict UTF-8 JSON decoder: rejects duplicate keys, nonfinite numbers, oversized
  payloads and excessive nesting; preserves null and empty containers.
- Complete JSON-Pointer leaf inventory; no values or credentials in audit output.
- Pydantic snapshot envelope: UTC, identity, endpoint and raw-byte SHA-256.
- Five-source bundle audit with basic MATCH identity/kickoff verification.
- Safe default: no recommendation and no training approval.
- Chronological date blocks, match-ID deduplication enforcement, label availability.
- Synthetic unit tests; these are not historical football backtests.

Run tests from repository root:
`python -m unittest discover -s full5_pipeline/tests -v`

Use the existing Pydantic dependency in requirements.txt.
No model dependencies are installed merely to claim their integration.

## Deliberately not claimed
A pre-kickoff timestamp in uploaded metadata is not authenticated evidence.
A max_time request is not evidence that every returned field is historically safe.
Metadata validation is not a substitute for source-specific ID and field mapping.
The current MATCH shape is a conservative adapter contract; unsupported shapes
fail closed. LEAGUE/FORM/TABLE/PLAYER adapters are still unverified.
All inventoried fields are PENDING_SCHEMA_REVIEW, not USED_DIRECT.

## Required next work
1. Read real five-source payloads, including any raw payloads embedded in reports.
   Do not infer contents from filenames. Never publish user payloads or API keys.
2. Verify each endpoint's response, pagination and historical semantics against
   actual account coverage. Implement rate limits, retry budgets and capture IDs.
3. Store raw response bytes privately and immutably; write provenance separately.
4. Implement exact source adapters and field registry for all 15 requested groups.
5. Provision/authorize a private database and storage target before external writes.
6. Join genuine results. Train preprocessing/selection on training blocks only.
7. Fit Poisson/DC and CatBoost baselines; retain an ensemble only after OOS benefit.
   Calibrate joint outputs consistently; complementary markets must sum to one.
8. SHAP explanations, MLflow lineage and fail-closed FastAPI endpoint.
9. iPhone selection stays manual. Scheduled collection is separate from selection.
10. Security, integration, historical and live smoke tests before explicit release.

No odds inputs. No fabricated replacement values. Missingness may become a
quality feature only after provenance and coverage checks. Player count is not
assumed to measure true squad depth. No fixed hit-rate or profit promises.

## Current execution limitation
This chat has GitHub read/write access but no local Python/filesystem execution
tool. Tests must run in CI or an authorized Python environment. The attached
Mantova/Sampdoria report has NOT been read by this package's author in this turn.
Model training and real-data validation are not complete.
