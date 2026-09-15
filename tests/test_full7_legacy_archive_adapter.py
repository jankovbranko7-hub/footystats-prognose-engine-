import unittest

from full7_legacy_archive_adapter import adapt_legacy_archive_report


def api(data):
    return {"success":True,"data":data}


def report(created="2033-05-18T03:16:30Z"):
    # kickoff 2,000,000,000 == later than archive timestamp above.
    home=101; away=202
    return {
        "created_at":created,
        "record_id":"404-test",
        "match":{"match_id":404},
        "source_coverage":{"missing":[]},
        "sources":{
            "match":{"filename":"404_MatchDaten.json","sha256":"m","content":api({"id":404,"homeID":home,"awayID":away,"competition_id":303,"date_unix":2_000_000_000,"refereeID":-1})},
            "league":{"filename":"303_LeagueDaten.json","sha256":"l","content":{"pages ":[api([{"id":home},{"id":away}])] }},
            "form":{"filename":"404_FormDaten.json","sha256":"f","content":{"teams":[api([{"id":away,"last_x_match_num":5}]),api([{"id":home,"last_x_match_num":5}])] }},
            "table":{"filename":"404_TableDaten.json","sha256":"t","content":api({"all_matches_table_overall":[{"id":home},{"id":away}]})},
            "player":{"filename":"404_PlayerDaten.json","sha256":"p","content":{"pages":[api([{"id":1,"club_team_id":home},{"id":2,"club_team_id":away}])] }},
        },
    }


class LegacyArchiveAdapterTests(unittest.TestCase):
    def test_valid_archive_strict(self):
        out=adapt_legacy_archive_report(report())
        self.assertEqual(out["identity"]["match_id"],404)
        self.assertEqual(out["quality"]["provenance_mode"],"LEGACY_ARCHIVE_STRICT")
        self.assertFalse(out["quality"]["source_level_max_time_available"])
        self.assertEqual(out["quality"]["referee_status"],"NOT_CAPTURED_HISTORICALLY")
        self.assertEqual(out["namespaces"]["referee"],{})
        self.assertEqual(out["namespaces"]["manager"],{})

    def test_form_is_mapped_by_team_id_not_position(self):
        out=adapt_legacy_archive_report(report())
        self.assertEqual(out["namespaces"]["form"]["home"]["data"][0]["id"],101)
        self.assertEqual(out["namespaces"]["form"]["away"]["data"][0]["id"],202)

    def test_post_kickoff_archive_fails(self):
        r=report(created="2035-01-01T00:00:00Z")
        self.assertRaises(ValueError,adapt_legacy_archive_report,r)

    def test_missing_source_fails(self):
        r=report(); del r["sources"]["player"]
        self.assertRaises(ValueError,adapt_legacy_archive_report,r)

    def test_no_source_timestamp_backfill(self):
        out=adapt_legacy_archive_report(report())
        for src in ("match","league","form","table","player"):
            self.assertIsNone(out["lineage"][src]["captured_at_unix"])
            self.assertIsNone(out["lineage"][src]["max_time"])

    def test_header_identity_mismatch_fails(self):
        r=report(); r["match"]["match_id"]=999
        self.assertRaises(ValueError,adapt_legacy_archive_report,r)


if __name__=="__main__":
    unittest.main()
