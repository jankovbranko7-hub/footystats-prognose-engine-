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

## Gate V1

Low-Sample BTTS: 3/3 applicable core confirmations. 2/3 remains BEOBACHTEN.

## Verification

GitHub Actions `V1 Standalone Check` verifies syntax, eight unit tests, Gate V1 3/3 vs 2/3 behavior, coherent probabilities, PlayerDetail competition filtering and zero imports of V0.4.x modules in the V1 runtime path.
