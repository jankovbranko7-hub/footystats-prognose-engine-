# FootyStats V1 FULL-DATA — Standalone Engine

V1 is an independent engine line. It is **not** a wrapper around V0.4.3 and `app_v1.py` does not import or execute any V0.4.x engine at runtime.

## Production lock

- `main` / current Render production remain unchanged.
- V1 lives only on `feat/gate-v1-full-data` until separately tested and explicitly promoted.
- Historical V0.4.x files remain in the repository only as production/history; they are not part of the V1 runtime path.

## V1-owned probability core

V1 calculates its own expected goals from pre-match components:
- league-shrunk venue xG/xGA,
- opponent venue defence/attack,
- FootyStats pre-match xG,
- Last10 Form xG/xGA when available.

The components are combined transparently with a geometric pre-match model. V1 then uses its own Dixon-Coles implementation (`v1_score_core.py`, rho initially -0.25 as an explicit V1 configuration value).

V1 does **not** use the V0.4.3 40-feature GLM coefficients as its runtime probability model.

## Gate V1

The structural confirmation rule is owned directly by V1:

```text
required_v1 = min(original_required, structural_applicable_block_count(family))
```

For Low-Sample BTTS this means `3/3`; 2/3 remains blocked. 1X2 and O/U retain their structural maximum of 4.

## FULL-DATA sources

1. MatchDaten
2. LeagueDaten
3. FormDaten
4. TableDaten
5. PlayerDaten
6. PlayerDetailDaten

### FormDaten
- FH-BTTS
- FTS / Clean Sheets
- Last5-minus-Last10 momentum
- 5/6/10 stability

### PlayerDaten
- player depth
- top-1/top-3 scoring concentration
- top-3 contribution concentration

### LeagueDaten
- goal regime
- SOT/shot
- xG/shot
- goals/SOT
- dangerous-attack share

### TableDaten
- normalized overall table position
- PPG
- GD per match
- sample reliability

### MatchDaten
- H2H
- structured FootyStats trends
- goal timing context

### PlayerDetailDaten
- npxG/90
- xA/90
- xG/90
- key passes/90
- shots/90
- shots on target/90
- goalkeeper save %, saves/90 and shots faced/90

The FULL-DATA layer is active for analysis and contradiction diagnostics. No learned coefficient is invented for new features before result-joined OOS validation.

## Standalone test entry point

```bash
python -m uvicorn app_v1:app --host 0.0.0.0 --port $PORT
```

Health endpoint:

```text
/api/health
```

Expected health fields include `standalone: true` and `v043_runtime_dependency: false`.
