# V1 FULL-DATA — Standalone Architecture

V1 is an independent engine line. It must not execute production V0.4.x modules at runtime.

Runtime ownership:
- `v1_base.py`: V1-owned copy of the stable file/API/archive infrastructure.
- `v1_decision_core.py`: V1-owned decision/evidence core.
- `v1_score_core.py`: V1-owned Dixon-Coles score-distribution core.
- `v1_probability_core.py`: V1-owned FULL-data probability core seed.
- `v1_full_data_engine.py`: V1 FULL-DATA extraction + Gate V1 + orchestration.
- `app_v1.py`: starts only V1-owned modules.

The proven numerical behavior from the earlier production line may be copied as an initialization/reference, but V1 owns the code and can evolve independently. `main`/production remains untouched.

FULL-DATA sources:
1. MatchDaten
2. LeagueDaten
3. FormDaten
4. TableDaten
5. PlayerDaten
6. PlayerDetailDaten

Gate V1 remains structural: Low-Sample BTTS requires 3/3 structurally applicable confirmation blocks; 2/3 does not pass. New FULL-DATA signals are not assigned invented probability weights without result-joined OOS validation.