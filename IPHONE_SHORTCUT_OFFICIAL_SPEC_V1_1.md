# iPhone Shortcut — FootyStats Official Analysis Spec v1.1

This is the implementation contract for the five-file iPhone workflow.
The user selects exactly one match. The Shortcut does not select bets or matches automatically.

## Required variables

- `FOOTYSTATS_API_KEY` — kept only inside the Shortcut; never written into an output JSON.
- `TODAY` — `yyyy-MM-dd` in Europe/Vienna.
- `MATCH_ID`
- `HOME_ID`
- `AWAY_ID`
- `SEASON_ID`
- `KICKOFF_UNIX`
- `STRICT_MAX_TIME = KICKOFF_UNIX - 1`
- `CAPTURED_AT_UNIX`

## Step 1 — List matches for manual selection

GET `https://api.football-data-api.com/todays-matches`

Query:

- `key=FOOTYSTATS_API_KEY`
- `date=TODAY`
- `timezone=Europe/Vienna`
- `page=PAGE`

Fetch all pages until `current_page == max_page`.
Display a selectable list such as `home_name – away_name · kickoff` and let the user select exactly one match.

Extract from the selected match:

- `MATCH_ID = id`
- `HOME_ID = homeID`
- `AWAY_ID = awayID`
- `SEASON_ID = competition_id`
- `KICKOFF_UNIX = date_unix`
- `STRICT_MAX_TIME = KICKOFF_UNIX - 1`

## Step 2 — MatchDaten

GET `/match?match_id=MATCH_ID`.
Save the complete raw FootyStats response as `${MATCH_ID}_MatchDaten.json` inside the SPEC wrapper. The API key is never written into the JSON. MatchDaten is a mixed endpoint: only the SPEC v1.1 pre-match whitelist is eligible for analysis; same-match post-match/result fields are never prediction inputs.

## Step 3 — LeagueDaten

GET `/league-season?season_id=SEASON_ID&max_time=STRICT_MAX_TIME` and `/league-teams?season_id=SEASON_ID&include=stats&max_time=STRICT_MAX_TIME&page=PAGE`.

Fetch every `/league-teams` page until `current_page == max_page`. Save the complete league response plus all team pages as `${SEASON_ID}_LeagueDaten.json`. Set `team_pagination_complete` to the Boolean value `true` only after successful completion of all pages.

## Step 4 — FormDaten

Run two calls:

1. GET `/lastx?team_id=HOME_ID`
2. GET `/lastx?team_id=AWAY_ID`

Store both complete raw responses in `${MATCH_ID}_FormDaten.json`. The documented Last-5/6/10 windows are retained. Because FootyStats does not document `max_time` for `/lastx`, strictness requires capture/source time before kickoff.

## Step 5 — TableDaten

GET `/league-tables?season_id=SEASON_ID&include=stats&max_time=STRICT_MAX_TIME`.
Save the complete raw response as `${MATCH_ID}_TableDaten.json`. Missing league/home/away/specific tables stay unavailable and are never fabricated.

## Step 6 — PlayerDaten

GET `/league-players?season_id=SEASON_ID&include=stats&max_time=STRICT_MAX_TIME&page=PAGE`.

FootyStats returns at most 200 players per page. Continue until `current_page == max_page` and retain the raw paginated response for completeness/audit. Set:

```json
"pagination_complete": true
```

as a real Boolean only after every page has been fetched successfully.

The backend analysis then uses only players whose `club_team_id` or `club_team_2_id` equals `HOME_ID` or `AWAY_ID`. Other league players do not become opponent/player signals; they may only be used as competition reference context. If one target team has no returned players, that player block is `NICHT VERFÜGBAR`, never zero strength.

## Step 7 — Validate and save exactly five files

The package must contain exactly:

1. `${MATCH_ID}_MatchDaten.json`
2. `${SEASON_ID}_LeagueDaten.json`
3. `${MATCH_ID}_FormDaten.json`
4. `${MATCH_ID}_TableDaten.json`
5. `${MATCH_ID}_PlayerDaten.json`

If any source fails, stop with an error. Do not invent substitute values. The Shortcut stops after the fifth local save; it does not automatically upload to Render and does not show an automatic Render result popup.

## Step 8 — Manual Render analysis

The user opens `https://footystats-prognose-engine.onrender.com`, selects the exact five JSON files for one match, and presses `SPEC v1.1 auswerten`.

The analysis endpoint is `/api/predict-bundle`.

## Interpretation contract

The backend evaluates the five FootyStats sources as SPEC-v1.1 evidence and reports the strongest supported market among Home, Draw, Away, BTTS Yes, BTTS No, Over 2.5 and Under 2.5.

- Home team: primary `home` splits.
- Away team: primary `away` splits.
- Overall: supporting context.
- `*_potential`: FootyStats historical/pre-match statistics, never relabelled as calibrated model probabilities.
- Same-match post-match values: never prediction features.
- Official FootyStats tutorial examples: evidence flags only.
- 0 competition matches = `COLD START`; 1–3 = `LOW SAMPLE`; neither is an automatic exclusion.
- Missing values = `NICHT VERFÜGBAR`, not zero strength and not a fabricated replacement.
- Related raw fields are grouped into evidence blocks so correlated columns are not counted as dozens of independent votes.
- Independent central sources (Match, League, Form, Table, Player) have priority in the strongest-market comparison.
- H2H/trends/diagnostic context is visible but does not receive an independent ranking vote.
- No V0.4.3 or V0.4.2 probability core is used.
- No fallback is used.
- No SPIELEN/BEOBACHTEN/AUSLASSEN decision engine is used.
