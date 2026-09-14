"""Synthetic envelopes matching observed shapes; no user payloads in the repository."""
import copy
import json
import unittest
from full5_pipeline.audit import DataError
from full5_pipeline.shortcut import adapt

K = 2_000_000_000
C = K - 3600


def page(rows, current=1, maximum=1, total=None):
    return {"success": True, "data": rows, "pager": {
        "current_page": current, "max_page": maximum,
        "total_results": len(rows) if total is None else total}}


def fixture():
    endpoints = {"MATCH": "/match", "LEAGUE": "/league-season", "FORM": "/lastx",
                 "TABLE": "/league-tables", "PLAYER": "/league-players"}
    docs = {}
    for source, endpoint in endpoints.items():
        meta = {"endpoint": endpoint, "captured_at_unix": str(C), "kickoff_unix": str(K)}
        if source in {"LEAGUE", "TABLE", "PLAYER"}:
            meta.update(season_id="77", max_time=str(K-1))
        docs[source] = {"_footystats_meta": meta}
    docs["MATCH"]["payload"] = page({"id": 1, "homeID": 10, "awayID": 20,
        "competition_id": 77, "date_unix": K, "status": "incomplete",
        "team_a_xg_prematch": 1.5, "team_a_xg": 0, "homeGoalCount": 0,
        "odds_ft_1": 1.5, "gpt_en": "Example", "h2h": {"n": 2}})
    docs["LEAGUE"]["payload"] = {"league": page({"id": 77}),
        "team_pages": page([{"id": 10, "stats": {"xg_for_avg_home": 1.5}},
                            {"id": 20, "stats": {"xg_for_avg_away": 1.2}}])}
    docs["FORM"]["payload"] = {side: page([
        {"id": team, "last_x_match_num": n, "last_x_home_away_or_overall": 0,
         "last_updated_match_timestamp": C-86400, "stats": {"x": 0}}
        for n in (5, 6, 10)]) for side, team in (("home", 10), ("away", 20))}
    docs["TABLE"]["payload"] = page({name: [{"id": 10}, {"id": 20}]
        for name in ("all_matches_table_overall", "all_matches_table_home",
                     "all_matches_table_away")})
    docs["PLAYER"]["payload"] = {"pages": [
        page([{"id": 100, "competition_id": 77, "club_team_id": 10,
               "last_match_timestamp": C-86400}], 1, 2, 2),
        page([{"id": 200, "competition_id": 77, "club_team_id": 20,
               "last_match_timestamp": 0}], 2, 2, 2)]}
    return docs


def run(docs):
    return adapt({s: json.dumps(d).encode() for s, d in docs.items()}, now_unix=C+60)


class ShortcutTests(unittest.TestCase):
    def test_actual_envelope_shapes(self):
        out = run(fixture())
        self.assertEqual(out["counts"], {"league_teams": 2, "league_players": 2,
                                         "home_players": 1, "away_players": 1})
        self.assertFalse(out["training_ready"])
        self.assertFalse(out["strict_prematch_certified"])

    def test_team_pages_can_be_a_list(self):
        docs = fixture()
        docs["LEAGUE"]["payload"]["team_pages"] = [docs["LEAGUE"]["payload"]["team_pages"]]
        self.assertEqual(run(docs)["counts"]["league_teams"], 2)

    def test_exclusions_are_not_features(self):
        out = run(fixture())
        statuses = {r["pointer"]: r["status"] for r in out["field_audit"]["MATCH"]}
        for key, status in (("odds_ft_1", "ODDS_BLOCKED"), ("gpt_en", "PROVIDER_TEXT_BLOCKED"),
                            ("homeGoalCount", "MATCH_FIELD_NOT_APPROVED"),
                            ("team_a_xg", "MATCH_FIELD_NOT_APPROVED"),
                            ("team_a_xg_prematch", "CANDIDATE_REQUIRES_VALIDATION")):
            self.assertEqual(statuses["/payload/data/"+key], status)

    def test_missing_page_despite_complete_flag(self):
        docs = fixture()
        docs["PLAYER"]["_footystats_meta"]["pagination_complete"] = True
        docs["PLAYER"]["payload"]["pages"].pop()
        with self.assertRaisesRegex(DataError, "INCOMPLETE_PAGINATION"):
            run(docs)

    def test_duplicate_player(self):
        docs = fixture()
        docs["PLAYER"]["payload"]["pages"][1]["data"][0]["id"] = 100
        with self.assertRaisesRegex(DataError, "DUPLICATE_ROW_ID"):
            run(docs)

    def test_duplicate_page(self):
        docs = fixture()
        docs["PLAYER"]["payload"]["pages"][1]["pager"]["current_page"] = 1
        with self.assertRaisesRegex(DataError, "DUPLICATE_PAGE"):
            run(docs)

    def test_wrong_team_form(self):
        docs = fixture()
        docs["FORM"]["payload"]["home"]["data"][0]["id"] = 20
        with self.assertRaisesRegex(DataError, "FORM_TEAM_MISMATCH"):
            run(docs)

    def test_future_form(self):
        docs = fixture()
        docs["FORM"]["payload"]["away"]["data"][0]["last_updated_match_timestamp"] = K
        with self.assertRaisesRegex(DataError, "FORM_CONTAINS_FUTURE_MATCH"):
            run(docs)

    def test_wrong_season_player(self):
        docs = fixture()
        docs["PLAYER"]["payload"]["pages"][0]["data"][0]["competition_id"] = 88
        with self.assertRaisesRegex(DataError, "PLAYER_SEASON_MISMATCH"):
            run(docs)

    def test_missing_target_in_table(self):
        docs = fixture()
        docs["TABLE"]["payload"]["data"]["all_matches_table_away"].pop()
        with self.assertRaisesRegex(DataError, "TARGET_TEAM_MISSING"):
            run(docs)

    def test_endpoint_and_capture(self):
        for key, value, code in (("endpoint", "/match", "SOURCE_ENDPOINT_MISMATCH"),
                                 ("captured_at_unix", str(K), "FUTURE_CAPTURE"),
                                 ("kickoff_unix", str(K+1), "CONFLICTING_KICKOFF"),
                                 ("season_id", "88", "CONFLICTING_SEASON_ID")):
            docs = fixture()
            docs["PLAYER"]["_footystats_meta"][key] = value
            with self.subTest(key=key), self.assertRaisesRegex(DataError, code):
                run(docs)

    def test_quoted_booleans_are_not_ids(self):
        docs = fixture()
        docs["MATCH"]["payload"]["data"]["homeID"] = True
        with self.assertRaises(DataError):
            run(docs)

    def test_invalid_provider_response(self):
        docs = fixture()
        docs["LEAGUE"]["payload"]["league"]["success"] = False
        with self.assertRaisesRegex(DataError, "PROVIDER_RESPONSE_INVALID"):
            run(docs)

    def test_lastx_cutoff_not_assumed_supported(self):
        docs = fixture()
        docs["FORM"]["_footystats_meta"]["max_time"] = str(K-1)
        with self.assertRaisesRegex(DataError, "LASTX_CUTOFF_UNSUPPORTED"):
            run(docs)
