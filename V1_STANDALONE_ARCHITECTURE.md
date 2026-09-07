# FootyStats V1 FULL-DATA — Standalone Architecture

V1 is an independent engine line. It is not a wrapper over V0.4.3 and it does not import or execute any V0.4.x engine at runtime.

## Runtime

- `app_v1.py` — independent FastAPI/UI entry point
- `v1_standalone_engine.py` — V1 probability, FULL-DATA extraction, evidence and Gate V1 logic
- `v1_score_core.py` — V1-owned Dixon-Coles score distribution
- `v1_runtime_contract.py` — import/source contract

The historical V0.4.x code remains untouched on `main` and is not part of the V1 runtime dependency graph.

## Six FootyStats sources

1. MatchDaten
2. LeagueDaten
3. FormDaten
4. TableDaten
5. PlayerDaten
6. PlayerDetailDaten

## V1 probability model

V1 computes expected goals independently from league-shrunk venue xG/xGA, opponent attack/defence, FootyStats pre-match xG and Last10 form xG/xGA when available. Components are combined through a transparent geometric pre-match model. No V0.4.3 40-feature GLM coefficients are loaded at runtime.

Dixon-Coles is owned by V1 in `v1_score_core.py`; rho=-0.25 is an explicit V1 configuration value, not a runtime dependency.

## Gate V1

Low-Sample BTTS uses the structural family requirement: 3/3 applicable core confirmations. 2/3 remains BEOBACHTEN. 1X2 and O/U retain a structural maximum of 4 confirmations.

## FULL-DATA enrichment

- Form: FH-BTTS, FTS/CS, 5-vs-10 momentum, 5/6/10 stability
- Player: depth and scoring/contribution concentration
- League: goal regime and chance quality
- Table: normalized position and sample reliability
- Match: H2H, trends and timing
- PlayerDetail: npxG/xA/xG, key passes, shots/SOT and goalkeeper metrics

New FULL-DATA signals are active in the analysis/contradiction layer. Learned probability coefficients are not invented before result-joined OOS validation.

## CI lock

`.github/workflows/v1-standalone-check.yml` verifies syntax, V1 unit tests, Gate V1 3/3 vs 2/3 behavior and absence of `app_v040`, `v041_engine`, `v042_engine`, or `v043_engine` imports in the V1 runtime path.
