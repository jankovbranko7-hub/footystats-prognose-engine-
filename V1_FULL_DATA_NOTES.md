# Gate V1 FULL-DATA Challenger

This branch is an isolated challenger built on the frozen V0.4.3 FULL-5 production engine.

## Production lock

- `main` / Render production are not changed by this branch.
- V0.4.3 FULL-5 lambdas, 40-feature coefficients, Alpha and Dixon-Coles probabilities remain unchanged.
- No new FULL-DATA feature is allowed to change probability or decision weighting before result-joined OOS validation.

## Gate V1

Only the confirmation requirement is made structurally reachable by market family:

```text
required_v1 = min(original_required, structural_applicable_block_count(family))
```

Therefore Low-Sample BTTS changes from impossible `4 required / 3 applicable` to `3/3 required`. 1X2 and O/U remain unchanged. Missing-but-applicable data does not lower the requirement.

## FULL-DATA research signals

- FormDaten: FH-BTTS, FTS/CS, Last5-vs-Last10 momentum, 5/6/10 stability.
- PlayerDaten: depth and scoring/contribution concentration.
- LeagueDaten: goal regime and chance quality (SOT/shot, xG/shot, goals/SOT, dangerous-attack share).
- TableDaten: overall normalized position, PPG, goal difference per match and sample reliability.
- MatchDaten: H2H, structured FootyStats trends and timing context.
- PlayerDetailDaten (new): current-competition npxG/90, xA/90, xG/90, key passes/90, shots/90, SOT/90, progressive passes and goalkeeper save/shot-facing metrics.

## Sixth FootyStats file

The V1 shortcut creates:

```text
[MatchID]_PlayerDetailDaten.json
```

It uses the existing League-Players response to identify only Home/Away players (`club_team_id` and `club_team_2_id`) and calls the FootyStats individual `player-stats` endpoint for those player IDs. The API key remains an iPhone Shortcut import question and is not stored in the repository.

## Test entry point

```bash
python -m uvicorn app_v1:app --host 0.0.0.0 --port $PORT
```

The test service health endpoint is `/api/health`; the research feature inventory is `/api/v1/feature-manifest`.
