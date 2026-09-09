# iPhone Shortcut — FootyStats Official Analysis Spec v1.1

This is the implementation contract for the existing five-file iPhone workflow.
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

GET `/match`

Query:

- `key=FOOTYSTATS_API_KEY`
- `match_id=MATCH_ID`

Save as `${MATCH_ID}_MatchDaten.json` with the wrapper:

```json
{
  "_footystats_meta": {
    "endpoint": "/match",
    "match_id": "MATCH_ID",
    "captured_at_unix": "CAPTURED_AT_UNIX",
    "kickoff_unix": "KICKOFF_UNIX",
    "max_time": null,
    "temporal_mode": "PREMATCH_FIELD_WHITELIST"
  },
  "payload": "RAW_RESPONSE"
}
```

Do not write the API key into the JSON.

## Step 3 — LeagueDaten

GET `/league-season`

Query:

- `key=FOOTYSTATS_API_KEY`
- `season_id=SEASON_ID`
- `max_time=STRICT_MAX_TIME`

Save as `${SEASON_ID}_LeagueDaten.json`.

Metadata must contain `endpoint=/league-season`, `kickoff_unix`, `captured_at_unix`, and `max_time=STRICT_MAX_TIME`.

## Step 4 — FormDaten

Run two calls:

1. GET `/lastx?team_id=HOME_ID`
2. GET `/lastx?team_id=AWAY_ID`

Store both raw responses in one `${MATCH_ID}_FormDaten.json`:

```json
{
  "_footystats_meta": {
    "endpoint": "/lastx",
    "team_ids": ["HOME_ID", "AWAY_ID"],
    "captured_at_unix": "CAPTURED_AT_UNIX",
    "kickoff_unix": "KICKOFF_UNIX",
    "max_time": null,
    "temporal_mode": "LIVE_CAPTURE_ONLY_NO_MAX_TIME"
  },
  "payload": {
    "home": "HOME_LASTX_RAW_RESPONSE",
    "away": "AWAY_LASTX_RAW_RESPONSE"
  }
}
```

Because FootyStats does not document `max_time` for `/lastx`, historical strictness is proven only by a capture/source timestamp before kickoff.

## Step 5 — TableDaten

GET `/league-tables`

Query:

- `key=FOOTYSTATS_API_KEY`
- `season_id=SEASON_ID`
- `include=stats`
- `max_time=STRICT_MAX_TIME`

Save as `${MATCH_ID}_TableDaten.json` with strict metadata.

## Step 6 — PlayerDaten

GET `/league-players`

Query:

- `key=FOOTYSTATS_API_KEY`
- `season_id=SEASON_ID`
- `include=stats`
- `max_time=STRICT_MAX_TIME`
- `page=PAGE`

FootyStats returns at most 200 players per page. Continue until `current_page == max_page`.
Concatenate player data in page order, retain pager audit information, then retain players whose `club_team_id` or `club_team_2_id` equals HOME_ID or AWAY_ID.

Save as `${MATCH_ID}_PlayerDaten.json` and set:

```json
"pagination_complete": true
```

only after every page was successfully fetched.

## Step 7 — Validate exactly five files

The package must contain exactly:

1. `${MATCH_ID}_MatchDaten.json`
2. `${SEASON_ID}_LeagueDaten.json`
3. `${MATCH_ID}_FormDaten.json`
4. `${MATCH_ID}_TableDaten.json`
5. `${MATCH_ID}_PlayerDaten.json`

If any source fails, stop with an error. Do not invent substitute values.

## Step 8 — Send to Render

POST multipart/form-data to:

`https://footystats-prognose-engine.onrender.com/api/predict-bundle`

Use form field `files` for all five JSON files.

## Interpretation contract

The backend, not the Shortcut, evaluates the match. The Shortcut only collects and preserves the five FootyStats sources.

- Home team: primary `home` splits.
- Away team: primary `away` splits.
- Overall: supporting context.
- `*_potential`: FootyStats historical/pre-match statistics, never relabelled as calibrated model probabilities.
- Same-match post-match values: never prediction features.
- Official FootyStats tutorial examples: evidence flags only.
- V0.4.3 FULL-5 Probability Core remains unchanged.
