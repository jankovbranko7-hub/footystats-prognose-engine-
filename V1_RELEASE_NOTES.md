# FootyStats V1 — V0.4.3 FULL-5 Core + Gate V1

## Production architecture

V1 keeps the proven V0.4.3 probability path frozen:

- 40 FULL-5 features
- production alpha = 3.0
- V0.4.2 hybrid lambda as fallback/base
- Dixon-Coles rho = -0.25
- no Elite-Lambda correction
- no invented replacement values
- same five iPhone export files: MatchDaten, LeagueDaten, FormDaten, TableDaten, PlayerDaten

V1 is an overlay above that probability core. It does not replace or reweight the V0.4.3 probabilities.

## Gate V1

The confirmation requirement is now:

`required = min(original_required, structural_applicable_block_count_for_family)`

Structural maxima:

- 1X2: 4
- BTTS: 3
- O/U 2.5: 4

Therefore only low-sample BTTS changes from an impossible 4-of-3 requirement to 3-of-3. Missing data does not lower the requirement. Low-sample BTTS 2-of-3 remains BEOBACHTEN.

## Six-stage challenger protocol

1. **V0.4.3 + Gate V1** — active production decision rule.
2. **First-Half BTTS Venue** — calculated from the existing LeagueDaten and exposed as a specialist diagnostic. No invented probability weight.
3. **CS/FTS Survival** — calculated from the existing LeagueDaten and exposed as a specialist diagnostic. No invented probability weight.
4. **FH-BTTS + CS/FTS** — joint direction is shown for BTTS robustness; it does not silently alter lambda/probability.
5. **Player Depth / Concentration** — calculated from the existing PlayerDaten and used as reliability context, not an unvalidated lambda adjustment.
6. **Combinations** — no hard probability reweighting is enabled until a combination proves incremental OOS value. Failed or unproven challengers are not smuggled into the probability core.

This follows the agreed rule: test one family at a time and only promote successful challengers.

## Visible Render behavior

The V0.4.3 pairing card remains visible.

For BEOBACHTEN, V1 now returns a football-readable reason such as:

- insufficient family strength,
- too few structurally required confirmations,
- a concrete contradictory evidence source,
- failed removal-stress robustness,
- low data quality,
- probability coherence failure.

Technical evidence block names remain available in the JSON, but the visible explanation uses human-readable labels and a sentence explaining why the market is not released.

## Shortcut

No new iPhone shortcut is required for V1. The existing five-file exporter remains the production input. PlayerDetailDaten is not required in V1.0.
